from __future__ import annotations

import json
import sqlite3
import uuid

from ..db import utc_now
from ..security import CurrentUser


def write_audit(
    connection: sqlite3.Connection,
    user: CurrentUser,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    query: str | None = None,
    metadata: dict | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO audit_logs
            (id, org_id, user_id, action, resource_type, resource_id, query, metadata_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            user.org_id,
            user.id,
            action,
            resource_type,
            resource_id,
            query,
            json.dumps(metadata or {}, ensure_ascii=False),
            utc_now(),
        ),
    )

