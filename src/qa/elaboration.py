"""
이슈 구체화(Elaboration) 모듈.

Stage 1: 모호한 이슈 설명을 RAG 컨텍스트를 활용하여 구조화된 스펙으로 변환한다.

동작 흐름:
    1. 원시 이슈 설명을 입력받는다.
    2. IssueRetriever로 유사 과거 이슈를 검색한다.
    3. ELABORATION_QUERY_TEMPLATE으로 사용자 메시지를 구성한다.
    4. Claude Agent SDK를 호출하여 구체화 결과를 생성한다.
    5. 결과를 파싱하여 ElaborationResult 데이터클래스로 반환한다.
"""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from claude_agent_sdk import ClaudeAgentOptions, query

from src._agent_lock import AGENT_ENV_LOCK as _AGENT_ENV_LOCK
from src.logger import get_logger
from src.qa.prompts import ELABORATION_QUERY_TEMPLATE, ELABORATION_SYSTEM_PROMPT
from src.retrieval.retriever import IssueRetriever, RetrievalResults

logger = get_logger(__name__)


@dataclass
class ElaborationResult:
    """이슈 구체화 결과 객체."""

    raw_input: str
    elaborated_spec: str
    symptoms: str
    root_cause_hypothesis: str
    reproduction_steps: str
    expected_vs_actual: str
    severity_estimate: Literal["Critical", "High", "Medium", "Low"]
    affected_components: list[str] = field(default_factory=list)
    context_used: RetrievalResults = field(
        default_factory=lambda: RetrievalResults(query="", results=[])
    )
    model_name: str = "claude-agent-sdk"

    def to_prompt_text(self) -> str:
        """Stage 2/3 프롬프트에 삽입할 구조화된 텍스트로 변환한다."""
        components_str = ", ".join(self.affected_components) if self.affected_components else "없음"
        return (
            f"## 이슈 구체화 결과 (Stage 1)\n\n"
            f"**원시 이슈 설명:** {self.raw_input}\n\n"
            f"#### 증상\n{self.symptoms}\n\n"
            f"#### 근본 원인 가설\n{self.root_cause_hypothesis}\n\n"
            f"#### 재현 단계\n{self.reproduction_steps}\n\n"
            f"#### 예상 동작 vs 실제 동작\n{self.expected_vs_actual}\n\n"
            f"#### 심각도 추정\n{self.severity_estimate}\n\n"
            f"#### 영향 컴포넌트\n{components_str}\n"
        )


class IssueElaborator:
    """
    Claude Agent SDK를 사용하여 모호한 이슈를 구체화하는 클래스.

    IssueRetriever로 유사 과거 이슈를 검색한 뒤,
    ELABORATION_SYSTEM_PROMPT와 함께 Claude에게 구체화를 요청한다.
    """

    def __init__(
        self,
        retriever: IssueRetriever,
        max_retries: int = 3,
        retry_wait_min: float = 1.0,
        retry_wait_max: float = 10.0,
    ) -> None:
        """
        Args:
            retriever: 유사 이슈 검색에 사용할 IssueRetriever 인스턴스
            max_retries: 최대 재시도 횟수 (기본값: 3)
            retry_wait_min: 재시도 최소 대기 시간(초) (기본값: 1.0)
            retry_wait_max: 재시도 최대 대기 시간(초) (기본값: 10.0)
        """
        self._retriever = retriever
        self.max_retries = max_retries
        self.retry_wait_min = retry_wait_min
        self.retry_wait_max = retry_wait_max
        self.model_name = "claude-agent-sdk"

        logger.info(
            "IssueElaborator 초기화: Claude Agent SDK 사용 (API 키 불필요), "
            "max_retries=%d",
            max_retries,
        )

    async def elaborate(self, raw_issue: str, top_k: int | None = None) -> ElaborationResult:
        """
        원시 이슈 설명을 구조화된 스펙으로 구체화한다.

        Args:
            raw_issue: 모호하거나 불완전한 이슈 설명
            top_k: RAG 검색 결과 수 (None이면 retriever 기본값 사용)

        Returns:
            ElaborationResult 객체

        Raises:
            ValueError: raw_issue가 비어 있는 경우
            RuntimeError: 최대 재시도 횟수 초과 후에도 생성 실패 시
        """
        if not raw_issue or not raw_issue.strip():
            raise ValueError("원시 이슈 설명이 비어 있습니다.")

        raw_issue = raw_issue.strip()

        # 1. 유사 이슈 검색
        retrieval = self._retriever.search(raw_issue, top_k=top_k)
        logger.info(
            "RAG 검색 완료: query='%s' (결과 %d개)",
            raw_issue[:100],
            len(retrieval.results),
        )

        # 2. 사용자 메시지 구성
        user_message = ELABORATION_QUERY_TEMPLATE.format(
            context=retrieval.get_context_text(),
            raw_issue=raw_issue,
        )

        # 3. Claude Agent SDK 호출 (재시도 포함)
        try:
            raw_text = await self._generate_with_retry(user_message)
            logger.info("구체화 생성 완료: %d자", len(raw_text))
        except Exception as exc:
            logger.error("구체화 생성 최종 실패: %s", exc)
            raise RuntimeError(f"Agent SDK 이슈 구체화 중 오류: {exc}") from exc

        # 4. 결과 파싱 후 ElaborationResult를 한 곳에서 생성
        parsed = self._parse_elaboration(raw_text)
        return ElaborationResult(
            raw_input=raw_issue,
            elaborated_spec=raw_text,
            context_used=retrieval,
            model_name=self.model_name,
            **parsed,
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
                        "구체화 생성 재시도 %d/%d (%.1f초 대기): %s",
                        attempt,
                        self.max_retries,
                        wait_time,
                        exc,
                    )
                    await asyncio.sleep(wait_time)

        raise last_exc  # type: ignore[misc]

    async def _query_agent(self, user_message: str) -> str:
        """
        Agent SDK로 Claude에 이슈 구체화를 요청하고 결과를 반환한다.

        ELABORATION_SYSTEM_PROMPT를 system_prompt로 사용하며,
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
                        system_prompt=ELABORATION_SYSTEM_PROMPT,
                    ),
                ):
                    if hasattr(message, "result") and message.result:
                        answer = message.result
                return answer
            finally:
                if claudecode_env is not None:
                    os.environ["CLAUDECODE"] = claudecode_env

    def _parse_elaboration(self, raw_text: str) -> dict[str, Any]:
        """Parse Claude output, return dict of parsed fields."""

        def _extract_section(text: str, header_pattern: str) -> str:
            """정규식으로 섹션 내용을 추출한다."""
            pattern = rf"###\s+{header_pattern}[^\n]*\n(.*?)(?=###|\Z)"
            match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            if match:
                return match.group(1).strip()
            return ""

        # 증상 (Symptoms)
        symptoms = _extract_section(raw_text, r"증상")

        # 근본 원인 가설 (Root Cause Hypothesis)
        root_cause_hypothesis = _extract_section(raw_text, r"근본\s*원인\s*가설")

        # 재현 단계 (Reproduction Steps)
        reproduction_steps = _extract_section(raw_text, r"재현\s*단계")

        # 예상 동작 vs 실제 동작 (Expected vs Actual)
        expected_vs_actual = _extract_section(raw_text, r"예상\s*동작\s*vs\s*실제\s*동작")

        # 심각도 추정 (Severity Estimate)
        severity_raw = _extract_section(raw_text, r"심각도\s*추정")
        severity_estimate: Literal["Critical", "High", "Medium", "Low"] = "Medium"
        if severity_raw:
            for level in ("Critical", "High", "Medium", "Low"):
                if re.search(rf'\b{level}\b', severity_raw, re.IGNORECASE):
                    severity_estimate = level  # type: ignore[assignment]
                    break

        # 영향 컴포넌트 (Affected Components)
        components_raw = _extract_section(raw_text, r"영향\s*컴포넌트")
        affected_components: list[str] = []
        if components_raw:
            # 쉼표 또는 줄바꿈으로 분리
            parts = re.split(r"[,\n]+", components_raw)
            for part in parts:
                # 마크다운 불릿 기호와 공백 제거
                cleaned = re.sub(r"^[-*•\s]+", "", part).strip()
                if cleaned:
                    affected_components.append(cleaned)

        # 주요 섹션이 모두 비어 있으면 파싱 실패 경고
        critical_fields = [symptoms, root_cause_hypothesis, reproduction_steps]
        if all(not f for f in critical_fields):
            logger.warning(
                "이슈 구체화 파싱 실패: 주요 섹션이 모두 비어 있습니다. "
                "Claude 출력 형식이 예상과 다를 수 있습니다. raw_text 앞 200자: %s",
                raw_text[:200],
            )

        return {
            "symptoms": symptoms,
            "root_cause_hypothesis": root_cause_hypothesis,
            "reproduction_steps": reproduction_steps,
            "expected_vs_actual": expected_vs_actual,
            "severity_estimate": severity_estimate,
            "affected_components": affected_components,
        }
