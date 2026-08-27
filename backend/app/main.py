from __future__ import annotations

from contextlib import asynccontextmanager
from collections import defaultdict, deque
import re
from time import monotonic

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import PlainTextResponse

from .api import admin, auth, chat, conversations, documents, knowledge_bases, uploads
from .config import PROJECT_ROOT, get_settings
from .db import init_db
from .seed import seed_documents, seed_identities
from .metrics import inc, observe, prometheus_text


_rate_windows: dict[str, deque[float]] = defaultdict(deque)


def _metric_path(path: str) -> str:
    # Avoid turning every document/conversation UUID into a Prometheus label.
    return re.sub(r"/[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}", "/{id}", path)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    settings.validate_runtime()
    init_db()
    if settings.demo_mode:
        seed_identities()
        init_db()
        await seed_documents()
    yield


app = FastAPI(
    title=get_settings().app_name,
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(get_settings().cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count", "X-Page", "X-Page-Size", "X-Total-Pages"],
)


@app.middleware("http")
async def runtime_middleware(request, call_next):
    started = monotonic()
    settings = get_settings()
    path = _metric_path(request.url.path)
    client_key = request.headers.get("Authorization", "").split(" ")[-1][:80]
    if not client_key:
        client_key = request.client.host if request.client else "unknown"
    should_limit = (
        settings.rate_limit_enabled
        and path.startswith("/api/")
        and path not in {"/api/health", "/metrics"}
    )
    if should_limit:
        now = monotonic()
        window = _rate_windows[client_key]
        cutoff = now - 60
        while window and window[0] < cutoff:
            window.popleft()
        allowed = len(window) < settings.rate_limit_per_minute + settings.rate_limit_burst
        if not allowed:
            inc("knowledge_http_rate_limited_total", {"path": path})
            return PlainTextResponse("请求过于频繁，请稍后再试", status_code=429, headers={"Retry-After": "60"})
        window.append(now)
    try:
        response = await call_next(request)
        inc("knowledge_http_requests_total", {"method": request.method, "path": path, "status": str(response.status_code)})
        return response
    finally:
        observe("knowledge_http_request_duration_ms", (monotonic() - started) * 1000, {"method": request.method, "path": path})

app.include_router(auth.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(knowledge_bases.router, prefix="/api")
app.include_router(uploads.router, prefix="/api")
app.include_router(conversations.router, prefix="/api")


@app.get("/api/health")
def health() -> dict[str, str | bool]:
    settings = get_settings()
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.app_env,
        "demo_mode": settings.demo_mode,
    }


@app.get("/metrics", include_in_schema=False)
def metrics() -> PlainTextResponse:
    return PlainTextResponse(prometheus_text(), media_type="text/plain; version=0.0.4")


frontend_dist = PROJECT_ROOT / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
