"""
PostgreSQL(asyncpg) 기반 대화 세션 저장소.

asyncpg를 사용하여 비동기로 PostgreSQL에 접근한다.
테이블은 초기화 시 자동 생성된다.

테이블 스키마:
    chat_sessions  — 세션 메타데이터
    chat_messages  — 개별 메시지 (session_id FK)
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import asyncpg

from src.chat.models import ChatMessage, ChatSession, FeedbackType, MessageRole
from src.logger import get_logger

logger = get_logger(__name__)

_CREATE_SESSIONS = """
CREATE TABLE IF NOT EXISTS chat_sessions (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
)
"""

_CREATE_MESSAGES = """
CREATE TABLE IF NOT EXISTS chat_messages (
    id               TEXT PRIMARY KEY,
    session_id       TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role             TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content          TEXT NOT NULL,
    context_doc_ids  JSONB NOT NULL DEFAULT '[]',
    feedback         TEXT DEFAULT NULL,
    created_at       TIMESTAMPTZ NOT NULL
)
"""

_CREATE_IDX_SESSION = (
    "CREATE INDEX IF NOT EXISTS idx_messages_session ON chat_messages(session_id)"
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class ChatRepository:
    """PostgreSQL(asyncpg) 기반 대화 세션 CRUD."""

    def __init__(self, postgres_url: str) -> None:
        # asyncpg는 postgresql:// 형식 URL을 직접 사용
        self._url = postgres_url
        self._pool: asyncpg.Pool | None = None

    async def initialize(self) -> None:
        """커넥션 풀 생성 및 테이블/인덱스를 생성한다. 이미 존재하면 무시."""
        self._pool = await asyncpg.create_pool(self._url)
        async with self._pool.acquire() as conn:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            await conn.execute(_CREATE_SESSIONS)
            await conn.execute(_CREATE_MESSAGES)
            await conn.execute(_CREATE_IDX_SESSION)
        logger.info("ChatRepository 초기화 완료: %s", self._url)

    async def close(self) -> None:
        """커넥션 풀을 닫는다."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    def _pool_or_raise(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("ChatRepository가 초기화되지 않았습니다. initialize()를 먼저 호출하세요.")
        return self._pool

    # ---- 세션 ----

    async def create_session(self, title: str = "") -> ChatSession:
        session = ChatSession(
            id=str(uuid.uuid4()),
            title=title or "새 대화",
        )
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO chat_sessions(id, title, created_at, updated_at) VALUES ($1,$2,$3,$4)",
                session.id, session.title, session.created_at, session.updated_at,
            )
        return session

    async def get_session(self, session_id: str) -> ChatSession | None:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT s.*, COUNT(m.id) AS message_count "
                "FROM chat_sessions s "
                "LEFT JOIN chat_messages m ON m.session_id = s.id "
                "WHERE s.id = $1 GROUP BY s.id",
                session_id,
            )
        if row is None:
            return None
        return ChatSession(
            id=row["id"],
            title=row["title"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            message_count=row["message_count"],
        )

    async def list_sessions(self, limit: int = 20) -> list[ChatSession]:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT s.*, COUNT(m.id) AS message_count "
                "FROM chat_sessions s "
                "LEFT JOIN chat_messages m ON m.session_id = s.id "
                "GROUP BY s.id ORDER BY s.updated_at DESC LIMIT $1",
                limit,
            )
        return [
            ChatSession(
                id=r["id"],
                title=r["title"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
                message_count=r["message_count"],
            )
            for r in rows
        ]

    async def update_session_title(self, session_id: str, title: str) -> None:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE chat_sessions SET title=$1, updated_at=$2 WHERE id=$3",
                title, _now_utc(), session_id,
            )

    async def delete_session(self, session_id: str) -> bool:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM chat_sessions WHERE id=$1", session_id
            )
        # asyncpg returns "DELETE N" string
        return result.split()[-1] != "0"

    # ---- 메시지 ----

    async def add_message(
        self,
        session_id: str,
        role: MessageRole,
        content: str,
        context_doc_ids: list[str] | None = None,
    ) -> ChatMessage:
        msg = ChatMessage(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role=role,
            content=content,
            context_doc_ids=context_doc_ids or [],
        )
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO chat_messages(id, session_id, role, content, context_doc_ids, created_at) "
                "VALUES ($1,$2,$3,$4,$5,$6)",
                msg.id, session_id, role.value, content,
                json.dumps(context_doc_ids or []),
                msg.created_at,
            )
            await conn.execute(
                "UPDATE chat_sessions SET updated_at=$1 WHERE id=$2",
                msg.created_at, session_id,
            )
        return msg

    async def get_messages(self, session_id: str) -> list[ChatMessage]:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM chat_messages WHERE session_id=$1 ORDER BY created_at",
                session_id,
            )
        return [_row_to_message(r) for r in rows]

    async def get_recent_messages(self, session_id: str, limit: int = 10) -> list[ChatMessage]:
        """최근 N개 메시지를 시간 순으로 반환 (LLM 컨텍스트 윈도우 제어용)."""
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM ("
                "  SELECT * FROM chat_messages WHERE session_id=$1 ORDER BY created_at DESC LIMIT $2"
                ") sub ORDER BY created_at",
                session_id, limit,
            )
        return [_row_to_message(r) for r in rows]

    async def update_message_feedback(
        self, message_id: str, feedback: FeedbackType | None
    ) -> bool:
        """메시지 피드백을 업데이트한다. 메시지가 없으면 False를 반환."""
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE chat_messages SET feedback=$1 WHERE id=$2",
                feedback.value if feedback else None, message_id,
            )
        return result.split()[-1] != "0"


def _row_to_message(r: asyncpg.Record) -> ChatMessage:
    """asyncpg Record를 ChatMessage로 변환한다."""
    raw_ctx = r["context_doc_ids"]
    # asyncpg는 JSONB를 자동으로 파이썬 객체로 변환하지만
    # 문자열로 반환될 수도 있으므로 방어적으로 처리한다.
    if isinstance(raw_ctx, str):
        context_doc_ids = json.loads(raw_ctx)
    else:
        context_doc_ids = raw_ctx if raw_ctx is not None else []

    return ChatMessage(
        id=r["id"],
        session_id=r["session_id"],
        role=MessageRole(r["role"]),
        content=r["content"],
        context_doc_ids=context_doc_ids,
        feedback=FeedbackType(r["feedback"]) if r["feedback"] else None,
        created_at=r["created_at"],
    )
