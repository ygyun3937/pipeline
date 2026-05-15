"""미답변 질문 추적기.

RAG 검색 결과가 없을 때 질문을 PostgreSQL 테이블에 저장한다.
관리자가 어떤 문서를 추가해야 하는지 파악하는 데 사용한다.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import asyncpg

from src.logger import get_logger

logger = get_logger(__name__)

_CREATE_MISSED_QUERIES = """
CREATE TABLE IF NOT EXISTS missed_queries (
    id         TEXT PRIMARY KEY,
    question   TEXT NOT NULL,
    session_id TEXT,
    logged_at  TIMESTAMPTZ NOT NULL,
    resolved   BOOLEAN NOT NULL DEFAULT FALSE
)
"""


class MissedQueryLogger:
    """미답변 질문을 PostgreSQL 테이블에 기록하는 유틸리티."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def create(cls, pool: asyncpg.Pool) -> "MissedQueryLogger":
        """테이블을 생성하고 인스턴스를 반환한다."""
        async with pool.acquire() as conn:
            await conn.execute(_CREATE_MISSED_QUERIES)
        return cls(pool)

    async def log(self, question: str, session_id: str | None = None) -> dict:
        """질문을 미답변 목록에 추가한다."""
        entry_id = str(uuid.uuid4())
        logged_at = datetime.now(timezone.utc)
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO missed_queries(id, question, session_id, logged_at, resolved) "
                "VALUES ($1, $2, $3, $4, $5)",
                entry_id, question, session_id, logged_at, False,
            )
        logger.info("미답변 질문 기록: '%s'", question[:80])
        return {
            "id": entry_id,
            "question": question,
            "session_id": session_id,
            "logged_at": logged_at.isoformat(),
            "resolved": False,
        }

    async def list_all(self, unresolved_only: bool = False) -> list[dict]:
        """저장된 미답변 질문 목록을 반환한다."""
        async with self._pool.acquire() as conn:
            if unresolved_only:
                rows = await conn.fetch(
                    "SELECT * FROM missed_queries WHERE resolved = FALSE ORDER BY logged_at DESC"
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM missed_queries ORDER BY logged_at DESC"
                )
        return [
            {
                "id": r["id"],
                "question": r["question"],
                "session_id": r["session_id"],
                "logged_at": r["logged_at"].isoformat(),
                "resolved": r["resolved"],
            }
            for r in rows
        ]

    async def mark_resolved(self, entry_id: str) -> bool:
        """특정 항목을 해결됨으로 표시한다."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE missed_queries SET resolved = TRUE WHERE id = $1",
                entry_id,
            )
        return result.split()[-1] != "0"
