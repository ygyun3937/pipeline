"""
임베딩(Embedding) 모듈 테스트 - IssueEmbedder v3 (PGVector).

테스트 대상:
    - add 모드: file_hash 기반 중복 방지 (멱등성)
    - update 모드: 기존 청크 삭제 후 재삽입
    - batch_size 설정 반영
    - _generate_chunk_id 결정론적 ID 생성
    - get_collection_stats 통계 반환
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.documents import Document

from src.embedding.embedder import (
    IssueEmbedder,
    _detect_section,
    _enrich_chunk_metadata,
    _generate_chunk_id,
)


def _make_chunk(
    content: str,
    file_hash: str = "abc123",
    source: str = "/data/issue.md",
    chunk_index: int = 0,
    doc_index: int = 0,
) -> Document:
    """테스트용 청크 Document를 생성한다."""
    return Document(
        page_content=content,
        metadata={
            "file_hash": file_hash,
            "source": source,
            "filename": source.split("/")[-1],
            "chunk_index": chunk_index,
            "doc_index": doc_index,
            "total_chunks": 3,
        },
    )


def _make_embedder(mock_pgvector_cls, tmp_path=None) -> IssueEmbedder:
    """테스트용 IssueEmbedder를 생성한다."""
    return IssueEmbedder(
        embedding_model="sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
        postgres_url="postgresql+psycopg://pipeline:pipeline@localhost:5432/issue_pipeline",
        collection_name="test_col",
    )


class TestGenerateChunkId:
    """_generate_chunk_id 함수 테스트."""

    def test_deterministic_id_with_file_hash(self) -> None:
        """동일한 file_hash + chunk_index 조합은 항상 같은 ID를 생성하는지 확인한다."""
        chunk = _make_chunk("내용", file_hash="deadbeef", chunk_index=2, doc_index=0)
        id1 = _generate_chunk_id(chunk)
        id2 = _generate_chunk_id(chunk)
        assert id1 == id2
        assert id1 == "deadbeef-doc0-chunk2"

    def test_different_chunks_have_different_ids(self) -> None:
        """다른 chunk_index를 가진 청크는 서로 다른 ID를 생성하는지 확인한다."""
        chunk0 = _make_chunk("내용A", file_hash="hash1", chunk_index=0)
        chunk1 = _make_chunk("내용B", file_hash="hash1", chunk_index=1)
        assert _generate_chunk_id(chunk0) != _generate_chunk_id(chunk1)

    def test_fallback_uuid_when_no_file_hash(self) -> None:
        """file_hash가 없으면 UUID 형식의 ID가 생성되는지 확인한다."""
        chunk = Document(page_content="내용", metadata={})
        chunk_id = _generate_chunk_id(chunk)
        # UUID는 하이픈을 포함한 36자 문자열
        assert len(chunk_id) == 36
        assert chunk_id.count("-") == 4


class TestIssueEmbedderAddMode:
    """IssueEmbedder add 모드(중복 방지) 테스트."""

    @patch("src.embedding.embedder.FastEmbedEmbeddings")
    @patch("src.embedding.embedder.PGVector")
    def test_add_mode_skips_duplicate_file_hash(
        self,
        mock_pgvector_cls,
        mock_embed_cls,
    ) -> None:
        """add 모드에서 이미 인덱싱된 file_hash를 가진 청크가 스킵되는지 확인한다."""
        mock_vs = MagicMock()
        # 기존 해시 "abc123"을 가진 문서 반환
        mock_vs.similarity_search.return_value = [
            Document(page_content="기존", metadata={"file_hash": "abc123"})
        ]
        mock_pgvector_cls.return_value = mock_vs

        embedder = _make_embedder(mock_pgvector_cls)

        chunks = [_make_chunk("중복 내용", file_hash="abc123")]
        result = embedder.add_documents(chunks, mode="add")

        assert result["total"] == 1
        assert result["added"] == 0
        assert result["skipped"] == 1
        # 벡터스토어 add_documents가 호출되지 않아야 함
        mock_vs.add_documents.assert_not_called()

    @patch("src.embedding.embedder.FastEmbedEmbeddings")
    @patch("src.embedding.embedder.PGVector")
    def test_add_mode_inserts_new_chunks(
        self,
        mock_pgvector_cls,
        mock_embed_cls,
    ) -> None:
        """add 모드에서 새로운 file_hash를 가진 청크가 삽입되는지 확인한다."""
        mock_vs = MagicMock()
        # 기존 해시가 없는 빈 결과
        mock_vs.similarity_search.return_value = []
        mock_pgvector_cls.return_value = mock_vs

        embedder = _make_embedder(mock_pgvector_cls)

        chunks = [
            _make_chunk("새 내용 A", file_hash="newfile1"),
            _make_chunk("새 내용 B", file_hash="newfile2"),
        ]
        result = embedder.add_documents(chunks, mode="add")

        assert result["total"] == 2
        assert result["added"] == 2
        assert result["skipped"] == 0
        # 벡터스토어 add_documents가 호출되어야 함
        mock_vs.add_documents.assert_called_once()

    @patch("src.embedding.embedder.FastEmbedEmbeddings")
    @patch("src.embedding.embedder.PGVector")
    def test_add_empty_chunks_returns_zero_stats(
        self,
        mock_pgvector_cls,
        mock_embed_cls,
    ) -> None:
        """빈 청크 목록을 전달하면 0 통계를 반환하는지 확인한다."""
        mock_pgvector_cls.return_value = MagicMock()
        embedder = _make_embedder(mock_pgvector_cls)

        result = embedder.add_documents([], mode="add")
        assert result == {"total": 0, "added": 0, "skipped": 0, "deleted": 0}


class TestIssueEmbedderUpdateMode:
    """IssueEmbedder update 모드(갱신) 테스트."""

    @patch("src.embedding.embedder.FastEmbedEmbeddings")
    @patch("src.embedding.embedder.PGVector")
    def test_update_mode_deletes_then_inserts(
        self,
        mock_pgvector_cls,
        mock_embed_cls,
    ) -> None:
        """
        update 모드에서 소스 파일의 기존 청크를 삭제한 후 새 청크를 삽입하는지 확인한다.
        """
        source = "/data/raw/issue.md"
        mock_vs = MagicMock()
        # delete_by_source 내부에서 similarity_search 호출 시 기존 청크 반환
        existing_doc = Document(
            page_content="기존 내용",
            metadata={"source": source, "_id": "oldhash-doc0-chunk0"},
        )
        existing_doc.id = "oldhash-doc0-chunk0"
        mock_vs.similarity_search.return_value = [existing_doc]
        mock_pgvector_cls.return_value = mock_vs

        embedder = _make_embedder(mock_pgvector_cls)

        chunks = [
            _make_chunk("수정된 내용 1", file_hash="newhash", source=source, chunk_index=0),
            _make_chunk("수정된 내용 2", file_hash="newhash", source=source, chunk_index=1),
        ]
        result = embedder.add_documents(chunks, mode="update")

        # 기존 청크 삭제 확인
        mock_vs.delete.assert_called_once()

        # 새 청크 삽입 확인
        mock_vs.add_documents.assert_called_once()

        assert result["added"] == 2
        assert result["skipped"] == 0

    @patch("src.embedding.embedder.FastEmbedEmbeddings")
    @patch("src.embedding.embedder.PGVector")
    def test_update_mode_groups_by_source(
        self,
        mock_pgvector_cls,
        mock_embed_cls,
    ) -> None:
        """
        update 모드에서 서로 다른 소스 파일이 각각 독립적으로 처리되는지 확인한다.
        """
        mock_vs = MagicMock()
        mock_vs.similarity_search.return_value = []
        mock_pgvector_cls.return_value = mock_vs

        embedder = _make_embedder(mock_pgvector_cls)

        chunks = [
            _make_chunk("내용A", source="/data/file_a.md", file_hash="hasha"),
            _make_chunk("내용B", source="/data/file_b.md", file_hash="hashb"),
        ]
        result = embedder.add_documents(chunks, mode="update")

        # 두 파일에 대해 각각 similarity_search 호출 확인
        assert mock_vs.similarity_search.call_count == 2

        assert result["total"] == 2
        assert result["added"] == 2


class TestDetectSection:
    """_detect_section 함수 테스트."""

    def test_detects_symptom_section(self) -> None:
        assert _detect_section("## 문제 현상\n\n에러가 발생했다.") == "증상"

    def test_detects_cause_section(self) -> None:
        assert _detect_section("## 원인 분석\n\n직접 원인은 풀 고갈이다.") == "원인"

    def test_detects_action_section(self) -> None:
        assert _detect_section("## 해결 방법\n\n즉시 조치 사항.") == "조치"

    def test_detects_prevention_section(self) -> None:
        assert _detect_section("## 재발 방지 대책\n\n1. 모니터링 추가") == "재발방지"

    def test_detects_basic_info_section(self) -> None:
        assert _detect_section("## 기본 정보\n\n이슈 ID: BUG-001") == "기본정보"

    def test_fallback_to_etc(self) -> None:
        assert _detect_section("그냥 텍스트 내용입니다.") == "기타"


class TestEnrichChunkMetadata:
    """_enrich_chunk_metadata 함수 테스트."""

    def test_adds_section_field(self) -> None:
        chunk = Document(
            page_content="## 원인 분석\n\n연결 풀 고갈",
            metadata={"file_hash": "abc"},
        )
        enriched = _enrich_chunk_metadata(chunk)
        assert enriched.metadata["section"] == "원인"

    def test_sets_doc_id_from_id_field(self) -> None:
        chunk = Document(
            page_content="내용",
            metadata={"id": "BUG-2024-001", "filename": "bug.md"},
        )
        enriched = _enrich_chunk_metadata(chunk)
        assert enriched.metadata["doc_id"] == "BUG-2024-001"

    def test_fallback_doc_id_to_filename(self) -> None:
        chunk = Document(
            page_content="내용",
            metadata={"filename": "bug.md"},
        )
        enriched = _enrich_chunk_metadata(chunk)
        assert enriched.metadata["doc_id"] == "bug.md"

    def test_defaults_domain_to_unknown(self) -> None:
        chunk = Document(page_content="내용", metadata={})
        enriched = _enrich_chunk_metadata(chunk)
        assert enriched.metadata["domain"] == "unknown"

    def test_existing_domain_preserved(self) -> None:
        chunk = Document(
            page_content="내용",
            metadata={"domain": "battery"},
        )
        enriched = _enrich_chunk_metadata(chunk)
        assert enriched.metadata["domain"] == "battery"

    def test_original_chunk_not_mutated(self) -> None:
        meta = {"file_hash": "abc"}
        chunk = Document(page_content="내용", metadata=meta)
        _enrich_chunk_metadata(chunk)
        assert "section" not in chunk.metadata  # 원본 불변


class TestIssueEmbedderBatchSize:
    """배치 크기 설정 테스트."""

    @patch("src.embedding.embedder.FastEmbedEmbeddings")
    @patch("src.embedding.embedder.PGVector")
    def test_custom_batch_size_is_stored(
        self,
        mock_pgvector_cls,
        mock_embed_cls,
    ) -> None:
        """커스텀 batch_size가 embedder에 저장되는지 확인한다."""
        mock_pgvector_cls.return_value = MagicMock()
        embedder = IssueEmbedder(
            embedding_model="sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
            postgres_url="postgresql+psycopg://pipeline:pipeline@localhost:5432/issue_pipeline",
            collection_name="test_col",
            batch_size=50,
        )
        assert embedder.batch_size == 50

    @patch("src.embedding.embedder.FastEmbedEmbeddings")
    @patch("src.embedding.embedder.PGVector")
    def test_default_batch_size_is_100(
        self,
        mock_pgvector_cls,
        mock_embed_cls,
    ) -> None:
        """기본 batch_size가 100인지 확인한다."""
        mock_pgvector_cls.return_value = MagicMock()
        embedder = IssueEmbedder(
            embedding_model="sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
            postgres_url="postgresql+psycopg://pipeline:pipeline@localhost:5432/issue_pipeline",
            collection_name="test_col",
        )
        assert embedder.batch_size == 100
