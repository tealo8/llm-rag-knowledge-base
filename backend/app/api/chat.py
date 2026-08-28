from __future__ import annotations

import hashlib
import json
import uuid
from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException

from ..config import get_settings
from ..db import db_session, utc_now
from ..schemas import ChatRequest, ChatResponse, CitationResponse
from ..security import (
    CurrentUser,
    get_current_user,
    require_knowledge_base_permission,
)
from ..services.answers import generate_answer
from ..services.audit import write_audit
from ..services.documents import resolve_knowledge_base
from ..services.governance import validate_user_query
from ..services.retrieval import hybrid_search
from ..services.settings import get_knowledge_base_settings


router = APIRouter(prefix="/chat", tags=["chat"])


def _conversation_context(
    payload: ChatRequest,
    user: CurrentUser,
) -> tuple[str, str, list[dict[str, str]], str | None]:
    with db_session() as connection:
        if payload.conversation_id:
            conversation = connection.execute(
                """
                SELECT id, knowledge_base_id FROM conversations
                WHERE id = ? AND org_id = ? AND user_id = ?
                """,
                (payload.conversation_id, user.org_id, user.id),
            ).fetchone()
            if conversation is None:
                raise HTTPException(status_code=404, detail="会话不存在或无权访问")
            kb_id = str(conversation["knowledge_base_id"])
            if payload.knowledge_base_id and payload.knowledge_base_id != kb_id:
                raise HTTPException(status_code=409, detail="会话不能切换到其他知识库")
            require_knowledge_base_permission(connection, user, kb_id, "view")
            kb_state = connection.execute("SELECT allow_qa FROM knowledge_bases WHERE id = ?", (kb_id,)).fetchone()
            if kb_state is not None and not bool(kb_state["allow_qa"]):
                raise HTTPException(status_code=403, detail="当前知识库暂未开放问答")
            conversation_id = str(conversation["id"])
        else:
            kb_id = resolve_knowledge_base(
                connection, user, payload.knowledge_base_id, "view"
            )
            kb_state = connection.execute("SELECT allow_qa FROM knowledge_bases WHERE id = ?", (kb_id,)).fetchone()
            if kb_state is not None and not bool(kb_state["allow_qa"]):
                raise HTTPException(status_code=403, detail="当前知识库暂未开放问答")
            conversation_id = str(uuid.uuid4())
            now = utc_now()
            connection.execute(
                """
                INSERT INTO conversations
                    (id, org_id, knowledge_base_id, user_id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    user.org_id,
                    kb_id,
                    user.id,
                    payload.query.strip()[:40],
                    now,
                    now,
                ),
            )
        rows = connection.execute(
            """
            SELECT role, content FROM conversation_messages
            WHERE conversation_id = ? ORDER BY created_at DESC LIMIT 20
            """,
            (conversation_id,),
        ).fetchall()
    chronological = [dict(row) for row in reversed(rows)]
    previous_user_query = next(
        (item["content"] for item in reversed(chronological) if item["role"] == "user"),
        None,
    )
    return conversation_id, kb_id, chronological, previous_user_query


@router.post("", response_model=ChatResponse)
async def chat(
    payload: ChatRequest, user: CurrentUser = Depends(get_current_user)
) -> ChatResponse:
    started = perf_counter()
    query_text = payload.query.strip()
    conversation_id, kb_id, history, previous_query = _conversation_context(payload, user)
    rag_settings = get_knowledge_base_settings(user.org_id, kb_id)
    if payload.rerank is not None:
        rag_settings["reranker_enabled"] = payload.rerank
    if payload.temperature is not None:
        rag_settings["temperature"] = payload.temperature
    validate_user_query(query_text, rag_settings)
    retrieval_query = (
        f"上一轮问题：{previous_query}\n当前追问：{query_text}"
        if previous_query
        else query_text
    )
    top_k = payload.top_k or int(rag_settings["top_k"])
    chunks, metrics = await hybrid_search(retrieval_query, user, top_k, kb_id, rag_settings)
    result = await generate_answer(
        query_text,
        chunks,
        rag_settings=rag_settings,
        history=history,
    )
    elapsed_ms = round((perf_counter() - started) * 1000, 1)
    citations = [
        CitationResponse(
            index=index,
            document_id=chunk.document_id,
            chunk_id=chunk.chunk_id,
            title=chunk.title,
            filename=chunk.filename,
            page_number=chunk.page_number,
            paragraph_number=chunk.paragraph_number,
            excerpt=chunk.text[:360],
            score=chunk.score,
        )
        for index, chunk in enumerate(chunks, start=1)
    ]
    metrics.update(result.metrics)
    metrics["latency_ms"] = elapsed_ms
    metrics["history_messages"] = len(history)
    user_message_id = str(uuid.uuid4())
    assistant_message_id = str(uuid.uuid4())
    now = utc_now()
    with db_session() as connection:
        connection.executemany(
            """
            INSERT INTO conversation_messages
                (id, conversation_id, role, content, citations_json, metrics_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (user_message_id, conversation_id, "user", query_text, "[]", "{}", now),
                (
                    assistant_message_id,
                    conversation_id,
                    "assistant",
                    result.text,
                    json.dumps([item.model_dump() for item in citations], ensure_ascii=False),
                    json.dumps(metrics, ensure_ascii=False),
                    now,
                ),
            ],
        )
        connection.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id)
        )
        write_audit(
            connection,
            user,
            "knowledge.query",
            "conversation",
            conversation_id,
            query=query_text if get_settings().audit_log_queries else None,
            metadata={
                **metrics,
                "query_sha256": hashlib.sha256(query_text.encode("utf-8")).hexdigest(),
                "query_length": len(query_text),
                "citations": len(citations),
                "document_ids": list(dict.fromkeys(item.document_id for item in citations)),
            },
        )
    return ChatResponse(
        answer=result.text,
        citations=citations,
        retrieval=metrics,
        conversation_id=conversation_id,
        message_id=assistant_message_id,
    )
