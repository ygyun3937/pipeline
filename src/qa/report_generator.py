"""
QA 리포트 생성(Report Generation) 모듈.

Stage 3: 구체화된 이슈 스펙, 테스트 가능성 평가 결과, 실제 테스트 결과를
         종합하여 완성도 높은 QA 리포트 초안을 생성하고 파일로 저장한다.

동작 흐름:
    1. ElaborationResult(Stage 1), FeasibilityResult(Stage 2), TestResultSet을 입력받는다.
    2. REPORT_QUERY_TEMPLATE으로 사용자 메시지를 구성한다.
    3. Claude Agent SDK를 호출하여 리포트를 생성한다.
    4. 결과를 파일로 저장하고 QAReportResult 데이터클래스로 반환한다.
"""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, query

from src._agent_lock import AGENT_ENV_LOCK as _AGENT_ENV_LOCK
from src.logger import get_logger
from src.qa.elaboration import ElaborationResult
from src.qa.feasibility import FeasibilityResult
from src.qa.prompts import REPORT_QUERY_TEMPLATE, REPORT_SYSTEM_PROMPT
from src.qa.test_result_parser import TestResultSet

logger = get_logger(__name__)


@dataclass
class QAReportResult:
    """QA 리포트 생성 결과 객체."""

    report_markdown: str        # Full rendered markdown report from Claude
    report_path: Path           # Saved file path
    issue_id: str               # Extracted from elaboration or generated timestamp
    verdict: str                # Mirrors FeasibilityResult.verdict
    pass_rate: float | None     # From TestResultSet.pass_rate, None if no test results
    generated_at: str           # ISO 8601 timestamp
    model_name: str = "claude-agent-sdk"


class QAReportGenerator:
    """
    Claude Agent SDK를 사용하여 QA 리포트를 생성하는 클래스.

    ElaborationResult(Stage 1), FeasibilityResult(Stage 2), TestResultSet을 입력받아
    REPORT_SYSTEM_PROMPT와 함께 Claude에게 리포트 생성을 요청하고
    결과를 Markdown 파일로 저장한다.
    """

    def __init__(
        self,
        reports_dir: str | Path,
        max_retries: int = 3,
        retry_wait_min: float = 1.0,
        retry_wait_max: float = 10.0,
    ) -> None:
        """
        Args:
            reports_dir: 리포트 파일을 저장할 디렉터리 경로
            max_retries: 최대 재시도 횟수 (기본값: 3)
            retry_wait_min: 재시도 최소 대기 시간(초) (기본값: 1.0)
            retry_wait_max: 재시도 최대 대기 시간(초) (기본값: 10.0)
        """
        self._reports_dir = Path(reports_dir)
        self._reports_dir.mkdir(parents=True, exist_ok=True)
        self.max_retries = max_retries
        self.retry_wait_min = retry_wait_min
        self.retry_wait_max = retry_wait_max
        self.model_name = "claude-agent-sdk"

        logger.info(
            "QAReportGenerator 초기화: Claude Agent SDK 사용 (API 키 불필요), "
            "reports_dir=%s, max_retries=%d",
            self._reports_dir,
            max_retries,
        )

    async def generate_report(
        self,
        elaboration: ElaborationResult,
        feasibility: FeasibilityResult,
        test_results: TestResultSet,
    ) -> QAReportResult:
        """
        QA 리포트를 생성하고 파일로 저장한다.

        Args:
            elaboration: Stage 1 이슈 구체화 결과
            feasibility: Stage 2 테스트 가능성 평가 결과
            test_results: 실제 테스트 결과 집합

        Returns:
            QAReportResult 객체

        Raises:
            RuntimeError: 최대 재시도 횟수 초과 후에도 생성 실패 시
        """
        # 1. Build user_message from REPORT_QUERY_TEMPLATE
        user_message = REPORT_QUERY_TEMPLATE.format(
            elaborated_issue=elaboration.to_prompt_text(),
            feasibility_summary=feasibility.to_prompt_text(),
            test_results_text=test_results.to_summary_text(),
        )

        # 2. Call _generate_with_retry
        try:
            raw_text = await self._generate_with_retry(user_message)
            logger.info("QA 리포트 생성 완료: %d자", len(raw_text))
        except Exception as exc:
            logger.error("QA 리포트 생성 최종 실패: %s", exc)
            raise RuntimeError(f"Agent SDK QA 리포트 생성 중 오류: {exc}") from exc

        # 3. Save to file
        generated_at = datetime.now(timezone.utc).isoformat()
        filename = self._build_report_filename(elaboration, feasibility)
        report_path = self._save_report(raw_text, filename)

        # 4. Extract metadata and return QAReportResult
        issue_id = self._extract_issue_id(elaboration)
        pass_rate = test_results.pass_rate if test_results.total > 0 else None

        return QAReportResult(
            report_markdown=raw_text,
            report_path=report_path,
            issue_id=issue_id,
            verdict=feasibility.verdict,
            pass_rate=pass_rate,
            generated_at=generated_at,
            model_name=self.model_name,
        )

    def _build_report_filename(
        self, elaboration: ElaborationResult, feasibility: FeasibilityResult
    ) -> str:
        """Build filename: QA_REPORT_{YYYYMMDD_HHMMSS_uuuuuu}_{severity}_{verdict}.md"""
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y%m%d_%H%M%S_") + f"{now.microsecond:06d}"
        severity = elaboration.severity_estimate.upper()
        verdict = feasibility.verdict.upper().replace("-", "_")
        return f"QA_REPORT_{timestamp}_{severity}_{verdict}.md"

    def _save_report(self, content: str, filename: str) -> Path:
        """Save report markdown to reports_dir/filename."""
        report_path = self._reports_dir / filename
        try:
            report_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            logger.error("QA 리포트 파일 저장 실패: %s | 오류: %s", report_path, exc)
            raise RuntimeError(f"QA 리포트 저장 실패: {exc}") from exc
        logger.info("QA 리포트 저장 완료: %s", report_path)
        return report_path

    def _extract_issue_id(self, elaboration: ElaborationResult) -> str:
        """Try to extract issue ID from raw_input or elaborated_spec.

        Pattern: BUG-XXXX-XXX, INCIDENT-XXXX-XXX, ISSUE-XXXX-XXX, etc.
        Falls back to timestamp-based ID if not found.
        """
        pattern = r'\b(BUG|INCIDENT|ISSUE|FEAT|REQ)-\d{4}-\d{3,}\b'
        for text in (elaboration.raw_input, elaboration.elaborated_spec):
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0).upper()
        # Fallback: timestamp-based
        return f"QA-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

    async def _generate_with_retry(self, user_message: str) -> str:
        """
        수동 재시도 루프.
        일시적 연결 오류나 런타임 오류 발생 시 지수 백오프로 재시도한다.
        """
        last_exc: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                return await self._query_agent(user_message)
            except (RuntimeError, ConnectionError, TimeoutError) as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    wait_time = min(
                        self.retry_wait_min * (2 ** (attempt - 1)),
                        self.retry_wait_max,
                    )
                    logger.warning(
                        "QA 리포트 생성 재시도 %d/%d (%.1f초 대기): %s",
                        attempt,
                        self.max_retries,
                        wait_time,
                        exc,
                    )
                    await asyncio.sleep(wait_time)

        raise last_exc  # type: ignore[misc]

    async def _query_agent(self, user_message: str) -> str:
        """
        Agent SDK로 Claude에 QA 리포트 생성을 요청하고 결과를 반환한다.

        REPORT_SYSTEM_PROMPT를 system_prompt로 사용하며,
        _AGENT_ENV_LOCK으로 환경변수 접근을 직렬화한다.
        """
        async with _AGENT_ENV_LOCK:
            claudecode_env = os.environ.pop("CLAUDECODE", None)
            try:
                answer = ""
                async for message in query(
                    prompt=user_message,
                    options=ClaudeAgentOptions(
                        allowed_tools=[],
                        system_prompt=REPORT_SYSTEM_PROMPT,
                    ),
                ):
                    if hasattr(message, "result") and message.result:
                        answer = message.result
                return answer
            finally:
                if claudecode_env is not None:
                    os.environ["CLAUDECODE"] = claudecode_env
