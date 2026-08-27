from __future__ import annotations

import json
import math
from time import perf_counter
from dataclasses import dataclass

from ..db import db_session
from ..security import CurrentUser, document_acl_sql
from .embeddings import EmbeddingService, cosine_similarity, fts_query, search_terms
from .model_client import ModelRequestError
from .settings import get_org_settings
from .vector_store import VectorStoreError, get_vector_store
from ..metrics import inc, observe


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    title: str
    filename: str
    page_number: int | None
    text: str
    paragraph_number: int | None = None
    score: float = 0.0


def _row_to_chunk(row) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=row["chunk_id"],
        document_id=row["document_id"],
        title=row["title"],
        filename=row["filename"],
        page_number=row["page_number"],
        paragraph_number=row["paragraph_number"],
        text=row["text"],
    )


async def hybrid_search(
    query: str, user: CurrentUser, top_k: int, knowledge_base_id: str
) -> tuple[list[RetrievedChunk], dict[str, int | float | str]]:
    started = perf_counter()
    acl_clause, acl_params = document_acl_sql(user)
    embedding_service = EmbeddingService()
    vector_store = get_vector_store()
    rag_settings = get_org_settings(user.org_id)
    query_embedding: list[float] | None = None
    vector_error: str | None = None
    try:
        query_embedding = (await embedding_service.embed([query]))[0]
    except ModelRequestError as exc:
        vector_error = str(exc)[:240]
    lexical_query = fts_query(query)
    query_terms = {
        term for term in search_terms(query) if len(term) > 1 or term.isascii()
    }

    def locally_relevant(text: str) -> bool:
        text_terms = {
            term for term in search_terms(text) if len(term) > 1 or term.isascii()
        }
        overlap = len(query_terms.intersection(text_terms))
        minimum = max(1, math.ceil(len(query_terms) * 0.15))
        return overlap >= minimum

    with db_session() as connection:
        lexical_rows = []
        if lexical_query and bool(rag_settings.get("bm25_enabled", True)):
            lexical_rows = connection.execute(
                f"""
                SELECT c.id AS chunk_id, c.document_id, c.page_number, c.paragraph_number, c.text,
                       d.title, d.filename, bm25(chunks_fts) AS lexical_score
                FROM chunks_fts
                JOIN chunks c ON c.id = chunks_fts.chunk_id
                JOIN documents d ON d.id = c.document_id
                WHERE chunks_fts MATCH ? AND d.status = 'indexed' AND d.is_current = 1
                  AND d.knowledge_base_id = ? AND ({acl_clause})
                ORDER BY lexical_score
                LIMIT 40
                """,
                [lexical_query, knowledge_base_id, *acl_params],
            ).fetchall()

        vector_rows = []
        authorized_document_ids: list[str] = []
        if query_embedding is not None:
            if vector_store.name == "sqlite":
                vector_rows = connection.execute(
                    f"""
                    SELECT c.id AS chunk_id, c.document_id, c.page_number, c.paragraph_number, c.text,
                           c.embedding_json, d.title, d.filename
                    FROM chunks c
                    JOIN documents d ON d.id = c.document_id
                    WHERE d.status = 'indexed' AND d.is_current = 1
                      AND d.knowledge_base_id = ? AND c.embedding_model = ? AND ({acl_clause})
                    LIMIT 5000
                    """,
                    [knowledge_base_id, embedding_service.backend_name, *acl_params],
                ).fetchall()
            else:
                authorized_document_ids = [
                    row["id"]
                    for row in connection.execute(
                        f"""
                        SELECT d.id FROM documents d
                        WHERE d.status = 'indexed' AND d.is_current = 1
                          AND d.knowledge_base_id = ? AND ({acl_clause})
                        """,
                        [knowledge_base_id, *acl_params],
                    ).fetchall()
                ]

    minimum_similarity = (
        0.05
        if embedding_service.backend_name == "local-feature-hashing"
        else float(rag_settings["similarity_threshold"])
    )
    external_scores: dict[str, float] = {}
    if query_embedding is not None and vector_store.name != "sqlite":
        try:
            matches = vector_store.search(
                user.org_id,
                knowledge_base_id,
                query_embedding,
                authorized_document_ids,
                40,
                minimum_similarity,
            )
            external_scores = {match.chunk_id: match.score for match in matches}
            if external_scores:
                placeholders = ",".join("?" for _ in external_scores)
                with db_session() as connection:
                    vector_rows = connection.execute(
                        f"""
                        SELECT c.id AS chunk_id, c.document_id, c.page_number,
                               c.paragraph_number, c.text, c.embedding_json,
                               d.title, d.filename
                        FROM chunks c JOIN documents d ON d.id = c.document_id
                        WHERE c.id IN ({placeholders}) AND d.knowledge_base_id = ?
                          AND ({acl_clause})
                        """,
                        [*external_scores, knowledge_base_id, *acl_params],
                    ).fetchall()
        except VectorStoreError as exc:
            vector_error = str(exc)[:240]
            vector_rows = []

    lexical = [_row_to_chunk(row) for row in lexical_rows]
    vector_scored = [] if query_embedding is None else [
        (
            external_scores.get(
                row["chunk_id"],
                cosine_similarity(query_embedding, json.loads(row["embedding_json"])),
            ),
            row,
        )
        for row in vector_rows
    ]
    vector_scored.sort(key=lambda item: item[0], reverse=True)
    vector = [
        _row_to_chunk(row)
        for score, row in vector_scored[:40]
        if score >= minimum_similarity
    ]

    # FTS5 uses OR recall, so its candidates still need minimum query-term evidence.
    lexical = [chunk for chunk in lexical if locally_relevant(chunk.text)]
    if embedding_service.backend_name == "local-feature-hashing":
        vector = [chunk for chunk in vector if locally_relevant(chunk.text)]

    # Reciprocal rank fusion makes scores comparable across BM25 and vector retrieval.
    combined: dict[str, RetrievedChunk] = {}
    scores: dict[str, float] = {}
    lexical_weight = float(rag_settings["lexical_weight"])
    vector_weight = float(rag_settings["vector_weight"])
    total_weight = lexical_weight + vector_weight
    if total_weight <= 0:
        lexical_weight, vector_weight, total_weight = 0.55, 0.45, 1.0
    for weight, ranking in (
        (lexical_weight / total_weight, lexical),
        (vector_weight / total_weight, vector),
    ):
        for rank, chunk in enumerate(ranking, start=1):
            combined[chunk.chunk_id] = chunk
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + weight / (60 + rank)

    if bool(rag_settings.get("reranker_enabled", False)):
        # Lightweight deterministic reranker: reward query-term coverage after fusion.
        for chunk in combined.values():
            chunk_terms = set(search_terms(chunk.text))
            coverage = len(query_terms.intersection(chunk_terms)) / max(len(query_terms), 1)
            scores[chunk.chunk_id] += 0.08 * coverage
    ordered = sorted(combined.values(), key=lambda item: scores[item.chunk_id], reverse=True)
    max_score = max(scores.values(), default=1.0)
    selected: list[RetrievedChunk] = []
    per_document: dict[str, int] = {}
    for chunk in ordered:
        if per_document.get(chunk.document_id, 0) >= 2:
            continue
        chunk.score = round(scores[chunk.chunk_id] / max_score, 4)
        selected.append(chunk)
        per_document[chunk.document_id] = per_document.get(chunk.document_id, 0) + 1
        if len(selected) >= top_k:
            break

    metrics: dict[str, int | float | str] = {
        "lexical_candidates": len(lexical),
        "vector_candidates": len(vector),
        "fused_candidates": len(combined),
        "embedding_backend": embedding_service.backend_name,
        "vector_store": vector_store.name,
        "vector_min_similarity": minimum_similarity,
        "top_vector_similarity": round(vector_scored[0][0], 4) if vector_scored else 0.0,
        "knowledge_base_id": knowledge_base_id,
        "lexical_weight": lexical_weight,
        "vector_weight": vector_weight,
        "bm25_enabled": bool(rag_settings.get("bm25_enabled", True)),
        "reranker_enabled": bool(rag_settings.get("reranker_enabled", False)),
    }
    if vector_error:
        metrics["retrieval_mode"] = "lexical_degraded"
        metrics["degraded_reason"] = f"embedding_unavailable: {vector_error}"
    elif query_embedding is not None and not vector_rows:
        metrics["retrieval_mode"] = "lexical_degraded"
        metrics["degraded_reason"] = "embedding_index_version_mismatch"
    else:
        metrics["retrieval_mode"] = "hybrid"
    observe("knowledge_retrieval_duration_ms", (perf_counter() - started) * 1000, {"mode": str(metrics["retrieval_mode"])})
    inc("knowledge_retrieval_requests_total", {"mode": str(metrics["retrieval_mode"])})
    metrics["retrieval_latency_ms"] = round((perf_counter() - started) * 1000, 1)
    return selected, metrics
