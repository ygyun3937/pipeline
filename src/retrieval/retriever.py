"""
검색(Retrieval) 모듈.

ChromaDB에서 쿼리와 의미적으로 유사한 이슈 문서 청크를 검색한다.
유사도 점수 필터링을 통해 관련성 낮은 결과를 제거한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langchain_chroma import Chroma
from langchain_core.documents import Document

from src.logger import get_logger

logger = get_logger(__name__)


@dataclass
class SearchResult:
    """검색 결과 단위 객체."""

    document: Document
    score: float
    rank: int

    @property
    def source(self) -> str:
        """소스 파일 경로를 반환한다."""
        return self.document.metadata.get("filename", "unknown")

    @property
    def page_content(self) -> str:
        """청크의 텍스트 내용을 반환한다."""
        return self.document.page_content

    def to_dict(self) -> dict[str, Any]:
        """직렬화 가능한 딕셔너리로 변환한다."""
        return {
            "rank": self.rank,
            "score": round(self.score, 4),
            "source": self.source,
            "content": self.page_content,
            "metadata": self.document.metadata,
        }


@dataclass
class RetrievalResults:
    """검색 결과 집합 객체."""

    query: str
    results: list[SearchResult] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        """검색 결과가 없는지 확인한다."""
        return len(self.results) == 0

    @property
    def top_result(self) -> SearchResult | None:
        """가장 관련성 높은 결과를 반환한다."""
        return self.results[0] if self.results else None

    def get_context_text(self, separator: str = "\n\n---\n\n") -> str:
        """
        LLM 프롬프트에 삽입할 컨텍스트 텍스트를 생성한다.

        Args:
            separator: 청크 간 구분자

        Returns:
            포맷된 컨텍스트 텍스트
        """
        if self.is_empty:
            return "관련 이슈 문서를 찾을 수 없습니다."

        sections = []
        for result in self.results:
            section = (
                f"[출처: {result.source} | 유사도: {result.score:.3f}]\n"
                f"{result.page_content}"
            )
            sections.append(section)

        return separator.join(sections)

    def to_dict(self) -> dict[str, Any]:
        """직렬화 가능한 딕셔너리로 변환한다."""
        return {
            "query": self.query,
            "result_count": len(self.results),
            "results": [r.to_dict() for r in self.results],
        }


class IssueRetriever:
    """
    ChromaDB에서 이슈 관련 청크를 검색하는 클래스.

    검색 방식:
        - 코사인 유사도(cosine similarity) 기반 벡터 검색
        - 유사도 임계값 필터링으로 낮은 관련성 결과 제거
    """

    def __init__(
        self,
        vectorstore: Chroma,
        top_k: int = 5,
        score_threshold: float = 0.3,
    ) -> None:
        """
        Args:
            vectorstore: LangChain Chroma 인스턴스
            top_k: 반환할 최대 결과 수
            score_threshold: 최소 유사도 점수 (0.0 ~ 1.0)
                             이 값 미만의 결과는 필터링된다.
        """
        if not 0.0 <= score_threshold <= 1.0:
            raise ValueError(
                f"score_threshold는 0.0 ~ 1.0 사이여야 합니다: {score_threshold}"
            )

        self._vectorstore = vectorstore
        self.top_k = top_k
        self.score_threshold = score_threshold

        logger.info(
            "IssueRetriever 초기화: top_k=%d, score_threshold=%.2f",
            top_k,
            score_threshold,
        )

    def search(
        self,
        query: str,
        top_k: int | None = None,
        filter: dict[str, Any] | None = None,
    ) -> RetrievalResults:
        """
        쿼리와 유사한 이슈 문서 청크를 검색한다.

        Args:
            query: 검색 쿼리 텍스트
            top_k: 반환할 결과 수 (None이면 인스턴스 기본값 사용)
            filter: ChromaDB where 절 메타데이터 필터
                예: {"domain": "battery"} 또는 {"severity": "critical"}

        Returns:
            RetrievalResults 객체
        """
        if not query or not query.strip():
            logger.warning("빈 쿼리로 검색 시도됨.")
            return RetrievalResults(query=query, results=[])

        k = top_k if top_k is not None else self.top_k
        query = query.strip()

        logger.info(
            "검색 시작: query='%s' (top_k=%d, filter=%s)", query[:100], k, filter
        )

        try:
            search_kwargs: dict[str, Any] = {"query": query, "k": k}
            if filter:
                search_kwargs["filter"] = filter
            raw_results: list[tuple[Document, float]] = (
                self._vectorstore.similarity_search_with_score(**search_kwargs)
            )
        except Exception as exc:
            logger.error("벡터 검색 실패: %s", exc)
            raise RuntimeError(f"검색 중 오류 발생: {exc}") from exc

        # cosine distance -> similarity 변환 후 임계값 필터링
        filtered: list[SearchResult] = []
        for rank, (doc, distance) in enumerate(raw_results, start=1):
            score = 1.0 - distance  # cosine distance [0,2] -> similarity [-1,1]
            if score >= self.score_threshold:
                filtered.append(SearchResult(document=doc, score=score, rank=rank))
            else:
                logger.debug(
                    "낮은 유사도로 필터링: rank=%d, score=%.4f (threshold=%.2f)",
                    rank,
                    score,
                    self.score_threshold,
                )

        logger.info(
            "검색 완료: %d개 결과 (필터링 전: %d개)", len(filtered), len(raw_results)
        )

        return RetrievalResults(query=query, results=filtered)

    def search_with_filter(
        self,
        query: str,
        metadata_filter: dict[str, Any],
        top_k: int | None = None,
    ) -> RetrievalResults:
        """메타데이터 필터 검색. search(filter=...) 의 편의 래퍼."""
        return self.search(query=query, top_k=top_k, filter=metadata_filter)

    def as_langchain_retriever(self, **kwargs: Any):
        """
        LangChain 표준 Retriever 인터페이스로 변환한다.
        LangChain Expression Language(LCEL) 체인 구성에 사용한다.
        """
        return self._vectorstore.as_retriever(
            search_type="similarity_score_threshold",
            search_kwargs={
                "k": self.top_k,
                "score_threshold": self.score_threshold,
                **kwargs,
            },
        )
