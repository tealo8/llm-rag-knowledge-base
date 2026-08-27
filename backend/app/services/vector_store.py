from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from ..config import get_settings


class VectorStoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class VectorRecord:
    chunk_id: str
    document_id: str
    vector: list[float]


@dataclass(frozen=True)
class VectorMatch:
    chunk_id: str
    score: float


class VectorStore(Protocol):
    name: str

    def upsert(self, org_id: str, knowledge_base_id: str, records: list[VectorRecord]) -> None: ...
    def delete_chunks(self, org_id: str, knowledge_base_id: str, chunk_ids: list[str]) -> None: ...
    def search(
        self,
        org_id: str,
        knowledge_base_id: str,
        query_vector: list[float],
        authorized_document_ids: list[str],
        limit: int,
        minimum_similarity: float,
    ) -> list[VectorMatch]: ...
    def health(self) -> dict: ...


class SqliteVectorStore:
    name = "sqlite"

    def upsert(self, org_id: str, knowledge_base_id: str, records: list[VectorRecord]) -> None:
        return None

    def delete_chunks(self, org_id: str, knowledge_base_id: str, chunk_ids: list[str]) -> None:
        return None

    def search(self, *args, **kwargs) -> list[VectorMatch]:
        raise VectorStoreError("sqlite vectors are queried by the retrieval service")

    def health(self) -> dict:
        return {"provider": self.name, "ready": True, "isolation": "logical SQL ACL"}


class ChromaVectorStore:
    name = "chroma"

    def __init__(self) -> None:
        try:
            import chromadb
        except ImportError as exc:
            raise VectorStoreError(
                "Chroma 驱动未安装，请安装 backend/requirements-vector.txt"
            ) from exc
        self.client = chromadb.PersistentClient(path=str(get_settings().chroma_path))

    @staticmethod
    def _collection_name(org_id: str, knowledge_base_id: str) -> str:
        digest = hashlib.sha256(f"{org_id}:{knowledge_base_id}".encode()).hexdigest()[:24]
        return f"kb-{digest}"

    def _collection(self, org_id: str, knowledge_base_id: str):
        return self.client.get_or_create_collection(
            self._collection_name(org_id, knowledge_base_id),
            metadata={"hnsw:space": "cosine", "org_id": org_id, "knowledge_base_id": knowledge_base_id},
        )

    def upsert(self, org_id: str, knowledge_base_id: str, records: list[VectorRecord]) -> None:
        if not records:
            return
        try:
            self._collection(org_id, knowledge_base_id).upsert(
                ids=[record.chunk_id for record in records],
                embeddings=[record.vector for record in records],
                metadatas=[{"document_id": record.document_id} for record in records],
            )
        except Exception as exc:
            raise VectorStoreError(f"Chroma 写入失败: {str(exc)[:240]}") from exc

    def delete_chunks(self, org_id: str, knowledge_base_id: str, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        try:
            self._collection(org_id, knowledge_base_id).delete(ids=chunk_ids)
        except Exception as exc:
            raise VectorStoreError(f"Chroma 删除失败: {str(exc)[:240]}") from exc

    def search(
        self,
        org_id: str,
        knowledge_base_id: str,
        query_vector: list[float],
        authorized_document_ids: list[str],
        limit: int,
        minimum_similarity: float,
    ) -> list[VectorMatch]:
        if not authorized_document_ids:
            return []
        try:
            result = self._collection(org_id, knowledge_base_id).query(
                query_embeddings=[query_vector],
                n_results=limit,
                where={"document_id": {"$in": authorized_document_ids}},
                include=["distances"],
            )
            ids = result.get("ids", [[]])[0]
            distances = result.get("distances", [[]])[0]
            return [
                VectorMatch(chunk_id=chunk_id, score=1.0 - float(distance))
                for chunk_id, distance in zip(ids, distances, strict=True)
                if 1.0 - float(distance) >= minimum_similarity
            ]
        except Exception as exc:
            raise VectorStoreError(f"Chroma 查询失败: {str(exc)[:240]}") from exc

    def health(self) -> dict:
        try:
            self.client.heartbeat()
            return {"provider": self.name, "ready": True, "isolation": "collection per knowledge base"}
        except Exception as exc:
            return {"provider": self.name, "ready": False, "error": str(exc)[:160]}


class PgVectorStore:
    name = "pgvector"

    def __init__(self) -> None:
        try:
            import psycopg
        except ImportError as exc:
            raise VectorStoreError(
                "PGVector 驱动未安装，请安装 backend/requirements-vector.txt"
            ) from exc
        self.psycopg = psycopg
        self.dsn = get_settings().pgvector_dsn
        dimensions = get_settings().pgvector_dimensions
        try:
            with self.psycopg.connect(self.dsn) as connection:
                connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
                connection.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS knowledge_vectors (
                        chunk_id TEXT PRIMARY KEY,
                        org_id TEXT NOT NULL,
                        knowledge_base_id TEXT NOT NULL,
                        document_id TEXT NOT NULL,
                        embedding vector({dimensions}) NOT NULL
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_vectors_scope ON knowledge_vectors(org_id, knowledge_base_id, document_id)"
                )
        except Exception as exc:
            raise VectorStoreError(f"PGVector 初始化失败: {str(exc)[:240]}") from exc

    @staticmethod
    def _vector(value: list[float]) -> str:
        return "[" + ",".join(str(item) for item in value) + "]"

    def upsert(self, org_id: str, knowledge_base_id: str, records: list[VectorRecord]) -> None:
        if not records:
            return
        try:
            with self.psycopg.connect(self.dsn) as connection:
                connection.executemany(
                    """
                    INSERT INTO knowledge_vectors
                        (chunk_id, org_id, knowledge_base_id, document_id, embedding)
                    VALUES (%s, %s, %s, %s, %s::vector)
                    ON CONFLICT(chunk_id) DO UPDATE SET
                        org_id=excluded.org_id,
                        knowledge_base_id=excluded.knowledge_base_id,
                        document_id=excluded.document_id,
                        embedding=excluded.embedding
                    """,
                    [
                        (record.chunk_id, org_id, knowledge_base_id, record.document_id, self._vector(record.vector))
                        for record in records
                    ],
                )
        except Exception as exc:
            raise VectorStoreError(f"PGVector 写入失败: {str(exc)[:240]}") from exc

    def delete_chunks(self, org_id: str, knowledge_base_id: str, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        try:
            with self.psycopg.connect(self.dsn) as connection:
                connection.execute(
                    "DELETE FROM knowledge_vectors WHERE org_id = %s AND knowledge_base_id = %s AND chunk_id = ANY(%s)",
                    (org_id, knowledge_base_id, chunk_ids),
                )
        except Exception as exc:
            raise VectorStoreError(f"PGVector 删除失败: {str(exc)[:240]}") from exc

    def search(
        self,
        org_id: str,
        knowledge_base_id: str,
        query_vector: list[float],
        authorized_document_ids: list[str],
        limit: int,
        minimum_similarity: float,
    ) -> list[VectorMatch]:
        if not authorized_document_ids:
            return []
        try:
            with self.psycopg.connect(self.dsn) as connection:
                rows = connection.execute(
                    """
                    SELECT chunk_id, 1 - (embedding <=> %s::vector) AS score
                    FROM knowledge_vectors
                    WHERE org_id = %s AND knowledge_base_id = %s
                      AND document_id = ANY(%s)
                      AND 1 - (embedding <=> %s::vector) >= %s
                    ORDER BY embedding <=> %s::vector LIMIT %s
                    """,
                    (
                        self._vector(query_vector), org_id, knowledge_base_id,
                        authorized_document_ids, self._vector(query_vector),
                        minimum_similarity, self._vector(query_vector), limit,
                    ),
                ).fetchall()
            return [VectorMatch(chunk_id=row[0], score=float(row[1])) for row in rows]
        except Exception as exc:
            raise VectorStoreError(f"PGVector 查询失败: {str(exc)[:240]}") from exc

    def health(self) -> dict:
        try:
            with self.psycopg.connect(self.dsn, connect_timeout=3) as connection:
                connection.execute("SELECT 1")
            return {"provider": self.name, "ready": True, "isolation": "logical tenant and knowledge-base columns"}
        except Exception as exc:
            return {"provider": self.name, "ready": False, "error": str(exc)[:160]}


@lru_cache
def get_vector_store() -> VectorStore:
    provider = get_settings().vector_store
    if provider == "chroma":
        return ChromaVectorStore()
    if provider == "pgvector":
        return PgVectorStore()
    return SqliteVectorStore()
