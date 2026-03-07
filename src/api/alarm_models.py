from __future__ import annotations
from pydantic import BaseModel, Field


class AlarmPayload(BaseModel):
    """장비 알람 수신 페이로드."""
    alarm_code: str = Field(..., description="알람 코드 (예: OVP-001)")
    alarm_message: str = Field(..., description="알람 메시지")
    voltage: float | None = Field(None, description="발생 시점 전압(V)")
    current: float | None = Field(None, description="발생 시점 전류(A)")
    temperature: float | None = Field(None, description="발생 시점 온도(°C)")
    unit_id: str | None = Field(None, description="장비 유닛/채널 ID")
    test_stage: str | None = Field(None, description="테스트 단계 (예: CC_CHARGE)")
    elapsed_seconds: int | None = Field(None, description="테스트 시작 후 경과 시간(초)")


_REPORT_SUMMARY_MAX_CHARS = 500


class AlarmReportResponse(BaseModel):
    """알람 QA 리포트 응답."""
    alarm_code: str = Field(..., description="알람 코드 (예: OVP-001)")
    severity: str = Field(..., description="심각도 추정값 (예: High, Critical)")
    verdict: str = Field(..., description="테스트 가능 여부 판정 (testable/not-testable/partially-testable)")
    reasoning: str = Field(..., description="판정 근거 설명")
    recommended_test_cases: list[str] = Field(..., description="권장 테스트 케이스 목록")
    report_path: str = Field(..., description="생성된 QA 리포트 파일 경로")
    report_summary: str = Field(
        ...,
        description=f"QA 리포트 요약 (최대 {_REPORT_SUMMARY_MAX_CHARS}자)",
    )
