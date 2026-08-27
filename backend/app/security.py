from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import get_settings
from .db import db_session


bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    id: str
    org_id: str
    username: str
    display_name: str
    email: str
    role: str


def hash_password(password: str, salt: bytes | None = None) -> str:
    password_salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), password_salt, 240_000)
    return f"pbkdf2_sha256$240000${password_salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(candidate.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_access_token(user_id: str) -> str:
    settings = get_settings()
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    now = int(time.time())
    payload = _b64url(
        json.dumps(
            {"sub": user_id, "iat": now, "exp": now + settings.jwt_ttl_minutes * 60},
            separators=(",", ":"),
        ).encode()
    )
    signature = _b64url(
        hmac.new(settings.jwt_secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    )
    return f"{header}.{payload}.{signature}"


def decode_access_token(token: str) -> str:
    try:
        header, payload, signature = token.split(".")
        expected = _b64url(
            hmac.new(
                get_settings().jwt_secret.encode(),
                f"{header}.{payload}".encode(),
                hashlib.sha256,
            ).digest()
        )
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid signature")
        claims = json.loads(_b64decode(payload))
        if int(claims["exp"]) < int(time.time()):
            raise ValueError("expired")
        return str(claims["sub"])
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录凭证无效或已过期",
        ) from exc


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(status_code=401, detail="请先登录")
    user_id = decode_access_token(credentials.credentials)
    with db_session() as connection:
        row = connection.execute(
            """
            SELECT id, org_id, username, display_name, email, role
            FROM users WHERE id = ? AND active = 1
            """,
            (user_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="用户不存在或已停用")
    return CurrentUser(**dict(row))


def require_roles(*roles: str):
    def dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="当前角色无权执行此操作")
        return user

    return dependency


KB_PERMISSION_CAPABILITIES = {
    "view": {"view"},
    "upload": {"upload"},
    "edit": {"view", "upload", "edit"},
    "admin": {"view", "upload", "edit", "admin"},
}


def knowledge_base_permission(
    connection, user: CurrentUser, knowledge_base_id: str
) -> str | None:
    knowledge_base = connection.execute(
        "SELECT id FROM knowledge_bases WHERE id = ? AND org_id = ?",
        (knowledge_base_id, user.org_id),
    ).fetchone()
    if knowledge_base is None:
        return None
    if user.role == "admin":
        return "admin"
    row = connection.execute(
        """
        SELECT permission FROM knowledge_base_access
        WHERE knowledge_base_id = ? AND user_id = ?
        """,
        (knowledge_base_id, user.id),
    ).fetchone()
    return str(row["permission"]) if row else None


def require_knowledge_base_permission(
    connection,
    user: CurrentUser,
    knowledge_base_id: str,
    minimum: str = "view",
) -> str:
    permission = knowledge_base_permission(connection, user, knowledge_base_id)
    if permission is None:
        raise HTTPException(status_code=404, detail="知识库不存在或无权访问")
    if minimum not in KB_PERMISSION_CAPABILITIES[permission]:
        raise HTTPException(status_code=403, detail="当前知识库权限不足")
    return permission


def document_acl_sql(user: CurrentUser, alias: str = "d") -> tuple[str, list[str]]:
    if user.role == "admin":
        return f"{alias}.org_id = ?", [user.org_id]
    clause = f"""
        {alias}.org_id = ?
        AND EXISTS (
            SELECT 1 FROM knowledge_base_access kba
            WHERE kba.knowledge_base_id = {alias}.knowledge_base_id
              AND kba.user_id = ?
              AND kba.permission IN ('view', 'edit', 'admin')
        )
        AND (
            {alias}.visibility = 'organization'
            OR {alias}.owner_id = ?
            OR (
                {alias}.visibility = 'restricted'
                AND (
                    EXISTS (
                        SELECT 1
                        FROM document_groups dg
                        JOIN user_groups ug ON ug.group_id = dg.group_id
                        WHERE dg.document_id = {alias}.id AND ug.user_id = ?
                    )
                    OR EXISTS (
                        SELECT 1 FROM document_users du
                        WHERE du.document_id = {alias}.id AND du.user_id = ?
                    )
                )
            )
        )
    """
    return clause, [user.org_id, user.id, user.id, user.id, user.id]
