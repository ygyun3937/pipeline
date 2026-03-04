"""
문서 수집(Ingestion) 모듈 테스트.

테스트 대상:
    - DocumentLoader: 파일 로딩 기능
    - DocumentChunker: 청킹 기능
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.ingestion.chunker import DocumentChunker
from src.ingestion.document_loader import DocumentLoader


# ---- DocumentLoader 테스트 ----

class TestDocumentLoader:
    """DocumentLoader 단위 테스트."""

    def test_load_markdown_file(self, tmp_path: Path) -> None:
        """Markdown 파일이 정상적으로 로드되는지 확인한다."""
        md_file = tmp_path / "test.md"
        md_file.write_text("# 테스트 문서\n\n내용입니다.", encoding="utf-8")

        loader = DocumentLoader(source_dir=tmp_path)
        docs = loader.load_file(md_file)

        assert len(docs) == 1
        assert "테스트 문서" in docs[0].page_content
        assert docs[0].metadata["file_type"] == "markdown"
        assert docs[0].metadata["filename"] == "test.md"

    def test_load_text_file(self, tmp_path: Path) -> None:
        """TXT 파일이 정상적으로 로드되는지 확인한다."""
        txt_file = tmp_path / "issue.txt"
        txt_file.write_text("버그 리포트 내용", encoding="utf-8")

        loader = DocumentLoader(source_dir=tmp_path)
        docs = loader.load_file(txt_file)

        assert len(docs) == 1
        assert docs[0].metadata["file_type"] == "text"

    def test_load_unsupported_file(self, tmp_path: Path) -> None:
        """지원하지 않는 파일 형식에서 ValueError가 발생하는지 확인한다."""
        invalid_file = tmp_path / "test.xlsx"
        invalid_file.write_bytes(b"fake content")

        loader = DocumentLoader(source_dir=tmp_path)
        with pytest.raises(ValueError, match="지원하지 않는 파일 형식"):
            loader.load_file(invalid_file)

    def test_load_directory(self, tmp_path: Path) -> None:
        """디렉토리 내 모든 지원 파일을 로드하는지 확인한다."""
        (tmp_path / "bug1.md").write_text("# Bug 1", encoding="utf-8")
        (tmp_path / "bug2.txt").write_text("Bug 2 content", encoding="utf-8")
        (tmp_path / "ignore.xlsx").write_bytes(b"not supported")

        loader = DocumentLoader(source_dir=tmp_path)
        results = list(loader.load_directory())

        # xlsx는 제외되고 md, txt만 로드됨
        assert len(results) == 2

    def test_metadata_contains_file_hash(self, tmp_path: Path) -> None:
        """로드된 문서에 file_hash 메타데이터가 포함되는지 확인한다."""
        md_file = tmp_path / "test.md"
        md_file.write_text("내용", encoding="utf-8")

        loader = DocumentLoader(source_dir=tmp_path)
        docs = loader.load_file(md_file)

        assert "file_hash" in docs[0].metadata
        assert len(docs[0].metadata["file_hash"]) == 32  # MD5 해시 길이

    def test_same_file_same_hash(self, tmp_path: Path) -> None:
        """같은 파일은 항상 동일한 해시를 생성하는지 확인한다 (멱등성)."""
        md_file = tmp_path / "test.md"
        md_file.write_text("동일한 내용", encoding="utf-8")

        loader = DocumentLoader(source_dir=tmp_path)
        docs1 = loader.load_file(md_file)
        docs2 = loader.load_file(md_file)

        assert docs1[0].metadata["file_hash"] == docs2[0].metadata["file_hash"]

    def test_nonexistent_directory_raises(self) -> None:
        """존재하지 않는 디렉토리에서 FileNotFoundError가 발생하는지 확인한다."""
        with pytest.raises(FileNotFoundError):
            DocumentLoader(source_dir="/nonexistent/path/12345")


# ---- DocumentChunker 테스트 ----

class TestDocumentChunker:
    """DocumentChunker 단위 테스트."""

    def test_basic_chunking(self) -> None:
        """기본 청킹이 정상 동작하는지 확인한다."""
        from langchain_core.documents import Document

        chunker = DocumentChunker(chunk_size=100, chunk_overlap=20)
        long_text = "A" * 500  # 500자 텍스트
        doc = Document(page_content=long_text, metadata={"source": "test.md"})

        chunks = chunker.chunk_documents([doc])

        assert len(chunks) > 1  # 청크로 분할됨
        for chunk in chunks:
            assert len(chunk.page_content) <= 100 + 20  # 크기 제한 준수

    def test_chunk_metadata_preserved(self) -> None:
        """원본 문서의 메타데이터가 청크에 복사되는지 확인한다."""
        from langchain_core.documents import Document

        chunker = DocumentChunker(chunk_size=50, chunk_overlap=10)
        doc = Document(
            page_content="테스트 내용 " * 20,
            metadata={"source": "bug.md", "file_hash": "abc123"},
        )

        chunks = chunker.chunk_documents([doc])

        assert len(chunks) >= 1
        # 원본 메타데이터 보존 확인
        assert chunks[0].metadata["source"] == "bug.md"
        assert chunks[0].metadata["file_hash"] == "abc123"
        # 청크 인덱스 메타데이터 추가 확인
        assert "chunk_index" in chunks[0].metadata
        assert "total_chunks" in chunks[0].metadata

    def test_chunk_overlap_greater_than_size_raises(self) -> None:
        """overlap이 chunk_size 이상이면 ValueError가 발생하는지 확인한다."""
        with pytest.raises(ValueError, match="chunk_overlap"):
            DocumentChunker(chunk_size=100, chunk_overlap=100)

    def test_empty_documents_returns_empty(self) -> None:
        """빈 문서 목록 입력 시 빈 목록을 반환하는지 확인한다."""
        chunker = DocumentChunker()
        result = chunker.chunk_documents([])
        assert result == []

    def test_estimate_chunk_count(self) -> None:
        """청크 수 추정이 합리적인 값을 반환하는지 확인한다."""
        chunker = DocumentChunker(chunk_size=100, chunk_overlap=20)
        count = chunker.estimate_chunk_count("A" * 500)
        assert count > 0
        assert count <= 10  # 500자 / (100-20) ≈ 6~7개 예상
