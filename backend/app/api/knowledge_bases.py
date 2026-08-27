from __future__ import annotations

import sqlite3
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ..db import db_session, utc_now
from ..pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, escape_like, set_pagination_headers
from ..schemas import (
    KnowledgeBaseAccessUpdate,
    KnowledgeBaseCreateRequest,
    KnowledgeBaseMemberAccess,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdateRequest,
)
from ..security import (
    CurrentUser,
    get_current_user,
    knowledge_base_permission,
    require_knowledge_base_permission,
    require_roles,
)
from ..services.audit import write_audit


router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


def _serialize(connection, row, user: CurrentUser) -> KnowledgeBaseResponse:
    permission = knowledge_base_permission(connection, user, row["id"])
    if permission is None:
        raise HTTPException(status_code=404, detail="知识库不存在或无权访问")
    return KnowledgeBaseResponse(
        id=row["id"],
        name=row["name"],
        slug=row["slug"],
        description=row["description"],
        status=row["status"],
        permission=permission,
        document_count=row["document_count"],
        created_at=row["created_at"],
    )


@router.get("", response_model=list[KnowledgeBaseResponse])
def list_knowledge_bases(
    response: Response,
    include_archived: bool = False,
    q: str = Query("", max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    user: CurrentUser = Depends(get_current_user),
) -> list[KnowledgeBaseResponse]:
    with db_session() as connection:
        if user.role == "admin":
            access_clause, params = "kb.org_id = ?", [user.org_id]
        else:
            access_clause, params = (
                "kb.org_id = ? AND EXISTS (SELECT 1 FROM knowledge_base_access kba WHERE kba.knowledge_base_id = kb.id AND kba.user_id = ?)",
                [user.org_id, user.id],
            )
        filters = [access_clause]
        if not include_archived:
            filters.append("kb.status = 'active'")
        cleaned_query = q.strip().lower()
        if cleaned_query:
            filters.append(
                "(LOWER(kb.name) LIKE ? ESCAPE '\\' OR LOWER(kb.slug) LIKE ? ESCAPE '\\' "
                "OR LOWER(kb.description) LIKE ? ESCAPE '\\')"
            )
            search_value = f"%{escape_like(cleaned_query)}%"
            params.extend([search_value, search_value, search_value])
        where_clause = " AND ".join(filters)
        total = connection.execute(
            f"SELECT COUNT(*) AS count FROM knowledge_bases kb WHERE {where_clause}",
            params,
        ).fetchone()["count"]
        offset = (page - 1) * page_size
        rows = connection.execute(
            f"""
            SELECT kb.*, COUNT(d.id) AS document_count
            FROM knowledge_bases kb
            LEFT JOIN documents d ON d.knowledge_base_id = kb.id AND d.is_current = 1
            WHERE {where_clause}
            GROUP BY kb.id ORDER BY LOWER(kb.name), kb.id LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
        ).fetchall()
        set_pagination_headers(
            response, total=total, page=page, page_size=page_size
        )
        return [_serialize(connection, row, user) for row in rows]


@router.post("", response_model=KnowledgeBaseResponse, status_code=201)
def create_knowledge_base(
    payload: KnowledgeBaseCreateRequest,
    user: CurrentUser = Depends(require_roles("admin")),
) -> KnowledgeBaseResponse:
    kb_id = str(uuid.uuid4())
    now = utc_now()
    try:
        with db_session() as connection:
            connection.execute(
                """
                INSERT INTO knowledge_bases
                    (id, org_id, name, slug, description, status, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)
                """,
                (kb_id, user.org_id, payload.name.strip(), payload.slug, payload.description.strip(), user.id, now, now),
            )
            connection.execute(
                "INSERT INTO knowledge_base_access (knowledge_base_id, user_id, permission, created_at) VALUES (?, ?, 'admin', ?)",
                (kb_id, user.id, now),
            )
            write_audit(connection, user, "knowledge_base.create", "knowledge_base", kb_id)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="知识库名称或标识已存在") from exc
    with db_session() as connection:
        row = connection.execute(
            "SELECT kb.*, 0 AS document_count FROM knowledge_bases kb WHERE id = ?", (kb_id,)
        ).fetchone()
        return _serialize(connection, row, user)


@router.patch("/{knowledge_base_id}", response_model=KnowledgeBaseResponse)
def update_knowledge_base(
    knowledge_base_id: str,
    payload: KnowledgeBaseUpdateRequest,
    user: CurrentUser = Depends(get_current_user),
) -> KnowledgeBaseResponse:
    with db_session() as connection:
        require_knowledge_base_permission(connection, user, knowledge_base_id, "admin")
        current = connection.execute(
            "SELECT * FROM knowledge_bases WHERE id = ?", (knowledge_base_id,)
        ).fetchone()
        name = payload.name.strip() if payload.name is not None else current["name"]
        description = payload.description.strip() if payload.description is not None else current["description"]
        status = payload.status or current["status"]
        connection.execute(
            "UPDATE knowledge_bases SET name = ?, description = ?, status = ?, updated_at = ? WHERE id = ?",
            (name, description, status, utc_now(), knowledge_base_id),
        )
        write_audit(
            connection,
            user,
            "knowledge_base.update",
            "knowledge_base",
            knowledge_base_id,
            metadata={"status": status},
        )
        row = connection.execute(
            """
            SELECT kb.*, COUNT(d.id) AS document_count FROM knowledge_bases kb
            LEFT JOIN documents d ON d.knowledge_base_id = kb.id AND d.is_current = 1
            WHERE kb.id = ? GROUP BY kb.id
            """,
            (knowledge_base_id,),
        ).fetchone()
        return _serialize(connection, row, user)


@router.delete("/{knowledge_base_id}", status_code=204, response_class=Response)
def delete_knowledge_base(
    knowledge_base_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    with db_session() as connection:
        require_knowledge_base_permission(connection, user, knowledge_base_id, "admin")
        document_count = connection.execute(
            "SELECT COUNT(*) AS count FROM documents WHERE knowledge_base_id = ?",
            (knowledge_base_id,),
        ).fetchone()["count"]
        if document_count:
            raise HTTPException(status_code=409, detail="知识库仍包含文档，请先删除文档或改为归档")
        connection.execute("DELETE FROM knowledge_bases WHERE id = ?", (knowledge_base_id,))
        write_audit(
            connection,
            user,
            "knowledge_base.delete",
            "knowledge_base",
            knowledge_base_id,
        )
    return Response(status_code=204)


@router.put("/{knowledge_base_id}/access", status_code=204, response_class=Response)
def set_knowledge_base_access(
    knowledge_base_id: str,
    payload: KnowledgeBaseAccessUpdate,
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    with db_session() as connection:
        require_knowledge_base_permission(connection, user, knowledge_base_id, "admin")
        target = connection.execute(
            "SELECT id FROM users WHERE id = ? AND org_id = ? AND active = 1",
            (payload.user_id, user.org_id),
        ).fetchone()
        if target is None:
            raise HTTPException(status_code=404, detail="成员不存在")
        if payload.permission is None:
            connection.execute(
                "DELETE FROM knowledge_base_access WHERE knowledge_base_id = ? AND user_id = ?",
                (knowledge_base_id, payload.user_id),
            )
        else:
            connection.execute(
                """
                INSERT INTO knowledge_base_access (knowledge_base_id, user_id, permission, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(knowledge_base_id, user_id) DO UPDATE SET permission = excluded.permission
                """,
                (knowledge_base_id, payload.user_id, payload.permission, utc_now()),
            )
        write_audit(
            connection,
            user,
            "knowledge_base.access.update",
            "knowledge_base",
            knowledge_base_id,
            metadata={"user_id": payload.user_id, "permission": payload.permission},
        )
    return Response(status_code=204)


@router.get("/{knowledge_base_id}/access", response_model=list[KnowledgeBaseMemberAccess])
def list_knowledge_base_access(
    knowledge_base_id: str,
    response: Response,
    q: str = Query("", max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    user: CurrentUser = Depends(get_current_user),
) -> list[KnowledgeBaseMemberAccess]:
    with db_session() as connection:
        require_knowledge_base_permission(connection, user, knowledge_base_id, "admin")
        filters = ["u.org_id = ?", "u.active = 1"]
        params: list[str | int] = [user.org_id]
        cleaned_query = q.strip().lower()
        if cleaned_query:
            filters.append(
                "(LOWER(u.display_name) LIKE ? ESCAPE '\\' OR LOWER(u.username) LIKE ? ESCAPE '\\' "
                "OR LOWER(u.email) LIKE ? ESCAPE '\\')"
            )
            search_value = f"%{escape_like(cleaned_query)}%"
            params.extend([search_value, search_value, search_value])
        where_clause = " AND ".join(filters)
        total = connection.execute(
            f"SELECT COUNT(*) AS count FROM users u WHERE {where_clause}", params
        ).fetchone()["count"]
        offset = (page - 1) * page_size
        rows = connection.execute(
            f"""
            SELECT u.id AS user_id, u.username, u.display_name, u.email, u.role,
                   kba.permission
            FROM users u
            LEFT JOIN knowledge_base_access kba
              ON kba.user_id = u.id AND kba.knowledge_base_id = ?
            WHERE {where_clause}
            ORDER BY CASE u.role WHEN 'admin' THEN 0 ELSE 1 END, LOWER(u.display_name), u.id
            LIMIT ? OFFSET ?
            """,
            [knowledge_base_id, *params, page_size, offset],
        ).fetchall()
        set_pagination_headers(
            response, total=total, page=page, page_size=page_size
        )
    return [KnowledgeBaseMemberAccess(**dict(row)) for row in rows]
