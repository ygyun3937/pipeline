"""QA 워크플로우 FastAPI 라우터."""
from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from src.api.qa_models import (
    ElaborateRequest,
    ElaborateResponse,
    FeasibilityRequest,
    FeasibilityResponse,
    PipelineResponse,
    ReportResponse,
    ValidationCriteriaResponse,
)
from src.logger import get_logger
from src.pipeline import IssuePipeline
from src.qa.elaboration import ElaborationResult
from src.qa.test_result_parser import TestResultParser, TestResultSet

logger = get_logger(__name__)
_parser = TestResultParser()

router = APIRouter(prefix="/api/v1/qa", tags=["QA"])


def _get_pipeline() -> IssuePipeline:
    """Lazy import to avoid circular imports with main.py."""
    from src.api.main import get_pipeline
    return get_pipeline()


def _make_empty_retrieval_results():
    """빈 RetrievalResults 인스턴스를 생성한다."""
    from src.retrieval.retriever import RetrievalResults
    return RetrievalResults(query="", results=[])


def _elaboration_from_feasibility_request(req: FeasibilityRequest) -> ElaborationResult:
    """FeasibilityRequest를 ElaborationResult로 변환한다 (Stage 2 독립 호출용)."""
    return ElaborationResult(
        raw_input=req.elaborated_spec,
        elaborated_spec=req.elaborated_spec,
        symptoms=req.symptoms,
        root_cause_hypothesis=req.root_cause_hypothesis,
        reproduction_steps=req.reproduction_steps,
        expected_vs_actual=req.expected_vs_actual,
        severity_estimate=req.severity_estimate,
        affected_components=req.affected_components,
        context_used=_make_empty_retrieval_results(),
        model_name="provided",
    )


def _make_empty_test_results() -> TestResultSet:
    """파일 없을 때 사용할 빈 TestResultSet을 반환한다."""
    return TestResultSet(
        source_filename="no_file",
        format="unknown",
        total=0,
        passed=0,
        failed=0,
        skipped=0,
        test_cases=[],
        raw_content="",
    )


@router.post(
    "/elaborate",
    response_model=ElaborateResponse,
    summary="Stage 1: 이슈 구체화",
)
async def elaborate_issue(
    request: ElaborateRequest,
    pipeline: IssuePipeline = Depends(_get_pipeline),
) -> ElaborateResponse:
    """모호한 이슈 설명을 RAG를 통해 구체적인 스펙으로 변환한다."""
    result = await pipeline.qa_elaborate(request.raw_issue)
    return ElaborateResponse(
        elaborated_spec=result.elaborated_spec,
        symptoms=result.symptoms,
        root_cause_hypothesis=result.root_cause_hypothesis,
        reproduction_steps=result.reproduction_steps,
        expected_vs_actual=result.expected_vs_actual,
        severity_estimate=result.severity_estimate,
        affected_components=result.affected_components,
        context_count=len(result.context_used.results),
        model=result.model_name,
    )


@router.post(
    "/assess-feasibility",
    response_model=FeasibilityResponse,
    summary="Stage 2: 테스트 가능여부 판단",
)
async def assess_feasibility(
    request: FeasibilityRequest,
    pipeline: IssuePipeline = Depends(_get_pipeline),
) -> FeasibilityResponse:
    """구체화된 이슈 스펙의 테스트 가능여부를 검증 기준에 따라 판단한다."""
    elaboration = _elaboration_from_feasibility_request(request)
    result = await pipeline.qa_assess_feasibility(elaboration)
    return FeasibilityResponse(
        verdict=result.verdict,
        reasoning=result.reasoning,
        reproducibility_score=result.reproducibility_score,
        measurability_score=result.measurability_score,
        acceptance_clarity_score=result.acceptance_clarity_score,
        test_scope_fit=result.test_scope_fit,
        recommended_test_cases=result.recommended_test_cases,
        model=result.model_name,
    )


@router.post(
    "/generate-report",
    response_model=ReportResponse,
    summary="Stage 3: QA 리포트 생성",
)
async def generate_report(
    elaborated_spec: Annotated[str, Form(min_length=1, max_length=10000)],
    feasibility_verdict: Annotated[str, Form()],
    feasibility_reasoning: Annotated[str, Form()],
    recommended_test_cases: Annotated[str, Form()] = "[]",
    test_result_file: Annotated[UploadFile | None, File()] = None,
    pipeline: IssuePipeline = Depends(_get_pipeline),
) -> ReportResponse:
    """테스트 결과 파일(JSON/CSV/MD)과 함께 QA 리포트를 생성하고 저장한다."""
    from src.qa.feasibility import FeasibilityResult
    from src.qa.validation_criteria import ValidationCriteria

    # ElaborationResult 복원
    elaboration = ElaborationResult(
        raw_input=elaborated_spec,
        elaborated_spec=elaborated_spec,
        symptoms="",
        root_cause_hypothesis="",
        reproduction_steps="",
        expected_vs_actual="",
        severity_estimate="Medium",
        affected_components=[],
        context_used=_make_empty_retrieval_results(),
        model_name="provided",
    )

    # recommended_test_cases 파싱
    try:
        test_cases_list = json.loads(recommended_test_cases)
        if not isinstance(test_cases_list, list):
            test_cases_list = []
    except (json.JSONDecodeError, ValueError):
        test_cases_list = []

    # FeasibilityResult 복원
    feasibility = FeasibilityResult(
        verdict=feasibility_verdict,
        reasoning=feasibility_reasoning,
        reproducibility_score=3,
        measurability_score=3,
        acceptance_clarity_score=3,
        test_scope_fit=True,
        recommended_test_cases=test_cases_list,
        criteria_applied=ValidationCriteria(
            reproducibility_required=True,
            measurability_required=True,
            acceptance_criteria_required=True,
            test_scope="integration",
            automation_required=False,
            manual_acceptable=True,
            custom_rules=[],
            raw_yaml={},
        ),
    )

    # 테스트 결과 파싱
    if test_result_file and test_result_file.filename:
        content = await test_result_file.read()
        test_results = _parser.parse_bytes(
            content,
            filename=test_result_file.filename,
            media_type=test_result_file.content_type,
        )
    else:
        test_results = _make_empty_test_results()

    result = await pipeline.qa_generate_report(elaboration, feasibility, test_results)
    return ReportResponse(
        report_markdown=result.report_markdown,
        report_path=str(result.report_path),
        issue_id=result.issue_id,
        verdict=result.verdict,
        pass_rate=result.pass_rate,
        generated_at=result.generated_at,
        model=result.model_name,
    )


@router.post(
    "/run-pipeline",
    response_model=PipelineResponse,
    summary="Stage 1~3 일괄 실행",
)
async def run_pipeline(
    raw_issue: Annotated[str, Form(min_length=1, max_length=5000)],
    test_result_file: Annotated[UploadFile | None, File()] = None,
    pipeline: IssuePipeline = Depends(_get_pipeline),
) -> PipelineResponse:
    """Stage 1 이슈 구체화 → Stage 2 가능여부 판단 → Stage 3 리포트 생성을 순서대로 실행한다."""
    # Stage 1
    elaboration = await pipeline.qa_elaborate(raw_issue)

    # Stage 2
    feasibility = await pipeline.qa_assess_feasibility(elaboration)

    # 테스트 결과 파싱
    if test_result_file and test_result_file.filename:
        content = await test_result_file.read()
        test_results = _parser.parse_bytes(
            content,
            filename=test_result_file.filename,
            media_type=test_result_file.content_type,
        )
    else:
        test_results = _make_empty_test_results()

    # Stage 3
    report = await pipeline.qa_generate_report(elaboration, feasibility, test_results)

    elab_resp = ElaborateResponse(
        elaborated_spec=elaboration.elaborated_spec,
        symptoms=elaboration.symptoms,
        root_cause_hypothesis=elaboration.root_cause_hypothesis,
        reproduction_steps=elaboration.reproduction_steps,
        expected_vs_actual=elaboration.expected_vs_actual,
        severity_estimate=elaboration.severity_estimate,
        affected_components=elaboration.affected_components,
        context_count=len(elaboration.context_used.results),
        model=elaboration.model_name,
    )
    feas_resp = FeasibilityResponse(
        verdict=feasibility.verdict,
        reasoning=feasibility.reasoning,
        reproducibility_score=feasibility.reproducibility_score,
        measurability_score=feasibility.measurability_score,
        acceptance_clarity_score=feasibility.acceptance_clarity_score,
        test_scope_fit=feasibility.test_scope_fit,
        recommended_test_cases=feasibility.recommended_test_cases,
        model=feasibility.model_name,
    )
    report_resp = ReportResponse(
        report_markdown=report.report_markdown,
        report_path=str(report.report_path),
        issue_id=report.issue_id,
        verdict=report.verdict,
        pass_rate=report.pass_rate,
        generated_at=report.generated_at,
        model=report.model_name,
    )

    return PipelineResponse(
        elaboration=elab_resp,
        feasibility=feas_resp,
        report=report_resp,
    )


@router.get(
    "/validation-criteria",
    response_model=ValidationCriteriaResponse,
    summary="현재 검증 기준 조회",
)
async def get_validation_criteria(
    pipeline: IssuePipeline = Depends(_get_pipeline),
) -> ValidationCriteriaResponse:
    """현재 적용 중인 QA 검증 기준 YAML 내용을 반환한다."""
    criteria = pipeline._get_criteria_loader().load()
    return ValidationCriteriaResponse(
        reproducibility_required=criteria.reproducibility_required,
        measurability_required=criteria.measurability_required,
        acceptance_criteria_required=criteria.acceptance_criteria_required,
        test_scope=criteria.test_scope,
        automation_required=criteria.automation_required,
        manual_acceptable=criteria.manual_acceptable,
        custom_rules=criteria.custom_rules,
        raw_yaml=criteria.raw_yaml,
    )
