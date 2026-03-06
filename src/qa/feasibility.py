"""
테스트 가능성 평가(Feasibility Assessment) 모듈.

Stage 2: 구체화된 이슈 스펙과 YAML 검증 기준을 바탕으로 테스트 가능 여부를 판단한다.

동작 흐름:
    1. ElaborationResult(Stage 1 결과)와 ValidationCriteria를 입력받는다.
    2. FEASIBILITY_QUERY_TEMPLATE으로 사용자 메시지를 구성한다.
    3. Claude Agent SDK를 호출하여 평가 결과를 생성한다.
    4. 결과를 파싱하여 FeasibilityResult 데이터클래스로 반환한다.
"""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass, field
from typing import Any, Literal

import yaml
from claude_agent_sdk import ClaudeAgentOptions, query

from src._agent_lock import AGENT_ENV_LOCK as _AGENT_ENV_LOCK
from src.logger import get_logger
from src.qa.elaboration import ElaborationResult
from src.qa.prompts import FEASIBILITY_QUERY_TEMPLATE, FEASIBILITY_SYSTEM_PROMPT
from src.qa.validation_criteria import ValidationCriteria

logger = get_logger(__name__)


@dataclass
class FeasibilityResult:
    """테스트 가능성 평가 결과 객체."""

    verdict: Literal["testable", "not-testable", "partially-testable"]
    reasoning: str
    reproducibility_score: int      # 0-5
    measurability_score: int        # 0-5
    acceptance_clarity_score: int   # 0-5
    test_scope_fit: bool
    recommended_test_cases: list[str] = field(default_factory=list)
    criteria_applied: ValidationCriteria = field(default=None)  # type: ignore[assignment]
    model_name: str = "claude-agent-sdk"

    def to_prompt_text(self) -> str:
        """Stage 3 프롬프트에 삽입할 구조화된 텍스트로 변환한다.

        #### 헤더를 사용하여 Stage 3의 ### 헤더와 충돌을 방지한다.
        """
        test_cases_str = ""
        if self.recommended_test_cases:
            numbered = "\n".join(
                f"{i + 1}. {tc}" for i, tc in enumerate(self.recommended_test_cases)
            )
            test_cases_str = numbered
        else:
            test_cases_str = "없음"

        scope_fit_str = "적합" if self.test_scope_fit else "부적합"

        return (
            f"## 테스트 가능성 평가 결과 (Stage 2)\n\n"
            f"#### 판정\n{self.verdict}\n\n"
            f"#### 근거\n{self.reasoning}\n\n"
            f"#### 점수\n"
            f"- 재현 가능성: {self.reproducibility_score}/5\n"
            f"- 측정 가능성: {self.measurability_score}/5\n"
            f"- 합격 기준 명확성: {self.acceptance_clarity_score}/5\n\n"
            f"#### 테스트 범위 적합성\n{scope_fit_str}\n\n"
            f"#### 권장 테스트 케이스\n{test_cases_str}\n"
        )


class FeasibilityAssessor:
    """
    Claude Agent SDK를 사용하여 이슈의 테스트 가능성을 평가하는 클래스.

    ElaborationResult(Stage 1)와 ValidationCriteria를 입력받아
    FEASIBILITY_SYSTEM_PROMPT와 함께 Claude에게 평가를 요청한다.
    """

    def __init__(
        self,
        max_retries: int = 3,
        retry_wait_min: float = 1.0,
        retry_wait_max: float = 10.0,
    ) -> None:
        """
        Args:
            max_retries: 최대 재시도 횟수 (기본값: 3)
            retry_wait_min: 재시도 최소 대기 시간(초) (기본값: 1.0)
            retry_wait_max: 재시도 최대 대기 시간(초) (기본값: 10.0)
        """
        self.max_retries = max_retries
        self.retry_wait_min = retry_wait_min
        self.retry_wait_max = retry_wait_max
        self.model_name = "claude-agent-sdk"

        logger.info(
            "FeasibilityAssessor 초기화: Claude Agent SDK 사용 (API 키 불필요), "
            "max_retries=%d",
            max_retries,
        )

    async def assess(
        self,
        elaboration: ElaborationResult,
        criteria: ValidationCriteria,
    ) -> FeasibilityResult:
        """
        구체화된 이슈와 검증 기준을 바탕으로 테스트 가능성을 평가한다.

        Args:
            elaboration: Stage 1 이슈 구체화 결과
            criteria: YAML 검증 기준 객체

        Returns:
            FeasibilityResult 객체

        Raises:
            ValueError: elaboration이 비어 있는 경우
            RuntimeError: 최대 재시도 횟수 초과 후에도 생성 실패 시
        """
        # 1. Validate elaboration is not empty
        if not elaboration.elaborated_spec or not elaboration.elaborated_spec.strip():
            raise ValueError("구체화된 이슈 스펙이 비어 있습니다.")

        # 2. Build user_message from FEASIBILITY_QUERY_TEMPLATE
        elaborated_issue = elaboration.to_prompt_text()
        criteria_yaml = yaml.dump(
            criteria.raw_yaml,
            allow_unicode=True,
            default_flow_style=False,
        )
        user_message = FEASIBILITY_QUERY_TEMPLATE.format(
            elaborated_issue=elaborated_issue,
            criteria_yaml=criteria_yaml,
        )

        # 3. Call _generate_with_retry
        try:
            raw_text = await self._generate_with_retry(user_message)
            logger.info("테스트 가능성 평가 생성 완료: %d자", len(raw_text))
        except Exception as exc:
            logger.error("테스트 가능성 평가 최종 실패: %s", exc)
            raise RuntimeError(f"Agent SDK 테스트 가능성 평가 중 오류: {exc}") from exc

        # 4. Parse result into FeasibilityResult
        parsed = self._parse_feasibility(raw_text, criteria)

        # 5. Return FeasibilityResult
        return FeasibilityResult(
            verdict=parsed["verdict"],
            reasoning=parsed["reasoning"],
            reproducibility_score=parsed["reproducibility_score"],
            measurability_score=parsed["measurability_score"],
            acceptance_clarity_score=parsed["acceptance_clarity_score"],
            test_scope_fit=parsed["test_scope_fit"],
            recommended_test_cases=parsed["recommended_test_cases"],
            criteria_applied=criteria,
            model_name=self.model_name,
        )

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
                        "테스트 가능성 평가 재시도 %d/%d (%.1f초 대기): %s",
                        attempt,
                        self.max_retries,
                        wait_time,
                        exc,
                    )
                    await asyncio.sleep(wait_time)

        raise last_exc  # type: ignore[misc]

    async def _query_agent(self, user_message: str) -> str:
        """
        Agent SDK로 Claude에 테스트 가능성 평가를 요청하고 결과를 반환한다.

        FEASIBILITY_SYSTEM_PROMPT를 system_prompt로 사용하며,
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
                        system_prompt=FEASIBILITY_SYSTEM_PROMPT,
                    ),
                ):
                    if hasattr(message, "result") and message.result:
                        answer = message.result
                return answer
            finally:
                if claudecode_env is not None:
                    os.environ["CLAUDECODE"] = claudecode_env

    def _parse_feasibility(self, raw_text: str, criteria: ValidationCriteria) -> dict[str, Any]:
        """Claude 출력을 파싱하여 FeasibilityResult 필드 딕셔너리를 반환한다.

        Args:
            raw_text: Claude가 생성한 원시 텍스트
            criteria: 적용된 검증 기준 (참조용)

        Returns:
            FeasibilityResult 생성에 필요한 필드 딕셔너리
        """

        def _extract_section(text: str, header_pattern: str) -> str:
            """정규식으로 섹션 내용을 추출한다."""
            pattern = rf"###\s+{header_pattern}[^\n]*\n(.*?)(?=###|\Z)"
            match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            if match:
                return match.group(1).strip()
            return ""

        # --- 판정 (Verdict) ---
        verdict_raw = _extract_section(raw_text, r"판정")
        verdict: Literal["testable", "not-testable", "partially-testable"] = "partially-testable"
        if verdict_raw:
            verdict_lower = verdict_raw.lower().strip()
            # Check not-testable variants first (before "testable" to avoid partial match)
            if any(kw in verdict_lower for kw in ("not-testable", "not testable", "테스트 불가", "불가")):
                verdict = "not-testable"
            elif any(kw in verdict_lower for kw in ("partially-testable", "partially testable", "부분적으로 테스트 가능", "부분적", "부분")):
                verdict = "partially-testable"
            elif any(kw in verdict_lower for kw in ("testable", "테스트 가능", "가능")):
                verdict = "testable"

        # --- 근거 (Reasoning) ---
        reasoning = _extract_section(raw_text, r"근거")

        # --- 점수 (Scores) ---
        scores_raw = _extract_section(raw_text, r"점수")
        reproducibility_score = 3
        measurability_score = 3
        acceptance_clarity_score = 3

        if scores_raw:
            for line in scores_raw.splitlines():
                # Look for score numbers 0-5 in each line
                score_match = re.search(r"\b([0-5])\b", line)
                if score_match:
                    score_val = int(score_match.group(1))
                    if re.search(r"재현", line):
                        reproducibility_score = score_val
                    elif re.search(r"측정", line):
                        measurability_score = score_val
                    elif re.search(r"합격|명확", line):
                        acceptance_clarity_score = score_val

        # --- 테스트 범위 적합성 (Test Scope Fit) ---
        scope_raw = _extract_section(raw_text, r"테스트\s*범위\s*적합성")
        test_scope_fit = True
        if scope_raw:
            scope_lower = scope_raw.lower().strip()
            # Check first line or first meaningful content for the verdict
            first_line = scope_lower.split("\n")[0].strip() if scope_lower else ""
            if re.search(r"\bno\b|부적합|불가", first_line):
                test_scope_fit = False
            elif re.search(r"\byes\b|적합|가능", first_line):
                test_scope_fit = True

        # --- 권장 테스트 케이스 (Recommended Test Cases) ---
        test_cases_raw = _extract_section(raw_text, r"권장\s*테스트\s*케이스")
        recommended_test_cases: list[str] = []
        if test_cases_raw:
            for line in test_cases_raw.splitlines():
                match = re.match(r"^\d+\.\s+(.+)", line.strip())
                if match:
                    recommended_test_cases.append(match.group(1).strip())

        # Warn if critical sections are missing
        if not verdict_raw and not reasoning and not scores_raw:
            logger.warning(
                "테스트 가능성 평가 파싱 실패: 주요 섹션이 모두 비어 있습니다. "
                "Claude 출력 형식이 예상과 다를 수 있습니다. raw_text 앞 200자: %s",
                raw_text[:200],
            )

        return {
            "verdict": verdict,
            "reasoning": reasoning,
            "reproducibility_score": reproducibility_score,
            "measurability_score": measurability_score,
            "acceptance_clarity_score": acceptance_clarity_score,
            "test_scope_fit": test_scope_fit,
            "recommended_test_cases": recommended_test_cases,
        }
