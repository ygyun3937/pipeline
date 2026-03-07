"""
생성(Generation) 모듈 테스트 - IssueAnswerGenerator v2.

테스트 대상:
    - 빈 질문 ValueError 발생
    - 컨텍스트 있을 때 RAG 템플릿 사용 확인
    - 컨텍스트 없을 때 NO_CONTEXT 템플릿 사용 확인
    - generate_without_context() 동작 확인
    - GenerationResult 구조 검증
    - 재시도 설정 초기화 확인
    - Agent SDK 오류 시 RuntimeError로 래핑 확인
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.documents import Document

from src.generation.generator import (
    GenerationResult,
    IssueAnswerGenerator,
    NO_CONTEXT_QUERY_TEMPLATE,
    RAG_QUERY_TEMPLATE,
    SYSTEM_PROMPT,
)
from src.retrieval.retriever import RetrievalResults, SearchResult


def _make_mock_llm(model_name: str = "test-model") -> MagicMock:
    """LLMClient Mock을 생성한다."""
    mock = MagicMock()
    mock.complete = AsyncMock(return_value="mock response")
    mock.model_name = model_name
    return mock


def _make_search_result(content: str, score: float = 0.8) -> SearchResult:
    """테스트용 SearchResult를 생성한다."""
    doc = Document(
        page_content=content,
        metadata={"filename": "test_issue.md", "source": "/data/test_issue.md"},
    )
    return SearchResult(document=doc, score=score, rank=1)


def _make_retrieval_results(
    results: list[SearchResult] | None = None,
) -> RetrievalResults:
    """테스트용 RetrievalResults를 생성한다."""
    return RetrievalResults(query="테스트 쿼리", results=results or [])


class TestGenerationResult:
    """GenerationResult 데이터 클래스 테스트."""

    def test_has_context_true_when_results_exist(self) -> None:
        """검색 결과가 있을 때 has_context가 True인지 확인한다."""
        result = SearchResult(
            document=Document(page_content="내용", metadata={}),
            score=0.9,
            rank=1,
        )
        gen_result = GenerationResult(
            question="질문",
            answer="답변",
            context_used=RetrievalResults(query="q", results=[result]),
            model_name="test-model",
        )
        assert gen_result.has_context is True

    def test_has_context_false_when_no_results(self) -> None:
        """검색 결과가 없을 때 has_context가 False인지 확인한다."""
        gen_result = GenerationResult(
            question="질문",
            answer="답변",
            context_used=RetrievalResults(query="q", results=[]),
            model_name="test-model",
        )
        assert gen_result.has_context is False

    def test_to_dict_structure(self) -> None:
        """to_dict()가 올바른 키를 포함하는지 확인한다."""
        gen_result = GenerationResult(
            question="질문",
            answer="답변",
            context_used=RetrievalResults(query="q", results=[]),
            model_name="test-model",
            input_tokens=100,
            output_tokens=50,
        )
        d = gen_result.to_dict()
        assert "question" in d
        assert "answer" in d
        assert "model" in d
        assert "context" in d
        assert "usage" in d
        assert d["usage"]["input_tokens"] == 100
        assert d["usage"]["output_tokens"] == 50


class TestIssueAnswerGeneratorInit:
    """IssueAnswerGenerator 초기화 테스트."""

    def test_default_retry_settings(self) -> None:
        """기본 재시도 설정이 올바르게 초기화되는지 확인한다."""
        generator = IssueAnswerGenerator(llm_client=_make_mock_llm())
        assert generator.max_retries == 3
        assert generator.retry_wait_min == 1.0
        assert generator.retry_wait_max == 10.0

    def test_custom_retry_settings(self) -> None:
        """커스텀 재시도 설정이 올바르게 적용되는지 확인한다."""
        generator = IssueAnswerGenerator(
            llm_client=_make_mock_llm(),
            max_retries=5,
            retry_wait_min=2.0,
            retry_wait_max=20.0,
        )
        assert generator.max_retries == 5
        assert generator.retry_wait_min == 2.0
        assert generator.retry_wait_max == 20.0

    def test_model_name_from_llm_client(self) -> None:
        """model_name이 llm_client.model_name에서 설정되는지 확인한다."""
        generator = IssueAnswerGenerator(llm_client=_make_mock_llm(model_name="test-model"))
        assert generator.model_name == "test-model"


class TestIssueAnswerGeneratorValidation:
    """IssueAnswerGenerator 입력 검증 테스트."""

    @pytest.mark.asyncio
    async def test_empty_question_raises_value_error(self) -> None:
        """빈 질문 전달 시 ValueError가 발생하는지 확인한다."""
        generator = IssueAnswerGenerator(llm_client=_make_mock_llm())
        retrieval = _make_retrieval_results()

        with pytest.raises(ValueError, match="질문이 비어 있습니다"):
            await generator.generate(question="", retrieval_results=retrieval)

    @pytest.mark.asyncio
    async def test_whitespace_only_question_raises_value_error(self) -> None:
        """공백만 있는 질문 전달 시 ValueError가 발생하는지 확인한다."""
        generator = IssueAnswerGenerator(llm_client=_make_mock_llm())
        retrieval = _make_retrieval_results()

        with pytest.raises(ValueError, match="질문이 비어 있습니다"):
            await generator.generate(question="   ", retrieval_results=retrieval)


class TestIssueAnswerGeneratorGenerate:
    """IssueAnswerGenerator.generate() 동작 테스트."""

    @pytest.mark.asyncio
    async def test_generate_with_context_uses_rag_template(self) -> None:
        """
        검색 결과가 있을 때 RAG_QUERY_TEMPLATE이 사용되는지 확인한다.
        llm.complete에 전달된 user_message에 컨텍스트가 포함되어야 한다.
        """
        mock_llm = _make_mock_llm()
        mock_llm.complete = AsyncMock(return_value="### 1. 증상\n테스트 답변")
        generator = IssueAnswerGenerator(llm_client=mock_llm)
        result_item = _make_search_result("이슈 문서 내용입니다.")
        retrieval = _make_retrieval_results([result_item])

        result = await generator.generate(question="오류 원인은?", retrieval_results=retrieval)

        assert isinstance(result, GenerationResult)
        assert result.answer == "### 1. 증상\n테스트 답변"
        assert result.question == "오류 원인은?"
        assert result.has_context is True

    @pytest.mark.asyncio
    async def test_generate_without_context_uses_no_context_template(self) -> None:
        """
        검색 결과가 없을 때 NO_CONTEXT_QUERY_TEMPLATE이 사용되는지 확인한다.
        """
        mock_llm = _make_mock_llm()
        mock_llm.complete = AsyncMock(return_value="### 1. 증상\n컨텍스트 없는 답변")
        generator = IssueAnswerGenerator(llm_client=mock_llm)
        retrieval = _make_retrieval_results([])  # 빈 결과

        result = await generator.generate(question="오류 원인은?", retrieval_results=retrieval)

        assert result.has_context is False
        assert result.answer == "### 1. 증상\n컨텍스트 없는 답변"

    @pytest.mark.asyncio
    async def test_generate_returns_correct_model_name(self) -> None:
        """GenerationResult의 model_name이 올바른지 확인한다."""
        mock_llm = _make_mock_llm(model_name="test-model")
        mock_llm.complete = AsyncMock(return_value="답변")
        generator = IssueAnswerGenerator(llm_client=mock_llm)
        retrieval = _make_retrieval_results()

        result = await generator.generate(question="질문", retrieval_results=retrieval)

        assert result.model_name == "test-model"

    @pytest.mark.asyncio
    async def test_generate_agent_error_raises_runtime_error(self) -> None:
        """
        LLM 호출 실패 시 RuntimeError로 래핑되어 발생하는지 확인한다.
        """
        mock_llm = _make_mock_llm()
        mock_llm.complete = AsyncMock(side_effect=RuntimeError("연결 실패"))
        generator = IssueAnswerGenerator(llm_client=mock_llm, max_retries=1)  # 재시도 1회로 빠른 테스트
        retrieval = _make_retrieval_results()

        with pytest.raises(RuntimeError, match="Agent SDK 답변 생성 중 오류"):
            await generator.generate(question="질문", retrieval_results=retrieval)


class TestIssueAnswerGeneratorWithoutContext:
    """generate_without_context() 테스트."""

    @pytest.mark.asyncio
    async def test_generate_without_context_calls_generate(self) -> None:
        """generate_without_context가 빈 RetrievalResults로 generate를 호출하는지 확인한다."""
        mock_llm = _make_mock_llm()
        mock_llm.complete = AsyncMock(return_value="답변")
        generator = IssueAnswerGenerator(llm_client=mock_llm)

        result = await generator.generate_without_context("테스트 질문")

        assert isinstance(result, GenerationResult)
        assert result.has_context is False
        assert result.question == "테스트 질문"


class TestSystemPrompt:
    """시스템 프롬프트 내용 검증 테스트."""

    def test_system_prompt_contains_four_sections(self) -> None:
        """시스템 프롬프트에 4개 섹션 지시가 포함되어 있는지 확인한다."""
        assert "증상" in SYSTEM_PROMPT
        assert "원인" in SYSTEM_PROMPT
        assert "조치방법" in SYSTEM_PROMPT
        assert "주요 관련 이력" in SYSTEM_PROMPT

    def test_system_prompt_contains_korean_language_instruction(self) -> None:
        """시스템 프롬프트에 한국어 답변 지시가 포함되어 있는지 확인한다."""
        assert "한국어" in SYSTEM_PROMPT

    def test_rag_template_contains_context_and_question_placeholders(self) -> None:
        """RAG 템플릿에 {context}와 {question} 플레이스홀더가 있는지 확인한다."""
        assert "{context}" in RAG_QUERY_TEMPLATE
        assert "{question}" in RAG_QUERY_TEMPLATE

    def test_no_context_template_contains_question_placeholder(self) -> None:
        """{question} 플레이스홀더가 NO_CONTEXT 템플릿에 있는지 확인한다."""
        assert "{question}" in NO_CONTEXT_QUERY_TEMPLATE
