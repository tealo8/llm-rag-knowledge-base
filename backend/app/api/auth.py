from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..db import db_session
from ..schemas import LoginRequest, LoginResponse, UserResponse
from ..security import CurrentUser, create_access_token, get_current_user, verify_password


router = APIRouter(prefix="/auth", tags=["auth"])


def serialize_user(user_id: str) -> UserResponse:
    with db_session() as connection:
        row = connection.execute(
            """
            SELECT u.id, u.org_id, o.name AS organization, u.username, u.display_name,
                   u.email, u.role
            FROM users u JOIN organizations o ON o.id = u.org_id
            WHERE u.id = ?
            """,
            (user_id,),
        ).fetchone()
        groups = connection.execute(
            """
            SELECT g.name FROM groups g
            JOIN user_groups ug ON ug.group_id = g.id
            WHERE ug.user_id = ? ORDER BY g.name
            """,
            (user_id,),
        ).fetchall()
    if row is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return UserResponse(**dict(row), groups=[group["name"] for group in groups])


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest) -> LoginResponse:
    with db_session() as connection:
        row = connection.execute(
            "SELECT id, password_hash FROM users WHERE username = ? AND active = 1",
            (payload.username,),
        ).fetchone()
    if row is None or not verify_password(payload.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return LoginResponse(
        access_token=create_access_token(row["id"]),
        user=serialize_user(row["id"]),
    )


@router.get("/me", response_model=UserResponse)
def me(user: CurrentUser = Depends(get_current_user)) -> UserResponse:
    return serialize_user(user.id)

