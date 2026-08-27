from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse

from ..config import get_settings
from ..db import db_session, utc_now
from ..pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, escape_like, set_pagination_headers
from ..schemas import (
    ChunkResponse,
    DocumentPermissionUpdate,
    DocumentResponse,
    GroupResponse,
)
from ..security import (
    CurrentUser,
    document_acl_sql,
    get_current_user,
    require_knowledge_base_permission,
)
from ..services.audit import write_audit
from ..services.documents import (
    ingest_document,
    reparse_document,
    validate_document_acl,
)
from ..services.vector_store import VectorStoreError, get_vector_store


router = APIRouter(prefix="/documents", tags=["documents"])


def _json_string_list(value: str, label: str) -> list[str]:
    try:
        parsed = json.loads(value)
        if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
            raise ValueError
        return parsed
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{label}参数无效") from exc


def _serialize_document(connection, row) -> DocumentResponse:
    group_rows = connection.execute(
        """
        SELECT g.id, g.name, g.description, COUNT(ug.user_id) AS member_count
        FROM groups g
        JOIN document_groups dg ON dg.group_id = g.id
        LEFT JOIN user_groups ug ON ug.group_id = g.id
        WHERE dg.document_id = ?
        GROUP BY g.id ORDER BY g.name
        """,
        (row["id"],),
    ).fetchall()
    allowed_users = connection.execute(
        "SELECT user_id FROM document_users WHERE document_id = ? ORDER BY user_id",
        (row["id"],),
    ).fetchall()
    values = dict(row)
    values["is_current"] = bool(values["is_current"])
    values["tags"] = json.loads(values.pop("tags_json") or "[]")
    return DocumentResponse(
        **values,
        groups=[GroupResponse(**dict(group)) for group in group_rows],
        allowed_user_ids=[item["user_id"] for item in allowed_users],
    )


DOCUMENT_SELECT = """
    SELECT d.id, d.owner_id, d.knowledge_base_id, d.filename, d.title,
           d.content_type, d.size_bytes, d.visibility, d.status, d.chunk_count,
           d.created_at, d.error, d.tags_json, d.version_group_id,
           d.version_number, d.is_current, d.archived_at, d.chunk_strategy,
           d.processing_stage, d.task_id,
           u.display_name AS owner_name
    FROM documents d JOIN users u ON u.id = d.owner_id
"""


def _get_document(document_id: str, user: CurrentUser) -> DocumentResponse:
    acl_clause, acl_params = document_acl_sql(user)
    with db_session() as connection:
        row = connection.execute(
            f"{DOCUMENT_SELECT} WHERE d.id = ? AND ({acl_clause})",
            [document_id, *acl_params],
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="文档不存在或无权访问")
        return _serialize_document(connection, row)


def _get_uploaded_document(document_id: str, user: CurrentUser) -> DocumentResponse:
    with db_session() as connection:
        row = connection.execute(
            f"{DOCUMENT_SELECT} WHERE d.id = ? AND d.org_id = ?",
            (document_id, user.org_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="上传结果不存在")
        return _serialize_document(connection, row)


@router.get("", response_model=list[DocumentResponse])
def list_documents(
    response: Response,
    knowledge_base_id: str | None = None,
    include_versions: bool = False,
    q: str = Query("", max_length=200),
    visibility: str | None = Query(None, pattern="^(organization|restricted|private)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    user: CurrentUser = Depends(get_current_user),
) -> list[DocumentResponse]:
    acl_clause, acl_params = document_acl_sql(user)
    filters = [f"({acl_clause})"]
    params: list[str | int] = list(acl_params)
    if knowledge_base_id:
        filters.append("d.knowledge_base_id = ?")
        params.append(knowledge_base_id)
    if not include_versions:
        filters.append("d.is_current = 1")
    if visibility:
        filters.append("d.visibility = ?")
        params.append(visibility)
    cleaned_query = q.strip().lower()
    if cleaned_query:
        filters.append(
            "(LOWER(d.title) LIKE ? ESCAPE '\\' OR LOWER(d.filename) LIKE ? ESCAPE '\\' "
            "OR LOWER(u.display_name) LIKE ? ESCAPE '\\')"
        )
        search_value = f"%{escape_like(cleaned_query)}%"
        params.extend([search_value, search_value, search_value])
    where_clause = " AND ".join(filters)
    offset = (page - 1) * page_size
    with db_session() as connection:
        total = connection.execute(
            f"SELECT COUNT(*) AS count FROM documents d JOIN users u ON u.id = d.owner_id WHERE {where_clause}",
            params,
        ).fetchone()["count"]
        rows = connection.execute(
            f"{DOCUMENT_SELECT} WHERE {where_clause} "
            "ORDER BY d.created_at DESC, d.id DESC LIMIT ? OFFSET ?",
            [*params, page_size, offset],
        ).fetchall()
        set_pagination_headers(
            response, total=total, page=page, page_size=page_size
        )
        return [_serialize_document(connection, row) for row in rows]


@router.post("", response_model=DocumentResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(""),
    knowledge_base_id: str | None = Form(None),
    visibility: str = Form("organization"),
    group_ids: str = Form("[]"),
    user_ids: str = Form("[]"),
    tags: str = Form("[]"),
    chunk_strategy: str | None = Form(None),
    version_of: str | None = Form(None),
    user: CurrentUser = Depends(get_current_user),
) -> DocumentResponse:
    if visibility not in {"organization", "restricted", "private"}:
        raise HTTPException(status_code=422, detail="无效的可见范围")
    parsed_group_ids = _json_string_list(group_ids, "用户组")
    parsed_user_ids = _json_string_list(user_ids, "指定用户")
    parsed_tags = _json_string_list(tags, "标签")
    settings = get_settings()
    content = await file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="文件超过直接上传上限，请使用分片上传")
    document_id = await ingest_document(
        user=user,
        filename=file.filename or "document",
        content_type=file.content_type or "application/octet-stream",
        content=content,
        title=title,
        knowledge_base_id=knowledge_base_id,
        visibility=visibility,
        group_ids=parsed_group_ids,
        user_ids=parsed_user_ids,
        tags=parsed_tags,
        chunk_strategy=chunk_strategy,
        version_of=version_of,
    )
    return _get_uploaded_document(document_id, user)


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(
    document_id: str, user: CurrentUser = Depends(get_current_user)
) -> DocumentResponse:
    return _get_document(document_id, user)


@router.get("/{document_id}/status", response_model=DocumentResponse)
def document_status(
    document_id: str, user: CurrentUser = Depends(get_current_user)
) -> DocumentResponse:
    """Polling-friendly status endpoint for asynchronous ingestion."""
    return _get_document(document_id, user)


@router.get("/{document_id}/versions", response_model=list[DocumentResponse])
def document_versions(
    document_id: str,
    response: Response,
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    user: CurrentUser = Depends(get_current_user),
) -> list[DocumentResponse]:
    current = _get_document(document_id, user)
    acl_clause, acl_params = document_acl_sql(user)
    params = [current.version_group_id, *acl_params]
    offset = (page - 1) * page_size
    with db_session() as connection:
        total = connection.execute(
            f"SELECT COUNT(*) AS count FROM documents d "
            f"WHERE d.version_group_id = ? AND ({acl_clause})",
            params,
        ).fetchone()["count"]
        rows = connection.execute(
            f"""
            {DOCUMENT_SELECT}
            WHERE d.version_group_id = ? AND ({acl_clause})
            ORDER BY d.version_number DESC, d.id DESC LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
        ).fetchall()
        set_pagination_headers(
            response, total=total, page=page, page_size=page_size
        )
        return [_serialize_document(connection, row) for row in rows]


@router.post("/{document_id}/activate", response_model=DocumentResponse)
def activate_document_version(
    document_id: str, user: CurrentUser = Depends(get_current_user)
) -> DocumentResponse:
    with db_session() as connection:
        row = connection.execute(
            "SELECT id, knowledge_base_id, version_group_id FROM documents WHERE id = ? AND org_id = ?",
            (document_id, user.org_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="文档版本不存在")
        require_knowledge_base_permission(connection, user, row["knowledge_base_id"], "edit")
        connection.execute(
            "UPDATE documents SET is_current = 0, archived_at = ? WHERE version_group_id = ?",
            (utc_now(), row["version_group_id"]),
        )
        connection.execute(
            "UPDATE documents SET is_current = 1, archived_at = NULL WHERE id = ?",
            (document_id,),
        )
        write_audit(connection, user, "document.version.activate", "document", document_id)
    return _get_document(document_id, user)


@router.post("/{document_id}/reparse")
async def reparse(
    document_id: str, user: CurrentUser = Depends(get_current_user)
) -> dict[str, int | str]:
    count = await reparse_document(document_id, user)
    return {"status": "indexed", "chunk_count": count}


@router.patch("/{document_id}/permissions", response_model=DocumentResponse)
def update_document_permissions(
    document_id: str,
    payload: DocumentPermissionUpdate,
    user: CurrentUser = Depends(get_current_user),
) -> DocumentResponse:
    with db_session() as connection:
        row = connection.execute(
            "SELECT id, owner_id, visibility, knowledge_base_id FROM documents WHERE id = ? AND org_id = ?",
            (document_id, user.org_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="文档不存在或无权修改权限")
        require_knowledge_base_permission(connection, user, row["knowledge_base_id"], "edit")
        groups, users = validate_document_acl(
            connection,
            user.org_id,
            payload.visibility,
            payload.group_ids,
            payload.user_ids,
        )
        previous_groups = [
            item["group_id"]
            for item in connection.execute(
                "SELECT group_id FROM document_groups WHERE document_id = ?", (document_id,)
            ).fetchall()
        ]
        previous_users = [
            item["user_id"]
            for item in connection.execute(
                "SELECT user_id FROM document_users WHERE document_id = ?", (document_id,)
            ).fetchall()
        ]
        connection.execute(
            "UPDATE documents SET visibility = ? WHERE id = ?", (payload.visibility, document_id)
        )
        connection.execute("DELETE FROM document_groups WHERE document_id = ?", (document_id,))
        connection.execute("DELETE FROM document_users WHERE document_id = ?", (document_id,))
        connection.executemany(
            "INSERT INTO document_groups (document_id, group_id) VALUES (?, ?)",
            [(document_id, group_id) for group_id in groups],
        )
        connection.executemany(
            "INSERT INTO document_users (document_id, user_id) VALUES (?, ?)",
            [(document_id, target_user_id) for target_user_id in users],
        )
        write_audit(
            connection,
            user,
            "document.permissions.update",
            "document",
            document_id,
            metadata={
                "from_visibility": row["visibility"],
                "to_visibility": payload.visibility,
                "from_group_ids": previous_groups,
                "to_group_ids": groups,
                "from_user_ids": previous_users,
                "to_user_ids": users,
            },
        )
    return _get_document(document_id, user)


@router.get("/{document_id}/download")
def download_document(document_id: str, user: CurrentUser = Depends(get_current_user)):
    document = _get_document(document_id, user)
    path = get_settings().upload_dir / f"{document_id}{Path(document.filename).suffix.lower()}"
    if not path.exists():
        raise HTTPException(status_code=404, detail="原始文件不存在")
    return FileResponse(path, filename=document.filename, media_type=document.content_type)


@router.get("/{document_id}/chunks/{chunk_id}", response_model=ChunkResponse)
def get_chunk(
    document_id: str,
    chunk_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> ChunkResponse:
    acl_clause, acl_params = document_acl_sql(user)
    with db_session() as connection:
        row = connection.execute(
            f"""
            SELECT c.id, c.document_id, d.title, c.page_number, c.paragraph_number, c.text
            FROM chunks c JOIN documents d ON d.id = c.document_id
            WHERE c.id = ? AND c.document_id = ? AND ({acl_clause})
            """,
            [chunk_id, document_id, *acl_params],
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="引用片段不存在或无权访问")
    return ChunkResponse(**dict(row))


@router.delete("/{document_id}", status_code=204, response_class=Response)
def delete_document(
    document_id: str, user: CurrentUser = Depends(get_current_user)
) -> Response:
    with db_session() as connection:
        row = connection.execute(
            "SELECT * FROM documents WHERE id = ? AND org_id = ?", (document_id, user.org_id)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="文档不存在或无权删除")
        require_knowledge_base_permission(connection, user, row["knowledge_base_id"], "edit")
        chunk_rows = connection.execute(
            "SELECT id FROM chunks WHERE document_id = ?", (document_id,)
        ).fetchall()
        try:
            get_vector_store().delete_chunks(
                user.org_id,
                row["knowledge_base_id"],
                [chunk["id"] for chunk in chunk_rows],
            )
        except VectorStoreError as exc:
            raise HTTPException(status_code=503, detail="向量库暂时不可用，文档未删除") from exc
        connection.executemany(
            "DELETE FROM chunks_fts WHERE chunk_id = ?", [(chunk["id"],) for chunk in chunk_rows]
        )
        connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        if row["is_current"]:
            replacement = connection.execute(
                "SELECT id FROM documents WHERE version_group_id = ? ORDER BY version_number DESC LIMIT 1",
                (row["version_group_id"],),
            ).fetchone()
            if replacement:
                connection.execute(
                    "UPDATE documents SET is_current = 1, archived_at = NULL WHERE id = ?",
                    (replacement["id"],),
                )
        write_audit(connection, user, "document.delete", "document", document_id)
    path = get_settings().upload_dir / f"{document_id}{Path(row['filename']).suffix.lower()}"
    path.unlink(missing_ok=True)
    return Response(status_code=204)
