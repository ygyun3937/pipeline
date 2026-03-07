"""
RAG 파이프라인 오케스트레이터.

문서 수집, 임베딩, 검색, 생성의 전체 워크플로우를 통합하여 관리한다.
각 컴포넌트를 조립하고 의존성을 주입하는 중앙 조정자(coordinator) 역할을 한다.

개선 사항 (v2):
    - index_documents()에 mode 파라미터 추가 ("add"|"update")
    - update 모드: 수정된 파일의 기존 청크 삭제 후 재삽입
    - add 모드: file_hash 기반 중복 방지 (기존 동작 유지)
    - 인덱싱 통계에 deleted 필드 추가
    - IssueAnswerGenerator에 재시도 설정 주입
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from src.config import Settings, get_settings
from src.embedding.embedder import IssueEmbedder, IndexMode
from src.generation.generator import GenerationResult, IssueAnswerGenerator
from src.ingestion.chunker import DocumentChunker
from src.ingestion.document_loader import DocumentLoader
from src.logger import get_logger, setup_logging
from src.qa.elaboration import ElaborationResult, IssueElaborator
from src.qa.feasibility import FeasibilityAssessor, FeasibilityResult
from src.qa.report_generator import QAReportGenerator, QAReportResult
from src.qa.validation_criteria import ValidationCriteria, ValidationCriteriaLoader
from src.qa.test_result_parser import TestResultSet
from src.retrieval.retriever import IssueRetriever, RetrievalResults

logger = get_logger(__name__)


class IssuePipeline:
    """
    RAG 기반 이슈 파이프라인의 핵심 오케스트레이터.

    사용 예시:
        pipeline = IssuePipeline.from_settings()

        # 문서 인덱싱 (신규 파일만 추가)
        stats = pipeline.index_documents()

        # 문서 인덱싱 (수정된 파일도 갱신)
        stats = pipeline.index_documents(mode="update")

        # 질문 답변
        result = pipeline.query("로그인 오류의 원인은 무엇인가요?")
        print(result.answer)
    """

    def __init__(
        self,
        settings: Settings,
        loader: DocumentLoader,
        chunker: DocumentChunker,
        embedder: IssueEmbedder,
        retriever: IssueRetriever,
        generator: IssueAnswerGenerator,
    ) -> None:
        self._settings = settings
        self._loader = loader
        self._chunker = chunker
        self._embedder = embedder
        self._retriever = retriever
        self._generator = generator

        self._elaborator: IssueElaborator | None = None
        self._feasibility_assessor: FeasibilityAssessor | None = None
        self._report_generator: QAReportGenerator | None = None
        self._criteria_loader: ValidationCriteriaLoader | None = None

        logger.info("IssuePipeline 초기화 완료")

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "IssuePipeline":
        """
        설정값을 기반으로 파이프라인 인스턴스를 생성한다.
        각 컴포넌트의 의존성을 자동으로 주입한다.

        Args:
            settings: Settings 인스턴스 (None이면 환경변수에서 로드)

        Returns:
            IssuePipeline 인스턴스
        """
        cfg = settings or get_settings()

        # 로깅 설정
        setup_logging(log_level=cfg.log_level, log_format=cfg.log_format)

        logger.info("파이프라인 컴포넌트 초기화 중...")

        # 1. 문서 로더
        raw_dir = Path(cfg.raw_documents_dir)
        raw_dir.mkdir(parents=True, exist_ok=True)
        loader = DocumentLoader(source_dir=raw_dir)

        # 2. 청킹 (한국어 최적화: chunk_size=800, overlap=150)
        chunker = DocumentChunker(
            chunk_size=cfg.chunk_size,
            chunk_overlap=cfg.chunk_overlap,
        )

        # 3. 임베딩 및 ChromaDB 저장 (sentence-transformers/paraphrase-multilingual-mpnet-base-v2, 한국어 지원 다국어 모델)
        embedder = IssueEmbedder(
            embedding_model=cfg.embedding_model,
            chroma_persist_dir=cfg.chroma_persist_dir,
            collection_name=cfg.chroma_collection_name,
            batch_size=cfg.embedding_batch_size,
        )

        # 4. 검색기 (score_threshold=0.4 강화)
        retriever = IssueRetriever(
            vectorstore=embedder.vectorstore,
            top_k=cfg.retrieval_top_k,
            score_threshold=cfg.retrieval_score_threshold,
        )

        # 5. 답변 생성기 (Claude Agent SDK, API 키 불필요, tenacity 재시도)
        generator = IssueAnswerGenerator(
            max_retries=cfg.generation_max_retries,
            retry_wait_min=cfg.generation_retry_wait_min,
            retry_wait_max=cfg.generation_retry_wait_max,
        )

        return cls(
            settings=cfg,
            loader=loader,
            chunker=chunker,
            embedder=embedder,
            retriever=retriever,
            generator=generator,
        )

    def index_documents(
        self,
        source_dir: str | Path | None = None,
        recursive: bool = False,
        mode: IndexMode = "add",
    ) -> dict[str, Any]:
        """
        디렉토리의 모든 이슈 문서를 읽어 벡터 DB에 인덱싱한다.

        Args:
            source_dir: 문서 디렉토리 (None이면 설정값 사용)
            recursive: 하위 디렉토리 포함 여부
            mode: 인덱싱 모드
                - "add": 신규 파일만 추가 (file_hash 중복 스킵, 기본값)
                - "update": 기존 청크 삭제 후 재삽입 (수정 파일 갱신 시 사용)

        Returns:
            인덱싱 결과 통계
                - files_processed: 처리된 파일 수
                - files_failed: 실패한 파일 수
                - chunks_total: 전체 청크 수
                - chunks_added: 새로 추가된 청크 수
                - chunks_skipped: 중복으로 스킵된 청크 수 (add 모드)
                - chunks_deleted: 삭제된 기존 청크 수 (update 모드)
        """
        if source_dir:
            loader = DocumentLoader(source_dir=source_dir)
        else:
            loader = self._loader

        stats: dict[str, Any] = {
            "files_processed": 0,
            "files_failed": 0,
            "chunks_total": 0,
            "chunks_added": 0,
            "chunks_skipped": 0,
            "chunks_deleted": 0,
        }

        logger.info(
            "문서 인덱싱 시작: %s (mode=%s)", loader.source_dir, mode
        )

        for file_path, documents in loader.load_directory(recursive=recursive):
            try:
                # 청킹
                chunks = self._chunker.chunk_documents(documents)

                # 임베딩 및 저장 (mode 전달)
                result = self._embedder.add_documents(chunks, mode=mode)

                stats["files_processed"] += 1
                stats["chunks_total"] += result["total"]
                stats["chunks_added"] += result["added"]
                stats["chunks_skipped"] += result.get("skipped", 0)
                stats["chunks_deleted"] += result.get("deleted", 0)

                logger.info(
                    "파일 인덱싱 완료: %s | 추가=%d, 스킵=%d, 삭제=%d",
                    file_path.name,
                    result["added"],
                    result.get("skipped", 0),
                    result.get("deleted", 0),
                )

            except Exception as exc:
                stats["files_failed"] += 1
                logger.error("파일 인덱싱 실패: %s | 오류: %s", file_path.name, exc)

        logger.info("인덱싱 완료: %s", stats)
        return stats

    async def query(
        self,
        question: str,
        top_k: int | None = None,
    ) -> GenerationResult:
        """
        질문에 대해 RAG 기반 답변을 생성한다.

        파이프라인 순서:
            1. 질문을 임베딩하여 유사한 이슈 문서 청크 검색
            2. 검색 결과를 컨텍스트로 Claude API에 전달
            3. 4개 섹션(증상/원인/조치방법/주요 관련 이력) 형식으로 답변 반환

        Args:
            question: 사용자 질문
            top_k: 검색 결과 수 (None이면 설정값 사용)

        Returns:
            GenerationResult 객체
        """
        logger.info("RAG 쿼리 시작: '%s'", question[:200])

        # 1. 검색
        retrieval_results = self._retriever.search(question, top_k=top_k)

        if retrieval_results.is_empty:
            logger.warning("관련 문서 없음: 컨텍스트 없이 답변 생성")

        # 2. 답변 생성
        result = await self._generator.generate(
            question=question,
            retrieval_results=retrieval_results,
        )

        return result

    def search_only(
        self,
        query: str,
        top_k: int | None = None,
    ) -> RetrievalResults:
        """
        LLM 호출 없이 검색만 수행한다.
        검색 결과를 미리 확인하거나 디버깅할 때 유용하다.
        """
        return self._retriever.search(query, top_k=top_k)

    def get_index_stats(self) -> dict[str, Any]:
        """현재 벡터 DB 인덱스 통계를 반환한다."""
        return self._embedder.get_collection_stats()

    def _get_elaborator(self) -> IssueElaborator:
        if self._elaborator is None:
            self._elaborator = IssueElaborator(
                retriever=self._retriever,
                max_retries=self._settings.generation_max_retries,
                retry_wait_min=self._settings.generation_retry_wait_min,
                retry_wait_max=self._settings.generation_retry_wait_max,
                top_k=self._settings.qa_elaboration_top_k,
            )
        return self._elaborator

    def _get_feasibility_assessor(self) -> FeasibilityAssessor:
        if self._feasibility_assessor is None:
            self._feasibility_assessor = FeasibilityAssessor(
                max_retries=self._settings.generation_max_retries,
                retry_wait_min=self._settings.generation_retry_wait_min,
                retry_wait_max=self._settings.generation_retry_wait_max,
            )
        return self._feasibility_assessor

    def _get_report_generator(self) -> QAReportGenerator:
        if self._report_generator is None:
            self._report_generator = QAReportGenerator(
                reports_dir=self._settings.qa_reports_dir,
                max_retries=self._settings.generation_max_retries,
                retry_wait_min=self._settings.generation_retry_wait_min,
                retry_wait_max=self._settings.generation_retry_wait_max,
            )
        return self._report_generator

    def _get_criteria_loader(self) -> ValidationCriteriaLoader:
        if self._criteria_loader is None:
            self._criteria_loader = ValidationCriteriaLoader(
                criteria_path=self._settings.qa_validation_criteria_path,
            )
        return self._criteria_loader

    async def qa_elaborate(self, raw_issue: str) -> ElaborationResult:
        """Stage 1: 모호한 이슈를 RAG 기반으로 구체화한다."""
        logger.info("QA Stage 1 - 이슈 구체화 시작: '%s'", raw_issue[:100])
        elaborator = self._get_elaborator()
        result = await elaborator.elaborate(raw_issue)
        logger.info("QA Stage 1 완료 - 심각도: %s", result.severity_estimate)
        return result

    async def qa_assess_feasibility(
        self,
        elaboration: ElaborationResult,
        criteria: ValidationCriteria | None = None,
    ) -> FeasibilityResult:
        """Stage 2: 구체화된 이슈의 테스트 가능여부를 판단한다."""
        logger.info("QA Stage 2 - 테스트 가능여부 판단 시작")
        assessor = self._get_feasibility_assessor()
        if criteria is None:
            criteria = self._get_criteria_loader().load()
        result = await assessor.assess(elaboration, criteria)
        logger.info("QA Stage 2 완료 - verdict: %s", result.verdict)
        return result

    async def qa_generate_report(
        self,
        elaboration: ElaborationResult,
        feasibility: FeasibilityResult,
        test_results: TestResultSet,
    ) -> QAReportResult:
        """Stage 3: QA 리포트 Markdown을 생성하고 파일로 저장한다."""
        logger.info("QA Stage 3 - 리포트 생성 시작")
        generator = self._get_report_generator()
        result = await generator.generate_report(elaboration, feasibility, test_results)
        logger.info("QA Stage 3 완료 - 리포트 저장: %s", result.report_path)
        return result
