from __future__ import annotations

import json
from time import perf_counter
from typing import Any

from ..db import db_session
from .embeddings import EmbeddingService
from .vector_store import VectorRecord, get_vector_store


def embedding_index_status(org_id: str) -> dict[str, Any]:
    service = EmbeddingService()
    with db_session() as connection:
        rows = connection.execute(
            """
            SELECT c.embedding_model, c.embedding_dimensions, COUNT(*) AS chunk_count
            FROM chunks c JOIN documents d ON d.id = c.document_id
            WHERE c.org_id = ? AND d.status = 'indexed'
            GROUP BY c.embedding_model, c.embedding_dimensions
            ORDER BY chunk_count DESC
            """,
            (org_id,),
        ).fetchall()
    versions = [dict(row) for row in rows]
    current = sum(
        int(row["chunk_count"])
        for row in rows
        if row["embedding_model"] == service.backend_name
    )
    total = sum(int(row["chunk_count"]) for row in rows)
    return {
        "configured_model": service.backend_name,
        "current_chunks": current,
        "stale_chunks": total - current,
        "total_chunks": total,
        "versions": versions,
    }


async def reindex_organization(org_id: str) -> dict[str, int | float | str]:
    service = EmbeddingService()
    vector_store = get_vector_store()
    with db_session() as connection:
        rows = connection.execute(
            """
            SELECT c.id, c.document_id, c.knowledge_base_id, c.text FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE c.org_id = ? AND d.status = 'indexed'
            ORDER BY c.document_id, c.position
            """,
            (org_id,),
        ).fetchall()
    started = perf_counter()
    vectors = await service.embed_batched([row["text"] for row in rows])
    updates = [
        (json.dumps(vector), service.backend_name, len(vector), row["id"])
        for row, vector in zip(rows, vectors, strict=True)
    ]
    records_by_knowledge_base: dict[str, list[VectorRecord]] = {}
    for row, vector in zip(rows, vectors, strict=True):
        records_by_knowledge_base.setdefault(row["knowledge_base_id"], []).append(
            VectorRecord(
                chunk_id=row["id"],
                document_id=row["document_id"],
                vector=vector,
            )
        )
    for knowledge_base_id, records in records_by_knowledge_base.items():
        vector_store.upsert(org_id, knowledge_base_id, records)
    with db_session() as connection:
        connection.executemany(
            """
            UPDATE chunks
            SET embedding_json = ?, embedding_model = ?, embedding_dimensions = ?
            WHERE id = ? AND org_id = ?
            """,
            [(*update, org_id) for update in updates],
        )
    return {
        "model": service.backend_name,
        "chunks_reindexed": len(updates),
        "dimensions": len(vectors[0]) if vectors else 0,
        "vector_store": vector_store.name,
        "latency_ms": round((perf_counter() - started) * 1000, 1),
    }
