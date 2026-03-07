"""
TestResultParser 단위 테스트.

외부 의존성 없이 순수 파싱 로직만 테스트한다.
"""

from __future__ import annotations

import json

import pytest

from src.qa.test_result_parser import TestResultParser, TestResultSet


@pytest.fixture
def parser() -> TestResultParser:
    return TestResultParser()


# ---------------------------------------------------------------------------
# JSON 파싱
# ---------------------------------------------------------------------------

class TestParseJsonList:
    """JSON 리스트 레이아웃 파싱."""

    def test_basic_list(self, parser: TestResultParser) -> None:
        data = [
            {"id": "1", "name": "Login test", "status": "pass"},
            {"id": "2", "name": "Logout test", "status": "fail", "error_message": "Timeout"},
            {"id": "3", "name": "Skip test", "status": "skip"},
        ]
        content = json.dumps(data).encode()
        result = parser.parse_bytes(content, "results.json")

        assert result.format == "json"
        assert result.total == 3
        assert result.passed == 1
        assert result.failed == 1
        assert result.skipped == 1

    def test_status_normalization(self, parser: TestResultParser) -> None:
        """'passed', 'success', 'failed', 'failure' 등 다양한 상태값 정규화."""
        data = [
            {"name": "t1", "status": "passed"},
            {"name": "t2", "status": "success"},
            {"name": "t3", "status": "failure"},
            {"name": "t4", "status": "failed"},
            {"name": "t5", "status": "skipped"},
        ]
        content = json.dumps(data).encode()
        result = parser.parse_bytes(content, "norm.json")

        statuses = [tc.status for tc in result.test_cases]
        assert statuses == ["pass", "pass", "fail", "fail", "skip"]

    def test_duration_parsed(self, parser: TestResultParser) -> None:
        data = [{"name": "t1", "status": "pass", "duration_ms": 123.4}]
        content = json.dumps(data).encode()
        result = parser.parse_bytes(content, "dur.json")

        assert result.test_cases[0].duration_ms == pytest.approx(123.4)

    def test_auto_id_assigned_when_missing(self, parser: TestResultParser) -> None:
        data = [{"name": "t1", "status": "pass"}]
        content = json.dumps(data).encode()
        result = parser.parse_bytes(content, "noid.json")

        assert result.test_cases[0].id == "1"

    def test_error_message_captured(self, parser: TestResultParser) -> None:
        data = [{"name": "t1", "status": "fail", "error_message": "AssertionError"}]
        content = json.dumps(data).encode()
        result = parser.parse_bytes(content, "err.json")

        assert result.test_cases[0].error_message == "AssertionError"


class TestParseJsonDict:
    """JSON 딕셔너리 레이아웃 파싱 (tests / testcases / results 키)."""

    def test_tests_key(self, parser: TestResultParser) -> None:
        data = {"tests": [{"name": "t1", "status": "pass"}]}
        content = json.dumps(data).encode()
        result = parser.parse_bytes(content, "dict.json")

        assert result.total == 1
        assert result.passed == 1

    def test_testcases_key(self, parser: TestResultParser) -> None:
        data = {"testcases": [{"name": "t1", "status": "fail"}]}
        content = json.dumps(data).encode()
        result = parser.parse_bytes(content, "dict.json")

        assert result.total == 1
        assert result.failed == 1

    def test_results_key(self, parser: TestResultParser) -> None:
        data = {"results": [{"name": "t1", "status": "skip"}]}
        content = json.dumps(data).encode()
        result = parser.parse_bytes(content, "dict.json")

        assert result.total == 1
        assert result.skipped == 1

    def test_media_type_overrides_extension(self, parser: TestResultParser) -> None:
        """media_type=application/json이면 확장자 무관하게 JSON으로 파싱."""
        data = [{"name": "t1", "status": "pass"}]
        content = json.dumps(data).encode()
        result = parser.parse_bytes(content, "results.txt", media_type="application/json")

        assert result.format == "json"
        assert result.total == 1


# ---------------------------------------------------------------------------
# CSV 파싱
# ---------------------------------------------------------------------------

class TestParseCsv:
    """CSV 형식 파싱 및 컬럼명 정규화."""

    def test_basic_csv(self, parser: TestResultParser) -> None:
        csv_text = "name,status,duration_ms\nLogin,pass,100\nLogout,fail,200\n"
        content = csv_text.encode()
        result = parser.parse_bytes(content, "results.csv")

        assert result.format == "csv"
        assert result.total == 2
        assert result.passed == 1
        assert result.failed == 1

    def test_column_aliases(self, parser: TestResultParser) -> None:
        """'result' 컬럼도 status로 인식된다."""
        csv_text = "test_name,result\nAuth,passed\nSession,failed\n"
        content = csv_text.encode()
        result = parser.parse_bytes(content, "aliases.csv")

        assert result.total == 2
        assert result.passed == 1
        assert result.failed == 1

    def test_csv_with_error_column(self, parser: TestResultParser) -> None:
        csv_text = "name,status,message\nTest A,fail,NullPointer\n"
        content = csv_text.encode()
        result = parser.parse_bytes(content, "err.csv")

        assert result.test_cases[0].error_message == "NullPointer"

    def test_csv_duration_column(self, parser: TestResultParser) -> None:
        csv_text = "name,status,duration\nTest A,pass,500\n"
        content = csv_text.encode()
        result = parser.parse_bytes(content, "dur.csv")

        assert result.test_cases[0].duration_ms == pytest.approx(500.0)

    def test_csv_media_type(self, parser: TestResultParser) -> None:
        csv_text = "name,status\nTest,pass\n"
        content = csv_text.encode()
        result = parser.parse_bytes(content, "file.txt", media_type="text/csv")

        assert result.format == "csv"


# ---------------------------------------------------------------------------
# Markdown 파싱
# ---------------------------------------------------------------------------

class TestParseMarkdownCheckbox:
    """Markdown 체크박스 (- [x] / - [ ]) 파싱."""

    def test_basic_checkboxes(self, parser: TestResultParser) -> None:
        md = "- [x] Login succeeds\n- [ ] Logout clears session\n- [x] Token refreshes\n"
        content = md.encode()
        result = parser.parse_bytes(content, "results.md")

        assert result.format == "markdown"
        assert result.total == 3
        assert result.passed == 2
        assert result.failed == 1

    def test_uppercase_x_checkbox(self, parser: TestResultParser) -> None:
        md = "- [X] Test passes\n"
        content = md.encode()
        result = parser.parse_bytes(content, "upper.md")

        assert result.test_cases[0].status == "pass"

    def test_checkbox_names_extracted(self, parser: TestResultParser) -> None:
        md = "- [x] My Test Name\n"
        content = md.encode()
        result = parser.parse_bytes(content, "names.md")

        assert result.test_cases[0].name == "My Test Name"

    def test_checkbox_assigns_sequential_ids(self, parser: TestResultParser) -> None:
        md = "- [x] First\n- [ ] Second\n"
        content = md.encode()
        result = parser.parse_bytes(content, "ids.md")

        assert result.test_cases[0].id == "1"
        assert result.test_cases[1].id == "2"


class TestParseMarkdownTable:
    """Markdown 표 파싱."""

    def test_basic_table(self, parser: TestResultParser) -> None:
        md = (
            "| id | name | status |\n"
            "|----|------|--------|\n"
            "| 1  | Auth test | pass |\n"
            "| 2  | DB test   | fail |\n"
        )
        content = md.encode()
        result = parser.parse_bytes(content, "table.md")

        assert result.format == "markdown"
        assert result.total == 2
        assert result.passed == 1
        assert result.failed == 1

    def test_table_with_gfm_alignment_separators(self, parser: TestResultParser) -> None:
        """GFM 정렬 구분선(:---:, :---, ---:) 스킵 확인."""
        md = (
            "| name | status |\n"
            "|:-----|-------:|\n"
            "| Test A | pass |\n"
        )
        content = md.encode()
        result = parser.parse_bytes(content, "gfm.md")

        assert result.total == 1
        assert result.passed == 1

    def test_table_with_result_column(self, parser: TestResultParser) -> None:
        """'result' 컬럼 별칭도 status로 인식된다."""
        md = (
            "| name | result |\n"
            "| ---- | ------ |\n"
            "| Test | passed |\n"
        )
        content = md.encode()
        result = parser.parse_bytes(content, "alias.md")

        assert result.passed == 1


# ---------------------------------------------------------------------------
# Fallback (파싱 실패)
# ---------------------------------------------------------------------------

class TestFallback:
    """파싱 실패 시 graceful fallback 검증."""

    def test_unknown_extension_returns_fallback(self, parser: TestResultParser) -> None:
        """알 수 없는 확장자: format='unknown', total=0, raw_content 포함."""
        content = b"some random content"
        result = parser.parse_bytes(content, "results.txt")

        assert result.format == "unknown"
        assert result.total == 0
        assert result.raw_content == "some random content"

    def test_invalid_json_returns_fallback(self, parser: TestResultParser) -> None:
        """잘못된 JSON 파싱 실패 시 fallback 반환."""
        content = b"this is not json {"
        result = parser.parse_bytes(content, "bad.json")

        assert result.format == "unknown"
        assert result.total == 0

    def test_markdown_with_no_parseable_content_returns_fallback(
        self, parser: TestResultParser
    ) -> None:
        """파싱 가능한 체크박스/표가 없는 마크다운은 fallback."""
        content = b"# Just a heading\n\nSome text without tests."
        result = parser.parse_bytes(content, "empty.md")

        assert result.total == 0


# ---------------------------------------------------------------------------
# pass_rate 프로퍼티
# ---------------------------------------------------------------------------

class TestPassRate:
    """TestResultSet.pass_rate 프로퍼티."""

    def test_pass_rate_zero_when_no_tests(self, parser: TestResultParser) -> None:
        result = TestResultSet(
            source_filename="f.json",
            format="json",
            total=0,
            passed=0,
            failed=0,
            skipped=0,
        )
        assert result.pass_rate == 0.0

    def test_pass_rate_hundred_percent(self, parser: TestResultParser) -> None:
        result = TestResultSet(
            source_filename="f.json",
            format="json",
            total=4,
            passed=4,
            failed=0,
            skipped=0,
        )
        assert result.pass_rate == 100.0

    def test_pass_rate_partial(self, parser: TestResultParser) -> None:
        result = TestResultSet(
            source_filename="f.json",
            format="json",
            total=3,
            passed=1,
            failed=2,
            skipped=0,
        )
        assert result.pass_rate == pytest.approx(33.3, abs=0.1)

    def test_pass_rate_from_json_parse(self, parser: TestResultParser) -> None:
        data = [
            {"name": "t1", "status": "pass"},
            {"name": "t2", "status": "pass"},
            {"name": "t3", "status": "fail"},
            {"name": "t4", "status": "fail"},
        ]
        content = json.dumps(data).encode()
        result = parser.parse_bytes(content, "rate.json")

        assert result.pass_rate == 50.0


# ---------------------------------------------------------------------------
# to_summary_text()
# ---------------------------------------------------------------------------

class TestToSummaryText:
    """TestResultSet.to_summary_text() 출력 검증."""

    def test_summary_contains_filename(self, parser: TestResultParser) -> None:
        data = [{"name": "t1", "status": "pass"}]
        content = json.dumps(data).encode()
        result = parser.parse_bytes(content, "my_results.json")

        summary = result.to_summary_text()
        assert "my_results.json" in summary

    def test_summary_contains_counts(self, parser: TestResultParser) -> None:
        data = [
            {"name": "t1", "status": "pass"},
            {"name": "t2", "status": "fail"},
        ]
        content = json.dumps(data).encode()
        result = parser.parse_bytes(content, "counts.json")

        summary = result.to_summary_text()
        assert "통과" in summary
        assert "실패" in summary

    def test_summary_contains_pass_rate(self, parser: TestResultParser) -> None:
        data = [{"name": "t1", "status": "pass"}]
        content = json.dumps(data).encode()
        result = parser.parse_bytes(content, "rate.json")

        summary = result.to_summary_text()
        assert "100.0" in summary

    def test_summary_lists_failed_cases(self, parser: TestResultParser) -> None:
        data = [{"name": "Auth fails", "status": "fail", "error_message": "NullPointer"}]
        content = json.dumps(data).encode()
        result = parser.parse_bytes(content, "fail.json")

        summary = result.to_summary_text()
        assert "Auth fails" in summary
        assert "NullPointer" in summary

    def test_summary_fallback_when_parse_fails(self, parser: TestResultParser) -> None:
        """파싱 실패 시 raw_content를 포함한 fallback 텍스트를 반환한다."""
        content = b"raw unparseable content"
        result = parser.parse_bytes(content, "bad.txt")

        summary = result.to_summary_text()
        assert "raw unparseable content" in summary
