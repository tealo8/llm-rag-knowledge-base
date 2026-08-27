from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .config import get_settings


SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS organizations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES organizations(id),
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    email TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'editor', 'viewer')),
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS groups (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES organizations(id),
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    UNIQUE (org_id, name)
);

CREATE TABLE IF NOT EXISTS user_groups (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    group_id TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, group_id)
);

CREATE TABLE IF NOT EXISTS knowledge_bases (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES organizations(id),
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    created_by TEXT REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (org_id, slug),
    UNIQUE (org_id, name)
);

CREATE TABLE IF NOT EXISTS knowledge_base_access (
    knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    permission TEXT NOT NULL CHECK (permission IN ('view', 'upload', 'edit', 'admin')),
    created_at TEXT NOT NULL,
    PRIMARY KEY (knowledge_base_id, user_id)
);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES organizations(id),
    owner_id TEXT NOT NULL REFERENCES users(id),
    knowledge_base_id TEXT REFERENCES knowledge_bases(id),
    filename TEXT NOT NULL,
    title TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    visibility TEXT NOT NULL CHECK (visibility IN ('organization', 'restricted', 'private')),
    status TEXT NOT NULL CHECK (status IN ('processing', 'indexed', 'failed')),
    chunk_count INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    tags_json TEXT NOT NULL DEFAULT '[]',
    version_group_id TEXT,
    version_number INTEGER NOT NULL DEFAULT 1,
    is_current INTEGER NOT NULL DEFAULT 1,
    archived_at TEXT,
    chunk_strategy TEXT NOT NULL DEFAULT 'fixed',
    created_at TEXT NOT NULL,
    UNIQUE (org_id, sha256)
);

CREATE TABLE IF NOT EXISTS document_groups (
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    group_id TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    PRIMARY KEY (document_id, group_id)
);

CREATE TABLE IF NOT EXISTS document_users (
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY (document_id, user_id)
);

CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    org_id TEXT NOT NULL REFERENCES organizations(id),
    knowledge_base_id TEXT REFERENCES knowledge_bases(id),
    position INTEGER NOT NULL,
    paragraph_number INTEGER,
    page_number INTEGER,
    text TEXT NOT NULL,
    search_text TEXT NOT NULL,
    embedding_json TEXT NOT NULL,
    embedding_model TEXT NOT NULL DEFAULT 'legacy',
    embedding_dimensions INTEGER NOT NULL DEFAULT 0,
    token_count INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (document_id, position)
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    chunk_id UNINDEXED,
    title,
    search_text,
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES organizations(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT,
    query TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS organization_settings (
    org_id TEXT PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
    settings_json TEXT NOT NULL DEFAULT '{}',
    updated_by TEXT REFERENCES users(id),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES organizations(id),
    knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    citations_json TEXT NOT NULL DEFAULT '[]',
    metrics_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS message_feedback (
    message_id TEXT NOT NULL REFERENCES conversation_messages(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rating TEXT NOT NULL CHECK (rating IN ('up', 'down')),
    comment TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    PRIMARY KEY (message_id, user_id)
);

CREATE TABLE IF NOT EXISTS upload_sessions (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES organizations(id),
    knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    total_size INTEGER NOT NULL,
    received_size INTEGER NOT NULL DEFAULT 0,
    chunk_size INTEGER NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'completed', 'aborted')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_dead_letters (
    id TEXT PRIMARY KEY,
    org_id TEXT REFERENCES organizations(id),
    task_id TEXT,
    task_name TEXT NOT NULL,
    document_id TEXT,
    error TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 1,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_users_org ON users(org_id);
CREATE INDEX IF NOT EXISTS idx_groups_org ON groups(org_id);
CREATE INDEX IF NOT EXISTS idx_kb_org_status ON knowledge_bases(org_id, status);
CREATE INDEX IF NOT EXISTS idx_kb_access_user ON knowledge_base_access(user_id, knowledge_base_id);
CREATE INDEX IF NOT EXISTS idx_documents_org_status ON documents(org_id, status);
CREATE INDEX IF NOT EXISTS idx_chunks_org_document ON chunks(org_id, document_id);
CREATE INDEX IF NOT EXISTS idx_audit_org_created ON audit_logs(org_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_conversations_user_updated ON conversations(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_conversation_created ON conversation_messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_dead_letters_created ON task_dead_letters(created_at DESC);
"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def connect(path: Path | None = None) -> sqlite3.Connection:
    db_path = path or get_settings().database_path
    connection = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def init_db(path: Path | None = None) -> None:
    with connect(path) as connection:
        connection.executescript(SCHEMA)
        _ensure_columns(
            connection,
            "chunks",
            {
                "embedding_model": "TEXT NOT NULL DEFAULT 'legacy'",
                "embedding_dimensions": "INTEGER NOT NULL DEFAULT 0",
                "knowledge_base_id": "TEXT REFERENCES knowledge_bases(id)",
                "paragraph_number": "INTEGER",
            },
        )
        _ensure_columns(
            connection,
            "documents",
            {
                "knowledge_base_id": "TEXT REFERENCES knowledge_bases(id)",
                "tags_json": "TEXT NOT NULL DEFAULT '[]'",
                "version_group_id": "TEXT",
                "version_number": "INTEGER NOT NULL DEFAULT 1",
                "is_current": "INTEGER NOT NULL DEFAULT 1",
                "archived_at": "TEXT",
                "chunk_strategy": "TEXT NOT NULL DEFAULT 'fixed'",
                "processing_stage": "TEXT NOT NULL DEFAULT 'queued'",
                "task_id": "TEXT",
            },
        )
        # Backfill stage values for databases created before asynchronous ingestion.
        connection.execute(
            "UPDATE documents SET processing_stage = CASE status WHEN 'indexed' THEN 'indexed' WHEN 'failed' THEN 'failed' ELSE COALESCE(processing_stage, 'queued') END"
        )
        _bootstrap_default_knowledge_bases(connection)
        connection.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_documents_kb_current
                ON documents(knowledge_base_id, is_current, status);
            CREATE INDEX IF NOT EXISTS idx_chunks_kb_document
                ON chunks(knowledge_base_id, document_id);
            """
        )


def _ensure_columns(
    connection: sqlite3.Connection,
    table: str,
    definitions: dict[str, str],
) -> None:
    columns = {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    for name, definition in definitions.items():
        if name not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _bootstrap_default_knowledge_bases(connection: sqlite3.Connection) -> None:
    now = utc_now()
    organizations = connection.execute("SELECT id, name FROM organizations").fetchall()
    for organization in organizations:
        kb_id = f"kb-default-{organization['id']}"
        creator = connection.execute(
            "SELECT id FROM users WHERE org_id = ? ORDER BY CASE role WHEN 'admin' THEN 0 ELSE 1 END LIMIT 1",
            (organization["id"],),
        ).fetchone()
        connection.execute(
            """
            INSERT OR IGNORE INTO knowledge_bases
                (id, org_id, name, slug, description, status, created_by, created_at, updated_at)
            VALUES (?, ?, ?, 'default', ?, 'active', ?, ?, ?)
            """,
            (
                kb_id,
                organization["id"],
                f"{organization['name']}知识库",
                "系统迁移的默认知识库",
                creator["id"] if creator else None,
                now,
                now,
            ),
        )
        connection.execute(
            "UPDATE documents SET knowledge_base_id = ?, version_group_id = COALESCE(version_group_id, id) WHERE org_id = ? AND knowledge_base_id IS NULL",
            (kb_id, organization["id"]),
        )
        connection.execute(
            """
            UPDATE chunks SET knowledge_base_id = ?
            WHERE org_id = ? AND knowledge_base_id IS NULL
            """,
            (kb_id, organization["id"]),
        )
        users = connection.execute(
            "SELECT id, role FROM users WHERE org_id = ?", (organization["id"],)
        ).fetchall()
        for user in users:
            permission = {
                "admin": "admin",
                "editor": "edit",
                "viewer": "view",
            }[user["role"]]
            connection.execute(
                """
                INSERT OR IGNORE INTO knowledge_base_access
                    (knowledge_base_id, user_id, permission, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (kb_id, user["id"], permission, now),
            )
        connection.execute(
            """
            INSERT OR IGNORE INTO organization_settings
                (org_id, settings_json, updated_by, updated_at)
            VALUES (?, '{}', ?, ?)
            """,
            (organization["id"], creator["id"] if creator else None, now),
        )


@contextmanager
def db_session() -> Generator[sqlite3.Connection, None, None]:
    connection = connect()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
