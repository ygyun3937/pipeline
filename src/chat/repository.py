"""
SQLite 기반 대화 세션 저장소.

aiosqlite를 사용하여 비동기로 SQLite에 접근한다.
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

import aiosqlite

from src.chat.models import ChatMessage, ChatSession, MessageRole
from src.logger import get_logger

logger = get_logger(__name__)

_CREATE_SESSIONS = """
CREATE TABLE IF NOT EXISTS chat_sessions (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_CREATE_MESSAGES = """
CREATE TABLE IF NOT EXISTS chat_messages (
    id               TEXT PRIMARY KEY,
    session_id       TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role             TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content          TEXT NOT NULL,
    context_doc_ids  TEXT NOT NULL DEFAULT '[]',
    created_at       TEXT NOT NULL
)
"""

_CREATE_IDX_SESSION = (
    "CREATE INDEX IF NOT EXISTS idx_messages_session ON chat_messages(session_id)"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


class ChatRepository:
    """SQLite 기반 대화 세션 CRUD."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)

    async def initialize(self) -> None:
        """테이블 및 인덱스를 생성한다. 이미 존재하면 무시."""
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            await db.execute(_CREATE_SESSIONS)
            await db.execute(_CREATE_MESSAGES)
            await db.execute(_CREATE_IDX_SESSION)
            await db.commit()
        logger.info("ChatRepository 초기화 완료: %s", self._db_path)

    # ---- 세션 ----

    async def create_session(self, title: str = "") -> ChatSession:
        session = ChatSession(
            id=str(uuid.uuid4()),
            title=title or "새 대화",
        )
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT INTO chat_sessions(id, title, created_at, updated_at) VALUES (?,?,?,?)",
                (session.id, session.title, session.created_at.isoformat(), session.updated_at.isoformat()),
            )
            await db.commit()
        return session

    async def get_session(self, session_id: str) -> ChatSession | None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT s.*, COUNT(m.id) AS message_count "
                "FROM chat_sessions s "
                "LEFT JOIN chat_messages m ON m.session_id = s.id "
                "WHERE s.id = ? GROUP BY s.id",
                (session_id,),
            ) as cur:
                row = await cur.fetchone()
        if row is None:
            return None
        return ChatSession(
            id=row["id"],
            title=row["title"],
            created_at=_parse_dt(row["created_at"]),
            updated_at=_parse_dt(row["updated_at"]),
            message_count=row["message_count"],
        )

    async def list_sessions(self, limit: int = 20) -> list[ChatSession]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT s.*, COUNT(m.id) AS message_count "
                "FROM chat_sessions s "
                "LEFT JOIN chat_messages m ON m.session_id = s.id "
                "GROUP BY s.id ORDER BY s.updated_at DESC LIMIT ?",
                (limit,),
            ) as cur:
                rows = await cur.fetchall()
        return [
            ChatSession(
                id=r["id"],
                title=r["title"],
                created_at=_parse_dt(r["created_at"]),
                updated_at=_parse_dt(r["updated_at"]),
                message_count=r["message_count"],
            )
            for r in rows
        ]

    async def update_session_title(self, session_id: str, title: str) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE chat_sessions SET title=?, updated_at=? WHERE id=?",
                (title, _now_iso(), session_id),
            )
            await db.commit()

    async def delete_session(self, session_id: str) -> bool:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            cur = await db.execute(
                "DELETE FROM chat_sessions WHERE id=?", (session_id,)
            )
            await db.commit()
            return cur.rowcount > 0

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
        now = msg.created_at.isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            await db.execute(
                "INSERT INTO chat_messages(id, session_id, role, content, context_doc_ids, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (msg.id, session_id, role.value, content, json.dumps(context_doc_ids or []), now),
            )
            await db.execute(
                "UPDATE chat_sessions SET updated_at=? WHERE id=?",
                (now, session_id),
            )
            await db.commit()
        return msg

    async def get_messages(self, session_id: str) -> list[ChatMessage]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM chat_messages WHERE session_id=? ORDER BY created_at",
                (session_id,),
            ) as cur:
                rows = await cur.fetchall()
        return [
            ChatMessage(
                id=r["id"],
                session_id=r["session_id"],
                role=MessageRole(r["role"]),
                content=r["content"],
                context_doc_ids=json.loads(r["context_doc_ids"]),
                created_at=_parse_dt(r["created_at"]),
            )
            for r in rows
        ]

    async def get_recent_messages(self, session_id: str, limit: int = 10) -> list[ChatMessage]:
        """최근 N개 메시지를 시간 순으로 반환 (LLM 컨텍스트 윈도우 제어용)."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM ("
                "  SELECT * FROM chat_messages WHERE session_id=? ORDER BY created_at DESC LIMIT ?"
                ") ORDER BY created_at",
                (session_id, limit),
            ) as cur:
                rows = await cur.fetchall()
        return [
            ChatMessage(
                id=r["id"],
                session_id=r["session_id"],
                role=MessageRole(r["role"]),
                content=r["content"],
                context_doc_ids=json.loads(r["context_doc_ids"]),
                created_at=_parse_dt(r["created_at"]),
            )
            for r in rows
        ]
