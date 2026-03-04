"""
임베딩(Embedding) 모듈 테스트 - IssueEmbedder v2.

테스트 대상:
    - add 모드: file_hash 기반 중복 방지 (멱등성)
    - update 모드: 기존 청크 삭제 후 재삽입
    - batch_size 설정 반영
    - _generate_chunk_id 결정론적 ID 생성
    - get_collection_stats 통계 반환
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import pytest
from langchain_core.documents import Document

from src.embedding.embedder import IssueEmbedder, _generate_chunk_id


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
    @patch("src.embedding.embedder.chromadb.PersistentClient")
    @patch("src.embedding.embedder.Chroma")
    def test_add_mode_skips_duplicate_file_hash(
        self,
        mock_chroma_cls,
        mock_client_cls,
        mock_embed_cls,
        tmp_path,
    ) -> None:
        """add 모드에서 이미 인덱싱된 file_hash를 가진 청크가 스킵되는지 확인한다."""
        # Mock 컬렉션이 기존 해시 "abc123"을 가지고 있다고 설정
        mock_collection = MagicMock()
        mock_collection.get.return_value = {
            "metadatas": [{"file_hash": "abc123"}],
            "ids": ["abc123-doc0-chunk0"],
        }
        mock_client_cls.return_value.get_collection.return_value = mock_collection

        embedder = IssueEmbedder(
            embedding_model="sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
            chroma_persist_dir=tmp_path,
            collection_name="test_col",
        )

        chunks = [_make_chunk("중복 내용", file_hash="abc123")]
        result = embedder.add_documents(chunks, mode="add")

        assert result["total"] == 1
        assert result["added"] == 0
        assert result["skipped"] == 1
        # 벡터스토어 add_documents가 호출되지 않아야 함
        mock_chroma_cls.return_value.add_documents.assert_not_called()

    @patch("src.embedding.embedder.FastEmbedEmbeddings")
    @patch("src.embedding.embedder.chromadb.PersistentClient")
    @patch("src.embedding.embedder.Chroma")
    def test_add_mode_inserts_new_chunks(
        self,
        mock_chroma_cls,
        mock_client_cls,
        mock_embed_cls,
        tmp_path,
    ) -> None:
        """add 모드에서 새로운 file_hash를 가진 청크가 삽입되는지 확인한다."""
        # 기존 해시가 없는 빈 컬렉션
        mock_collection = MagicMock()
        mock_collection.get.return_value = {"metadatas": [], "ids": []}
        mock_client_cls.return_value.get_collection.return_value = mock_collection

        embedder = IssueEmbedder(
            embedding_model="sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
            chroma_persist_dir=tmp_path,
            collection_name="test_col",
        )

        chunks = [
            _make_chunk("새 내용 A", file_hash="newfile1"),
            _make_chunk("새 내용 B", file_hash="newfile2"),
        ]
        result = embedder.add_documents(chunks, mode="add")

        assert result["total"] == 2
        assert result["added"] == 2
        assert result["skipped"] == 0
        # 벡터스토어 add_documents가 호출되어야 함
        mock_chroma_cls.return_value.add_documents.assert_called_once()

    @patch("src.embedding.embedder.FastEmbedEmbeddings")
    @patch("src.embedding.embedder.chromadb.PersistentClient")
    @patch("src.embedding.embedder.Chroma")
    def test_add_empty_chunks_returns_zero_stats(
        self,
        mock_chroma_cls,
        mock_client_cls,
        mock_embed_cls,
        tmp_path,
    ) -> None:
        """빈 청크 목록을 전달하면 0 통계를 반환하는지 확인한다."""
        embedder = IssueEmbedder(
            embedding_model="sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
            chroma_persist_dir=tmp_path,
            collection_name="test_col",
        )

        result = embedder.add_documents([], mode="add")
        assert result == {"total": 0, "added": 0, "skipped": 0, "deleted": 0}


class TestIssueEmbedderUpdateMode:
    """IssueEmbedder update 모드(갱신) 테스트."""

    @patch("src.embedding.embedder.FastEmbedEmbeddings")
    @patch("src.embedding.embedder.chromadb.PersistentClient")
    @patch("src.embedding.embedder.Chroma")
    def test_update_mode_deletes_then_inserts(
        self,
        mock_chroma_cls,
        mock_client_cls,
        mock_embed_cls,
        tmp_path,
    ) -> None:
        """
        update 모드에서 소스 파일의 기존 청크를 삭제한 후 새 청크를 삽입하는지 확인한다.
        """
        source = "/data/raw/issue.md"

        # delete_by_source가 호출될 때 컬렉션의 get()이 반환할 값
        mock_collection = MagicMock()
        mock_collection.get.return_value = {
            "metadatas": [{"source": source}],
            "ids": ["oldhash-doc0-chunk0"],
        }
        mock_client_cls.return_value.get_collection.return_value = mock_collection

        embedder = IssueEmbedder(
            embedding_model="sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
            chroma_persist_dir=tmp_path,
            collection_name="test_col",
        )

        chunks = [
            _make_chunk("수정된 내용 1", file_hash="newhash", source=source, chunk_index=0),
            _make_chunk("수정된 내용 2", file_hash="newhash", source=source, chunk_index=1),
        ]
        result = embedder.add_documents(chunks, mode="update")

        # 기존 청크 삭제 확인
        mock_collection.delete.assert_called_once_with(ids=["oldhash-doc0-chunk0"])

        # 새 청크 삽입 확인
        mock_chroma_cls.return_value.add_documents.assert_called_once()

        assert result["added"] == 2
        assert result["deleted"] == 1
        assert result["skipped"] == 0

    @patch("src.embedding.embedder.FastEmbedEmbeddings")
    @patch("src.embedding.embedder.chromadb.PersistentClient")
    @patch("src.embedding.embedder.Chroma")
    def test_update_mode_groups_by_source(
        self,
        mock_chroma_cls,
        mock_client_cls,
        mock_embed_cls,
        tmp_path,
    ) -> None:
        """
        update 모드에서 서로 다른 소스 파일이 각각 독립적으로 처리되는지 확인한다.
        """
        mock_collection = MagicMock()
        mock_collection.get.return_value = {"metadatas": [], "ids": []}
        mock_client_cls.return_value.get_collection.return_value = mock_collection

        embedder = IssueEmbedder(
            embedding_model="sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
            chroma_persist_dir=tmp_path,
            collection_name="test_col",
        )

        chunks = [
            _make_chunk("내용A", source="/data/file_a.md", file_hash="hasha"),
            _make_chunk("내용B", source="/data/file_b.md", file_hash="hashb"),
        ]
        result = embedder.add_documents(chunks, mode="update")

        # 두 파일에 대해 각각 delete 호출 확인
        assert mock_collection.get.call_count == 2

        assert result["total"] == 2
        assert result["added"] == 2


class TestIssueEmbedderBatchSize:
    """배치 크기 설정 테스트."""

    @patch("src.embedding.embedder.FastEmbedEmbeddings")
    @patch("src.embedding.embedder.chromadb.PersistentClient")
    @patch("src.embedding.embedder.Chroma")
    def test_custom_batch_size_is_stored(
        self,
        mock_chroma_cls,
        mock_client_cls,
        mock_embed_cls,
        tmp_path,
    ) -> None:
        """커스텀 batch_size가 embedder에 저장되는지 확인한다."""
        embedder = IssueEmbedder(
            embedding_model="sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
            chroma_persist_dir=tmp_path,
            collection_name="test_col",
            batch_size=50,
        )
        assert embedder.batch_size == 50

    @patch("src.embedding.embedder.FastEmbedEmbeddings")
    @patch("src.embedding.embedder.chromadb.PersistentClient")
    @patch("src.embedding.embedder.Chroma")
    def test_default_batch_size_is_100(
        self,
        mock_chroma_cls,
        mock_client_cls,
        mock_embed_cls,
        tmp_path,
    ) -> None:
        """기본 batch_size가 100인지 확인한다."""
        embedder = IssueEmbedder(
            embedding_model="sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
            chroma_persist_dir=tmp_path,
            collection_name="test_col",
        )
        assert embedder.batch_size == 100
