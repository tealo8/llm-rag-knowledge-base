from __future__ import annotations

import argparse
import getpass
import sqlite3
import uuid

from .db import db_session, init_db, utc_now
from .security import hash_password


def bootstrap_admin(args: argparse.Namespace) -> None:
    password = args.password or getpass.getpass("Initial admin password: ")
    if len(password) < 12:
        raise SystemExit("管理员密码至少需要 12 个字符")
    init_db()
    try:
        with db_session() as connection:
            organization = connection.execute(
                "SELECT id FROM organizations WHERE slug = ?", (args.org_slug,)
            ).fetchone()
            org_id = str(organization["id"]) if organization else str(uuid.uuid4())
            if organization is None:
                connection.execute(
                    "INSERT INTO organizations (id, name, slug, created_at) VALUES (?, ?, ?, ?)",
                    (org_id, args.org_name, args.org_slug, utc_now()),
                )
            connection.execute(
                """
                INSERT INTO users
                    (id, org_id, username, display_name, email, password_hash, role, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'admin', ?)
                """,
                (
                    str(uuid.uuid4()),
                    org_id,
                    args.username,
                    args.display_name,
                    args.email,
                    hash_password(password),
                    utc_now(),
                ),
            )
    except sqlite3.IntegrityError as exc:
        raise SystemExit(f"初始化失败，组织标识或用户名可能已存在：{exc}") from exc
    print(f"Created admin {args.username!r} in organization {args.org_slug!r}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Knowledge Hub administration CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    bootstrap = subparsers.add_parser("bootstrap-admin", help="create the first organization admin")
    bootstrap.add_argument("--org-name", required=True)
    bootstrap.add_argument("--org-slug", required=True)
    bootstrap.add_argument("--username", required=True)
    bootstrap.add_argument("--display-name", required=True)
    bootstrap.add_argument("--email", required=True)
    bootstrap.add_argument("--password", help="prefer the interactive prompt to avoid shell history")
    bootstrap.set_defaults(handler=bootstrap_admin)
    args = parser.parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
