from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..config import get_settings
from ..db import db_session, utc_now
from ..schemas import UploadSessionCreate, UploadSessionResponse
from ..security import CurrentUser, get_current_user, require_knowledge_base_permission
from ..services.audit import write_audit
from ..services.documents import ingest_document, safe_filename
from .documents import _get_uploaded_document


router = APIRouter(prefix="/uploads", tags=["uploads"])


def _serialize(row) -> UploadSessionResponse:
    return UploadSessionResponse(
        id=row["id"],
        filename=row["filename"],
        total_size=row["total_size"],
        received_size=row["received_size"],
        chunk_size=row["chunk_size"],
        next_part=row["received_size"] // row["chunk_size"],
        status=row["status"],
    )


@router.post("", response_model=UploadSessionResponse, status_code=201)
def create_upload_session(
    payload: UploadSessionCreate,
    user: CurrentUser = Depends(get_current_user),
) -> UploadSessionResponse:
    settings = get_settings()
    filename = safe_filename(payload.filename)
    if payload.total_size > settings.max_chunked_upload_bytes:
        raise HTTPException(status_code=413, detail="文件超过分片上传总大小上限")
    session_id = str(uuid.uuid4())
    now = utc_now()
    with db_session() as connection:
        require_knowledge_base_permission(
            connection, user, payload.knowledge_base_id, "upload"
        )
        connection.execute(
            """
            INSERT INTO upload_sessions
                (id, org_id, knowledge_base_id, user_id, filename, content_type,
                 total_size, received_size, chunk_size, metadata_json, status,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, 'open', ?, ?)
            """,
            (
                session_id,
                user.org_id,
                payload.knowledge_base_id,
                user.id,
                filename,
                payload.content_type,
                payload.total_size,
                payload.chunk_size,
                json.dumps(
                    {
                        "title": payload.title,
                        "visibility": payload.visibility,
                        "group_ids": payload.group_ids,
                        "user_ids": payload.user_ids,
                        "tags": payload.tags,
                        "chunk_strategy": payload.chunk_strategy,
                        "version_of": payload.version_of,
                    },
                    ensure_ascii=False,
                ),
                now,
                now,
            ),
        )
        row = connection.execute(
            "SELECT * FROM upload_sessions WHERE id = ?", (session_id,)
        ).fetchone()
    return _serialize(row)


@router.put("/{session_id}/parts/{part_number}", response_model=UploadSessionResponse)
async def upload_part(
    session_id: str,
    part_number: int,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> UploadSessionResponse:
    if part_number < 0:
        raise HTTPException(status_code=422, detail="分片编号必须从 0 开始")
    body = await request.body()
    with db_session() as connection:
        row = connection.execute(
            "SELECT * FROM upload_sessions WHERE id = ? AND org_id = ? AND user_id = ?",
            (session_id, user.org_id, user.id),
        ).fetchone()
        if row is None or row["status"] != "open":
            raise HTTPException(status_code=404, detail="上传会话不存在或已经结束")
        expected_part = row["received_size"] // row["chunk_size"]
        if part_number != expected_part:
            raise HTTPException(status_code=409, detail=f"应上传第 {expected_part} 个分片")
        remaining = row["total_size"] - row["received_size"]
        expected_size = min(row["chunk_size"], remaining)
        if not body or len(body) != expected_size:
            raise HTTPException(status_code=422, detail=f"当前分片大小必须为 {expected_size} bytes")
        path = get_settings().upload_session_dir / f"{session_id}.part"
        with path.open("ab") as output:
            output.write(body)
        received = row["received_size"] + len(body)
        connection.execute(
            "UPDATE upload_sessions SET received_size = ?, updated_at = ? WHERE id = ?",
            (received, utc_now(), session_id),
        )
        updated = connection.execute(
            "SELECT * FROM upload_sessions WHERE id = ?", (session_id,)
        ).fetchone()
    return _serialize(updated)


@router.post("/{session_id}/complete")
async def complete_upload(
    session_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, object]:
    with db_session() as connection:
        row = connection.execute(
            "SELECT * FROM upload_sessions WHERE id = ? AND org_id = ? AND user_id = ?",
            (session_id, user.org_id, user.id),
        ).fetchone()
        if row is None or row["status"] != "open":
            raise HTTPException(status_code=404, detail="上传会话不存在或已经结束")
        if row["received_size"] != row["total_size"]:
            raise HTTPException(status_code=409, detail="文件分片尚未全部上传")
        metadata = json.loads(row["metadata_json"])
    path = get_settings().upload_session_dir / f"{session_id}.part"
    if not path.exists() or path.stat().st_size != row["total_size"]:
        raise HTTPException(status_code=409, detail="服务端分片文件不完整")
    document_id = await ingest_document(
        user=user,
        filename=row["filename"],
        content_type=row["content_type"],
        content=path.read_bytes(),
        title=metadata["title"],
        knowledge_base_id=row["knowledge_base_id"],
        visibility=metadata["visibility"],
        group_ids=metadata["group_ids"],
        user_ids=metadata["user_ids"],
        tags=metadata["tags"],
        chunk_strategy=metadata["chunk_strategy"],
        version_of=metadata["version_of"],
    )
    with db_session() as connection:
        connection.execute(
            "UPDATE upload_sessions SET status = 'completed', updated_at = ? WHERE id = ?",
            (utc_now(), session_id),
        )
        write_audit(
            connection,
            user,
            "upload_session.complete",
            "upload_session",
            session_id,
            metadata={"document_id": document_id, "size_bytes": row["total_size"]},
        )
    path.unlink(missing_ok=True)
    return {
        "document_id": document_id,
        "status": "processing_complete",
        "document": _get_uploaded_document(document_id, user).model_dump(),
    }


@router.delete("/{session_id}", status_code=204, response_class=Response)
def abort_upload(
    session_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    with db_session() as connection:
        row = connection.execute(
            "SELECT id FROM upload_sessions WHERE id = ? AND org_id = ? AND user_id = ? AND status = 'open'",
            (session_id, user.org_id, user.id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="上传会话不存在或已经结束")
        connection.execute(
            "UPDATE upload_sessions SET status = 'aborted', updated_at = ? WHERE id = ?",
            (utc_now(), session_id),
        )
    (get_settings().upload_session_dir / f"{session_id}.part").unlink(missing_ok=True)
    return Response(status_code=204)
