"""
문서 수집(Ingestion) 모듈 - 문서 로더.

PDF, Markdown, 텍스트 파일을 읽어 LangChain Document 객체로 변환한다.
각 문서에는 소스 경로, 파일 유형, 로드 시각 등의 메타데이터가 포함된다.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from langchain_core.documents import Document

from src.logger import get_logger

logger = get_logger(__name__)

# 지원하는 파일 확장자 목록
SUPPORTED_EXTENSIONS = {".pdf", ".md", ".txt", ".markdown"}


class DocumentLoader:
    """
    다양한 형식의 이슈 문서를 로드하는 클래스.

    지원 형식:
        - PDF (.pdf): pypdf 라이브러리 사용
        - Markdown (.md, .markdown): 텍스트로 로드
        - 텍스트 (.txt): UTF-8 인코딩으로 로드
    """

    def __init__(self, source_dir: str | Path) -> None:
        """
        Args:
            source_dir: 문서가 저장된 디렉토리 경로
        """
        self.source_dir = Path(source_dir)
        if not self.source_dir.exists():
            raise FileNotFoundError(f"소스 디렉토리를 찾을 수 없습니다: {self.source_dir}")

    def load_file(self, file_path: str | Path) -> list[Document]:
        """
        단일 파일을 로드하여 Document 객체 목록으로 반환한다.

        Args:
            file_path: 로드할 파일 경로

        Returns:
            Document 객체 목록. PDF는 페이지 단위, 나머지는 파일 단위로 반환.

        Raises:
            ValueError: 지원하지 않는 파일 형식인 경우
            RuntimeError: 파일 로드 중 오류 발생 시
        """
        path = Path(file_path)
        ext = path.suffix.lower()

        if ext not in SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"지원하지 않는 파일 형식: {ext}. "
                f"지원 형식: {', '.join(SUPPORTED_EXTENSIONS)}"
            )

        logger.info("문서 로드 시작: %s (형식: %s)", path.name, ext)

        try:
            if ext == ".pdf":
                docs = self._load_pdf(path)
            else:
                docs = self._load_text(path)

            logger.info(
                "문서 로드 완료: %s -> %d개 Document 생성", path.name, len(docs)
            )
            return docs

        except Exception as exc:
            logger.error("문서 로드 실패: %s | 오류: %s", path.name, exc)
            raise RuntimeError(f"'{path.name}' 로드 실패: {exc}") from exc

    def load_directory(
        self, recursive: bool = False
    ) -> Iterator[tuple[Path, list[Document]]]:
        """
        소스 디렉토리의 모든 지원 파일을 순차적으로 로드한다.

        Args:
            recursive: 하위 디렉토리까지 탐색할지 여부

        Yields:
            (파일 경로, Document 목록) 튜플
        """
        pattern = "**/*" if recursive else "*"
        files = [
            f
            for f in self.source_dir.glob(pattern)
            if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
        ]

        logger.info(
            "디렉토리 스캔 완료: %s | %d개 파일 발견", self.source_dir, len(files)
        )

        for file_path in sorted(files):
            try:
                docs = self.load_file(file_path)
                yield file_path, docs
            except (ValueError, RuntimeError) as exc:
                # 개별 파일 오류는 경고로 처리하고 계속 진행
                logger.warning("파일 스킵: %s | 사유: %s", file_path.name, exc)

    def _load_pdf(self, path: Path) -> list[Document]:
        """PDF 파일을 페이지 단위로 로드한다."""
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        docs: list[Document] = []
        file_hash = _compute_file_hash(path)

        for page_num, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            text = text.strip()

            if not text:
                logger.debug("빈 페이지 스킵: %s (페이지 %d)", path.name, page_num)
                continue

            docs.append(
                Document(
                    page_content=text,
                    metadata=_build_metadata(
                        path=path,
                        file_type="pdf",
                        file_hash=file_hash,
                        page=page_num,
                        total_pages=len(reader.pages),
                    ),
                )
            )

        return docs

    def _load_text(self, path: Path) -> list[Document]:
        """텍스트 또는 Markdown 파일을 로드한다."""
        # UTF-8 우선, 실패 시 CP949(한국어 인코딩) 시도
        for encoding in ("utf-8", "cp949", "utf-8-sig"):
            try:
                content = path.read_text(encoding=encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise RuntimeError(f"인코딩 감지 실패: {path.name}")

        content = content.strip()
        if not content:
            return []

        ext = path.suffix.lower()
        file_type = "markdown" if ext in (".md", ".markdown") else "text"

        return [
            Document(
                page_content=content,
                metadata=_build_metadata(
                    path=path,
                    file_type=file_type,
                    file_hash=_compute_file_hash(path),
                ),
            )
        ]


def _build_metadata(
    path: Path,
    file_type: str,
    file_hash: str,
    page: int | None = None,
    total_pages: int | None = None,
) -> dict:
    """문서 메타데이터를 구성한다."""
    metadata: dict = {
        "source": str(path.resolve()),
        "filename": path.name,
        "file_type": file_type,
        "file_hash": file_hash,
        "loaded_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    if page is not None:
        metadata["page"] = page
    if total_pages is not None:
        metadata["total_pages"] = total_pages
    return metadata


def _compute_file_hash(path: Path) -> str:
    """파일의 MD5 해시를 계산한다. 중복 문서 감지에 활용한다."""
    md5 = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            md5.update(chunk)
    return md5.hexdigest()
