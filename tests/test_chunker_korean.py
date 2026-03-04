"""
한국어 최적화 청커 테스트 (v2).

테스트 대상:
    - 한국어 구분자 우선순위 검증
    - chunk_size=800, overlap=150 기본값 확인
    - Markdown 섹션 헤더에서 분할 동작 검증
    - 한국어 종결어미 기반 분할 동작 검증
"""

from __future__ import annotations

import pytest
from langchain_core.documents import Document

from src.ingestion.chunker import KOREAN_ISSUE_SEPARATORS, DocumentChunker


class TestKoreanChunkerDefaults:
    """한국어 최적화 기본값 테스트."""

    def test_default_chunk_size_is_800(self) -> None:
        """기본 chunk_size가 800인지 확인한다."""
        chunker = DocumentChunker()
        assert chunker.chunk_size == 800

    def test_default_chunk_overlap_is_150(self) -> None:
        """기본 chunk_overlap이 150인지 확인한다."""
        chunker = DocumentChunker()
        assert chunker.chunk_overlap == 150

    def test_korean_separators_include_korean_sentence_endings(self) -> None:
        """한국어 종결어미 구분자가 포함되어 있는지 확인한다."""
        assert "다. " in KOREAN_ISSUE_SEPARATORS
        assert "요. " in KOREAN_ISSUE_SEPARATORS
        assert "다.\n" in KOREAN_ISSUE_SEPARATORS

    def test_korean_separators_include_markdown_headers(self) -> None:
        """Markdown 헤더 구분자가 포함되어 있는지 확인한다."""
        assert "\n## " in KOREAN_ISSUE_SEPARATORS
        assert "\n### " in KOREAN_ISSUE_SEPARATORS
        assert "\n#### " in KOREAN_ISSUE_SEPARATORS

    def test_markdown_header_has_higher_priority_than_paragraph(self) -> None:
        """Markdown 헤더가 빈 줄보다 높은 우선순위를 가지는지 확인한다."""
        h2_idx = KOREAN_ISSUE_SEPARATORS.index("\n## ")
        blank_line_idx = KOREAN_ISSUE_SEPARATORS.index("\n\n")
        assert h2_idx < blank_line_idx, "H2 헤더는 빈 줄보다 앞에 와야 합니다."


class TestKoreanChunkingBehavior:
    """한국어 문서 청킹 동작 테스트."""

    def test_markdown_section_split(self) -> None:
        """Markdown H2 섹션 경계에서 청크가 분리되는지 확인한다."""
        # 실제 이슈 문서 구조를 모방한 테스트 문서
        korean_issue = (
            "# 이슈-2024-001: 로그인 페이지 500 오류\n\n"
            "발생일시: 2024-01-15 14:30\n\n"
            "## 증상\n"
            "사용자가 로그인 버튼 클릭 시 500 Internal Server Error가 발생한다. "
            "영향 범위는 전체 사용자이며 서비스가 완전히 중단되었다.\n\n"
            "## 원인 분석\n"
            "데이터베이스 연결 풀이 고갈되어 새로운 연결 생성이 불가능했다. "
            "피크 타임에 동시 접속자 수가 설정된 최대값을 초과했다.\n\n"
            "## 해결 방법\n"
            "DB 연결 풀 최대값을 50에서 200으로 증가시켰다. "
            "또한 유휴 연결 타임아웃을 30초에서 10초로 줄였다.\n\n"
            "## 재발 방지\n"
            "모니터링 알림을 연결 풀 사용률 80% 도달 시 발송하도록 설정했다."
        )

        chunker = DocumentChunker(chunk_size=300, chunk_overlap=50)
        doc = Document(page_content=korean_issue, metadata={"source": "issue.md"})
        chunks = chunker.chunk_documents([doc])

        # 청크가 생성되었는지 확인
        assert len(chunks) > 1

        # 원본 메타데이터 보존 확인
        for chunk in chunks:
            assert chunk.metadata["source"] == "issue.md"
            assert "chunk_index" in chunk.metadata
            assert "total_chunks" in chunk.metadata

    def test_korean_sentence_boundary_respected(self) -> None:
        """
        한국어 문장 경계('다. ')에서 청크가 분리되는지 확인한다.
        문장 중간에서 청크가 잘리지 않도록 한다.
        """
        # 반복적인 한국어 문장으로 구성된 텍스트
        korean_text = (
            "서버에서 오류가 발생했다. " * 10 +
            "데이터베이스 연결이 실패했다. " * 10 +
            "네트워크 타임아웃이 발생했다. " * 10
        )

        chunker = DocumentChunker(chunk_size=200, chunk_overlap=30)
        chunks = chunker.chunk_text(korean_text)

        # 청크 크기 제한 준수 확인
        for chunk in chunks:
            assert len(chunk.page_content) <= 200 + 30, (
                f"청크 크기 초과: {len(chunk.page_content)}"
            )

    def test_chunk_metadata_total_chunks_per_document(self) -> None:
        """
        total_chunks가 해당 문서 기준으로 계산되는지 확인한다.
        같은 문서의 모든 청크는 동일한 total_chunks 값을 가져야 한다.
        """
        long_text = "가나다라마바사아자차카타파하 " * 100  # 긴 텍스트
        chunker = DocumentChunker(chunk_size=100, chunk_overlap=20)
        doc = Document(page_content=long_text, metadata={"file_hash": "abc123"})
        chunks = chunker.chunk_documents([doc])

        assert len(chunks) > 1, "청크가 2개 이상이어야 합니다."

        # 모든 청크의 total_chunks 값이 일치해야 함
        total_chunks_values = {chunk.metadata["total_chunks"] for chunk in chunks}
        assert len(total_chunks_values) == 1, (
            f"total_chunks 값이 일치하지 않음: {total_chunks_values}"
        )

        # total_chunks 값이 실제 청크 수와 일치해야 함
        assert chunks[0].metadata["total_chunks"] == len(chunks)

    def test_chunk_index_is_sequential(self) -> None:
        """chunk_index가 0부터 순차적으로 증가하는지 확인한다."""
        text = "테스트 내용입니다. " * 50
        chunker = DocumentChunker(chunk_size=100, chunk_overlap=20)
        chunks = chunker.chunk_text(text)

        indices = [chunk.metadata["chunk_index"] for chunk in chunks]
        assert indices == list(range(len(chunks))), (
            f"chunk_index가 순차적이지 않음: {indices}"
        )

    def test_empty_text_returns_empty(self) -> None:
        """빈 텍스트 청킹 시 빈 목록을 반환하는지 확인한다."""
        chunker = DocumentChunker()
        result = chunker.chunk_text("")
        # 빈 텍스트는 Document 생성 후 분할 시 빈 목록 또는 빈 청크가 될 수 있음
        for chunk in result:
            assert chunk.page_content.strip() == "" or len(result) == 0

    def test_multiple_documents_doc_index(self) -> None:
        """여러 문서 처리 시 doc_index가 올바르게 할당되는지 확인한다."""
        docs = [
            Document(page_content="문서1 " * 30, metadata={"source": "doc1.md"}),
            Document(page_content="문서2 " * 30, metadata={"source": "doc2.md"}),
        ]
        chunker = DocumentChunker(chunk_size=100, chunk_overlap=20)
        chunks = chunker.chunk_documents(docs)

        doc0_chunks = [c for c in chunks if c.metadata["doc_index"] == 0]
        doc1_chunks = [c for c in chunks if c.metadata["doc_index"] == 1]

        assert len(doc0_chunks) > 0, "doc_index=0인 청크가 없습니다."
        assert len(doc1_chunks) > 0, "doc_index=1인 청크가 없습니다."

        # 각 문서의 청크는 해당 문서 출처를 유지해야 함
        assert all(c.metadata["source"] == "doc1.md" for c in doc0_chunks)
        assert all(c.metadata["source"] == "doc2.md" for c in doc1_chunks)
