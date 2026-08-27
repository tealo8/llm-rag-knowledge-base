from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import PlainTextResponse

from ..db import db_session, utc_now
from ..pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, escape_like, set_pagination_headers
from ..schemas import (
    CitationResponse,
    ConversationDetail,
    ConversationMessageResponse,
    ConversationSummary,
    FeedbackRequest,
)
from ..security import CurrentUser, get_current_user, require_knowledge_base_permission
from ..services.audit import write_audit


router = APIRouter(prefix="/conversations", tags=["conversations"])


def _conversation_row(connection, conversation_id: str, user: CurrentUser):
    row = connection.execute(
        """
        SELECT c.id, c.knowledge_base_id, kb.name AS knowledge_base_name,
               c.title, c.created_at, c.updated_at,
               COUNT(cm.id) AS message_count
        FROM conversations c
        JOIN knowledge_bases kb ON kb.id = c.knowledge_base_id
        LEFT JOIN conversation_messages cm ON cm.conversation_id = c.id
        WHERE c.id = ? AND c.org_id = ? AND c.user_id = ?
        GROUP BY c.id
        """,
        (conversation_id, user.org_id, user.id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")
    require_knowledge_base_permission(connection, user, row["knowledge_base_id"], "view")
    return row


@router.get("", response_model=list[ConversationSummary])
def list_conversations(
    response: Response,
    knowledge_base_id: str | None = None,
    q: str = Query("", max_length=200),
    page: int = Query(1, ge=1),
    page_size: int | None = Query(None, ge=1, le=MAX_PAGE_SIZE),
    limit: int | None = Query(None, ge=1, le=MAX_PAGE_SIZE, include_in_schema=False),
    user: CurrentUser = Depends(get_current_user),
) -> list[ConversationSummary]:
    page_size = page_size or limit or DEFAULT_PAGE_SIZE
    filters = ["c.org_id = ?", "c.user_id = ?"]
    params: list[str | int] = [user.org_id, user.id]
    if knowledge_base_id:
        filters.append("c.knowledge_base_id = ?")
        params.append(knowledge_base_id)
    if user.role != "admin":
        filters.append(
            "EXISTS (SELECT 1 FROM knowledge_base_access kba "
            "WHERE kba.knowledge_base_id = c.knowledge_base_id AND kba.user_id = ? "
            "AND kba.permission IN ('view', 'edit', 'admin'))"
        )
        params.append(user.id)
    cleaned_query = q.strip().lower()
    if cleaned_query:
        filters.append("LOWER(c.title) LIKE ? ESCAPE '\\'")
        params.append(f"%{escape_like(cleaned_query)}%")
    where_clause = " AND ".join(filters)
    offset = (page - 1) * page_size
    with db_session() as connection:
        if knowledge_base_id:
            require_knowledge_base_permission(connection, user, knowledge_base_id, "view")
        total = connection.execute(
            f"SELECT COUNT(*) AS count FROM conversations c WHERE {where_clause}",
            params,
        ).fetchone()["count"]
        rows = connection.execute(
            f"""
            SELECT c.id, c.knowledge_base_id, kb.name AS knowledge_base_name,
                   c.title, c.created_at, c.updated_at, COUNT(cm.id) AS message_count
            FROM conversations c JOIN knowledge_bases kb ON kb.id = c.knowledge_base_id
            LEFT JOIN conversation_messages cm ON cm.conversation_id = c.id
            WHERE {where_clause}
            GROUP BY c.id ORDER BY c.updated_at DESC, c.id DESC LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
        ).fetchall()
        set_pagination_headers(
            response, total=total, page=page, page_size=page_size
        )
    return [ConversationSummary(**dict(row)) for row in rows]


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> ConversationDetail:
    with db_session() as connection:
        conversation = _conversation_row(connection, conversation_id, user)
        rows = connection.execute(
            """
            SELECT cm.*, mf.rating AS feedback FROM conversation_messages cm
            LEFT JOIN message_feedback mf ON mf.message_id = cm.id AND mf.user_id = ?
            WHERE cm.conversation_id = ? ORDER BY cm.created_at
            """,
            (user.id, conversation_id),
        ).fetchall()
    messages = [
        ConversationMessageResponse(
            id=row["id"],
            role=row["role"],
            content=row["content"],
            citations=[CitationResponse(**item) for item in json.loads(row["citations_json"])],
            metrics=json.loads(row["metrics_json"]),
            feedback=row["feedback"],
            created_at=row["created_at"],
        )
        for row in rows
    ]
    return ConversationDetail(**dict(conversation), messages=messages)


@router.put("/{conversation_id}/messages/{message_id}/feedback", status_code=204, response_class=Response)
def set_feedback(
    conversation_id: str,
    message_id: str,
    payload: FeedbackRequest,
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    with db_session() as connection:
        _conversation_row(connection, conversation_id, user)
        message = connection.execute(
            "SELECT id FROM conversation_messages WHERE id = ? AND conversation_id = ? AND role = 'assistant'",
            (message_id, conversation_id),
        ).fetchone()
        if message is None:
            raise HTTPException(status_code=404, detail="回答消息不存在")
        connection.execute(
            """
            INSERT INTO message_feedback (message_id, user_id, rating, comment, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(message_id, user_id) DO UPDATE SET
                rating = excluded.rating, comment = excluded.comment, created_at = excluded.created_at
            """,
            (message_id, user.id, payload.rating, payload.comment.strip(), utc_now()),
        )
        write_audit(
            connection,
            user,
            "answer.feedback",
            "message",
            message_id,
            metadata={"rating": payload.rating},
        )
    return Response(status_code=204)


@router.get("/{conversation_id}/export", response_class=PlainTextResponse)
def export_conversation(
    conversation_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> PlainTextResponse:
    detail = get_conversation(conversation_id, user)
    lines = [f"# {detail.title}", "", f"知识库：{detail.knowledge_base_name}", ""]
    for message in detail.messages:
        lines.append("## 问题" if message.role == "user" else "## 回答")
        lines.extend(["", message.content, ""])
        for citation in message.citations:
            location = f"第 {citation.page_number} 页" if citation.page_number else f"段落 {citation.paragraph_number or '-'}"
            lines.append(f"- [{citation.index}] {citation.title} / {citation.filename} / {location}")
        if message.citations:
            lines.append("")
    return PlainTextResponse(
        "\n".join(lines),
        headers={"Content-Disposition": f'attachment; filename="conversation-{conversation_id}.md"'},
    )


@router.delete("/{conversation_id}", status_code=204, response_class=Response)
def delete_conversation(
    conversation_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    with db_session() as connection:
        _conversation_row(connection, conversation_id, user)
        connection.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        write_audit(connection, user, "conversation.delete", "conversation", conversation_id)
    return Response(status_code=204)
