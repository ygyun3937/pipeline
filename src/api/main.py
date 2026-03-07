"""
FastAPI 기반 이슈 파이프라인 API 서버.

엔드포인트:
    GET  /health          - 서버 상태 확인 (임베딩 모델 포함)
    GET  /api/v1/stats    - 인덱스 통계 조회
    POST /api/v1/query    - RAG 질문 답변
    POST /api/v1/search   - 유사 문서 검색 (LLM 없음)
    POST /api/v1/index    - 문서 인덱싱 실행 (add|update 모드 지원)

의존성 주입:
    FastAPI의 Depends를 사용하여 파이프라인 인스턴스를 주입한다.
    애플리케이션 수명주기(lifespan)에서 한 번만 초기화한다.

개선 사항 (v2):
    - /health: embedding_model 필드 추가, settings.anthropic_model 참조 수정
    - /api/v1/index: mode 파라미터 처리 (add|update)
    - IndexResponse: chunks_deleted 필드 포함
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.models import (
    ErrorResponse,
    HealthResponse,
    IndexRequest,
    IndexResponse,
    QueryRequest,
    QueryResponse,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
    StatsResponse,
)
from src.api.qa_router import router as qa_router
from src.config import get_settings
from src.logger import get_logger, setup_logging
from src.pipeline import IssuePipeline

logger = get_logger(__name__)

# 파이프라인 싱글턴 (lifespan에서 초기화)
_pipeline: IssuePipeline | None = None

APP_VERSION = "0.2.0"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    FastAPI 애플리케이션 수명주기 관리.
    서버 시작 시 파이프라인을 초기화하고, 종료 시 리소스를 정리한다.
    """
    global _pipeline  # noqa: PLW0603

    settings = get_settings()
    setup_logging(log_level=settings.log_level, log_format=settings.log_format)

    logger.info("Issue Pipeline API 서버 시작 중... (v%s)", APP_VERSION)

    try:
        _pipeline = IssuePipeline.from_settings(settings)
        logger.info("파이프라인 초기화 완료 - API 서버 준비됨")
    except Exception as exc:
        logger.error("파이프라인 초기화 실패: %s", exc)
        raise

    yield  # 서버 실행 중

    logger.info("API 서버 종료 중...")
    _pipeline = None


def get_pipeline() -> IssuePipeline:
    """FastAPI 의존성 주입: 파이프라인 인스턴스를 반환한다."""
    if _pipeline is None:
        raise HTTPException(
            status_code=503,
            detail="파이프라인이 초기화되지 않았습니다. 서버를 재시작해주세요.",
        )
    return _pipeline


# FastAPI 앱 생성
app = FastAPI(
    title="Issue Pipeline API",
    description="사내 버그/이슈 문서를 RAG로 처리하는 지식 파이프라인 API",
    version=APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS 설정 (개발 환경)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 프로덕션에서는 실제 도메인으로 제한할 것
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# QA 라우터 등록
app.include_router(qa_router)


# ---- 전역 예외 핸들러 ----

@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    logger.warning("잘못된 입력값: %s", exc)
    return JSONResponse(
        status_code=400,
        content=ErrorResponse(error="잘못된 입력값", detail=str(exc)).model_dump(),
    )


@app.exception_handler(RuntimeError)
async def runtime_error_handler(request: Request, exc: RuntimeError) -> JSONResponse:
    logger.error("처리 중 오류 발생: %s", exc)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(error="서버 처리 오류", detail=str(exc)).model_dump(),
    )


# ---- 헬스체크 ----

@app.get(
    "/health",
    response_model=HealthResponse,
    summary="서버 상태 확인",
    tags=["System"],
)
async def health_check() -> HealthResponse:
    """서버가 정상 동작 중인지 확인한다."""
    settings = get_settings()
    return HealthResponse(
        status="healthy",
        version=APP_VERSION,
        model=settings.anthropic_model,
        embedding_model=settings.embedding_model,
    )


# ---- 통계 ----

@app.get(
    "/api/v1/stats",
    response_model=StatsResponse,
    summary="인덱스 통계 조회",
    tags=["Index"],
)
async def get_stats(
    pipeline: IssuePipeline = Depends(get_pipeline),
) -> StatsResponse:
    """벡터 DB에 저장된 청크 수 등 인덱스 통계를 반환한다."""
    stats = pipeline.get_index_stats()
    return StatsResponse(**stats)


# ---- 문서 인덱싱 ----

@app.post(
    "/api/v1/index",
    response_model=IndexResponse,
    summary="문서 인덱싱",
    tags=["Index"],
)
async def index_documents(
    request: IndexRequest,
    pipeline: IssuePipeline = Depends(get_pipeline),
) -> IndexResponse:
    """
    지정된 디렉토리의 이슈 문서를 읽어 벡터 DB에 인덱싱한다.

    mode="add" (기본값): 이미 인덱싱된 파일은 자동으로 스킵된다 (멱등성 보장).
    mode="update": 기존 청크를 삭제 후 재삽입한다 (수정된 파일 갱신).
    """
    logger.info(
        "인덱싱 요청: source_dir=%s, recursive=%s, mode=%s",
        request.source_dir,
        request.recursive,
        request.mode,
    )

    stats = pipeline.index_documents(
        source_dir=request.source_dir,
        recursive=request.recursive,
        mode=request.mode,
    )

    mode_desc = "갱신" if request.mode == "update" else "추가"
    return IndexResponse(
        **stats,
        message=(
            f"{stats['files_processed']}개 파일 처리 완료 "
            f"({stats['chunks_added']}개 청크 {mode_desc}, "
            f"{stats['chunks_skipped']}개 스킵, "
            f"{stats.get('chunks_deleted', 0)}개 삭제)"
        ),
    )


# ---- RAG 쿼리 ----

@app.post(
    "/api/v1/query",
    response_model=QueryResponse,
    summary="RAG 질문 답변",
    tags=["RAG"],
)
async def query(
    request: QueryRequest,
    pipeline: IssuePipeline = Depends(get_pipeline),
) -> QueryResponse:
    """
    이슈 문서를 검색하여 컨텍스트를 구성하고 Claude API로 답변을 생성한다.

    - 증상 / 원인 / 조치방법 / 주요 관련 이력 4개 섹션으로 답변한다.
    - 관련 이슈 문서가 없는 경우에도 답변을 생성한다 (컨텍스트 없음으로 표시).
    - include_context=true로 요청하면 검색된 원본 청크도 함께 반환한다.
    """
    logger.info("쿼리 요청: '%s'", request.question[:100])

    result = await pipeline.query(question=request.question, top_k=request.top_k)

    # 컨텍스트 포함 여부에 따라 응답 구성
    context_items = None
    if request.include_context:
        context_items = [
            SearchResultItem(**r.to_dict())
            for r in result.context_used.results
        ]

    return QueryResponse(
        question=result.question,
        answer=result.answer,
        model=result.model_name,
        context_count=len(result.context_used.results),
        context=context_items,
        usage={
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
        },
    )


# ---- 검색 전용 ----

@app.post(
    "/api/v1/search",
    response_model=SearchResponse,
    summary="유사 문서 검색 (LLM 없음)",
    tags=["RAG"],
)
async def search(
    request: SearchRequest,
    pipeline: IssuePipeline = Depends(get_pipeline),
) -> SearchResponse:
    """
    LLM 호출 없이 벡터 검색만 수행하여 유사한 이슈 청크를 반환한다.
    검색 결과 확인이나 디버깅에 유용하다.
    """
    logger.info("검색 요청: '%s'", request.query[:100])

    results = pipeline.search_only(query=request.query, top_k=request.top_k)

    return SearchResponse(
        query=results.query,
        result_count=len(results.results),
        results=[SearchResultItem(**r.to_dict()) for r in results.results],
    )
