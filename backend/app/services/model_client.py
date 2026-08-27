from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import perf_counter
from typing import Any

import httpx

from ..config import get_settings
from ..metrics import inc, observe


class ModelRequestError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelResponse:
    data: dict[str, Any]
    attempts: int
    latency_ms: float


async def post_json(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
) -> ModelResponse:
    settings = get_settings()
    started = perf_counter()
    operation = "embedding" if "/embed" in url or "embeddings" in url else "generation"
    last_error = "unknown model error"
    attempts = settings.model_max_retries + 1
    async with httpx.AsyncClient(timeout=settings.model_timeout_seconds) as client:
        for attempt in range(1, attempts + 1):
            try:
                response = await client.post(url, headers=headers, json=payload)
                if response.status_code < 400:
                    inc("knowledge_model_requests_total", {"operation": operation, "status": "success"})
                    observe("knowledge_model_request_duration_ms", (perf_counter() - started) * 1000, {"operation": operation})
                    return ModelResponse(
                        data=response.json(),
                        attempts=attempt,
                        latency_ms=round((perf_counter() - started) * 1000, 1),
                    )
                last_error = f"HTTP {response.status_code}: {response.text[:240]}"
                if response.status_code not in {408, 429} and response.status_code < 500:
                    break
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            except (ValueError, TypeError) as exc:
                last_error = f"invalid model response: {exc}"
                break
            if attempt < attempts:
                await asyncio.sleep(0.25 * (2 ** (attempt - 1)))
    inc("knowledge_model_requests_total", {"operation": operation, "status": "error"})
    observe("knowledge_model_request_duration_ms", (perf_counter() - started) * 1000, {"operation": operation})
    raise ModelRequestError(last_error)


async def ollama_runtime_status() -> dict[str, Any]:
    settings = get_settings()
    if settings.llm_provider != "ollama" and settings.embedding_provider != "ollama":
        return {
            "reachable": True,
            "generation": {
                "model": settings.llm_model,
                "ready": settings.llm_provider != "disabled",
                "capabilities": [] if settings.llm_provider == "disabled" else ["completion"],
            },
            "embedding": {
                "model": "local-feature-hashing" if settings.embedding_provider == "local" else settings.embedding_model,
                "ready": True,
                "dimensions": settings.embedding_dimensions if settings.embedding_provider == "local" else None,
                "capabilities": ["embedding"],
            },
        }
    try:
        async with httpx.AsyncClient(timeout=min(settings.model_timeout_seconds, 10)) as client:
            response = await client.get(f"{settings.ollama_base_url}/api/tags")
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        return {
            "reachable": False,
            "error": f"{type(exc).__name__}: {str(exc)[:160]}",
            "generation": {"model": settings.llm_model, "ready": False},
            "embedding": {"model": settings.embedding_model, "ready": False},
        }

    models = {item.get("name", ""): item for item in payload.get("models", [])}

    def state(model_name: str, capability: str) -> dict[str, Any]:
        item = models.get(model_name)
        capabilities = item.get("capabilities", []) if item else []
        return {
            "model": model_name,
            "ready": bool(item and capability in capabilities),
            "size_bytes": item.get("size") if item else None,
            "parameter_size": item.get("details", {}).get("parameter_size") if item else None,
            "quantization": item.get("details", {}).get("quantization_level") if item else None,
            "dimensions": item.get("details", {}).get("embedding_length") if item else None,
            "capabilities": capabilities,
        }

    return {
        "reachable": True,
        "generation": state(settings.llm_model, "completion"),
        "embedding": state(settings.embedding_model, "embedding"),
    }
