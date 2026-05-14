"""
ChatRepository 통합 테스트.
임시 SQLite 파일을 사용하므로 실제 DB에 영향을 주지 않는다.
"""

from __future__ import annotations

import pytest

from src.chat.models import ChatSession, MessageRole
from src.chat.repository import ChatRepository


@pytest.fixture
async def repo(tmp_path):
    r = ChatRepository(tmp_path / "test_chat.db")
    await r.initialize()
    return r


class TestChatSession:
    async def test_create_session_default_title(self, repo):
        session = await repo.create_session()
        assert session.id
        assert session.title == "새 대화"

    async def test_create_session_custom_title(self, repo):
        session = await repo.create_session(title="OVP 알람 문의")
        assert session.title == "OVP 알람 문의"

    async def test_get_session_returns_correct(self, repo):
        created = await repo.create_session(title="테스트 세션")
        fetched = await repo.get_session(created.id)
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.title == "테스트 세션"

    async def test_get_session_not_found(self, repo):
        result = await repo.get_session("nonexistent-id")
        assert result is None

    async def test_list_sessions_empty(self, repo):
        sessions = await repo.list_sessions()
        assert sessions == []

    async def test_list_sessions_ordered_by_updated_at(self, repo):
        s1 = await repo.create_session(title="첫 번째")
        s2 = await repo.create_session(title="두 번째")
        # 최신 순이므로 s2가 먼저 나와야 함
        sessions = await repo.list_sessions()
        assert len(sessions) == 2
        assert sessions[0].id == s2.id
        assert sessions[1].id == s1.id

    async def test_update_session_title(self, repo):
        session = await repo.create_session(title="원래 제목")
        await repo.update_session_title(session.id, "수정된 제목")
        fetched = await repo.get_session(session.id)
        assert fetched.title == "수정된 제목"

    async def test_delete_session_returns_true(self, repo):
        session = await repo.create_session()
        result = await repo.delete_session(session.id)
        assert result is True

    async def test_delete_nonexistent_session_returns_false(self, repo):
        result = await repo.delete_session("nonexistent")
        assert result is False

    async def test_delete_session_cascades_messages(self, repo):
        session = await repo.create_session()
        await repo.add_message(session.id, MessageRole.USER, "안녕하세요")
        await repo.delete_session(session.id)
        messages = await repo.get_messages(session.id)
        assert messages == []


class TestChatMessage:
    async def test_add_user_message(self, repo):
        session = await repo.create_session()
        msg = await repo.add_message(session.id, MessageRole.USER, "OVP 알람 원인은?")
        assert msg.role == MessageRole.USER
        assert msg.content == "OVP 알람 원인은?"
        assert msg.session_id == session.id

    async def test_add_assistant_message_with_context(self, repo):
        session = await repo.create_session()
        ctx = ["BATTERY-2024-001", "BATTERY-2024-005"]
        msg = await repo.add_message(
            session.id, MessageRole.ASSISTANT, "OVP-001은 센서 캘리브레이션 오류입니다.", context_doc_ids=ctx
        )
        assert msg.context_doc_ids == ctx

    async def test_get_messages_ordered(self, repo):
        session = await repo.create_session()
        await repo.add_message(session.id, MessageRole.USER, "질문1")
        await repo.add_message(session.id, MessageRole.ASSISTANT, "답변1")
        await repo.add_message(session.id, MessageRole.USER, "질문2")
        messages = await repo.get_messages(session.id)
        assert len(messages) == 3
        assert messages[0].role == MessageRole.USER
        assert messages[1].role == MessageRole.ASSISTANT
        assert messages[2].role == MessageRole.USER

    async def test_get_messages_empty_for_new_session(self, repo):
        session = await repo.create_session()
        messages = await repo.get_messages(session.id)
        assert messages == []

    async def test_get_recent_messages_limit(self, repo):
        session = await repo.create_session()
        for i in range(6):
            role = MessageRole.USER if i % 2 == 0 else MessageRole.ASSISTANT
            await repo.add_message(session.id, role, f"메시지 {i}")
        recent = await repo.get_recent_messages(session.id, limit=3)
        assert len(recent) == 3
        assert recent[-1].content == "메시지 5"

    async def test_message_count_in_session(self, repo):
        session = await repo.create_session()
        await repo.add_message(session.id, MessageRole.USER, "q1")
        await repo.add_message(session.id, MessageRole.ASSISTANT, "a1")
        fetched = await repo.get_session(session.id)
        assert fetched.message_count == 2

    async def test_add_message_updates_session_updated_at(self, repo):
        session = await repo.create_session()
        original_updated = session.updated_at
        await repo.add_message(session.id, MessageRole.USER, "새 메시지")
        fetched = await repo.get_session(session.id)
        assert fetched.updated_at >= original_updated

    async def test_context_doc_ids_default_empty(self, repo):
        session = await repo.create_session()
        msg = await repo.add_message(session.id, MessageRole.USER, "질문")
        assert msg.context_doc_ids == []
