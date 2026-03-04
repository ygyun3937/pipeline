"""
FastAPI 엔드포인트 통합 테스트 (v2).

실제 외부 API 없이 파이프라인을 Mock으로 대체하여 API 레이어만 테스트한다.

개선 사항:
    - /health 엔드포인트: embedding_model 필드 검증 추가
    - /api/v1/index: mode 파라미터(add|update) 전달 검증
    - IndexResponse: chunks_deleted 필드 포함 검증
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.main import app, get_pipeline
from src.generation.generator import GenerationResult
from src.retrieval.retriever import RetrievalResults


def _make_mock_pipeline() -> MagicMock:
    """테스트용 Mock 파이프라인을 생성한다."""
    mock = MagicMock()

    # query()는 async이므로 AsyncMock으로 설정
    mock_retrieval = RetrievalResults(query="테스트", results=[])
    mock.query = AsyncMock(return_value=GenerationResult(
        question="테스트 질문",
        answer="### 1. 증상\n테스트 답변입니다.\n\n### 2. 원인\n확인 불가",
        context_used=mock_retrieval,
        model_name="claude-agent-sdk",
        input_tokens=100,
        output_tokens=50,
    ))

    # search_only() 결과 설정
    mock.search_only.return_value = RetrievalResults(query="테스트", results=[])

    # index_documents() 결과 설정 (add 모드 기본)
    mock.index_documents.return_value = {
        "files_processed": 3,
        "files_failed": 0,
        "chunks_total": 15,
        "chunks_added": 15,
        "chunks_skipped": 0,
        "chunks_deleted": 0,
    }

    # get_index_stats() 결과 설정
    mock.get_index_stats.return_value = {
        "collection_name": "issue_documents",
        "total_chunks": 42,
    }

    return mock


@pytest.fixture
def mock_pipeline():
    """테스트용 Mock 파이프라인 fixture."""
    return _make_mock_pipeline()


@pytest.fixture
def client(mock_pipeline):
    """테스트 클라이언트를 생성하고 파이프라인 의존성을 Mock으로 교체한다."""
    # FastAPI 의존성 오버라이드
    app.dependency_overrides[get_pipeline] = lambda: mock_pipeline

    with TestClient(app) as test_client:
        yield test_client

    # 테스트 후 오버라이드 초기화
    app.dependency_overrides.clear()


class TestHealthEndpoint:
    """헬스체크 엔드포인트 테스트."""

    def test_health_returns_200(self, client: TestClient) -> None:
        """GET /health가 200을 반환하는지 확인한다."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_response_structure(self, client: TestClient) -> None:
        """헬스체크 응답에 필수 필드가 있는지 확인한다."""
        response = client.get("/health")
        data = response.json()
        assert "status" in data
        assert "version" in data
        assert "model" in data

    def test_health_response_contains_embedding_model(
        self, client: TestClient
    ) -> None:
        """헬스체크 응답에 embedding_model 필드가 있는지 확인한다 (v2 신규)."""
        response = client.get("/health")
        data = response.json()
        assert "embedding_model" in data

    def test_health_status_is_healthy(self, client: TestClient) -> None:
        """헬스체크 응답의 status가 'healthy'인지 확인한다."""
        response = client.get("/health")
        data = response.json()
        assert data["status"] == "healthy"


class TestQueryEndpoint:
    """RAG 쿼리 엔드포인트 테스트."""

    def test_query_returns_answer(self, client: TestClient) -> None:
        """POST /api/v1/query가 답변을 반환하는지 확인한다."""
        response = client.post(
            "/api/v1/query",
            json={"question": "로그인 오류의 원인은?"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "answer" in data
        assert len(data["answer"]) > 0

    def test_query_response_has_required_fields(self, client: TestClient) -> None:
        """쿼리 응답에 필수 필드가 있는지 확인한다."""
        response = client.post(
            "/api/v1/query",
            json={"question": "테스트 질문"},
        )
        data = response.json()
        assert "question" in data
        assert "answer" in data
        assert "model" in data
        assert "context_count" in data
        assert "usage" in data

    def test_query_with_empty_question_returns_422(self, client: TestClient) -> None:
        """빈 질문으로 요청하면 422 Unprocessable Entity가 반환되는지 확인한다."""
        response = client.post(
            "/api/v1/query",
            json={"question": ""},
        )
        assert response.status_code == 422

    def test_query_with_context(self, client: TestClient) -> None:
        """include_context=true일 때 context 필드가 포함되는지 확인한다."""
        response = client.post(
            "/api/v1/query",
            json={"question": "테스트 질문", "include_context": True},
        )
        data = response.json()
        assert "context" in data
        assert isinstance(data["context"], list)

    def test_query_without_context_is_none(self, client: TestClient) -> None:
        """include_context=false(기본값)일 때 context 필드가 None인지 확인한다."""
        response = client.post(
            "/api/v1/query",
            json={"question": "테스트 질문"},
        )
        data = response.json()
        assert data["context"] is None

    def test_query_top_k_validation(self, client: TestClient) -> None:
        """top_k가 허용 범위(1~20)를 벗어나면 422가 반환되는지 확인한다."""
        response = client.post(
            "/api/v1/query",
            json={"question": "테스트", "top_k": 0},
        )
        assert response.status_code == 422

        response = client.post(
            "/api/v1/query",
            json={"question": "테스트", "top_k": 21},
        )
        assert response.status_code == 422


class TestSearchEndpoint:
    """검색 엔드포인트 테스트."""

    def test_search_returns_results(self, client: TestClient) -> None:
        """POST /api/v1/search가 정상 응답을 반환하는지 확인한다."""
        response = client.post(
            "/api/v1/search",
            json={"query": "데이터베이스 오류"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "query" in data
        assert "result_count" in data
        assert "results" in data

    def test_search_empty_query_returns_422(self, client: TestClient) -> None:
        """빈 쿼리로 검색하면 422가 반환되는지 확인한다."""
        response = client.post(
            "/api/v1/search",
            json={"query": ""},
        )
        assert response.status_code == 422


class TestIndexEndpoint:
    """문서 인덱싱 엔드포인트 테스트."""

    def test_index_add_mode_default(self, client: TestClient, mock_pipeline) -> None:
        """기본 add 모드로 인덱싱 요청이 처리되는지 확인한다."""
        response = client.post(
            "/api/v1/index",
            json={},
        )
        assert response.status_code == 200
        data = response.json()
        assert "files_processed" in data
        assert "chunks_added" in data

        # mode 기본값이 "add"인지 확인 (파이프라인 호출 인자)
        call_kwargs = mock_pipeline.index_documents.call_args
        assert call_kwargs.kwargs.get("mode") == "add"

    def test_index_update_mode(self, client: TestClient, mock_pipeline) -> None:
        """update 모드로 인덱싱 요청이 처리되는지 확인한다."""
        # update 모드에서 deleted 값 반환
        mock_pipeline.index_documents.return_value = {
            "files_processed": 2,
            "files_failed": 0,
            "chunks_total": 10,
            "chunks_added": 10,
            "chunks_skipped": 0,
            "chunks_deleted": 8,
        }

        response = client.post(
            "/api/v1/index",
            json={"mode": "update"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["chunks_deleted"] == 8

        # mode="update"가 파이프라인에 전달되었는지 확인
        call_kwargs = mock_pipeline.index_documents.call_args
        assert call_kwargs.kwargs.get("mode") == "update"

    def test_index_response_has_chunks_deleted(self, client: TestClient) -> None:
        """IndexResponse에 chunks_deleted 필드가 있는지 확인한다 (v2 신규)."""
        response = client.post("/api/v1/index", json={})
        data = response.json()
        assert "chunks_deleted" in data

    def test_index_invalid_mode_returns_422(self, client: TestClient) -> None:
        """잘못된 mode 값으로 요청 시 422가 반환되는지 확인한다."""
        response = client.post(
            "/api/v1/index",
            json={"mode": "invalid_mode"},
        )
        assert response.status_code == 422


class TestStatsEndpoint:
    """통계 엔드포인트 테스트."""

    def test_stats_returns_correct_data(self, client: TestClient) -> None:
        """GET /api/v1/stats가 인덱스 통계를 반환하는지 확인한다."""
        response = client.get("/api/v1/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total_chunks"] == 42
        assert data["collection_name"] == "issue_documents"

    def test_stats_fields_present(self, client: TestClient) -> None:
        """통계 응답에 필수 필드가 있는지 확인한다."""
        response = client.get("/api/v1/stats")
        data = response.json()
        assert "collection_name" in data
        assert "total_chunks" in data
