from __future__ import annotations

import json
from typing import Any

from ..config import get_settings
from ..db import db_session, utc_now


DEFAULT_RAG_SETTINGS: dict[str, Any] = {
    "chunk_strategy": "fixed",
    "chunk_size": 720,
    "chunk_overlap": 100,
    "top_k": 6,
    "lexical_weight": 0.55,
    "vector_weight": 0.45,
    "bm25_enabled": True,
    "reranker_enabled": False,
    "similarity_threshold": None,
    "temperature": 0.1,
    "strict_rag": True,
    "max_context_chars": 12000,
    "max_history_messages": 10,
    "prompt_injection_filter": True,
    "sensitive_words": [],
    "system_prompt": "",
}


def get_org_settings(org_id: str) -> dict[str, Any]:
    with db_session() as connection:
        row = connection.execute(
            "SELECT settings_json FROM organization_settings WHERE org_id = ?",
            (org_id,),
        ).fetchone()
    custom = json.loads(row["settings_json"]) if row else {}
    settings = {**DEFAULT_RAG_SETTINGS, **custom}
    if settings["similarity_threshold"] is None:
        settings["similarity_threshold"] = get_settings().vector_min_similarity
    return settings


def save_org_settings(org_id: str, user_id: str, values: dict[str, Any]) -> dict[str, Any]:
    merged = {**get_org_settings(org_id), **values}
    with db_session() as connection:
        connection.execute(
            """
            INSERT INTO organization_settings (org_id, settings_json, updated_by, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(org_id) DO UPDATE SET
                settings_json = excluded.settings_json,
                updated_by = excluded.updated_by,
                updated_at = excluded.updated_at
            """,
            (org_id, json.dumps(merged, ensure_ascii=False), user_id, utc_now()),
        )
    return merged
