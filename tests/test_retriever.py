"""
검색(Retrieval) 모듈 테스트.

외부 API 의존성을 Mock으로 대체하여 단위 테스트를 수행한다.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from langchain_core.documents import Document

from src.retrieval.retriever import IssueRetriever, RetrievalResults, SearchResult


def _make_mock_vectorstore(search_results: list[tuple[Document, float]]) -> MagicMock:
    """테스트용 Mock 벡터스토어를 생성한다."""
    mock_vs = MagicMock()
    mock_vs.similarity_search_with_score.return_value = search_results
    return mock_vs


def _make_document(content: str, filename: str = "test.md") -> Document:
    """테스트용 Document를 생성한다."""
    return Document(
        page_content=content,
        metadata={"filename": filename, "source": f"/path/{filename}"},
    )


class TestSearchResult:
    """SearchResult 데이터 클래스 테스트."""

    def test_to_dict(self) -> None:
        """SearchResult.to_dict()가 올바른 키를 포함하는지 확인한다."""
        doc = _make_document("테스트 내용")
        result = SearchResult(document=doc, score=0.85, rank=1)
        d = result.to_dict()

        assert d["rank"] == 1
        assert d["score"] == 0.85
        assert d["source"] == "test.md"
        assert d["content"] == "테스트 내용"


class TestRetrievalResults:
    """RetrievalResults 데이터 클래스 테스트."""

    def test_is_empty_when_no_results(self) -> None:
        """결과가 없으면 is_empty가 True인지 확인한다."""
        results = RetrievalResults(query="test", results=[])
        assert results.is_empty is True

    def test_top_result_returns_first(self) -> None:
        """top_result가 첫 번째 결과를 반환하는지 확인한다."""
        doc = _make_document("첫 번째 결과")
        result = SearchResult(document=doc, score=0.9, rank=1)
        results = RetrievalResults(query="test", results=[result])

        assert results.top_result is not None
        assert results.top_result.score == 0.9

    def test_top_result_none_when_empty(self) -> None:
        """결과가 없으면 top_result가 None인지 확인한다."""
        results = RetrievalResults(query="test", results=[])
        assert results.top_result is None

    def test_get_context_text_with_results(self) -> None:
        """검색 결과가 있을 때 컨텍스트 텍스트가 생성되는지 확인한다."""
        doc = _make_document("이슈 내용")
        result = SearchResult(document=doc, score=0.8, rank=1)
        results = RetrievalResults(query="test", results=[result])

        context = results.get_context_text()
        assert "이슈 내용" in context
        assert "test.md" in context

    def test_get_context_text_empty(self) -> None:
        """결과가 없을 때 '찾을 수 없습니다' 메시지가 반환되는지 확인한다."""
        results = RetrievalResults(query="test", results=[])
        context = results.get_context_text()
        assert "찾을 수 없습니다" in context


class TestIssueRetriever:
    """IssueRetriever 단위 테스트."""

    def test_search_returns_filtered_results(self) -> None:
        """유사도 임계값 미만 결과가 필터링되는지 확인한다."""
        # similarity_search_with_score는 cosine distance를 반환한다 (낮을수록 유사).
        # retriever 내부에서 score = 1.0 - distance 변환 후 임계값 필터링.
        # 0.15 distance → 0.85 similarity (통과)
        # 0.30 distance → 0.70 similarity (통과)
        # 0.80 distance → 0.20 similarity (임계값 0.3 미만 → 필터링)
        docs_with_distances = [
            (_make_document("관련 문서 A"), 0.15),
            (_make_document("관련 문서 B"), 0.30),
            (_make_document("관련 없는 문서"), 0.80),
        ]
        mock_vs = _make_mock_vectorstore(docs_with_distances)
        retriever = IssueRetriever(vectorstore=mock_vs, top_k=5, score_threshold=0.3)

        results = retriever.search("테스트 쿼리")

        assert len(results.results) == 2  # 0.80 distance(=0.20 similarity)는 필터링됨
        assert results.results[0].score == pytest.approx(0.85)

    def test_search_empty_query_returns_empty(self) -> None:
        """빈 쿼리로 검색하면 빈 결과를 반환하는지 확인한다."""
        mock_vs = _make_mock_vectorstore([])
        retriever = IssueRetriever(vectorstore=mock_vs)

        results = retriever.search("")
        assert results.is_empty

    def test_search_preserves_rank_order(self) -> None:
        """검색 결과의 순위가 반환 순서대로 배정되는지 확인한다."""
        # distance 값으로 전달 (ChromaDB cosine distance 방식)
        docs_with_distances = [
            (_make_document("A"), 0.1),   # 0.90 similarity
            (_make_document("B"), 0.3),   # 0.70 similarity
            (_make_document("C"), 0.5),   # 0.50 similarity
        ]
        mock_vs = _make_mock_vectorstore(docs_with_distances)
        retriever = IssueRetriever(vectorstore=mock_vs, score_threshold=0.0)

        results = retriever.search("쿼리")

        ranks = [r.rank for r in results.results]
        assert ranks == [1, 2, 3]


    def test_search_with_filter_passes_filter_to_vectorstore(self) -> None:
        """filter 파라미터가 vectorstore에 전달되는지 확인한다."""
        mock_vs = _make_mock_vectorstore([])
        retriever = IssueRetriever(vectorstore=mock_vs, top_k=5, score_threshold=0.0)

        retriever.search("쿼리", filter={"domain": "battery"})

        call_kwargs = mock_vs.similarity_search_with_score.call_args
        assert call_kwargs.kwargs.get("filter") == {"domain": "battery"}

    def test_search_without_filter_does_not_pass_filter_key(self) -> None:
        """filter 없이 검색 시 vectorstore에 filter 키가 전달되지 않는지 확인한다."""
        mock_vs = _make_mock_vectorstore([])
        retriever = IssueRetriever(vectorstore=mock_vs)

        retriever.search("쿼리")

        call_kwargs = mock_vs.similarity_search_with_score.call_args
        assert "filter" not in (call_kwargs.kwargs or {})

    def test_search_with_filter_convenience_method(self) -> None:
        """search_with_filter()가 search(filter=...)와 동일하게 동작하는지 확인한다."""
        mock_vs = _make_mock_vectorstore([])
        retriever = IssueRetriever(vectorstore=mock_vs, score_threshold=0.0)

        retriever.search_with_filter("쿼리", metadata_filter={"severity": "critical"})

        call_kwargs = mock_vs.similarity_search_with_score.call_args
        assert call_kwargs.kwargs.get("filter") == {"severity": "critical"}

    def test_invalid_score_threshold_raises(self) -> None:
        """유효하지 않은 임계값으로 초기화하면 ValueError가 발생하는지 확인한다."""
        mock_vs = MagicMock()
        with pytest.raises(ValueError, match="score_threshold"):
            IssueRetriever(vectorstore=mock_vs, score_threshold=1.5)

    def test_custom_top_k_overrides_default(self) -> None:
        """search() 호출 시 top_k 파라미터가 기본값을 오버라이드하는지 확인한다."""
        mock_vs = _make_mock_vectorstore([])
        retriever = IssueRetriever(vectorstore=mock_vs, top_k=5)

        retriever.search("쿼리", top_k=3)

        # Mock 호출 시 k=3으로 요청되었는지 확인
        call_kwargs = mock_vs.similarity_search_with_score.call_args
        assert call_kwargs.kwargs.get("k") == 3 or call_kwargs.args[1] == 3
