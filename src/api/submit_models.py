"""이슈 제출 웹 폼 Pydantic 모델."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class IssueSubmitForm(BaseModel):
    """웹 폼 제출 데이터 모델."""

    domain: Literal["battery", "software", "incident"]
    severity: Literal["critical", "high", "medium", "low"]
    title: str = Field(min_length=2, max_length=200)
    symptom: str = Field(min_length=5)
    cause: str = Field(min_length=5)
    action: str = Field(min_length=5)
    prevention: str = ""

    # 배터리 전용
    alarm_code: str = ""
    channel: str = ""
    test_phase: str = ""

    # 소프트웨어/장애 전용
    affected_range: str = ""
    status: Literal["resolved", "ongoing", "investigating"] = "resolved"


class SubmitResult(BaseModel):
    """제출 결과."""

    issue_id: str
    filename: str
    domain: str
    indexed: bool
