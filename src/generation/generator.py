"""
생성(Generation) 모듈.

LLMClient를 사용하여 검색된 이슈 문서를 바탕으로
사용자 질문에 대한 답변을 생성한다.

개선 사항 (v2):
    - system_prompt를 prompt와 분리하여 역할 지시 강화
    - tenacity 재시도 로직 추가 (최대 3회, 지수 백오프)
    - 4개 섹션(증상/원인/조치방법/주요 관련 이력) 구조 강제 명시
    - 컨텍스트 없을 때 명확한 안내 메시지 포함
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from src.llm.base import LLMClient
from src.logger import get_logger
from src.retrieval.retriever import RetrievalResults

logger = get_logger(__name__)

# ---- 시스템 프롬프트 (역할 지시) ----
# system_prompt를 user_message와 분리하여
# 사용자 메시지(RAG 컨텍스트 + 질문)와 역할 지시를 명확히 분리한다.
SYSTEM_PROMPT = """당신은 사내 이슈 및 버그 관리 시스템의 전문 AI 어시스턴트입니다.

역할:
- 제공된 이슈 문서, 버그 리포트, 장애 보고서를 분석하여 정확한 답변을 제공합니다.
- 과거 유사 이슈와의 연관성을 찾아 인사이트를 제공합니다.
- 기술적 내용을 명확하고 구조적으로 설명합니다.

답변 원칙:
1. 반드시 제공된 이슈 문서 컨텍스트에 기반하여 답변하세요. 일반 지식, 학습 데이터, 추측으로 답변하지 마세요.
2. 컨텍스트에 없는 내용은 절대 추론하거나 보완하지 말고 "문서에서 확인 불가"로 표시하세요.
3. 반드시 아래 4개 섹션 형식을 정확히 지켜서 답변하세요.
4. 기술적 용어는 정확하게 사용하세요.
5. 답변은 한국어로 작성하세요.
6. 각 섹션은 반드시 포함되어야 하며, 내용이 없더라도 "문서에서 확인 불가"를 기재하세요.

## 필수 답변 형식

### 1. 증상
- 사용자/시스템이 경험한 현상을 구체적으로 기술
- 오류 메시지, 발생 조건, 영향받은 기능 포함

### 2. 원인
- 확인된 근본 원인을 기술
- 원인이 불명확하면 "문서에서 확인 불가" 표시

### 3. 조치방법
- 실제 적용된 해결 절차를 단계별로 기술
- 임시 조치와 영구 조치를 구분하여 기술
- 미확인 시 "문서에서 확인 불가" 표시

### 4. 주요 관련 이력
- 이슈 ID, 발생일시, 심각도, 영향 범위 등 핵심 메타정보
- 출처 문서명과 유사도 점수 명시
- 유사 재발 이력이 있으면 함께 기재"""

# ---- RAG 쿼리 템플릿 (사용자 메시지) ----
RAG_QUERY_TEMPLATE = """다음은 관련 이슈 문서들입니다 (유사도 점수 포함):

{context}

---

위 이슈 문서들을 참고하여 다음 질문에 답변해주세요.
반드시 [### 1. 증상 / ### 2. 원인 / ### 3. 조치방법 / ### 4. 주요 관련 이력] 4개 섹션 형식으로 작성하세요.

질문: {question}"""

# 컨텍스트 없을 때 사용하는 템플릿
# 시스템 원칙: 등록된 이슈 문서 기반으로만 답변 — LLM 자체 지식 사용 금지
NO_CONTEXT_QUERY_TEMPLATE = """등록된 이슈 문서에서 관련 내용을 찾을 수 없었습니다.
이 시스템은 반드시 등록된 이슈 문서 기반으로만 답변합니다. 일반 지식으로 답변하지 마세요.

아래 형식으로 안내 메시지를 반환하세요:

### 1. 증상
문서에서 확인 불가 — 관련 이슈가 등록되지 않았습니다.

### 2. 원인
문서에서 확인 불가

### 3. 조치방법
문서에서 확인 불가 — 유사 이슈가 있다면 이슈 등록 후 재조회하세요. (/submit)

### 4. 주요 관련 이력
검색된 문서 없음 — 질문: {question}"""


@dataclass
class GenerationResult:
    """LLM 답변 생성 결과 객체."""

    question: str
    answer: str
    context_used: RetrievalResults
    model_name: str
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def has_context(self) -> bool:
        return not self.context_used.is_empty

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer,
            "model": self.model_name,
            "context": self.context_used.to_dict(),
            "usage": {
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
            },
        }


class IssueAnswerGenerator:
    """
    LLMClient를 사용하여 이슈 문서 기반 답변을 생성하는 클래스.

    개선 사항 (v2):
        - system_prompt 분리: 역할 지시와 RAG 컨텍스트를 명확히 구분
        - tenacity 재시도: 일시적 오류(RuntimeError, ConnectionError 등) 대응
        - 4섹션 구조 강제: 증상/원인/조치방법/주요 관련 이력
    """

    def __init__(
        self,
        llm_client: LLMClient,
        max_retries: int = 3,
        retry_wait_min: float = 1.0,
        retry_wait_max: float = 10.0,
    ) -> None:
        """
        Args:
            llm_client: LLM 백엔드 클라이언트
            max_retries: 답변 생성 최대 재시도 횟수 (기본값: 3)
            retry_wait_min: 재시도 최소 대기 시간(초) (기본값: 1.0)
            retry_wait_max: 재시도 최대 대기 시간(초) (기본값: 10.0)
        """
        self._llm = llm_client
        self.model_name = llm_client.model_name
        self.max_retries = max_retries
        self.retry_wait_min = retry_wait_min
        self.retry_wait_max = retry_wait_max

        logger.info(
            "IssueAnswerGenerator 초기화: model=%s, max_retries=%d",
            self.model_name,
            max_retries,
        )

    async def generate(
        self,
        question: str,
        retrieval_results: RetrievalResults,
    ) -> GenerationResult:
        """
        검색 결과를 컨텍스트로 사용하여 질문에 대한 답변을 생성한다.

        Args:
            question: 사용자 질문
            retrieval_results: IssueRetriever.search()의 결과

        Returns:
            GenerationResult 객체

        Raises:
            ValueError: 질문이 비어 있는 경우
            RuntimeError: 최대 재시도 횟수 초과 후에도 답변 생성 실패 시
        """
        if not question or not question.strip():
            raise ValueError("질문이 비어 있습니다.")

        question = question.strip()

        # 컨텍스트 유무에 따라 다른 사용자 메시지 템플릿 사용
        if retrieval_results.is_empty:
            user_message = NO_CONTEXT_QUERY_TEMPLATE.format(question=question)
            logger.warning(
                "관련 문서 없음 - 컨텍스트 없이 답변 생성: question='%s'",
                question[:100],
            )
        else:
            context = retrieval_results.get_context_text()
            user_message = RAG_QUERY_TEMPLATE.format(
                context=context, question=question
            )
            logger.info(
                "답변 생성 시작: question='%s' (컨텍스트 %d개)",
                question[:100],
                len(retrieval_results.results),
            )

        try:
            answer = await self._generate_with_retry(user_message)
            logger.info("답변 생성 완료: %d자", len(answer))

            return GenerationResult(
                question=question,
                answer=answer,
                context_used=retrieval_results,
                model_name=self.model_name,
            )

        except Exception as exc:
            logger.error("답변 생성 최종 실패: %s", exc)
            raise RuntimeError(f"LLM 답변 생성 중 오류: {exc}") from exc

    async def _generate_with_retry(self, user_message: str) -> str:
        """
        수동 재시도 루프.
        일시적 연결 오류나 런타임 오류 발생 시 지수 백오프로 재시도한다.
        비동기 컨텍스트에서 안전하게 동작하도록 asyncio.sleep을 사용한다.
        """
        last_exc: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                return await self._llm.complete(SYSTEM_PROMPT, user_message)
            except (RuntimeError, ConnectionError, TimeoutError) as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    # 지수 백오프: min ~ max 범위 내에서 대기
                    wait_time = min(
                        self.retry_wait_min * (2 ** (attempt - 1)),
                        self.retry_wait_max,
                    )
                    logger.warning(
                        "답변 생성 재시도 %d/%d (%.1f초 대기): %s",
                        attempt,
                        self.max_retries,
                        wait_time,
                        exc,
                    )
                    await asyncio.sleep(wait_time)

        raise last_exc  # type: ignore[misc]

    async def generate_without_context(self, question: str) -> GenerationResult:
        """
        검색 컨텍스트 없이 질문에 답변한다.
        디버깅이나 컨텍스트 없는 상황 테스트에 사용한다.
        """
        empty_results = RetrievalResults(query=question, results=[])
        return await self.generate(question=question, retrieval_results=empty_results)

    async def generate_stream(
        self,
        question: str,
        retrieval_results: RetrievalResults,
    ) -> AsyncGenerator[str, None]:
        """
        응답 텍스트를 청크 단위로 스트리밍한다.

        각 청크는 str이며, 호출자가 SSE 등의 형식으로 래핑한다.
        AnthropicClient / OllamaClient는 진짜 토큰 스트리밍을,
        ClaudeClient는 완성 후 단일 청크로 yield한다.

        Yields:
            str: 텍스트 청크
        """
        if not question or not question.strip():
            raise ValueError("질문이 비어 있습니다.")

        question = question.strip()

        if retrieval_results.is_empty:
            user_message = NO_CONTEXT_QUERY_TEMPLATE.format(question=question)
        else:
            user_message = RAG_QUERY_TEMPLATE.format(
                context=retrieval_results.get_context_text(), question=question
            )

        logger.info("스트리밍 생성 시작: question='%s'", question[:100])

        async for chunk in self._llm.stream(SYSTEM_PROMPT, user_message):
            yield chunk

        logger.info("스트리밍 생성 완료")
