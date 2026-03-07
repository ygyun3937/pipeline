from __future__ import annotations
from fastapi import APIRouter, Depends
from src.api.alarm_models import AlarmPayload, AlarmReportResponse
from src.api.dependencies import get_pipeline
from src.logger import get_logger
from src.pipeline import IssuePipeline
from src.qa.test_result_parser import TestResultSet

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/alarm", tags=["Alarm QA"])


def _build_raw_issue(payload: AlarmPayload) -> str:
    """AlarmPayload를 Stage 1 입력용 자연어 이슈 설명으로 변환한다."""
    lines = [
        f"알람 코드: {payload.alarm_code}",
        f"알람 메시지: {payload.alarm_message}",
    ]
    if payload.unit_id:
        lines.append(f"채널/유닛: {payload.unit_id}")
    if payload.test_stage:
        lines.append(f"테스트 단계: {payload.test_stage}")
    if payload.elapsed_seconds is not None:
        lines.append(f"경과 시간: {payload.elapsed_seconds}초")
    measurements = []
    if payload.voltage is not None:
        measurements.append(f"전압 {payload.voltage}V")
    if payload.current is not None:
        measurements.append(f"전류 {payload.current}A")
    if payload.temperature is not None:
        measurements.append(f"온도 {payload.temperature}°C")
    if measurements:
        lines.append(f"측정값: {', '.join(measurements)}")
    return "\n".join(lines)


@router.post(
    "/ingest",
    response_model=AlarmReportResponse,
    summary="배터리 알람 자동 QA 처리",
)
async def ingest_alarm(
    payload: AlarmPayload,
    pipeline: IssuePipeline = Depends(get_pipeline),
) -> AlarmReportResponse:
    """장비 알람 발생 시 Stage 1~3 QA 파이프라인을 자동 실행한다."""
    logger.info("알람 수신: %s - %s", payload.alarm_code, payload.alarm_message)

    raw_issue = _build_raw_issue(payload)

    # Stage 1
    elaboration = await pipeline.qa_elaborate(raw_issue)

    # Stage 2
    criteria = pipeline.get_validation_criteria()
    feasibility = await pipeline.qa_assess_feasibility(elaboration, criteria)

    # Stage 3 (테스트 결과 없이 리포트 생성)
    empty_results = TestResultSet(
        source_filename="N/A (알람 자동 처리)",
        format="unknown",
        total=0,
        passed=0,
        failed=0,
        skipped=0,
        test_cases=[],
        raw_content="",
    )
    report = await pipeline.qa_generate_report(elaboration, feasibility, empty_results)

    logger.info(
        "알람 QA 완료: %s → 심각도=%s, 판정=%s, 리포트=%s",
        payload.alarm_code,
        elaboration.severity_estimate,
        feasibility.verdict,
        report.report_path,
    )

    return AlarmReportResponse(
        alarm_code=payload.alarm_code,
        severity=elaboration.severity_estimate,
        verdict=feasibility.verdict,
        reasoning=feasibility.reasoning,
        recommended_test_cases=feasibility.recommended_test_cases,
        report_path=str(report.report_path),
        report_summary=report.report_markdown[:500],
    )
