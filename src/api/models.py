"""
FastAPI 요청/응답 Pydantic 모델 정의.

개선 사항 (v2):
    - IndexRequest에 mode 필드 추가 ("add"|"update")
    - IndexResponse에 chunks_deleted 필드 추가
    - HealthResponse에 embedding_model 필드 추가
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ---- 요청 모델 ----

class QueryRequest(BaseModel):
    """RAG 쿼리 요청 모델."""

    question: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="이슈 관련 질문",
        examples=["로그인 페이지에서 500 에러가 발생하는 원인은 무엇인가요?"],
    )
    top_k: int | None = Field(
        default=None,
        ge=1,
        le=20,
        description="검색 결과 최대 수 (기본값: 설정파일 값 사용)",
    )
    include_context: bool = Field(
        default=False,
        description="응답에 검색된 컨텍스트 포함 여부",
    )


class SearchRequest(BaseModel):
    """검색 전용 요청 모델 (LLM 호출 없음)."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="검색 쿼리",
    )
    top_k: int | None = Field(
        default=None,
        ge=1,
        le=20,
        description="검색 결과 최대 수",
    )


class IndexRequest(BaseModel):
    """문서 인덱싱 요청 모델."""

    source_dir: str | None = Field(
        default=None,
        description="인덱싱할 디렉토리 경로 (None이면 기본 설정 경로 사용)",
    )
    recursive: bool = Field(
        default=False,
        description="하위 디렉토리 포함 여부",
    )
    mode: Literal["add", "update"] = Field(
        default="add",
        description=(
            "인덱싱 모드: "
            "'add'=신규 파일만 추가 (file_hash 중복 스킵), "
            "'update'=기존 청크 삭제 후 재삽입 (파일 수정 시 갱신)"
        ),
    )


# ---- 응답 모델 ----

class SearchResultItem(BaseModel):
    """개별 검색 결과 아이템."""

    rank: int
    score: float
    source: str
    content: str
    metadata: dict[str, Any]


class QueryResponse(BaseModel):
    """RAG 쿼리 응답 모델."""

    question: str
    answer: str
    model: str
    context_count: int = Field(description="사용된 컨텍스트 청크 수")
    context: list[SearchResultItem] | None = Field(
        default=None,
        description="검색된 컨텍스트 (include_context=true일 때만 포함)",
    )
    usage: dict[str, int] = Field(description="토큰 사용량")


class SearchResponse(BaseModel):
    """검색 응답 모델."""

    query: str
    result_count: int
    results: list[SearchResultItem]


class IndexResponse(BaseModel):
    """인덱싱 응답 모델."""

    files_processed: int
    files_failed: int
    chunks_total: int
    chunks_added: int
    chunks_skipped: int
    chunks_deleted: int = Field(
        default=0, description="삭제된 기존 청크 수 (update 모드에서만 의미 있음)"
    )
    message: str


class StatsResponse(BaseModel):
    """인덱스 통계 응답 모델."""

    collection_name: str
    total_chunks: int


class HealthResponse(BaseModel):
    """헬스체크 응답 모델."""

    status: str
    version: str
    model: str
    embedding_model: str = Field(default="", description="사용 중인 임베딩 모델")


class ErrorResponse(BaseModel):
    """에러 응답 모델."""

    error: str
    detail: str | None = None
