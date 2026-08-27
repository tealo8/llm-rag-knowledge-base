"""Optional Celery integration for document indexing.

The API remains usable without Celery when TASK_QUEUE=inline. In production,
run `celery -A app.tasks:celery_app worker --loglevel=INFO` with Redis.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

from .config import get_settings
from .db import db_session
from .services.documents import _index_document

try:
    from celery import Celery

    settings = get_settings()
    celery_app = Celery(
        "knowledge_hub",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
    )
    celery_app.conf.update(
        task_time_limit=settings.task_timeout_seconds,
        task_soft_time_limit=max(1, settings.task_timeout_seconds - 30),
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        task_track_started=True,
        task_default_retry_delay=10,
        task_max_retries=3,
    )

    @celery_app.task(
        bind=True,
        name="app.tasks.index_document_task",
        max_retries=3,
    )
    def index_document_task(self, document_id: str) -> int:
        settings = get_settings()
        path: Path | None = None
        with db_session() as connection:
            document = connection.execute(
                "SELECT filename FROM documents WHERE id = ?", (document_id,)
            ).fetchone()
            if document:
                path = settings.upload_dir / f"{document_id}{Path(document['filename']).suffix.lower()}"
        if path is None or not path.exists():
            error = "原始文件不存在，无法执行索引任务"
            _mark_failed(document_id, error, task_id=self.request.id, attempts=self.request.retries + 1)
            _write_dead_letter(document_id, error, self.request.id, self.request.retries + 1)
            return 0
        try:
            return asyncio.run(_index_document(document_id, path.read_bytes()))
        except Exception as exc:
            if self.request.retries < self.max_retries:
                raise self.retry(exc=exc, countdown=min(60, 10 * (2 ** self.request.retries)))
            error = str(getattr(exc, "detail", exc))[:500]
            _mark_failed(document_id, error, task_id=self.request.id, attempts=self.request.retries + 1)
            _write_dead_letter(document_id, error, self.request.id, self.request.retries + 1)
            raise


    def enqueue_document_index(document_id: str) -> str:
        result = index_document_task.apply_async(
            args=[document_id], expires=get_settings().task_timeout_seconds
        )
        return str(result.id)

except ImportError:  # pragma: no cover - exercised only in minimal local installs
    celery_app = None

    def enqueue_document_index(document_id: str) -> str:
        raise RuntimeError("TASK_QUEUE=celery 需要安装 celery 和 redis 依赖")


def _mark_failed(document_id: str, error: str, *, task_id: str | None = None, attempts: int = 1) -> None:
    with db_session() as connection:
        connection.execute(
            "UPDATE documents SET status = 'failed', processing_stage = 'failed', error = ? WHERE id = ?",
            (error[:500], document_id),
        )


def _write_dead_letter(document_id: str, error: str, task_id: str | None, attempts: int) -> None:
    with db_session() as connection:
        row = connection.execute("SELECT org_id FROM documents WHERE id = ?", (document_id,)).fetchone()
        connection.execute(
            "INSERT INTO task_dead_letters (id, org_id, task_id, task_name, document_id, error, attempts, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
            (str(uuid.uuid4()), row["org_id"] if row else None, task_id, "app.tasks.index_document_task", document_id, error[:500], attempts, json.dumps({"document_id": document_id})),
        )
