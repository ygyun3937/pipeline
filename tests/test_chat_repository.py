"""
ChatRepository 단위 테스트.
asyncpg.Pool을 Mock으로 대체하여 실제 DB 없이 테스트한다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.chat.models import ChatMessage, ChatSession, FeedbackType, MessageRole
from src.chat.repository import ChatRepository, _row_to_message


# ---------------------------------------------------------------------------
# 헬퍼: asyncpg Record 모킹
# ---------------------------------------------------------------------------

def _make_record(**kwargs) -> MagicMock:
    """asyncpg.Record처럼 동작하는 mock을 반환한다."""
    rec = MagicMock()
    rec.__getitem__ = lambda self, key: kwargs[key]
    rec.keys = lambda: list(kwargs.keys())
    return rec


_NOW = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def _session_record(
    sid: str = "s-001",
    title: str = "새 대화",
    message_count: int = 0,
) -> MagicMock:
    return _make_record(
        id=sid,
        title=title,
        created_at=_NOW,
        updated_at=_NOW,
        message_count=message_count,
    )


def _message_record(
    mid: str = "m-001",
    session_id: str = "s-001",
    role: str = "user",
    content: str = "hello",
    context_doc_ids=None,
    feedback: str | None = None,
) -> MagicMock:
    return _make_record(
        id=mid,
        session_id=session_id,
        role=role,
        content=content,
        context_doc_ids=context_doc_ids if context_doc_ids is not None else [],
        feedback=feedback,
        created_at=_NOW,
    )


# ---------------------------------------------------------------------------
# Fixture: mock pool + repository (already initialized)
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_pool():
    pool = MagicMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    pool.close = AsyncMock()
    return pool, conn


@pytest.fixture
def repo(mock_pool):
    pool, conn = mock_pool
    r = ChatRepository.__new__(ChatRepository)
    r._url = "postgresql://pipeline:pipeline@localhost:5432/issue_pipeline"
    r._pool = pool
    return r, conn


# ---------------------------------------------------------------------------
# Session tests
# ---------------------------------------------------------------------------

class TestChatSession:
    async def test_create_session_default_title(self, repo):
        r, conn = repo
        conn.execute = AsyncMock(return_value=None)
        session = await r.create_session()
        assert session.id
        assert session.title == "새 대화"

    async def test_create_session_custom_title(self, repo):
        r, conn = repo
        conn.execute = AsyncMock(return_value=None)
        session = await r.create_session(title="OVP 알람 문의")
        assert session.title == "OVP 알람 문의"

    async def test_get_session_returns_correct(self, repo):
        r, conn = repo
        conn.fetchrow = AsyncMock(return_value=_session_record("s-001", "테스트 세션"))
        fetched = await r.get_session("s-001")
        assert fetched is not None
        assert fetched.id == "s-001"
        assert fetched.title == "테스트 세션"

    async def test_get_session_not_found(self, repo):
        r, conn = repo
        conn.fetchrow = AsyncMock(return_value=None)
        result = await r.get_session("nonexistent-id")
        assert result is None

    async def test_list_sessions_empty(self, repo):
        r, conn = repo
        conn.fetch = AsyncMock(return_value=[])
        sessions = await r.list_sessions()
        assert sessions == []

    async def test_list_sessions_returns_items(self, repo):
        r, conn = repo
        conn.fetch = AsyncMock(return_value=[
            _session_record("s-002", "두 번째"),
            _session_record("s-001", "첫 번째"),
        ])
        sessions = await r.list_sessions()
        assert len(sessions) == 2
        assert sessions[0].id == "s-002"

    async def test_update_session_title(self, repo):
        r, conn = repo
        conn.execute = AsyncMock(return_value=None)
        await r.update_session_title("s-001", "수정된 제목")
        conn.execute.assert_awaited_once()

    async def test_delete_session_returns_true(self, repo):
        r, conn = repo
        conn.execute = AsyncMock(return_value="DELETE 1")
        result = await r.delete_session("s-001")
        assert result is True

    async def test_delete_nonexistent_session_returns_false(self, repo):
        r, conn = repo
        conn.execute = AsyncMock(return_value="DELETE 0")
        result = await r.delete_session("nonexistent")
        assert result is False


# ---------------------------------------------------------------------------
# Message tests
# ---------------------------------------------------------------------------

class TestChatMessage:
    async def test_add_user_message(self, repo):
        r, conn = repo
        conn.execute = AsyncMock(return_value=None)
        msg = await r.add_message("s-001", MessageRole.USER, "OVP 알람 원인은?")
        assert msg.role == MessageRole.USER
        assert msg.content == "OVP 알람 원인은?"
        assert msg.session_id == "s-001"

    async def test_add_assistant_message_with_context(self, repo):
        r, conn = repo
        conn.execute = AsyncMock(return_value=None)
        ctx = ["BATTERY-2024-001", "BATTERY-2024-005"]
        msg = await r.add_message(
            "s-001", MessageRole.ASSISTANT, "OVP-001은 센서 캘리브레이션 오류입니다.", context_doc_ids=ctx
        )
        assert msg.context_doc_ids == ctx

    async def test_get_messages_ordered(self, repo):
        r, conn = repo
        conn.fetch = AsyncMock(return_value=[
            _message_record("m-1", role="user", content="질문1"),
            _message_record("m-2", role="assistant", content="답변1"),
            _message_record("m-3", role="user", content="질문2"),
        ])
        messages = await r.get_messages("s-001")
        assert len(messages) == 3
        assert messages[0].role == MessageRole.USER
        assert messages[1].role == MessageRole.ASSISTANT
        assert messages[2].role == MessageRole.USER

    async def test_get_messages_empty_for_new_session(self, repo):
        r, conn = repo
        conn.fetch = AsyncMock(return_value=[])
        messages = await r.get_messages("s-001")
        assert messages == []

    async def test_get_recent_messages_limit(self, repo):
        r, conn = repo
        conn.fetch = AsyncMock(return_value=[
            _message_record(f"m-{i}", content=f"메시지 {i}") for i in range(3)
        ])
        recent = await r.get_recent_messages("s-001", limit=3)
        assert len(recent) == 3

    async def test_context_doc_ids_default_empty(self, repo):
        r, conn = repo
        conn.execute = AsyncMock(return_value=None)
        msg = await r.add_message("s-001", MessageRole.USER, "질문")
        assert msg.context_doc_ids == []

    async def test_update_message_feedback_returns_true(self, repo):
        r, conn = repo
        conn.execute = AsyncMock(return_value="UPDATE 1")
        result = await r.update_message_feedback("m-001", FeedbackType.THUMBS_UP)
        assert result is True

    async def test_update_message_feedback_returns_false_when_not_found(self, repo):
        r, conn = repo
        conn.execute = AsyncMock(return_value="UPDATE 0")
        result = await r.update_message_feedback("no-such", FeedbackType.THUMBS_UP)
        assert result is False


# ---------------------------------------------------------------------------
# _row_to_message helper
# ---------------------------------------------------------------------------

class TestRowToMessage:
    def test_parses_jsonb_list(self):
        rec = _message_record(context_doc_ids=["doc1", "doc2"])
        msg = _row_to_message(rec)
        assert msg.context_doc_ids == ["doc1", "doc2"]

    def test_parses_json_string(self):
        rec = _message_record(context_doc_ids='["doc1"]')
        msg = _row_to_message(rec)
        assert msg.context_doc_ids == ["doc1"]

    def test_none_context_doc_ids(self):
        rec = _message_record(context_doc_ids=None)
        msg = _row_to_message(rec)
        assert msg.context_doc_ids == []

    def test_feedback_parsed(self):
        rec = _message_record(feedback="thumbs_up")
        msg = _row_to_message(rec)
        assert msg.feedback == FeedbackType.THUMBS_UP

    def test_feedback_none(self):
        rec = _message_record(feedback=None)
        msg = _row_to_message(rec)
        assert msg.feedback is None
