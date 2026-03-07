"""QA 워크플로우 전용 FastAPI 요청/응답 Pydantic 모델."""
from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field


# ---- 요청 모델 ----

class ElaborateRequest(BaseModel):
    """Stage 1 이슈 구체화 요청."""
    raw_issue: str = Field(
        ..., min_length=1, max_length=5000,
        description="구체화할 원본 이슈 설명",
        examples=["로그인 시 500 에러 간헐적 발생"],
    )


class FeasibilityRequest(BaseModel):
    """Stage 2 테스트 가능여부 판단 요청."""
    elaborated_spec: str = Field(
        ..., min_length=1, max_length=10000,
        description="Stage 1에서 구체화된 이슈 전체 텍스트",
    )
    severity_estimate: Literal["Critical", "High", "Medium", "Low"] = Field(
        default="Medium",
        description="예상 심각도",
    )
    symptoms: str = Field(default="", description="증상 설명")
    root_cause_hypothesis: str = Field(default="", description="근본원인 가설")
    reproduction_steps: str = Field(default="", description="재현 단계")
    expected_vs_actual: str = Field(default="", description="예상 vs 실제 동작")
    affected_components: list[str] = Field(default_factory=list, description="영향받는 컴포넌트")


class RunPipelineRequest(BaseModel):
    """Stage 1~3 일괄 실행 요청 (파일 업로드 별도)."""
    raw_issue: str = Field(
        ..., min_length=1, max_length=5000,
        description="원본 이슈 설명",
    )


# ---- 응답 모델 ----

class ElaborateResponse(BaseModel):
    """Stage 1 이슈 구체화 응답."""
    elaborated_spec: str
    symptoms: str
    root_cause_hypothesis: str
    reproduction_steps: str
    expected_vs_actual: str
    severity_estimate: Literal["Critical", "High", "Medium", "Low"]
    affected_components: list[str]
    context_count: int = Field(description="RAG에서 사용된 컨텍스트 수")
    model: str


class FeasibilityResponse(BaseModel):
    """Stage 2 테스트 가능여부 응답."""
    verdict: Literal["testable", "not-testable", "partially-testable"]
    reasoning: str
    reproducibility_score: int = Field(ge=0, le=5)
    measurability_score: int = Field(ge=0, le=5)
    acceptance_clarity_score: int = Field(ge=0, le=5)
    test_scope_fit: bool
    recommended_test_cases: list[str]
    model: str


class ReportResponse(BaseModel):
    """Stage 3 QA 리포트 생성 응답."""
    report_markdown: str
    report_path: str
    issue_id: str
    verdict: str
    pass_rate: float | None
    generated_at: str
    model: str


class ValidationCriteriaResponse(BaseModel):
    """현재 적용 중인 검증 기준 응답."""
    reproducibility_required: bool
    measurability_required: bool
    acceptance_criteria_required: bool
    test_scope: str
    automation_required: bool
    manual_acceptable: bool
    custom_rules: list[str]
    raw_yaml: dict[str, Any]


class PipelineResponse(BaseModel):
    """Stage 1~3 일괄 실행 응답."""
    elaboration: ElaborateResponse
    feasibility: FeasibilityResponse
    report: ReportResponse
