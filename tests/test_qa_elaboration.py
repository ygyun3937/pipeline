"""
IssueElaborator 단위 테스트.

_query_agent를 AsyncMock으로 패치하여 실제 LLM 호출 없이 테스트한다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.qa.elaboration import ElaborationResult, IssueElaborator
from src.retrieval.retriever import RetrievalResults


# ---------------------------------------------------------------------------
# 헬퍼 / 픽스처
# ---------------------------------------------------------------------------

def _make_retriever() -> MagicMock:
    """IssueRetriever를 MagicMock으로 대체한다."""
    mock = MagicMock()
    mock.search.return_value = RetrievalResults(query="test", results=[])
    return mock


FAKE_ELABORATION_RESPONSE = """\
### 증상
로그인 페이지에서 간헐적으로 500 Internal Server Error가 발생합니다.

### 근본 원인 가설
DB 커넥션 풀 고갈로 인한 timeout 추정입니다.

### 재현 단계
1. 로그인 페이지 접속
2. 동시 다수 요청 발생

### 예상 동작 vs 실제 동작
예상: 200 OK
실제: 500 Internal Server Error

### 심각도 추정
High - 다수 사용자에게 영향

### 영향 컴포넌트
auth-service, database-pool
"""

FAKE_EMPTY_RESPONSE = """\
이것은 섹션 헤더가 없는 텍스트입니다.
파싱할 수 있는 구조화된 내용이 없습니다.
"""


@pytest.fixture
def elaborator() -> IssueElaborator:
    retriever = _make_retriever()
    return IssueElaborator(retriever=retriever, max_retries=1)


# ---------------------------------------------------------------------------
# elaborate() 해피 패스
# ---------------------------------------------------------------------------

class TestElaborateHappyPath:
    """elaborate() 정상 동작 테스트."""

    @pytest.mark.asyncio
    async def test_returns_elaboration_result(self, elaborator: IssueElaborator) -> None:
        """elaborate()가 ElaborationResult를 반환하는지 확인."""
        with patch.object(
            elaborator, "_query_agent", new=AsyncMock(return_value=FAKE_ELABORATION_RESPONSE)
        ):
            result = await elaborator.elaborate("로그인 오류 발생")

        assert isinstance(result, ElaborationResult)

    @pytest.mark.asyncio
    async def test_raw_input_preserved(self, elaborator: IssueElaborator) -> None:
        """raw_input이 입력 이슈 텍스트로 설정되는지 확인."""
        with patch.object(
            elaborator, "_query_agent", new=AsyncMock(return_value=FAKE_ELABORATION_RESPONSE)
        ):
            result = await elaborator.elaborate("로그인 오류 발생")

        assert result.raw_input == "로그인 오류 발생"

    @pytest.mark.asyncio
    async def test_elaborated_spec_is_raw_text(self, elaborator: IssueElaborator) -> None:
        """elaborated_spec이 Claude 출력 전체인지 확인."""
        with patch.object(
            elaborator, "_query_agent", new=AsyncMock(return_value=FAKE_ELABORATION_RESPONSE)
        ):
            result = await elaborator.elaborate("로그인 오류 발생")

        assert result.elaborated_spec == FAKE_ELABORATION_RESPONSE

    @pytest.mark.asyncio
    async def test_context_used_set(self, elaborator: IssueElaborator) -> None:
        """context_used가 RetrievalResults로 설정되는지 확인."""
        with patch.object(
            elaborator, "_query_agent", new=AsyncMock(return_value=FAKE_ELABORATION_RESPONSE)
        ):
            result = await elaborator.elaborate("로그인 오류 발생")

        assert isinstance(result.context_used, RetrievalResults)

    @pytest.mark.asyncio
    async def test_raises_value_error_for_empty_input(
        self, elaborator: IssueElaborator
    ) -> None:
        """빈 입력에 ValueError가 발생하는지 확인."""
        with pytest.raises(ValueError, match="비어"):
            await elaborator.elaborate("")

    @pytest.mark.asyncio
    async def test_raises_value_error_for_whitespace_input(
        self, elaborator: IssueElaborator
    ) -> None:
        """공백만 있는 입력에 ValueError가 발생하는지 확인."""
        with pytest.raises(ValueError):
            await elaborator.elaborate("   ")

    @pytest.mark.asyncio
    async def test_runtime_error_on_agent_failure(
        self, elaborator: IssueElaborator
    ) -> None:
        """_query_agent가 RuntimeError를 raise하면 RuntimeError로 래핑되어 반환."""
        with patch.object(
            elaborator,
            "_query_agent",
            new=AsyncMock(side_effect=RuntimeError("network error")),
        ):
            with pytest.raises(RuntimeError):
                await elaborator.elaborate("test issue")


# ---------------------------------------------------------------------------
# _parse_elaboration()
# ---------------------------------------------------------------------------

class TestParseElaboration:
    """_parse_elaboration() 파싱 로직 테스트."""

    def test_symptoms_parsed(self, elaborator: IssueElaborator) -> None:
        parsed = elaborator._parse_elaboration(FAKE_ELABORATION_RESPONSE)
        assert "500 Internal Server Error" in parsed["symptoms"]

    def test_root_cause_parsed(self, elaborator: IssueElaborator) -> None:
        parsed = elaborator._parse_elaboration(FAKE_ELABORATION_RESPONSE)
        assert "DB 커넥션 풀" in parsed["root_cause_hypothesis"]

    def test_reproduction_steps_parsed(self, elaborator: IssueElaborator) -> None:
        parsed = elaborator._parse_elaboration(FAKE_ELABORATION_RESPONSE)
        assert "로그인 페이지 접속" in parsed["reproduction_steps"]

    def test_expected_vs_actual_parsed(self, elaborator: IssueElaborator) -> None:
        parsed = elaborator._parse_elaboration(FAKE_ELABORATION_RESPONSE)
        assert "200 OK" in parsed["expected_vs_actual"]

    def test_severity_estimate_parsed(self, elaborator: IssueElaborator) -> None:
        parsed = elaborator._parse_elaboration(FAKE_ELABORATION_RESPONSE)
        assert parsed["severity_estimate"] == "High"

    def test_affected_components_parsed(self, elaborator: IssueElaborator) -> None:
        parsed = elaborator._parse_elaboration(FAKE_ELABORATION_RESPONSE)
        assert "auth-service" in parsed["affected_components"]
        assert "database-pool" in parsed["affected_components"]

    def test_returns_dict_with_required_keys(self, elaborator: IssueElaborator) -> None:
        parsed = elaborator._parse_elaboration(FAKE_ELABORATION_RESPONSE)
        required_keys = {
            "symptoms",
            "root_cause_hypothesis",
            "reproduction_steps",
            "expected_vs_actual",
            "severity_estimate",
            "affected_components",
        }
        assert required_keys.issubset(parsed.keys())


# ---------------------------------------------------------------------------
# severity_estimate 정규화
# ---------------------------------------------------------------------------

class TestSeverityNormalization:
    """severity_estimate 정규화 테스트."""

    @pytest.mark.parametrize(
        "severity_text, expected",
        [
            ("Critical - 전체 서비스 불가", "Critical"),
            ("High - 다수 사용자 영향", "High"),
            ("Medium - 일부 기능 영향", "Medium"),
            ("Low - 최소 영향", "Low"),
            ("critical", "Critical"),
            ("HIGH", "High"),
        ],
    )
    def test_severity_levels(
        self,
        elaborator: IssueElaborator,
        severity_text: str,
        expected: str,
    ) -> None:
        text = f"### 증상\n증상 텍스트\n### 심각도 추정\n{severity_text}\n"
        parsed = elaborator._parse_elaboration(text)
        assert parsed["severity_estimate"] == expected

    def test_default_severity_is_medium_when_missing(
        self, elaborator: IssueElaborator
    ) -> None:
        """심각도 섹션이 없으면 기본값 'Medium'."""
        text = "### 증상\n증상만 있고 심각도 없음\n"
        parsed = elaborator._parse_elaboration(text)
        assert parsed["severity_estimate"] == "Medium"

    def test_severity_word_boundary(self, elaborator: IssueElaborator) -> None:
        """'Highly' 같이 단어 경계 없는 패턴은 'High'로 잘못 매칭되지 않아야 한다."""
        # 단어 경계 \b 패턴 적용 확인
        text = "### 심각도 추정\nHighly critical situation\n"
        parsed = elaborator._parse_elaboration(text)
        # "Critical"이 단어 경계 있으므로 Critical로 매칭
        assert parsed["severity_estimate"] == "Critical"


# ---------------------------------------------------------------------------
# 빈/누락 섹션 처리
# ---------------------------------------------------------------------------

class TestEmptyMissingSections:
    """빈/누락 섹션 처리 테스트."""

    def test_empty_sections_get_empty_string_defaults(
        self, elaborator: IssueElaborator
    ) -> None:
        """섹션이 모두 없으면 빈 문자열로 반환된다."""
        parsed = elaborator._parse_elaboration(FAKE_EMPTY_RESPONSE)

        assert parsed["symptoms"] == ""
        assert parsed["root_cause_hypothesis"] == ""
        assert parsed["reproduction_steps"] == ""

    def test_empty_components_gets_empty_list(
        self, elaborator: IssueElaborator
    ) -> None:
        """영향 컴포넌트 섹션이 없으면 빈 리스트."""
        parsed = elaborator._parse_elaboration(FAKE_EMPTY_RESPONSE)
        assert parsed["affected_components"] == []

    @pytest.mark.asyncio
    async def test_elaborate_with_empty_response_still_returns_result(
        self, elaborator: IssueElaborator
    ) -> None:
        """Claude가 구조화 없는 응답을 반환해도 ElaborationResult를 반환한다."""
        with patch.object(
            elaborator, "_query_agent", new=AsyncMock(return_value=FAKE_EMPTY_RESPONSE)
        ):
            result = await elaborator.elaborate("이슈 설명")

        assert isinstance(result, ElaborationResult)
        assert result.symptoms == ""
        assert result.severity_estimate == "Medium"
