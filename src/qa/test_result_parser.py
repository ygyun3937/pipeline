"""
테스트 결과 파서 모듈.

JSON, CSV, Markdown 형식의 테스트 결과 파일을 파싱하여
구조화된 TestResultSet 객체로 반환한다.

지원 형식:
    - JSON: 리스트 또는 {"tests": [...]} / {"testcases": [...]} / {"results": [...]} 구조
    - CSV: 헤더 행 포함, 필드명 자동 정규화
    - Markdown: 체크박스 목록(- [x] / - [ ]) 또는 표(| col | col |) 형식
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from src.logger import get_logger

logger = get_logger(__name__)


@dataclass
class TestCase:
    """개별 테스트 케이스 결과 객체."""

    id: str
    name: str
    status: Literal["pass", "fail", "skip", "error"]
    duration_ms: float | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TestResultSet:
    """테스트 결과 집합 객체."""

    source_filename: str
    format: Literal["json", "csv", "markdown", "unknown"]
    total: int
    passed: int
    failed: int
    skipped: int
    test_cases: list[TestCase] = field(default_factory=list)
    raw_content: str = ""

    @property
    def pass_rate(self) -> float:
        """통과율을 백분율로 반환한다 (소수점 1자리)."""
        if self.total == 0:
            return 0.0
        return round(self.passed / self.total * 100, 1)

    def to_summary_text(self) -> str:
        """
        Claude 프롬프트 삽입용 사람이 읽기 쉬운 요약 텍스트를 반환한다.

        파싱에 실패하여 test_cases가 비어 있으면 원본 내용을 직접 반환한다.
        """
        if not self.test_cases and self.total == 0:
            return (
                f"테스트 결과 파싱 불가 - 원본 내용 ({len(self.raw_content)}자)을"
                f" 직접 Claude에 전달합니다.\n\n원본:\n{self.raw_content[:3000]}"
            )

        lines = [
            f"파일: {self.source_filename} (형식: {self.format})",
            (
                f"전체: {self.total}개 | 통과: {self.passed}개 | "
                f"실패: {self.failed}개 | 스킵: {self.skipped}개 | "
                f"통과율: {self.pass_rate}%"
            ),
            "",
        ]
        failed_cases = [tc for tc in self.test_cases if tc.status in ("fail", "error")]
        if failed_cases:
            lines.append("=== 실패 케이스 ===")
            for tc in failed_cases:
                lines.append(f"[{tc.id}] {tc.name}")
                if tc.error_message:
                    lines.append(f"  오류: {tc.error_message}")
        return "\n".join(lines)


class TestResultParser:
    """
    JSON/CSV/Markdown 테스트 결과 파일을 파싱하는 클래스.

    파일 확장자 또는 media_type을 기반으로 포맷을 자동 감지하며,
    파싱 실패 시 raw_content를 포함한 fallback TestResultSet을 반환한다.
    """

    # 상태값 정규화 매핑
    STATUS_MAP: dict[str, str] = {
        "pass": "pass",
        "passed": "pass",
        "success": "pass",
        "ok": "pass",
        "true": "pass",
        "fail": "fail",
        "failed": "fail",
        "failure": "fail",
        "false": "fail",
        "error": "error",
        "skip": "skip",
        "skipped": "skip",
        "ignored": "skip",
    }

    # 필드명 별칭 집합
    NAME_ALIASES: set[str] = {"test_name", "testname", "name", "title", "description"}
    ID_ALIASES: set[str] = {"id", "test_id", "testid"}
    STATUS_ALIASES: set[str] = {"status", "result", "outcome", "state"}
    DURATION_ALIASES: set[str] = {"duration_ms", "durationms", "duration", "time_ms", "timems"}
    ERROR_ALIASES: set[str] = {
        "error_message",
        "errormessage",
        "error",
        "failure_message",
        "failuremessage",
        "message",
    }

    def parse_bytes(
        self,
        content: bytes,
        filename: str,
        media_type: str | None = None,
    ) -> TestResultSet:
        """
        바이트 데이터를 파싱하여 TestResultSet을 반환한다.

        Args:
            content: 파일 바이트 데이터
            filename: 원본 파일명 (확장자 감지에 사용)
            media_type: HTTP Content-Type (선택, 감지 보조에 사용)

        Returns:
            TestResultSet 객체. 파싱 실패 시 raw_content 포함 fallback 반환.
        """
        text = content.decode("utf-8", errors="replace")
        fmt = self._detect_format(filename, media_type)
        logger.info("테스트 결과 파싱: filename=%s, format=%s", filename, fmt)

        try:
            if fmt == "json":
                return self._parse_json(text, filename)
            elif fmt == "csv":
                return self._parse_csv(text, filename)
            elif fmt == "markdown":
                return self._parse_markdown(text, filename)
        except Exception as exc:
            logger.warning("파싱 실패, fallback 반환: %s", exc)

        return TestResultSet(
            source_filename=filename,
            format="unknown",
            total=0,
            passed=0,
            failed=0,
            skipped=0,
            raw_content=text,
        )

    def _detect_format(self, filename: str, media_type: str | None) -> str:
        """파일명 확장자 또는 media_type으로 포맷을 감지한다."""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

        if ext == "json" or media_type in ("application/json",):
            return "json"
        if ext == "csv" or media_type in ("text/csv",):
            return "csv"
        if ext in ("md", "markdown") or media_type in ("text/markdown",):
            return "markdown"
        return "unknown"

    def _normalise_status(self, raw: str) -> str:
        """원시 상태값을 표준 상태값으로 정규화한다. 매핑 실패 시 'fail' 반환."""
        return self.STATUS_MAP.get(str(raw).lower().strip(), "fail")

    def _get_field(self, row: dict, aliases: set[str], default: Any = None) -> Any:
        """
        딕셔너리에서 별칭 집합에 해당하는 첫 번째 값을 반환한다.

        키를 소문자 + 하이픈->언더스코어 변환 후 별칭과 비교한다.
        """
        for key in row:
            if key.lower().replace("-", "_") in aliases:
                return row[key]
        return default

    def _parse_json(self, content: str, filename: str) -> TestResultSet:
        """JSON 형식 테스트 결과를 파싱한다."""
        data = json.loads(content)
        cases: list[TestCase] = []

        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("tests", data.get("testcases", data.get("results", [])))
        else:
            raise ValueError("지원하지 않는 JSON 구조입니다.")

        for i, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            raw_id = self._get_field(item, self.ID_ALIASES, str(i + 1))
            raw_name = self._get_field(item, self.NAME_ALIASES, f"Test {i + 1}")
            raw_status = self._get_field(item, self.STATUS_ALIASES, "fail")
            raw_dur = self._get_field(item, self.DURATION_ALIASES)
            raw_err = self._get_field(item, self.ERROR_ALIASES)

            cases.append(
                TestCase(
                    id=str(raw_id),
                    name=str(raw_name),
                    status=self._normalise_status(str(raw_status)),  # type: ignore[arg-type]
                    duration_ms=float(raw_dur) if raw_dur is not None else None,
                    error_message=str(raw_err) if raw_err else None,
                )
            )

        passed = sum(1 for tc in cases if tc.status == "pass")
        failed = sum(1 for tc in cases if tc.status in ("fail", "error"))
        skipped = sum(1 for tc in cases if tc.status == "skip")

        return TestResultSet(
            source_filename=filename,
            format="json",
            total=len(cases),
            passed=passed,
            failed=failed,
            skipped=skipped,
            test_cases=cases,
            raw_content=content,
        )

    def _parse_csv(self, content: str, filename: str) -> TestResultSet:
        """CSV 형식 테스트 결과를 파싱한다."""
        reader = csv.DictReader(io.StringIO(content))
        cases: list[TestCase] = []

        for i, row in enumerate(reader):
            raw_id = self._get_field(row, self.ID_ALIASES, str(i + 1))
            raw_name = self._get_field(row, self.NAME_ALIASES, f"Test {i + 1}")
            raw_status = self._get_field(row, self.STATUS_ALIASES, "fail")
            raw_dur = self._get_field(row, self.DURATION_ALIASES)
            raw_err = self._get_field(row, self.ERROR_ALIASES)

            cases.append(
                TestCase(
                    id=str(raw_id),
                    name=str(raw_name),
                    status=self._normalise_status(str(raw_status)),  # type: ignore[arg-type]
                    duration_ms=float(raw_dur) if raw_dur else None,
                    error_message=str(raw_err) if raw_err else None,
                )
            )

        passed = sum(1 for tc in cases if tc.status == "pass")
        failed = sum(1 for tc in cases if tc.status in ("fail", "error"))
        skipped = sum(1 for tc in cases if tc.status == "skip")

        return TestResultSet(
            source_filename=filename,
            format="csv",
            total=len(cases),
            passed=passed,
            failed=failed,
            skipped=skipped,
            test_cases=cases,
            raw_content=content,
        )

    def _parse_markdown(self, content: str, filename: str) -> TestResultSet:
        """
        Markdown 형식 테스트 결과를 파싱한다.

        Pattern A: 체크박스 목록 (- [x] 통과 / - [ ] 실패)
        Pattern B: 마크다운 표 (| id | name | status | ...)
        """
        cases: list[TestCase] = []

        # Pattern A: 체크박스 목록
        # - [x] 테스트 이름
        # - [ ] 테스트 이름 - FAILED: 오류 메시지
        checkbox_pattern = re.compile(
            r"^\s*-\s+\[([xX ])\]\s+(.+?)(?:\s*[-\u2013]\s*(?:FAIL(?:ED)?|ERROR):\s*(.+))?$",
            re.MULTILINE,
        )
        for m in checkbox_pattern.finditer(content):
            checked = m.group(1)
            name_raw = m.group(2).strip()
            error = m.group(3)
            status = "pass" if checked.lower() == "x" else "fail"
            cases.append(
                TestCase(
                    id=str(len(cases) + 1),
                    name=name_raw,
                    status=status,  # type: ignore[arg-type]
                    error_message=error,
                )
            )

        # Pattern B: 마크다운 표
        if not cases:
            table_row = re.compile(r"^\|(.+)\|$", re.MULTILINE)
            rows = table_row.findall(content)
            header: list[str] | None = None

            for row in rows:
                cols = [c.strip() for c in row.split("|")]

                if header is None:
                    # 헤더 행 감지: status 관련 컬럼이 있는 행
                    if any(c.lower().replace(" ", "_") in self.STATUS_ALIASES for c in cols):
                        header = [c.lower().replace(" ", "_") for c in cols]
                    continue

                # 구분선 행 스킵 (--- 또는 ---- 등)
                if set(cols) <= {"-", "---", "----", "-----"}:
                    continue

                row_dict = dict(zip(header, cols))
                raw_id = self._get_field(row_dict, self.ID_ALIASES, str(len(cases) + 1))
                raw_name = self._get_field(
                    row_dict, self.NAME_ALIASES, f"Test {len(cases) + 1}"
                )
                raw_status = self._get_field(row_dict, self.STATUS_ALIASES, "fail")
                raw_err = self._get_field(row_dict, self.ERROR_ALIASES)

                cases.append(
                    TestCase(
                        id=str(raw_id),
                        name=str(raw_name),
                        status=self._normalise_status(str(raw_status)),  # type: ignore[arg-type]
                        error_message=str(raw_err) if raw_err else None,
                    )
                )

        if not cases:
            raise ValueError("마크다운에서 파싱 가능한 테스트 케이스를 찾을 수 없습니다.")

        passed = sum(1 for tc in cases if tc.status == "pass")
        failed = sum(1 for tc in cases if tc.status in ("fail", "error"))
        skipped = sum(1 for tc in cases if tc.status == "skip")

        return TestResultSet(
            source_filename=filename,
            format="markdown",
            total=len(cases),
            passed=passed,
            failed=failed,
            skipped=skipped,
            test_cases=cases,
            raw_content=content,
        )
