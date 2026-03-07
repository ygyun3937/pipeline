"""
FeasibilityAssessor 단위 테스트.

_query_agent를 AsyncMock으로 패치하여 실제 LLM 호출 없이 테스트한다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.qa.elaboration import ElaborationResult
from src.qa.feasibility import FeasibilityAssessor, FeasibilityResult
from src.qa.validation_criteria import ValidationCriteria
from src.retrieval.retriever import RetrievalResults


# ---------------------------------------------------------------------------
# 헬퍼 팩토리
# ---------------------------------------------------------------------------

def _make_elaboration(
    elaborated_spec: str = "spec text",
    severity: str = "High",
) -> ElaborationResult:
    return ElaborationResult(
        raw_input="test issue",
        elaborated_spec=elaborated_spec,
        symptoms="symptom description",
        root_cause_hypothesis="root cause hypothesis",
        reproduction_steps="steps to reproduce",
        expected_vs_actual="expected vs actual",
        severity_estimate=severity,  # type: ignore[arg-type]
        affected_components=["auth"],
        context_used=RetrievalResults(query="", results=[]),
        model_name="test",
    )


def _make_criteria(test_scope: str = "integration") -> ValidationCriteria:
    return ValidationCriteria(
        reproducibility_required=True,
        measurability_required=True,
        acceptance_criteria_required=True,
        test_scope=test_scope,
        automation_required=False,
        manual_acceptable=True,
        custom_rules=[],
        raw_yaml={},
    )


FAKE_FEASIBILITY_RESPONSE = """\
### 판정
testable - 이슈는 테스트 가능합니다.

### 근거
재현 단계가 명확하고 측정 기준이 있습니다.

### 점수
- 재현 가능성: 4/5
- 측정 가능성: 4/5
- 합격 기준 명확성: 3/5

### 테스트 범위 적합성
yes - integration 테스트 적합

### 권장 테스트 케이스
1. Test login with valid credentials
2. Test login with invalid credentials
3. Test concurrent login requests
"""

FAKE_NOT_TESTABLE_RESPONSE = """\
### 판정
not-testable - 이슈는 테스트 불가합니다.

### 근거
재현 단계가 명확하지 않습니다.

### 점수
- 재현 가능성: 1/5
- 측정 가능성: 2/5
- 합격 기준 명확성: 1/5

### 테스트 범위 적합성
no - 부적합

### 권장 테스트 케이스
"""

FAKE_PARTIALLY_TESTABLE_RESPONSE = """\
### 판정
partially-testable - 일부만 테스트 가능합니다.

### 근거
일부 기능은 테스트 가능하지만 전체는 불가합니다.

### 점수
- 재현 가능성: 3/5
- 측정 가능성: 2/5
- 합격 기준 명확성: 3/5

### 테스트 범위 적합성
yes - 부분적 적합

### 권장 테스트 케이스
1. Partial test case A
"""

FAKE_EMPTY_RESPONSE = "이 응답에는 구조화된 섹션이 없습니다."


@pytest.fixture
def assessor() -> FeasibilityAssessor:
    return FeasibilityAssessor(max_retries=1)


# ---------------------------------------------------------------------------
# assess() 해피 패스
# ---------------------------------------------------------------------------

class TestAssessHappyPath:
    """assess() 정상 동작 테스트."""

    @pytest.mark.asyncio
    async def test_returns_feasibility_result(self, assessor: FeasibilityAssessor) -> None:
        elaboration = _make_elaboration()
        criteria = _make_criteria()

        with patch.object(
            assessor, "_query_agent", new=AsyncMock(return_value=FAKE_FEASIBILITY_RESPONSE)
        ):
            result = await assessor.assess(elaboration, criteria)

        assert isinstance(result, FeasibilityResult)

    @pytest.mark.asyncio
    async def test_criteria_applied_set(self, assessor: FeasibilityAssessor) -> None:
        elaboration = _make_elaboration()
        criteria = _make_criteria()

        with patch.object(
            assessor, "_query_agent", new=AsyncMock(return_value=FAKE_FEASIBILITY_RESPONSE)
        ):
            result = await assessor.assess(elaboration, criteria)

        assert result.criteria_applied is criteria

    @pytest.mark.asyncio
    async def test_raises_value_error_for_empty_spec(
        self, assessor: FeasibilityAssessor
    ) -> None:
        elaboration = _make_elaboration(elaborated_spec="")
        criteria = _make_criteria()

        with pytest.raises(ValueError, match="비어"):
            await assessor.assess(elaboration, criteria)

    @pytest.mark.asyncio
    async def test_raises_runtime_error_on_agent_failure(
        self, assessor: FeasibilityAssessor
    ) -> None:
        elaboration = _make_elaboration()
        criteria = _make_criteria()

        with patch.object(
            assessor,
            "_query_agent",
            new=AsyncMock(side_effect=RuntimeError("network error")),
        ):
            with pytest.raises(RuntimeError):
                await assessor.assess(elaboration, criteria)

    @pytest.mark.asyncio
    async def test_model_name_set(self, assessor: FeasibilityAssessor) -> None:
        elaboration = _make_elaboration()
        criteria = _make_criteria()

        with patch.object(
            assessor, "_query_agent", new=AsyncMock(return_value=FAKE_FEASIBILITY_RESPONSE)
        ):
            result = await assessor.assess(elaboration, criteria)

        assert result.model_name == "claude-agent-sdk"


# ---------------------------------------------------------------------------
# _parse_feasibility() 판정 파싱
# ---------------------------------------------------------------------------

class TestParseFeasibilityVerdict:
    """verdict 파싱 테스트."""

    def test_testable_verdict(self, assessor: FeasibilityAssessor) -> None:
        criteria = _make_criteria()
        parsed = assessor._parse_feasibility(FAKE_FEASIBILITY_RESPONSE, criteria)
        assert parsed["verdict"] == "testable"

    def test_not_testable_verdict(self, assessor: FeasibilityAssessor) -> None:
        criteria = _make_criteria()
        parsed = assessor._parse_feasibility(FAKE_NOT_TESTABLE_RESPONSE, criteria)
        assert parsed["verdict"] == "not-testable"

    def test_partially_testable_verdict(self, assessor: FeasibilityAssessor) -> None:
        criteria = _make_criteria()
        parsed = assessor._parse_feasibility(FAKE_PARTIALLY_TESTABLE_RESPONSE, criteria)
        assert parsed["verdict"] == "partially-testable"

    def test_default_verdict_on_missing_section(
        self, assessor: FeasibilityAssessor
    ) -> None:
        """판정 섹션이 없으면 기본값 'partially-testable'."""
        criteria = _make_criteria()
        parsed = assessor._parse_feasibility(FAKE_EMPTY_RESPONSE, criteria)
        assert parsed["verdict"] == "partially-testable"


# ---------------------------------------------------------------------------
# 점수 파싱
# ---------------------------------------------------------------------------

class TestParseFeasibilityScores:
    """점수(0-5) 파싱 테스트."""

    def test_reproducibility_score(self, assessor: FeasibilityAssessor) -> None:
        criteria = _make_criteria()
        parsed = assessor._parse_feasibility(FAKE_FEASIBILITY_RESPONSE, criteria)
        assert parsed["reproducibility_score"] == 4

    def test_measurability_score(self, assessor: FeasibilityAssessor) -> None:
        criteria = _make_criteria()
        parsed = assessor._parse_feasibility(FAKE_FEASIBILITY_RESPONSE, criteria)
        assert parsed["measurability_score"] == 4

    def test_acceptance_clarity_score(self, assessor: FeasibilityAssessor) -> None:
        criteria = _make_criteria()
        parsed = assessor._parse_feasibility(FAKE_FEASIBILITY_RESPONSE, criteria)
        assert parsed["acceptance_clarity_score"] == 3

    def test_not_testable_scores_are_low(self, assessor: FeasibilityAssessor) -> None:
        criteria = _make_criteria()
        parsed = assessor._parse_feasibility(FAKE_NOT_TESTABLE_RESPONSE, criteria)
        assert parsed["reproducibility_score"] == 1
        assert parsed["measurability_score"] == 2

    def test_default_scores_when_missing(self, assessor: FeasibilityAssessor) -> None:
        """점수 섹션이 없으면 기본값 3."""
        criteria = _make_criteria()
        parsed = assessor._parse_feasibility(FAKE_EMPTY_RESPONSE, criteria)
        assert parsed["reproducibility_score"] == 3
        assert parsed["measurability_score"] == 3
        assert parsed["acceptance_clarity_score"] == 3


# ---------------------------------------------------------------------------
# test_scope_fit 파싱
# ---------------------------------------------------------------------------

class TestParseScopeFit:
    """test_scope_fit 파싱 테스트."""

    def test_scope_fit_true_when_yes(self, assessor: FeasibilityAssessor) -> None:
        criteria = _make_criteria()
        parsed = assessor._parse_feasibility(FAKE_FEASIBILITY_RESPONSE, criteria)
        assert parsed["test_scope_fit"] is True

    def test_scope_fit_false_when_no(self, assessor: FeasibilityAssessor) -> None:
        criteria = _make_criteria()
        parsed = assessor._parse_feasibility(FAKE_NOT_TESTABLE_RESPONSE, criteria)
        assert parsed["test_scope_fit"] is False

    def test_scope_fit_default_true_when_missing(
        self, assessor: FeasibilityAssessor
    ) -> None:
        """테스트 범위 섹션이 없으면 기본값 True."""
        criteria = _make_criteria()
        parsed = assessor._parse_feasibility(FAKE_EMPTY_RESPONSE, criteria)
        assert parsed["test_scope_fit"] is True


# ---------------------------------------------------------------------------
# 권장 테스트 케이스 파싱
# ---------------------------------------------------------------------------

class TestParseRecommendedTestCases:
    """권장 테스트 케이스 리스트 파싱 테스트."""

    def test_test_cases_extracted(self, assessor: FeasibilityAssessor) -> None:
        criteria = _make_criteria()
        parsed = assessor._parse_feasibility(FAKE_FEASIBILITY_RESPONSE, criteria)

        cases = parsed["recommended_test_cases"]
        assert len(cases) == 3
        assert any("login" in c.lower() for c in cases)

    def test_test_cases_empty_when_none_listed(
        self, assessor: FeasibilityAssessor
    ) -> None:
        criteria = _make_criteria()
        parsed = assessor._parse_feasibility(FAKE_NOT_TESTABLE_RESPONSE, criteria)
        assert parsed["recommended_test_cases"] == []

    def test_single_test_case(self, assessor: FeasibilityAssessor) -> None:
        criteria = _make_criteria()
        parsed = assessor._parse_feasibility(FAKE_PARTIALLY_TESTABLE_RESPONSE, criteria)
        assert len(parsed["recommended_test_cases"]) == 1
        assert "Partial test case A" in parsed["recommended_test_cases"][0]


# ---------------------------------------------------------------------------
# 통합: assess() 결과 필드 검증
# ---------------------------------------------------------------------------

class TestAssessResultFields:
    """assess() 반환값의 모든 필드 검증."""

    @pytest.mark.asyncio
    async def test_all_fields_present(self, assessor: FeasibilityAssessor) -> None:
        elaboration = _make_elaboration()
        criteria = _make_criteria()

        with patch.object(
            assessor, "_query_agent", new=AsyncMock(return_value=FAKE_FEASIBILITY_RESPONSE)
        ):
            result = await assessor.assess(elaboration, criteria)

        assert result.verdict == "testable"
        assert isinstance(result.reasoning, str)
        assert 0 <= result.reproducibility_score <= 5
        assert 0 <= result.measurability_score <= 5
        assert 0 <= result.acceptance_clarity_score <= 5
        assert isinstance(result.test_scope_fit, bool)
        assert isinstance(result.recommended_test_cases, list)
        assert result.criteria_applied is criteria
