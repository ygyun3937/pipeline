"""
QAReportGenerator 단위 테스트.

llm_client.complete를 AsyncMock으로 패치하고 tmp_path 픽스처로 임시 디렉터리를 사용한다.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from src.qa.elaboration import ElaborationResult
from src.qa.feasibility import FeasibilityResult
from src.qa.report_generator import QAReportGenerator, QAReportResult
from src.qa.test_result_parser import TestResultSet
from src.qa.validation_criteria import ValidationCriteria
from src.retrieval.retriever import RetrievalResults


def _make_mock_llm(model_name: str = "test-model") -> MagicMock:
    """LLMClient Mock을 생성한다."""
    mock = MagicMock()
    mock.complete = AsyncMock(return_value="mock response")
    mock.model_name = model_name
    return mock


# ---------------------------------------------------------------------------
# 헬퍼 팩토리
# ---------------------------------------------------------------------------

def _make_elaboration(
    raw_input: str = "로그인 오류 발생",
    elaborated_spec: str = "spec text",
    severity: str = "High",
) -> ElaborationResult:
    return ElaborationResult(
        raw_input=raw_input,
        elaborated_spec=elaborated_spec,
        symptoms="symptom",
        root_cause_hypothesis="root cause",
        reproduction_steps="steps",
        expected_vs_actual="expected vs actual",
        severity_estimate=severity,  # type: ignore[arg-type]
        affected_components=["auth"],
        context_used=RetrievalResults(query="", results=[]),
        model_name="test",
    )


def _make_criteria() -> ValidationCriteria:
    return ValidationCriteria(
        reproducibility_required=True,
        measurability_required=True,
        acceptance_criteria_required=True,
        test_scope="integration",
        automation_required=False,
        manual_acceptable=True,
        custom_rules=[],
        raw_yaml={},
    )


def _make_feasibility(verdict: str = "testable") -> FeasibilityResult:
    return FeasibilityResult(
        verdict=verdict,  # type: ignore[arg-type]
        reasoning="ok",
        reproducibility_score=4,
        measurability_score=4,
        acceptance_clarity_score=4,
        test_scope_fit=True,
        recommended_test_cases=["Test login"],
        criteria_applied=_make_criteria(),
    )


def _make_test_results(total: int = 0, passed: int = 0) -> TestResultSet:
    return TestResultSet(
        source_filename="results.json",
        format="json",
        total=total,
        passed=passed,
        failed=total - passed,
        skipped=0,
    )


FAKE_REPORT_MARKDOWN = """\
# QA Report

## Issue Summary
로그인 오류 발생에 대한 QA 리포트

## Verdict
testable

## Test Results
총 10개 중 9개 통과
"""


# ---------------------------------------------------------------------------
# generate_report() 해피 패스
# ---------------------------------------------------------------------------

class TestGenerateReportHappyPath:
    """generate_report() 정상 동작 테스트."""

    @pytest.mark.asyncio
    async def test_returns_qa_report_result(self, tmp_path: Path) -> None:
        generator = QAReportGenerator(llm_client=_make_mock_llm(), reports_dir=tmp_path)
        elaboration = _make_elaboration()
        feasibility = _make_feasibility()
        test_results = _make_test_results()

        with patch.object(
            generator._llm,
            "complete",
            new=AsyncMock(return_value=FAKE_REPORT_MARKDOWN),
        ):
            result = await generator.generate_report(elaboration, feasibility, test_results)

        assert isinstance(result, QAReportResult)

    @pytest.mark.asyncio
    async def test_report_markdown_matches_agent_output(self, tmp_path: Path) -> None:
        generator = QAReportGenerator(llm_client=_make_mock_llm(), reports_dir=tmp_path)
        elaboration = _make_elaboration()
        feasibility = _make_feasibility()
        test_results = _make_test_results()

        with patch.object(
            generator._llm,
            "complete",
            new=AsyncMock(return_value=FAKE_REPORT_MARKDOWN),
        ):
            result = await generator.generate_report(elaboration, feasibility, test_results)

        assert result.report_markdown == FAKE_REPORT_MARKDOWN

    @pytest.mark.asyncio
    async def test_report_saved_to_disk(self, tmp_path: Path) -> None:
        generator = QAReportGenerator(llm_client=_make_mock_llm(), reports_dir=tmp_path)
        elaboration = _make_elaboration()
        feasibility = _make_feasibility()
        test_results = _make_test_results()

        with patch.object(
            generator._llm,
            "complete",
            new=AsyncMock(return_value=FAKE_REPORT_MARKDOWN),
        ):
            result = await generator.generate_report(elaboration, feasibility, test_results)

        assert result.report_path.exists()
        assert result.report_path.read_text(encoding="utf-8") == FAKE_REPORT_MARKDOWN

    @pytest.mark.asyncio
    async def test_report_path_is_in_reports_dir(self, tmp_path: Path) -> None:
        generator = QAReportGenerator(llm_client=_make_mock_llm(), reports_dir=tmp_path)
        elaboration = _make_elaboration()
        feasibility = _make_feasibility()
        test_results = _make_test_results()

        with patch.object(
            generator._llm,
            "complete",
            new=AsyncMock(return_value=FAKE_REPORT_MARKDOWN),
        ):
            result = await generator.generate_report(elaboration, feasibility, test_results)

        assert result.report_path.parent == tmp_path

    @pytest.mark.asyncio
    async def test_verdict_mirrors_feasibility(self, tmp_path: Path) -> None:
        generator = QAReportGenerator(llm_client=_make_mock_llm(), reports_dir=tmp_path)
        elaboration = _make_elaboration()
        feasibility = _make_feasibility(verdict="not-testable")
        test_results = _make_test_results()

        with patch.object(
            generator._llm,
            "complete",
            new=AsyncMock(return_value=FAKE_REPORT_MARKDOWN),
        ):
            result = await generator.generate_report(elaboration, feasibility, test_results)

        assert result.verdict == "not-testable"

    @pytest.mark.asyncio
    async def test_pass_rate_none_when_no_tests(self, tmp_path: Path) -> None:
        generator = QAReportGenerator(llm_client=_make_mock_llm(), reports_dir=tmp_path)
        elaboration = _make_elaboration()
        feasibility = _make_feasibility()
        test_results = _make_test_results(total=0)

        with patch.object(
            generator._llm,
            "complete",
            new=AsyncMock(return_value=FAKE_REPORT_MARKDOWN),
        ):
            result = await generator.generate_report(elaboration, feasibility, test_results)

        assert result.pass_rate is None

    @pytest.mark.asyncio
    async def test_pass_rate_set_when_tests_present(self, tmp_path: Path) -> None:
        generator = QAReportGenerator(llm_client=_make_mock_llm(), reports_dir=tmp_path)
        elaboration = _make_elaboration()
        feasibility = _make_feasibility()
        test_results = _make_test_results(total=10, passed=9)

        with patch.object(
            generator._llm,
            "complete",
            new=AsyncMock(return_value=FAKE_REPORT_MARKDOWN),
        ):
            result = await generator.generate_report(elaboration, feasibility, test_results)

        assert result.pass_rate == pytest.approx(90.0)

    @pytest.mark.asyncio
    async def test_generated_at_is_iso_format(self, tmp_path: Path) -> None:
        generator = QAReportGenerator(llm_client=_make_mock_llm(), reports_dir=tmp_path)
        elaboration = _make_elaboration()
        feasibility = _make_feasibility()
        test_results = _make_test_results()

        with patch.object(
            generator._llm,
            "complete",
            new=AsyncMock(return_value=FAKE_REPORT_MARKDOWN),
        ):
            result = await generator.generate_report(elaboration, feasibility, test_results)

        # ISO 8601: 최소한 'T' 구분자가 포함되어야 한다
        assert "T" in result.generated_at

    @pytest.mark.asyncio
    async def test_raises_runtime_error_on_agent_failure(self, tmp_path: Path) -> None:
        generator = QAReportGenerator(llm_client=_make_mock_llm(), reports_dir=tmp_path)
        elaboration = _make_elaboration()
        feasibility = _make_feasibility()
        test_results = _make_test_results()

        with patch.object(
            generator._llm,
            "complete",
            new=AsyncMock(side_effect=RuntimeError("network error")),
        ):
            with pytest.raises(RuntimeError):
                await generator.generate_report(elaboration, feasibility, test_results)


# ---------------------------------------------------------------------------
# _build_report_filename()
# ---------------------------------------------------------------------------

class TestBuildReportFilename:
    """_build_report_filename() 포맷 검증."""

    def test_starts_with_prefix(self, tmp_path: Path) -> None:
        generator = QAReportGenerator(llm_client=_make_mock_llm(), reports_dir=tmp_path, filename_prefix="QA_REPORT")
        elaboration = _make_elaboration(severity="High")
        feasibility = _make_feasibility(verdict="testable")

        filename = generator._build_report_filename(elaboration, feasibility)
        assert filename.startswith("QA_REPORT_")

    def test_ends_with_md(self, tmp_path: Path) -> None:
        generator = QAReportGenerator(llm_client=_make_mock_llm(), reports_dir=tmp_path)
        elaboration = _make_elaboration()
        feasibility = _make_feasibility()

        filename = generator._build_report_filename(elaboration, feasibility)
        assert filename.endswith(".md")

    def test_contains_severity(self, tmp_path: Path) -> None:
        generator = QAReportGenerator(llm_client=_make_mock_llm(), reports_dir=tmp_path)
        elaboration = _make_elaboration(severity="Critical")
        feasibility = _make_feasibility()

        filename = generator._build_report_filename(elaboration, feasibility)
        assert "CRITICAL" in filename

    def test_contains_verdict(self, tmp_path: Path) -> None:
        generator = QAReportGenerator(llm_client=_make_mock_llm(), reports_dir=tmp_path)
        elaboration = _make_elaboration()
        feasibility = _make_feasibility(verdict="not-testable")

        filename = generator._build_report_filename(elaboration, feasibility)
        assert "NOT_TESTABLE" in filename

    def test_custom_prefix(self, tmp_path: Path) -> None:
        generator = QAReportGenerator(llm_client=_make_mock_llm(), reports_dir=tmp_path, filename_prefix="TEST_RPT")
        elaboration = _make_elaboration()
        feasibility = _make_feasibility()

        filename = generator._build_report_filename(elaboration, feasibility)
        assert filename.startswith("TEST_RPT_")


# ---------------------------------------------------------------------------
# _save_report()
# ---------------------------------------------------------------------------

class TestSaveReport:
    """_save_report() OSError → RuntimeError 변환 테스트."""

    def test_save_creates_file(self, tmp_path: Path) -> None:
        generator = QAReportGenerator(llm_client=_make_mock_llm(), reports_dir=tmp_path)
        path = generator._save_report("# Test Report", "test_report.md")

        assert path.exists()
        assert path.read_text(encoding="utf-8") == "# Test Report"

    def test_save_os_error_raises_runtime_error(self, tmp_path: Path) -> None:
        """파일 저장 실패 시 OSError → RuntimeError 변환."""
        generator = QAReportGenerator(llm_client=_make_mock_llm(), reports_dir=tmp_path)

        with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
            with pytest.raises(RuntimeError, match="저장 실패"):
                generator._save_report("# Report", "fail.md")

    def test_save_returns_path_object(self, tmp_path: Path) -> None:
        generator = QAReportGenerator(llm_client=_make_mock_llm(), reports_dir=tmp_path)
        path = generator._save_report("content", "report.md")

        assert isinstance(path, Path)


# ---------------------------------------------------------------------------
# _extract_issue_id()
# ---------------------------------------------------------------------------

class TestExtractIssueId:
    """_extract_issue_id() ID 추출 및 fallback 테스트."""

    def test_extracts_bug_id_from_raw_input(self, tmp_path: Path) -> None:
        generator = QAReportGenerator(llm_client=_make_mock_llm(), reports_dir=tmp_path)
        elaboration = _make_elaboration(raw_input="BUG-2024-001 로그인 오류")

        issue_id = generator._extract_issue_id(elaboration)
        assert issue_id == "BUG-2024-001"

    def test_extracts_incident_id(self, tmp_path: Path) -> None:
        generator = QAReportGenerator(llm_client=_make_mock_llm(), reports_dir=tmp_path)
        elaboration = _make_elaboration(
            raw_input="INCIDENT-2024-042 서비스 장애"
        )

        issue_id = generator._extract_issue_id(elaboration)
        assert issue_id == "INCIDENT-2024-042"

    def test_extracts_id_from_elaborated_spec(self, tmp_path: Path) -> None:
        generator = QAReportGenerator(llm_client=_make_mock_llm(), reports_dir=tmp_path)
        elaboration = _make_elaboration(
            raw_input="일반 이슈 설명",
            elaborated_spec="ISSUE-2024-100 상세 스펙 내용",
        )

        issue_id = generator._extract_issue_id(elaboration)
        assert issue_id == "ISSUE-2024-100"

    def test_fallback_id_when_no_pattern(self, tmp_path: Path) -> None:
        generator = QAReportGenerator(llm_client=_make_mock_llm(), reports_dir=tmp_path)
        elaboration = _make_elaboration(
            raw_input="패턴 없는 이슈 설명",
            elaborated_spec="패턴 없는 스펙",
        )

        issue_id = generator._extract_issue_id(elaboration)
        assert issue_id.startswith("QA-")

    def test_id_uppercased(self, tmp_path: Path) -> None:
        """추출된 ID는 대문자로 반환된다."""
        generator = QAReportGenerator(llm_client=_make_mock_llm(), reports_dir=tmp_path)
        elaboration = _make_elaboration(raw_input="bug-2024-001 소문자 이슈")

        issue_id = generator._extract_issue_id(elaboration)
        assert issue_id == "BUG-2024-001"

    def test_feat_id_extracted(self, tmp_path: Path) -> None:
        generator = QAReportGenerator(llm_client=_make_mock_llm(), reports_dir=tmp_path)
        elaboration = _make_elaboration(raw_input="FEAT-2024-999 기능 요청")

        issue_id = generator._extract_issue_id(elaboration)
        assert issue_id == "FEAT-2024-999"


# ---------------------------------------------------------------------------
# reports_dir 자동 생성
# ---------------------------------------------------------------------------

class TestReportsDirCreation:
    """reports_dir이 없으면 자동 생성되는지 확인."""

    def test_creates_missing_directory(self, tmp_path: Path) -> None:
        new_dir = tmp_path / "nested" / "reports"
        assert not new_dir.exists()

        generator = QAReportGenerator(llm_client=_make_mock_llm(), reports_dir=new_dir)

        assert new_dir.exists()
