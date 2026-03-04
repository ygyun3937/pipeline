"""
문서 청킹(Chunking) 모듈.

LangChain의 RecursiveCharacterTextSplitter를 사용하여
긴 문서를 의미 있는 단위로 분할한다.

한국어 이슈 문서에 최적화된 구분자 전략:
  - Markdown 섹션 헤더(H2~H4)를 최우선으로 분리하여 섹션 경계를 유지한다.
  - 한국어 마침표(。)와 영어 마침표(.) 모두 문장 경계로 처리한다.
  - 느낌표, 물음표 등 문장 종결 부호를 포함한다.
  - chunk_size=800은 한국어 문서의 특성(조사, 어미 포함 밀도)을 반영한 권장값이다.
"""

from __future__ import annotations

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.logger import get_logger

logger = get_logger(__name__)

# 한국어 이슈 문서에 최적화된 청크 구분자 우선순위.
# 의미 단위(섹션 > 문단 > 문장 > 어절 > 문자) 순으로 분할한다.
# 한국어 특성:
#   - 문장 종결: 다. / 요. / 니다. / 습니다. 등 마침표로 끝남
#   - 열거: 줄바꿈(\n) 후 '-', '*', '1.' 등 시작
#   - 섹션 경계: Markdown 헤더 (##, ###)
KOREAN_ISSUE_SEPARATORS = [
    "\n## ",       # Markdown H2 헤더 (원인 분석, 해결 방법, 재발 방지 등 주요 섹션)
    "\n### ",      # Markdown H3 헤더
    "\n#### ",     # Markdown H4 헤더
    "\n\n",        # 빈 줄 (문단 경계, 한국어 문서에서 가장 강한 의미 경계)
    "\n",          # 줄바꿈 (목록 항목 경계)
    "다. ",        # 한국어 종결어미 '다'로 끝나는 문장
    "요. ",        # 한국어 종결어미 '요'로 끝나는 문장 (구어체)
    "다.\n",       # 줄바꿈 포함 문장 경계
    ". ",          # 영어/숫자 문장 끝 (오류 메시지, 코드 포함 시)
    "。",          # 한자권 마침표
    "? ",          # 의문문
    "! ",          # 감탄문
    ", ",          # 쉼표 (열거)
    " ",           # 어절 단위
    "",            # 마지막 수단: 문자 단위
]


class DocumentChunker:
    """
    Document 객체를 청크로 분할하는 클래스.

    한국어 이슈 문서(버그 리포트, 장애 보고서 등)에 최적화된
    구분자 우선순위와 chunk_size를 사용한다.

    주요 변경사항 (v2):
        - chunk_size 기본값: 1000 → 800 (한국어 밀도 반영)
        - chunk_overlap 기본값: 200 → 150 (overlap 비율 유지)
        - 한국어 종결어미 기반 구분자 추가
        - 총 청크 수(total_chunks)를 파일 전체 기준으로 계산
    """

    def __init__(self, chunk_size: int = 800, chunk_overlap: int = 150) -> None:
        """
        Args:
            chunk_size: 청크 최대 문자 수 (기본값: 800, 한국어 권장)
            chunk_overlap: 인접 청크 간 겹침 문자 수 (기본값: 150)
                           겹침이 있으면 문맥이 청크 경계에서 잘리지 않는다.
        """
        if chunk_overlap >= chunk_size:
            raise ValueError(
                f"chunk_overlap({chunk_overlap})은 chunk_size({chunk_size})보다 작아야 합니다."
            )

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=KOREAN_ISSUE_SEPARATORS,
            length_function=len,
            is_separator_regex=False,
            # 구분자를 청크 앞에 보존하여 Markdown 구조 유지
            keep_separator=True,
        )

        logger.info(
            "DocumentChunker 초기화 (한국어 최적화): chunk_size=%d, chunk_overlap=%d",
            chunk_size,
            chunk_overlap,
        )

    def chunk_documents(self, documents: list[Document]) -> list[Document]:
        """
        Document 목록을 청크 단위로 분할한다.

        원본 문서의 메타데이터는 각 청크에 복사되며,
        청크 인덱스(chunk_index)와 총 청크 수(total_chunks)가 추가된다.

        total_chunks는 해당 문서(doc) 기준으로 계산한다.
        동일 파일의 청크들이 같은 total_chunks 값을 공유하여
        "3/7 번째 청크" 와 같은 위치 추적이 가능하다.

        Args:
            documents: 분할할 Document 목록

        Returns:
            청크로 분할된 Document 목록
        """
        if not documents:
            logger.warning("청킹할 문서가 없습니다.")
            return []

        all_chunks: list[Document] = []
        total_original = len(documents)

        for doc_idx, doc in enumerate(documents):
            chunks = self._splitter.split_documents([doc])

            # 각 청크에 인덱스 메타데이터 추가
            # total_chunks: 이 문서(doc)에서 파생된 청크 수
            for chunk_idx, chunk in enumerate(chunks):
                chunk.metadata["chunk_index"] = chunk_idx
                chunk.metadata["total_chunks"] = len(chunks)
                chunk.metadata["doc_index"] = doc_idx
                all_chunks.append(chunk)

            logger.debug(
                "문서 %d/%d 청킹 완료: %d개 청크 생성 (원본: %d자)",
                doc_idx + 1,
                total_original,
                len(chunks),
                len(doc.page_content),
            )

        logger.info(
            "전체 청킹 완료: %d개 문서 -> %d개 청크",
            total_original,
            len(all_chunks),
        )
        return all_chunks

    def chunk_text(self, text: str, metadata: dict | None = None) -> list[Document]:
        """
        순수 텍스트를 청크로 분할한다.
        문서 객체 없이 텍스트만 있을 때 사용한다.

        Args:
            text: 분할할 텍스트
            metadata: 청크에 추가할 메타데이터

        Returns:
            청크 Document 목록
        """
        doc = Document(page_content=text, metadata=metadata or {})
        return self.chunk_documents([doc])

    def estimate_chunk_count(self, text: str) -> int:
        """
        텍스트를 실제 분할하지 않고 예상 청크 수를 추정한다.
        대용량 문서 처리 전 사전 검토에 유용하다.
        """
        if not text:
            return 0
        # 겹침을 고려한 간단한 추정식
        effective_size = self.chunk_size - self.chunk_overlap
        return max(1, (len(text) + effective_size - 1) // effective_size)
