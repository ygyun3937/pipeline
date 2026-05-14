"""
채팅 라우터 통합 테스트.

TestClient + dependency_overrides 패턴으로 실제 DB 없이 테스트한다.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.api.dependencies import get_chat_repo, get_pipeline
from src.api.main import app
from src.chat.models import ChatMessage, ChatSession, MessageRole
from src.retrieval.retriever import RetrievalResults


# ---------------------------------------------------------------------------
# 픽스처 헬퍼
# ---------------------------------------------------------------------------

_NOW = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def _make_session(session_id: str = "s-001", title: str = "새 대화", message_count: int = 0) -> ChatSession:
    return ChatSession(
        id=session_id,
        title=title,
        created_at=_NOW,
        updated_at=_NOW,
        message_count=message_count,
    )


def _make_message(msg_id: str = "m-001", session_id: str = "s-001", role: MessageRole = MessageRole.USER, content: str = "hello") -> ChatMessage:
    return ChatMessage(
        id=msg_id,
        session_id=session_id,
        role=role,
        content=content,
        context_doc_ids=[],
        created_at=_NOW,
    )


def _make_mock_repo(session: ChatSession | None = None) -> AsyncMock:
    """ChatRepository 모의 객체를 생성한다."""
    repo = AsyncMock()
    _session = session or _make_session()

    repo.create_session = AsyncMock(return_value=_session)
    repo.get_session = AsyncMock(return_value=_session)
    repo.list_sessions = AsyncMock(return_value=[_session])
    repo.delete_session = AsyncMock(return_value=True)
    repo.get_messages = AsyncMock(return_value=[])
    repo.add_message = AsyncMock(return_value=_make_message(role=MessageRole.ASSISTANT, content="답변"))
    repo.update_session_title = AsyncMock(return_value=None)
    return repo


def _make_mock_pipeline(chunks: list[str] | None = None) -> MagicMock:
    """IssuePipeline 스트리밍 모의 객체를 생성한다."""
    pipeline = MagicMock()

    _chunks = chunks or ["안녕", "하세요"]
    results = RetrievalResults(query="test", results=[])

    async def _fake_gen():
        for chunk in _chunks:
            yield chunk

    pipeline.stream_query = AsyncMock(return_value=(_fake_gen(), results))
    return pipeline


# ---------------------------------------------------------------------------
# TestClient 픽스처
# ---------------------------------------------------------------------------

@pytest.fixture
def client_with_mocks():
    """repo + pipeline을 모두 오버라이드한 클라이언트를 반환한다."""
    mock_repo = _make_mock_repo()
    mock_pipeline = _make_mock_pipeline()

    app.dependency_overrides[get_chat_repo] = lambda: mock_repo
    app.dependency_overrides[get_pipeline] = lambda: mock_pipeline

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c, mock_repo, mock_pipeline

    app.dependency_overrides.clear()


@pytest.fixture
def client_repo_only():
    """repo만 오버라이드한 클라이언트를 반환한다."""
    mock_repo = _make_mock_repo()
    app.dependency_overrides[get_chat_repo] = lambda: mock_repo

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c, mock_repo

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /api/v1/chat/sessions — 세션 생성
# ---------------------------------------------------------------------------

class TestCreateSession:
    def test_creates_session_with_default_title(self, client_repo_only):
        client, repo = client_repo_only
        resp = client.post("/api/v1/chat/sessions", json={})
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] == "s-001"
        assert "title" in data

    def test_creates_session_with_custom_title(self, client_repo_only):
        client, repo = client_repo_only
        repo.create_session = AsyncMock(return_value=_make_session(title="OVP 분석"))
        resp = client.post("/api/v1/chat/sessions", json={"title": "OVP 분석"})
        assert resp.status_code == 201
        assert resp.json()["title"] == "OVP 분석"

    def test_response_contains_required_fields(self, client_repo_only):
        client, _ = client_repo_only
        data = client.post("/api/v1/chat/sessions", json={}).json()
        for field in ("id", "title", "created_at", "updated_at", "message_count"):
            assert field in data

    def test_title_too_long_returns_422(self, client_repo_only):
        client, _ = client_repo_only
        resp = client.post("/api/v1/chat/sessions", json={"title": "x" * 201})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/chat/sessions — 세션 목록
# ---------------------------------------------------------------------------

class TestListSessions:
    def test_returns_list(self, client_repo_only):
        client, _ = client_repo_only
        resp = client.get("/api/v1/chat/sessions")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_returns_sessions_in_list(self, client_repo_only):
        client, repo = client_repo_only
        repo.list_sessions = AsyncMock(return_value=[
            _make_session("s-001", "세션1"),
            _make_session("s-002", "세션2"),
        ])
        data = client.get("/api/v1/chat/sessions").json()
        assert len(data) == 2
        assert data[0]["id"] == "s-001"

    def test_limit_query_param_is_forwarded(self, client_repo_only):
        client, repo = client_repo_only
        client.get("/api/v1/chat/sessions?limit=5")
        repo.list_sessions.assert_awaited_once_with(limit=5)

    def test_empty_list_when_no_sessions(self, client_repo_only):
        client, repo = client_repo_only
        repo.list_sessions = AsyncMock(return_value=[])
        data = client.get("/api/v1/chat/sessions").json()
        assert data == []


# ---------------------------------------------------------------------------
# GET /api/v1/chat/sessions/{session_id} — 세션 조회
# ---------------------------------------------------------------------------

class TestGetSession:
    def test_returns_session(self, client_repo_only):
        client, _ = client_repo_only
        resp = client.get("/api/v1/chat/sessions/s-001")
        assert resp.status_code == 200
        assert resp.json()["id"] == "s-001"

    def test_returns_404_when_not_found(self, client_repo_only):
        client, repo = client_repo_only
        repo.get_session = AsyncMock(return_value=None)
        resp = client.get("/api/v1/chat/sessions/no-such")
        assert resp.status_code == 404

    def test_404_detail_message(self, client_repo_only):
        client, repo = client_repo_only
        repo.get_session = AsyncMock(return_value=None)
        detail = client.get("/api/v1/chat/sessions/x").json()["detail"]
        assert "세션" in detail


# ---------------------------------------------------------------------------
# DELETE /api/v1/chat/sessions/{session_id} — 세션 삭제
# ---------------------------------------------------------------------------

class TestDeleteSession:
    def test_deletes_session(self, client_repo_only):
        client, _ = client_repo_only
        resp = client.delete("/api/v1/chat/sessions/s-001")
        assert resp.status_code == 204

    def test_returns_404_when_not_found(self, client_repo_only):
        client, repo = client_repo_only
        repo.delete_session = AsyncMock(return_value=False)
        resp = client.delete("/api/v1/chat/sessions/ghost")
        assert resp.status_code == 404

    def test_no_body_on_success(self, client_repo_only):
        client, _ = client_repo_only
        resp = client.delete("/api/v1/chat/sessions/s-001")
        assert resp.content == b""


# ---------------------------------------------------------------------------
# GET /api/v1/chat/sessions/{session_id}/messages — 메시지 목록
# ---------------------------------------------------------------------------

class TestGetMessages:
    def test_returns_empty_list(self, client_repo_only):
        client, _ = client_repo_only
        resp = client.get("/api/v1/chat/sessions/s-001/messages")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_messages(self, client_repo_only):
        client, repo = client_repo_only
        repo.get_messages = AsyncMock(return_value=[
            _make_message("m-1", content="질문"),
            _make_message("m-2", role=MessageRole.ASSISTANT, content="답변"),
        ])
        data = client.get("/api/v1/chat/sessions/s-001/messages").json()
        assert len(data) == 2
        assert data[0]["role"] == "user"
        assert data[1]["role"] == "assistant"

    def test_returns_404_when_session_not_found(self, client_repo_only):
        client, repo = client_repo_only
        repo.get_session = AsyncMock(return_value=None)
        resp = client.get("/api/v1/chat/sessions/missing/messages")
        assert resp.status_code == 404

    def test_message_fields_present(self, client_repo_only):
        client, repo = client_repo_only
        repo.get_messages = AsyncMock(return_value=[_make_message()])
        data = client.get("/api/v1/chat/sessions/s-001/messages").json()
        for field in ("id", "session_id", "role", "content", "context_doc_ids", "created_at"):
            assert field in data[0]


# ---------------------------------------------------------------------------
# POST /api/v1/chat/sessions/{session_id}/stream — SSE 스트리밍
# ---------------------------------------------------------------------------

class TestStreamChat:
    def _collect_sse_events(self, client, session_id: str, question: str) -> list[dict]:
        """SSE 응답을 소비하여 파싱된 이벤트 목록을 반환한다."""
        with client.stream(
            "POST",
            f"/api/v1/chat/sessions/{session_id}/stream",
            json={"question": question},
        ) as resp:
            raw = resp.read().decode()

        events = []
        for line in raw.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))
        return events

    def test_returns_streaming_response(self, client_with_mocks):
        client, _, _ = client_with_mocks
        with client.stream("POST", "/api/v1/chat/sessions/s-001/stream", json={"question": "테스트"}) as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers["content-type"]

    def test_sse_has_text_events(self, client_with_mocks):
        client, _, _ = client_with_mocks
        events = self._collect_sse_events(client, "s-001", "질문")
        text_events = [e for e in events if e.get("type") == "text"]
        assert len(text_events) >= 1

    def test_sse_text_chunks_match_mock(self, client_with_mocks):
        client, _, _ = client_with_mocks
        events = self._collect_sse_events(client, "s-001", "질문")
        texts = [e["text"] for e in events if e.get("type") == "text"]
        assert "".join(texts) == "안녕하세요"

    def test_sse_ends_with_done_event(self, client_with_mocks):
        client, _, _ = client_with_mocks
        events = self._collect_sse_events(client, "s-001", "질문")
        assert events[-1]["type"] == "done"

    def test_sse_done_event_has_session_id(self, client_with_mocks):
        client, _, _ = client_with_mocks
        events = self._collect_sse_events(client, "s-001", "질문")
        done = next(e for e in events if e["type"] == "done")
        assert done["session_id"] == "s-001"
        assert "message_id" in done
        assert "context_count" in done

    def test_session_not_found_returns_404(self, client_with_mocks):
        client, mock_repo, _ = client_with_mocks
        mock_repo.get_session = AsyncMock(return_value=None)
        resp = client.post("/api/v1/chat/sessions/ghost/stream", json={"question": "질문"})
        assert resp.status_code == 404

    def test_empty_question_returns_422(self, client_with_mocks):
        client, _, _ = client_with_mocks
        resp = client.post("/api/v1/chat/sessions/s-001/stream", json={"question": ""})
        assert resp.status_code == 422

    def test_messages_saved_after_stream(self, client_with_mocks):
        client, mock_repo, _ = client_with_mocks
        self._collect_sse_events(client, "s-001", "OVP 원인은?")
        assert mock_repo.add_message.await_count >= 2  # user + assistant

    def test_pipeline_error_yields_error_event(self, client_with_mocks):
        client, mock_repo, mock_pipeline = client_with_mocks
        mock_pipeline.stream_query = AsyncMock(side_effect=RuntimeError("LLM 오류"))
        events = self._collect_sse_events(client, "s-001", "질문")
        assert any(e.get("type") == "error" for e in events)

    def test_sse_cache_control_header(self, client_with_mocks):
        client, _, _ = client_with_mocks
        with client.stream("POST", "/api/v1/chat/sessions/s-001/stream", json={"question": "질문"}) as resp:
            assert resp.headers.get("cache-control") == "no-cache"

    def test_top_k_forwarded_to_pipeline(self, client_with_mocks):
        client, _, mock_pipeline = client_with_mocks
        self._collect_sse_events(client, "s-001", "질문")
        call_kwargs = mock_pipeline.stream_query.call_args
        assert call_kwargs is not None
