from __future__ import annotations

import json
import sqlite3
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ..config import get_settings
from ..db import db_session, utc_now
from ..pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, escape_like, set_pagination_headers
from ..schemas import (
    AdminUserCreateRequest,
    AdminUserResponse,
    AdminUserStatusUpdate,
    AuditResponse,
    GroupCreateRequest,
    GroupResponse,
    RagSettingsUpdate,
    UserAccessUpdate,
)
from ..security import CurrentUser, get_current_user, hash_password, require_roles
from ..services.audit import write_audit
from ..services.model_client import ModelRequestError, ollama_runtime_status
from ..services.reindex import embedding_index_status, reindex_organization
from ..services.settings import get_org_settings, save_org_settings
from ..services.vector_store import VectorStoreError, get_vector_store


router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/settings")
def rag_settings(
    user: CurrentUser = Depends(require_roles("admin")),
) -> dict:
    return get_org_settings(user.org_id)


@router.put("/settings")
def update_rag_settings(
    payload: RagSettingsUpdate,
    user: CurrentUser = Depends(require_roles("admin")),
) -> dict:
    if payload.chunk_overlap >= payload.chunk_size:
        raise HTTPException(status_code=422, detail="切块重叠度必须小于切块大小")
    if payload.lexical_weight + payload.vector_weight <= 0:
        raise HTTPException(status_code=422, detail="至少一个检索权重必须大于 0")
    values = payload.model_dump()
    values["sensitive_words"] = list(
        dict.fromkeys(word.strip() for word in payload.sensitive_words if word.strip())
    )
    saved = save_org_settings(user.org_id, user.id, values)
    with db_session() as connection:
        write_audit(
            connection,
            user,
            "system.settings.update",
            "organization",
            user.org_id,
            metadata={
                key: value
                for key, value in saved.items()
                if key not in {"system_prompt", "sensitive_words"}
            },
        )
    return saved


@router.get("/system/status")
async def system_status(
    user: CurrentUser = Depends(require_roles("admin")),
) -> dict:
    try:
        vector_store = get_vector_store().health()
    except VectorStoreError as exc:
        vector_store = {
            "provider": get_settings().vector_store,
            "ready": False,
            "error": str(exc)[:240],
        }
    return {
        "models": await ollama_runtime_status(),
        "index": embedding_index_status(user.org_id),
        "vector_store": vector_store,
    }


@router.post("/reindex")
async def reindex(
    user: CurrentUser = Depends(require_roles("admin")),
) -> dict:
    try:
        result = await reindex_organization(user.org_id)
    except (ModelRequestError, VectorStoreError) as exc:
        raise HTTPException(status_code=503, detail=f"索引服务暂时不可用：{str(exc)[:200]}") from exc
    with db_session() as connection:
        write_audit(
            connection,
            user,
            "index.rebuild",
            "organization",
            user.org_id,
            metadata=result,
        )
    return {**result, "index": embedding_index_status(user.org_id)}


@router.get("/tasks/dead-letters")
def dead_letters(
    response: Response,
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    user: CurrentUser = Depends(require_roles("admin")),
) -> list[dict]:
    offset = (page - 1) * page_size
    with db_session() as connection:
        total = connection.execute("SELECT COUNT(*) AS count FROM task_dead_letters WHERE org_id = ?", (user.org_id,)).fetchone()["count"]
        rows = connection.execute(
            "SELECT id, task_id, task_name, document_id, error, attempts, payload_json, created_at, resolved_at FROM task_dead_letters WHERE org_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (user.org_id, page_size, offset),
        ).fetchall()
    set_pagination_headers(response, total=total, page=page, page_size=page_size)
    return [
        {**dict(row), "payload": json.loads(row["payload_json"] or "{}")}
        for row in rows
    ]


def _serialize_group(row) -> GroupResponse:
    return GroupResponse(**dict(row))


def _user_groups(connection, user_id: str) -> list[GroupResponse]:
    rows = connection.execute(
        """
        SELECT g.id, g.name, g.description, COUNT(all_members.user_id) AS member_count
        FROM groups g
        JOIN user_groups membership ON membership.group_id = g.id
        LEFT JOIN user_groups all_members ON all_members.group_id = g.id
        WHERE membership.user_id = ?
        GROUP BY g.id ORDER BY g.name
        """,
        (user_id,),
    ).fetchall()
    return [_serialize_group(row) for row in rows]


@router.get("/groups", response_model=list[GroupResponse])
def groups(
    response: Response,
    q: str = Query("", max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    user: CurrentUser = Depends(get_current_user),
) -> list[GroupResponse]:
    with db_session() as connection:
        filters = ["g.org_id = ?"]
        params: list[str | int] = [user.org_id]
        cleaned_query = q.strip().lower()
        if cleaned_query:
            filters.append(
                "(LOWER(g.name) LIKE ? ESCAPE '\\' OR LOWER(g.description) LIKE ? ESCAPE '\\')"
            )
            search_value = f"%{escape_like(cleaned_query)}%"
            params.extend([search_value, search_value])
        where_clause = " AND ".join(filters)
        total = connection.execute(
            f"SELECT COUNT(*) AS count FROM groups g WHERE {where_clause}", params
        ).fetchone()["count"]
        offset = (page - 1) * page_size
        rows = connection.execute(
            f"""
            SELECT g.id, g.name, g.description, COUNT(ug.user_id) AS member_count
            FROM groups g LEFT JOIN user_groups ug ON ug.group_id = g.id
            WHERE {where_clause} GROUP BY g.id
            ORDER BY LOWER(g.name), g.id LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
        ).fetchall()
        set_pagination_headers(
            response, total=total, page=page, page_size=page_size
        )
    return [_serialize_group(row) for row in rows]


@router.post("/groups", response_model=GroupResponse, status_code=201)
def create_group(
    payload: GroupCreateRequest,
    user: CurrentUser = Depends(require_roles("admin")),
) -> GroupResponse:
    group_id = str(uuid.uuid4())
    try:
        with db_session() as connection:
            connection.execute(
                "INSERT INTO groups (id, org_id, name, description) VALUES (?, ?, ?, ?)",
                (group_id, user.org_id, payload.name.strip(), payload.description.strip()),
            )
            write_audit(
                connection,
                user,
                "group.create",
                "group",
                group_id,
                metadata={"name": payload.name.strip()},
            )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="当前组织已存在同名用户组") from exc
    return GroupResponse(
        id=group_id,
        name=payload.name.strip(),
        description=payload.description.strip(),
        member_count=0,
    )


@router.delete("/groups/{group_id}", status_code=204, response_class=Response)
def delete_group(
    group_id: str,
    user: CurrentUser = Depends(require_roles("admin")),
) -> Response:
    with db_session() as connection:
        group = connection.execute(
            "SELECT id, name FROM groups WHERE id = ? AND org_id = ?",
            (group_id, user.org_id),
        ).fetchone()
        if group is None:
            raise HTTPException(status_code=404, detail="用户组不存在")
        document_count = connection.execute(
            "SELECT COUNT(*) AS count FROM document_groups WHERE group_id = ?",
            (group_id,),
        ).fetchone()["count"]
        if document_count:
            raise HTTPException(status_code=409, detail="该用户组仍被文档权限使用，不能删除")
        connection.execute("DELETE FROM groups WHERE id = ?", (group_id,))
        write_audit(
            connection,
            user,
            "group.delete",
            "group",
            group_id,
            metadata={"name": group["name"]},
        )
    return Response(status_code=204)


@router.get("/users", response_model=list[AdminUserResponse])
def users(
    response: Response,
    q: str = Query("", max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    user: CurrentUser = Depends(require_roles("admin")),
) -> list[AdminUserResponse]:
    with db_session() as connection:
        filters = ["org_id = ?"]
        params: list[str | int] = [user.org_id]
        cleaned_query = q.strip().lower()
        if cleaned_query:
            filters.append(
                "(LOWER(display_name) LIKE ? ESCAPE '\\' OR LOWER(username) LIKE ? ESCAPE '\\' "
                "OR LOWER(email) LIKE ? ESCAPE '\\')"
            )
            search_value = f"%{escape_like(cleaned_query)}%"
            params.extend([search_value, search_value, search_value])
        where_clause = " AND ".join(filters)
        total = connection.execute(
            f"SELECT COUNT(*) AS count FROM users WHERE {where_clause}", params
        ).fetchone()["count"]
        offset = (page - 1) * page_size
        rows = connection.execute(
            f"""
            SELECT id, username, display_name, email, role, active
            FROM users WHERE {where_clause}
            ORDER BY CASE role WHEN 'admin' THEN 1 WHEN 'editor' THEN 2 ELSE 3 END,
                     LOWER(display_name), id LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
        ).fetchall()
        set_pagination_headers(
            response, total=total, page=page, page_size=page_size
        )
        return [
            AdminUserResponse(**dict(row), groups=_user_groups(connection, row["id"]))
            for row in rows
        ]


@router.post("/users", response_model=AdminUserResponse, status_code=201)
def create_user(
    payload: AdminUserCreateRequest,
    user: CurrentUser = Depends(require_roles("admin")),
) -> AdminUserResponse:
    user_id = str(uuid.uuid4())
    with db_session() as connection:
        group_ids = list(dict.fromkeys(payload.group_ids))
        if group_ids:
            placeholders = ",".join("?" for _ in group_ids)
            count = connection.execute(
                f"SELECT COUNT(*) AS count FROM groups WHERE org_id = ? AND id IN ({placeholders})",
                [user.org_id, *group_ids],
            ).fetchone()["count"]
            if count != len(group_ids):
                raise HTTPException(status_code=403, detail="包含不属于当前组织的用户组")
        try:
            connection.execute(
                """
                INSERT INTO users
                    (id, org_id, username, display_name, email, password_hash, role, active, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    user_id,
                    user.org_id,
                    payload.username,
                    payload.display_name.strip(),
                    payload.email.strip(),
                    hash_password(payload.password),
                    payload.role,
                    utc_now(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="用户名已存在") from exc
        connection.executemany(
            "INSERT INTO user_groups (user_id, group_id) VALUES (?, ?)",
            [(user_id, group_id) for group_id in group_ids],
        )
        write_audit(
            connection, user, "user.create", "user", user_id, metadata={"role": payload.role}
        )
        row = connection.execute(
            "SELECT id, username, display_name, email, role, active FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        return AdminUserResponse(
            **dict(row), groups=_user_groups(connection, user_id)
        )


@router.patch("/users/{target_user_id}/status", status_code=204, response_class=Response)
def update_user_status(
    target_user_id: str,
    payload: AdminUserStatusUpdate,
    user: CurrentUser = Depends(require_roles("admin")),
) -> Response:
    with db_session() as connection:
        target = connection.execute(
            "SELECT id, role, active FROM users WHERE id = ? AND org_id = ?",
            (target_user_id, user.org_id),
        ).fetchone()
        if target is None:
            raise HTTPException(status_code=404, detail="成员不存在")
        if target_user_id == user.id and not payload.active:
            raise HTTPException(status_code=409, detail="不能停用当前登录账号")
        if target["role"] == "admin" and target["active"] and not payload.active:
            active_admins = connection.execute(
                "SELECT COUNT(*) AS count FROM users WHERE org_id = ? AND role = 'admin' AND active = 1",
                (user.org_id,),
            ).fetchone()["count"]
            if active_admins <= 1:
                raise HTTPException(status_code=409, detail="组织必须至少保留一名有效管理员")
        connection.execute(
            "UPDATE users SET active = ? WHERE id = ?", (int(payload.active), target_user_id)
        )
        write_audit(
            connection,
            user,
            "user.status.update",
            "user",
            target_user_id,
            metadata={"active": payload.active},
        )
    return Response(status_code=204)


@router.patch("/users/{target_user_id}/access", response_model=AdminUserResponse)
def update_user_access(
    target_user_id: str,
    payload: UserAccessUpdate,
    user: CurrentUser = Depends(require_roles("admin")),
) -> AdminUserResponse:
    with db_session() as connection:
        target = connection.execute(
            """
            SELECT id, username, display_name, email, role, active
            FROM users WHERE id = ? AND org_id = ? AND active = 1
            """,
            (target_user_id, user.org_id),
        ).fetchone()
        if target is None:
            raise HTTPException(status_code=404, detail="成员不存在")

        group_ids = list(dict.fromkeys(payload.group_ids))
        if group_ids:
            placeholders = ",".join("?" for _ in group_ids)
            matched = connection.execute(
                f"SELECT id FROM groups WHERE org_id = ? AND id IN ({placeholders})",
                [user.org_id, *group_ids],
            ).fetchall()
            if len(matched) != len(group_ids):
                raise HTTPException(status_code=403, detail="包含不属于当前组织的用户组")

        if target["role"] == "admin" and payload.role != "admin":
            admin_count = connection.execute(
                "SELECT COUNT(*) AS count FROM users WHERE org_id = ? AND role = 'admin' AND active = 1",
                (user.org_id,),
            ).fetchone()["count"]
            if admin_count <= 1:
                raise HTTPException(status_code=409, detail="组织必须至少保留一名管理员")

        previous_groups = [
            row["group_id"]
            for row in connection.execute(
                "SELECT group_id FROM user_groups WHERE user_id = ?", (target_user_id,)
            ).fetchall()
        ]
        connection.execute(
            "UPDATE users SET role = ? WHERE id = ?", (payload.role, target_user_id)
        )
        connection.execute("DELETE FROM user_groups WHERE user_id = ?", (target_user_id,))
        connection.executemany(
            "INSERT INTO user_groups (user_id, group_id) VALUES (?, ?)",
            [(target_user_id, group_id) for group_id in group_ids],
        )
        write_audit(
            connection,
            user,
            "user.access.update",
            "user",
            target_user_id,
            metadata={
                "from_role": target["role"],
                "to_role": payload.role,
                "from_group_ids": previous_groups,
                "to_group_ids": group_ids,
            },
        )
        updated = connection.execute(
            "SELECT id, username, display_name, email, role, active FROM users WHERE id = ?",
            (target_user_id,),
        ).fetchone()
        return AdminUserResponse(
            **dict(updated), groups=_user_groups(connection, target_user_id)
        )


@router.get("/audit", response_model=list[AuditResponse])
def audit_logs(
    response: Response,
    q: str = Query("", max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    user: CurrentUser = Depends(require_roles("admin")),
) -> list[AuditResponse]:
    with db_session() as connection:
        filters = ["a.org_id = ?"]
        params: list[str | int] = [user.org_id]
        cleaned_query = q.strip().lower()
        if cleaned_query:
            filters.append(
                "(LOWER(u.display_name) LIKE ? ESCAPE '\\' OR LOWER(a.action) LIKE ? ESCAPE '\\' "
                "OR LOWER(COALESCE(a.query, '')) LIKE ? ESCAPE '\\' "
                "OR LOWER(COALESCE(a.resource_id, '')) LIKE ? ESCAPE '\\')"
            )
            search_value = f"%{escape_like(cleaned_query)}%"
            params.extend([search_value, search_value, search_value, search_value])
        where_clause = " AND ".join(filters)
        total = connection.execute(
            f"SELECT COUNT(*) AS count FROM audit_logs a JOIN users u ON u.id = a.user_id "
            f"WHERE {where_clause}",
            params,
        ).fetchone()["count"]
        offset = (page - 1) * page_size
        rows = connection.execute(
            f"""
            SELECT a.id, u.display_name AS user_name, a.action, a.resource_type,
                   a.resource_id, a.query, a.metadata_json, a.created_at
            FROM audit_logs a JOIN users u ON u.id = a.user_id
            WHERE {where_clause}
            ORDER BY a.created_at DESC, a.id DESC LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
        ).fetchall()
        set_pagination_headers(
            response, total=total, page=page, page_size=page_size
        )
    return [
        AuditResponse(
            id=row["id"],
            user_name=row["user_name"],
            action=row["action"],
            resource_type=row["resource_type"],
            resource_id=row["resource_id"],
            query=row["query"] if get_settings().audit_log_queries else None,
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
        )
        for row in rows
    ]
