from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import Response as FastAPIResponse
from fastapi.responses import PlainTextResponse
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from ..db import db_session, utc_now
from ..pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, escape_like, set_pagination_headers
from ..schemas import (
    CitationResponse,
    ConversationDetail,
    ConversationMessageResponse,
    ConversationSummary,
    FeedbackRequest,
    ConversationUpdateRequest,
    ConversationBranchRequest,
    ConversationShareRequest,
    ConversationShareResponse,
    SharedConversationAccessRequest,
    SharedConversationResponse,
)
from ..security import CurrentUser, get_current_user, require_knowledge_base_permission, hash_password, verify_password
from ..services.audit import write_audit


router = APIRouter(prefix="/conversations", tags=["conversations"])


def _conversation_row(connection, conversation_id: str, user: CurrentUser):
    row = connection.execute(
        """
        SELECT c.id, c.knowledge_base_id, kb.name AS knowledge_base_name,
               c.title, c.created_at, c.updated_at, c.favorite, c.parent_id,
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
    favorite: bool | None = None,
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
    if favorite is not None:
        filters.append("c.favorite = ?")
        params.append(int(favorite))
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
                   c.title, c.created_at, c.updated_at, c.favorite, c.parent_id, COUNT(cm.id) AS message_count
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
            SELECT cm.*, mf.rating AS feedback, mf.reason AS feedback_reason FROM conversation_messages cm
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
            feedback_reason=row["feedback_reason"],
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
            INSERT INTO message_feedback (message_id, user_id, rating, comment, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id, user_id) DO UPDATE SET
                rating = excluded.rating, comment = excluded.comment, reason = excluded.reason, created_at = excluded.created_at
            """,
            (message_id, user.id, payload.rating, payload.comment.strip(), payload.reason, utc_now()),
        )
        write_audit(
            connection,
            user,
            "answer.feedback",
            "message",
            message_id,
            metadata={"rating": payload.rating, "reason": payload.reason},
        )
    return Response(status_code=204)


@router.patch("/{conversation_id}", response_model=ConversationSummary)
def update_conversation(
    conversation_id: str,
    payload: ConversationUpdateRequest,
    user: CurrentUser = Depends(get_current_user),
) -> ConversationSummary:
    with db_session() as connection:
        _conversation_row(connection, conversation_id, user)
        current = connection.execute("SELECT title, favorite FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        title = payload.title.strip() if payload.title is not None else current["title"]
        if not title:
            raise HTTPException(status_code=422, detail="会话标题不能为空")
        favorite = int(payload.favorite) if payload.favorite is not None else current["favorite"]
        connection.execute("UPDATE conversations SET title = ?, favorite = ?, updated_at = ? WHERE id = ?", (title, favorite, utc_now(), conversation_id))
        write_audit(connection, user, "conversation.update", "conversation", conversation_id, metadata={"title": title, "favorite": bool(favorite)})
        row = connection.execute(
            """SELECT c.id, c.knowledge_base_id, kb.name AS knowledge_base_name, c.title,
               c.created_at, c.updated_at, c.favorite, c.parent_id, COUNT(cm.id) AS message_count
               FROM conversations c JOIN knowledge_bases kb ON kb.id = c.knowledge_base_id
               LEFT JOIN conversation_messages cm ON cm.conversation_id = c.id
               WHERE c.id = ? GROUP BY c.id""", (conversation_id,)
        ).fetchone()
    return ConversationSummary(**dict(row))


@router.post("/{conversation_id}/branch", response_model=ConversationSummary, status_code=201)
def branch_conversation(
    conversation_id: str,
    payload: ConversationBranchRequest,
    user: CurrentUser = Depends(get_current_user),
) -> ConversationSummary:
    with db_session() as connection:
        source = _conversation_row(connection, conversation_id, user)
        message_limit = None
        if payload.message_id:
            message = connection.execute("SELECT created_at FROM conversation_messages WHERE id = ? AND conversation_id = ?", (payload.message_id, conversation_id)).fetchone()
            if message is None:
                raise HTTPException(status_code=404, detail="分支起点消息不存在")
            message_limit = message["created_at"]
        new_id = str(secrets.token_hex(16))
        now = utc_now()
        title = (payload.title or f"{source['title']} · 分支").strip()[:120]
        connection.execute("INSERT INTO conversations (id, org_id, knowledge_base_id, user_id, title, created_at, updated_at, parent_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (new_id, user.org_id, source["knowledge_base_id"], user.id, title, now, now, conversation_id))
        rows = connection.execute("SELECT * FROM conversation_messages WHERE conversation_id = ? AND (? IS NULL OR created_at <= ?) ORDER BY created_at", (conversation_id, message_limit, message_limit)).fetchall()
        for row in rows:
            connection.execute("INSERT INTO conversation_messages (id, conversation_id, role, content, citations_json, metrics_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (str(secrets.token_hex(16)), new_id, row["role"], row["content"], row["citations_json"], row["metrics_json"], row["created_at"]))
        write_audit(connection, user, "conversation.branch", "conversation", new_id, metadata={"parent_id": conversation_id, "message_id": payload.message_id})
        row = connection.execute("SELECT c.id, c.knowledge_base_id, kb.name AS knowledge_base_name, c.title, c.created_at, c.updated_at, c.favorite, c.parent_id, COUNT(cm.id) AS message_count FROM conversations c JOIN knowledge_bases kb ON kb.id = c.knowledge_base_id LEFT JOIN conversation_messages cm ON cm.conversation_id = c.id WHERE c.id = ? GROUP BY c.id", (new_id,)).fetchone()
    return ConversationSummary(**dict(row))


@router.post("/{conversation_id}/share", response_model=ConversationShareResponse, status_code=201)
def create_share(
    conversation_id: str,
    payload: ConversationShareRequest,
    user: CurrentUser = Depends(get_current_user),
) -> ConversationShareResponse:
    with db_session() as connection:
        _conversation_row(connection, conversation_id, user)
        token = secrets.token_urlsafe(32)
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=payload.expires_in_hours)).isoformat() if payload.expires_in_hours else None
        now = utc_now()
        share_id = str(secrets.token_hex(16))
        connection.execute("INSERT INTO conversation_shares (id, conversation_id, created_by, mode, token_hash, password_hash, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (share_id, conversation_id, user.id, payload.mode, hashlib.sha256(token.encode()).hexdigest(), hash_password(payload.password) if payload.password else None, expires_at, now))
        write_audit(connection, user, "conversation.share.create", "conversation", conversation_id, metadata={"mode": payload.mode, "expires_at": expires_at})
    return ConversationShareResponse(id=share_id, conversation_id=conversation_id, mode=payload.mode, token=token, expires_at=expires_at, created_at=now)


@router.post("/share/{token}/access", response_model=SharedConversationResponse)
def get_shared_conversation(token: str, payload: SharedConversationAccessRequest) -> FastAPIResponse:
    with db_session() as connection:
        row = connection.execute("SELECT s.*, c.title, kb.name AS knowledge_base_name FROM conversation_shares s JOIN conversations c ON c.id = s.conversation_id JOIN knowledge_bases kb ON kb.id = c.knowledge_base_id WHERE s.token_hash = ? AND s.revoked_at IS NULL", (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="分享链接不存在或已撤销")
        if row["expires_at"] and datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
            raise HTTPException(status_code=410, detail="分享链接已过期")
        if row["password_hash"] and (not payload.password or not verify_password(payload.password, row["password_hash"])):
            raise HTTPException(status_code=401, detail="分享链接需要访问密码")
        messages = connection.execute("SELECT * FROM conversation_messages WHERE conversation_id = ? ORDER BY created_at", (row["conversation_id"],)).fetchall()
    serialized = [ConversationMessageResponse(id=item["id"], role=item["role"], content=item["content"], citations=[CitationResponse(**v) for v in json.loads(item["citations_json"])], metrics=json.loads(item["metrics_json"]), feedback=None, created_at=item["created_at"]) for item in messages]
    response = SharedConversationResponse(title=row["title"], knowledge_base_name=row["knowledge_base_name"], mode=row["mode"], expires_at=row["expires_at"], messages=serialized)
    return FastAPIResponse(
        response.model_dump_json(),
        media_type="application/json",
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


def _text_pdf(text: str) -> bytes:
    """Create a multi-page PDF with a built-in CJK font mapping."""
    font_name = "STSong-Light"
    if font_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(font_name))
    output = BytesIO()
    document = canvas.Canvas(output, pagesize=(595, 842), pageCompression=1)
    document.setTitle("知域会话导出")
    document.setAuthor("知域企业私有 RAG 知识库")
    document.setFont(font_name, 10)
    left, top, bottom, line_height, max_width = 42, 800, 42, 16, 511
    y = top

    def wrapped_lines(value: str):
        if not value:
            yield ""
            return
        current = ""
        for character in value.expandtabs(4):
            candidate = current + character
            if current and pdfmetrics.stringWidth(candidate, font_name, 10) > max_width:
                yield current
                current = character
            else:
                current = candidate
        yield current

    for source_line in text.splitlines():
        for line in wrapped_lines(source_line):
            if y < bottom:
                document.showPage()
                document.setFont(font_name, 10)
                y = top
            document.drawString(left, y, line)
            y -= line_height
    document.save()
    return output.getvalue()


@router.get("/{conversation_id}/export")
def export_conversation(
    conversation_id: str,
    format: str = Query("markdown", pattern="^(markdown|pdf)$"),
    user: CurrentUser = Depends(get_current_user),
) -> Response:
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
    markdown = "\n".join(lines)
    if format == "pdf":
        return FastAPIResponse(_text_pdf(markdown), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="conversation-{conversation_id}.pdf"'})
    return PlainTextResponse(markdown, headers={"Content-Disposition": f'attachment; filename="conversation-{conversation_id}.md"'})


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
