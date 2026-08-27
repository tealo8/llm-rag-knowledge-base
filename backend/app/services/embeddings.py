from __future__ import annotations

import hashlib
import math
import re

from ..config import get_settings
from .model_client import ModelRequestError, post_json


LATIN_WORD = re.compile(r"[a-zA-Z0-9_]+")
CHINESE_RUN = re.compile(r"[\u3400-\u9fff]+")


def search_terms(text: str) -> list[str]:
    """Tokenize Latin words and Chinese unigrams/bigrams for SQLite FTS."""
    terms = [match.group(0).lower() for match in LATIN_WORD.finditer(text)]
    for match in CHINESE_RUN.finditer(text):
        run = match.group(0)
        terms.extend(run)
        terms.extend(run[index : index + 2] for index in range(len(run) - 1))
    return list(dict.fromkeys(term for term in terms if term.strip()))


def fts_text(text: str) -> str:
    return " ".join(search_terms(text))


def fts_query(text: str) -> str:
    terms = search_terms(text)[:32]
    return " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms)


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        return vector
    return [value / norm for value in vector]


def local_embedding(text: str, dimensions: int) -> list[float]:
    """Deterministic feature hashing reserved for tests and explicit degraded mode."""
    vector = [0.0] * dimensions
    for term in search_terms(text):
        digest = hashlib.blake2b(term.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "little") % dimensions
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[bucket] += sign * (1.0 + math.log1p(len(term)))
    return _normalize(vector)


class EmbeddingService:
    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def backend_name(self) -> str:
        if self.settings.embedding_provider == "local":
            return "local-feature-hashing"
        return f"{self.settings.embedding_provider}:{self.settings.embedding_model}"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        provider = self.settings.embedding_provider
        if provider == "local":
            return [local_embedding(text, self.settings.embedding_dimensions) for text in texts]
        if provider == "ollama":
            response = await post_json(
                f"{self.settings.ollama_base_url}/api/embed",
                {"model": self.settings.embedding_model, "input": texts},
            )
            vectors = response.data.get("embeddings")
        elif provider == "openai":
            response = await post_json(
                f"{self.settings.llm_base_url}/embeddings",
                {"model": self.settings.embedding_model, "input": texts},
                headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
            )
            items = sorted(response.data.get("data", []), key=lambda item: item["index"])
            vectors = [item["embedding"] for item in items]
        else:
            raise ModelRequestError(f"unsupported embedding provider: {provider}")

        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise ModelRequestError("embedding response count does not match input count")
        normalized: list[list[float]] = []
        dimensions: int | None = None
        for vector in vectors:
            if not isinstance(vector, list) or not vector:
                raise ModelRequestError("embedding response contains an empty vector")
            cast = [float(value) for value in vector]
            dimensions = dimensions or len(cast)
            if len(cast) != dimensions:
                raise ModelRequestError("embedding response contains mixed dimensions")
            normalized.append(_normalize(cast))
        return normalized

    async def embed_batched(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        batch_size = max(1, self.settings.embedding_batch_size)
        for start in range(0, len(texts), batch_size):
            vectors.extend(await self.embed(texts[start : start + batch_size]))
        return vectors


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True))
