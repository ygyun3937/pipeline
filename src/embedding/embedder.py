"""
임베딩(Embedding) 모듈.

FastEmbed sentence-transformers/paraphrase-multilingual-mpnet-base-v2 다국어 모델을 사용하여 문서 청크를
벡터로 변환하고 ChromaDB에 저장한다.

paraphrase-multilingual-mpnet-base-v2 선택 이유:
    - 한국어 포함 50개 이상 언어 지원
    - ONNX 기반 로컬 실행 (API 키 불필요)
    - fastembed에서 공식 지원하는 한국어 다국어 모델

멱등성(idempotency) 보장:
    - add 모드: 동일한 file_hash를 가진 문서는 재처리하지 않는다.
    - update 모드: 동일한 소스 파일의 기존 청크를 삭제 후 재삽입한다.
                   파일 수정 시 최신 내용으로 갱신하는 데 사용한다.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any, Literal

import chromadb
from langchain_chroma import Chroma
from langchain_community.embeddings import FastEmbedEmbeddings
from langchain_core.documents import Document
from tenacity import retry, stop_after_attempt, wait_exponential

from src.logger import get_logger

logger = get_logger(__name__)

# 인덱싱 모드 타입 정의
IndexMode = Literal["add", "update"]


class IssueEmbedder:
    """
    이슈 문서 청크를 임베딩하여 ChromaDB에 저장하는 클래스.

    특징:
        - sentence-transformers/paraphrase-multilingual-mpnet-base-v2 다국어 ONNX 모델 (한국어 지원)
        - file_hash 기반 중복 처리 방지 (add 모드, 멱등성)
        - 소스 파일 기준 갱신 (update 모드, 수정된 파일 재인덱싱)
        - 배치 처리로 임베딩 효율화
        - 재시도 로직으로 임시 오류 대응
    """

    def __init__(
        self,
        embedding_model: str,
        chroma_persist_dir: str | Path,
        collection_name: str,
        batch_size: int = 100,
    ) -> None:
        """
        Args:
            embedding_model: FastEmbed 로컬 임베딩 모델명 (ONNX, API 키 불필요)
                             권장: "sentence-transformers/paraphrase-multilingual-mpnet-base-v2" (한국어 지원 다국어 모델)
            chroma_persist_dir: ChromaDB 데이터 저장 경로
            collection_name: ChromaDB 컬렉션 이름
            batch_size: 배치 처리 크기 (기본값: 100)
        """
        self.collection_name = collection_name
        self.batch_size = batch_size
        persist_dir = Path(chroma_persist_dir)
        persist_dir.mkdir(parents=True, exist_ok=True)

        # 로컬 ONNX 다국어 임베딩 초기화 (API 키/PyTorch 불필요)
        logger.info("로컬 임베딩 모델 로딩 중: %s", embedding_model)
        self._embeddings = FastEmbedEmbeddings(model_name=embedding_model)

        # ChromaDB 클라이언트 초기화 (영구 저장)
        self._chroma_client = chromadb.PersistentClient(path=str(persist_dir))

        # LangChain Chroma 래퍼 초기화 (코사인 거리 명시 - FastEmbed 호환성)
        self._vectorstore = Chroma(
            client=self._chroma_client,
            collection_name=collection_name,
            embedding_function=self._embeddings,
            collection_metadata={"hnsw:space": "cosine"},
        )

        logger.info(
            "IssueEmbedder 초기화 완료: model=%s, collection=%s, batch_size=%d",
            embedding_model,
            collection_name,
            batch_size,
        )

    def add_documents(
        self,
        chunks: list[Document],
        mode: IndexMode = "add",
    ) -> dict[str, Any]:
        """
        청크 목록을 임베딩하여 ChromaDB에 저장한다.

        Args:
            chunks: 저장할 Document 청크 목록
            mode: 인덱싱 모드
                - "add": 동일 file_hash 존재 시 스킵 (기본값, 멱등성)
                - "update": 동일 소스 파일의 기존 청크 삭제 후 재삽입
                            (파일 수정 시 최신 내용으로 갱신)

        Returns:
            처리 결과 통계 딕셔너리
                - total: 전체 청크 수
                - added: 새로 추가된 청크 수
                - skipped: 중복으로 스킵된 청크 수 (add 모드에서만 의미 있음)
                - deleted: 삭제된 기존 청크 수 (update 모드에서만 의미 있음)
        """
        if not chunks:
            logger.warning("저장할 청크가 없습니다.")
            return {"total": 0, "added": 0, "skipped": 0, "deleted": 0}

        if mode == "update":
            return self._add_with_update(chunks)
        else:
            return self._add_with_dedup(chunks)

    def _add_with_dedup(self, chunks: list[Document]) -> dict[str, Any]:
        """
        add 모드: file_hash 기반 중복 방지로 새 청크만 추가한다.
        이미 처리된 파일은 스킵하여 멱등성을 보장한다.
        """
        # 이미 처리된 file_hash 조회
        existing_hashes = self._get_existing_file_hashes()
        logger.info("기존 인덱스된 파일 해시 수: %d", len(existing_hashes))

        # 중복 필터링
        new_chunks = [
            chunk
            for chunk in chunks
            if chunk.metadata.get("file_hash") not in existing_hashes
        ]
        skipped = len(chunks) - len(new_chunks)

        if skipped > 0:
            logger.info("%d개 청크 스킵 (중복 파일 해시)", skipped)

        if not new_chunks:
            logger.info("모든 청크가 이미 인덱싱되어 있습니다.")
            return {"total": len(chunks), "added": 0, "skipped": skipped, "deleted": 0}

        # 배치 처리로 ChromaDB에 저장
        added = self._add_chunks_in_batches(new_chunks)

        result = {"total": len(chunks), "added": added, "skipped": skipped, "deleted": 0}
        logger.info("임베딩 저장 완료 (add 모드): %s", result)
        return result

    def _add_with_update(self, chunks: list[Document]) -> dict[str, Any]:
        """
        update 모드: 소스 파일 기준으로 기존 청크를 삭제 후 재삽입한다.
        파일 내용이 수정되었을 때 최신 내용으로 갱신하는 데 사용한다.
        """
        # 소스 파일 경로별로 청크 그룹화
        chunks_by_source: dict[str, list[Document]] = {}
        for chunk in chunks:
            source = chunk.metadata.get("source", "")
            chunks_by_source.setdefault(source, []).append(chunk)

        total_deleted = 0
        total_added = 0

        for source_path, source_chunks in chunks_by_source.items():
            # 기존 청크 삭제
            deleted = self.delete_by_source(source_path)
            total_deleted += deleted

            # 새 청크 삽입
            added = self._add_chunks_in_batches(source_chunks)
            total_added += added

            logger.info(
                "소스 파일 갱신: %s | 삭제 %d개, 추가 %d개",
                source_path,
                deleted,
                added,
            )

        result = {
            "total": len(chunks),
            "added": total_added,
            "skipped": 0,
            "deleted": total_deleted,
        }
        logger.info("임베딩 저장 완료 (update 모드): %s", result)
        return result

    def _add_chunks_in_batches(self, chunks: list[Document]) -> int:
        """배치 단위로 청크를 ChromaDB에 저장한다. 각 배치별로 독립적으로 재시도한다."""
        total_added = 0

        for i in range(0, len(chunks), self.batch_size):
            batch = [_enrich_chunk_metadata(c) for c in chunks[i : i + self.batch_size]]

            # 각 청크에 고유 ID 부여 (file_hash + chunk_index 조합)
            ids = [_generate_chunk_id(chunk) for chunk in batch]

            self._add_single_batch(batch, ids)
            total_added += len(batch)

            logger.debug(
                "배치 저장: %d~%d / %d",
                i + 1,
                min(i + self.batch_size, len(chunks)),
                len(chunks),
            )

        return total_added

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def _add_single_batch(self, batch: list[Document], ids: list[str]) -> None:
        """단일 배치를 ChromaDB에 저장한다. 실패 시 최대 3회 재시도.

        배치 단위로 재시도를 적용함으로써, 중간에 실패해도 이미 성공한
        앞 배치들을 중복 삽입하지 않도록 한다.
        """
        self._vectorstore.add_documents(documents=batch, ids=ids)

    def _get_existing_file_hashes(self) -> set[str]:
        """ChromaDB에 저장된 모든 file_hash 집합을 반환한다."""
        try:
            collection = self._chroma_client.get_collection(self.collection_name)
            result = collection.get(include=["metadatas"])
            metadatas = result.get("metadatas") or []
            return {m.get("file_hash", "") for m in metadatas if m}
        except Exception as exc:
            logger.warning("기존 해시 조회 실패 (새 컬렉션으로 간주): %s", exc)
            return set()

    def delete_by_source(self, source_path: str) -> int:
        """
        특정 소스 파일의 모든 청크를 삭제한다.
        update 모드에서 재인덱싱 전 기존 데이터를 정리하거나
        특정 파일을 인덱스에서 제거할 때 사용한다.

        Args:
            source_path: 삭제할 소스 파일 경로 (메타데이터의 'source' 값)

        Returns:
            삭제된 청크 수
        """
        try:
            collection = self._chroma_client.get_collection(self.collection_name)
            result = collection.get(
                where={"source": source_path},
                include=["metadatas"],
            )
            ids_to_delete = result.get("ids", [])

            if ids_to_delete:
                collection.delete(ids=ids_to_delete)
                logger.info(
                    "소스 파일 청크 삭제: %s (%d개)", source_path, len(ids_to_delete)
                )
            return len(ids_to_delete)

        except Exception as exc:
            logger.error("청크 삭제 실패: %s | 오류: %s", source_path, exc)
            return 0

    def get_collection_stats(self) -> dict[str, Any]:
        """ChromaDB 컬렉션 통계를 반환한다."""
        try:
            collection = self._chroma_client.get_collection(self.collection_name)
            count = collection.count()
            return {
                "collection_name": self.collection_name,
                "total_chunks": count,
            }
        except Exception as exc:
            logger.error("통계 조회 실패: %s", exc)
            return {"collection_name": self.collection_name, "total_chunks": 0}

    @property
    def vectorstore(self) -> Chroma:
        """LangChain Chroma 인스턴스를 반환한다. Retriever 생성에 사용."""
        return self._vectorstore


# 섹션 감지용 키워드 패턴 (순서 중요: 더 구체적인 것 먼저)
_SECTION_PATTERNS: list[tuple[str, str]] = [
    ("재발방지", r"재발\s*방지|대책|개선"),
    ("테스트결과", r"테스트\s*결과|검증\s*결과"),
    ("조치", r"해결\s*방법|즉시\s*조치|복구|조치\s*방법"),
    ("원인", r"원인\s*분석|직접\s*원인|근본\s*원인"),
    ("증상", r"증상|문제\s*현상|장애\s*현상|에러|오류"),
    ("기본정보", r"기본\s*정보|버그\s*기본|장애\s*개요"),
]


def _detect_section(text: str) -> str:
    """청크 텍스트에서 마크다운 헤더 또는 키워드로 문서 섹션을 감지한다."""
    header_match = re.search(r"^#{2,3}\s+(.+)$", text, re.MULTILINE)
    search_target = header_match.group(1) if header_match else text[:300]
    for section_name, pattern in _SECTION_PATTERNS:
        if re.search(pattern, search_target, re.IGNORECASE):
            return section_name
    return "기타"


def _enrich_chunk_metadata(chunk: Document) -> Document:
    """ChromaDB 저장 전 청크 메타데이터에 확장 필드를 주입한다."""
    meta = dict(chunk.metadata)
    meta.setdefault("doc_id", meta.get("id", meta.get("filename", "")))
    meta.setdefault("domain", "unknown")
    meta.setdefault("severity", "unknown")
    meta.setdefault("status", "unknown")
    meta.setdefault("alarm_code", "")
    meta["section"] = _detect_section(chunk.page_content)
    return Document(page_content=chunk.page_content, metadata=meta)


def _generate_chunk_id(chunk: Document) -> str:
    """
    청크의 고유 ID를 생성한다.
    file_hash + chunk_index 조합으로 결정론적(deterministic) ID를 생성하여
    동일 문서의 재처리 시 같은 ID가 생성되도록 한다.
    update 모드에서 중복 삽입 방지에 활용된다.
    """
    file_hash = chunk.metadata.get("file_hash", "")
    chunk_index = chunk.metadata.get("chunk_index", 0)
    doc_index = chunk.metadata.get("doc_index", 0)

    if file_hash:
        # 결정론적 ID: 동일 입력 -> 동일 ID
        return f"{file_hash}-doc{doc_index}-chunk{chunk_index}"
    else:
        # 해시가 없는 경우 UUID로 폴백
        return str(uuid.uuid4())
