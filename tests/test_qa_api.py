"""
QA API 엔드포인트 통합 테스트.

TestClient + dependency_overrides 패턴으로 실제 파이프라인 없이 테스트한다.
tests/test_api.py의 패턴을 따른다.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.api.dependencies import get_pipeline
from src.api.main import app
from src.qa.elaboration import ElaborationResult
from src.qa.feasibility import FeasibilityResult
from src.qa.report_generator import QAReportResult
from src.qa.validation_criteria import ValidationCriteria
from src.retrieval.retriever import RetrievalResults


# ---------------------------------------------------------------------------
# Mock 팩토리
# ---------------------------------------------------------------------------

def _make_qa_mock_pipeline() -> MagicMock:
    """QA 테스트용 Mock 파이프라인을 생성한다."""
    mock = MagicMock()

    # qa_elaborate (async)
    mock.qa_elaborate = AsyncMock(
        return_value=ElaborationResult(
            raw_input="test",
            elaborated_spec="spec",
            symptoms="s",
            root_cause_hypothesis="r",
            reproduction_steps="steps",
            expected_vs_actual="e vs a",
            severity_estimate="High",
            affected_components=["auth"],
            context_used=RetrievalResults(query="", results=[]),
            model_name="test",
        )
    )

    # qa_assess_feasibility (async)
    mock.qa_assess_feasibility = AsyncMock(
        return_value=FeasibilityResult(
            verdict="testable",
            reasoning="ok",
            reproducibility_score=4,
            measurability_score=4,
            acceptance_clarity_score=4,
            test_scope_fit=True,
            recommended_test_cases=["Test login"],
            criteria_applied=ValidationCriteria(
                reproducibility_required=True,
                measurability_required=True,
                acceptance_criteria_required=True,
                test_scope="integration",
                automation_required=False,
                manual_acceptable=True,
                custom_rules=[],
                raw_yaml={},
            ),
        )
    )

    # qa_generate_report (async)
    mock.qa_generate_report = AsyncMock(
        return_value=QAReportResult(
            report_markdown="# QA Report",
            report_path=Path("/tmp/report.md"),
            issue_id="QA-20240101",
            verdict="testable",
            pass_rate=0.9,
            generated_at="2024-01-01T00:00:00+00:00",
        )
    )

    # get_validation_criteria (sync)
    mock.get_validation_criteria.return_value = ValidationCriteria(
        reproducibility_required=True,
        measurability_required=True,
        acceptance_criteria_required=True,
        test_scope="integration",
        automation_required=False,
        manual_acceptable=True,
        custom_rules=[],
        raw_yaml={},
    )

    return mock


@pytest.fixture
def qa_mock_pipeline() -> MagicMock:
    """QA Mock 파이프라인 픽스처."""
    return _make_qa_mock_pipeline()


@pytest.fixture
def qa_client(qa_mock_pipeline: MagicMock) -> TestClient:
    """QA 테스트 클라이언트 픽스처."""
    app.dependency_overrides[get_pipeline] = lambda: qa_mock_pipeline

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /api/v1/qa/elaborate
# ---------------------------------------------------------------------------

class TestQAElaborateEndpoint:
    """Stage 1 이슈 구체화 엔드포인트 테스트."""

    def test_elaborate_returns_200(self, qa_client: TestClient) -> None:
        response = qa_client.post(
            "/api/v1/qa/elaborate",
            json={"raw_issue": "로그인 시 500 에러 간헐적 발생"},
        )
        assert response.status_code == 200

    def test_elaborate_response_has_elaborated_spec(self, qa_client: TestClient) -> None:
        response = qa_client.post(
            "/api/v1/qa/elaborate",
            json={"raw_issue": "로그인 시 500 에러 간헐적 발생"},
        )
        data = response.json()
        assert "elaborated_spec" in data

    def test_elaborate_response_has_required_fields(self, qa_client: TestClient) -> None:
        response = qa_client.post(
            "/api/v1/qa/elaborate",
            json={"raw_issue": "로그인 시 500 에러 간헐적 발생"},
        )
        data = response.json()
        required_fields = {
            "elaborated_spec",
            "symptoms",
            "root_cause_hypothesis",
            "reproduction_steps",
            "expected_vs_actual",
            "severity_estimate",
            "affected_components",
            "context_count",
            "model",
        }
        assert required_fields.issubset(data.keys())

    def test_elaborate_with_empty_raw_issue_returns_422(
        self, qa_client: TestClient
    ) -> None:
        """빈 raw_issue는 422 Unprocessable Entity를 반환해야 한다."""
        response = qa_client.post(
            "/api/v1/qa/elaborate",
            json={"raw_issue": ""},
        )
        assert response.status_code == 422

    def test_elaborate_calls_pipeline(
        self, qa_client: TestClient, qa_mock_pipeline: MagicMock
    ) -> None:
        """파이프라인의 qa_elaborate()가 호출되는지 확인."""
        qa_client.post(
            "/api/v1/qa/elaborate",
            json={"raw_issue": "테스트 이슈"},
        )
        qa_mock_pipeline.qa_elaborate.assert_called_once()

    def test_elaborate_missing_raw_issue_returns_422(self, qa_client: TestClient) -> None:
        """raw_issue 필드 자체가 없으면 422."""
        response = qa_client.post(
            "/api/v1/qa/elaborate",
            json={},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/v1/qa/assess-feasibility
# ---------------------------------------------------------------------------

class TestQAAssessFeasibilityEndpoint:
    """Stage 2 테스트 가능여부 판단 엔드포인트 테스트."""

    def test_assess_feasibility_returns_200(self, qa_client: TestClient) -> None:
        response = qa_client.post(
            "/api/v1/qa/assess-feasibility",
            json={"elaborated_spec": "로그인 오류에 대한 상세 스펙"},
        )
        assert response.status_code == 200

    def test_assess_feasibility_response_has_verdict(
        self, qa_client: TestClient
    ) -> None:
        response = qa_client.post(
            "/api/v1/qa/assess-feasibility",
            json={"elaborated_spec": "상세 스펙"},
        )
        data = response.json()
        assert "verdict" in data

    def test_assess_feasibility_response_has_required_fields(
        self, qa_client: TestClient
    ) -> None:
        response = qa_client.post(
            "/api/v1/qa/assess-feasibility",
            json={"elaborated_spec": "상세 스펙"},
        )
        data = response.json()
        required_fields = {
            "verdict",
            "reasoning",
            "reproducibility_score",
            "measurability_score",
            "acceptance_clarity_score",
            "test_scope_fit",
            "recommended_test_cases",
            "model",
        }
        assert required_fields.issubset(data.keys())

    def test_assess_feasibility_empty_spec_returns_422(
        self, qa_client: TestClient
    ) -> None:
        response = qa_client.post(
            "/api/v1/qa/assess-feasibility",
            json={"elaborated_spec": ""},
        )
        assert response.status_code == 422

    def test_assess_feasibility_verdict_value(self, qa_client: TestClient) -> None:
        """verdict가 testable/not-testable/partially-testable 중 하나인지 확인."""
        response = qa_client.post(
            "/api/v1/qa/assess-feasibility",
            json={"elaborated_spec": "상세 스펙"},
        )
        data = response.json()
        assert data["verdict"] in ("testable", "not-testable", "partially-testable")


# ---------------------------------------------------------------------------
# POST /api/v1/qa/generate-report (multipart form)
# ---------------------------------------------------------------------------

class TestQAGenerateReportEndpoint:
    """Stage 3 QA 리포트 생성 엔드포인트 테스트."""

    def _base_form_data(self) -> dict:
        return {
            "elaborated_spec": "상세 스펙 내용",
            "feasibility_verdict": "testable",
            "feasibility_reasoning": "테스트 가능합니다.",
        }

    def test_generate_report_returns_200(self, qa_client: TestClient) -> None:
        response = qa_client.post(
            "/api/v1/qa/generate-report",
            data=self._base_form_data(),
        )
        assert response.status_code == 200

    def test_generate_report_has_report_markdown(self, qa_client: TestClient) -> None:
        response = qa_client.post(
            "/api/v1/qa/generate-report",
            data=self._base_form_data(),
        )
        data = response.json()
        assert "report_markdown" in data

    def test_generate_report_has_required_fields(self, qa_client: TestClient) -> None:
        response = qa_client.post(
            "/api/v1/qa/generate-report",
            data=self._base_form_data(),
        )
        data = response.json()
        required_fields = {
            "report_markdown",
            "report_path",
            "issue_id",
            "verdict",
            "pass_rate",
            "generated_at",
            "model",
        }
        assert required_fields.issubset(data.keys())

    def test_generate_report_with_json_file(self, qa_client: TestClient) -> None:
        """JSON 테스트 결과 파일 업로드 시 정상 처리되는지 확인."""
        test_data = json.dumps([
            {"name": "t1", "status": "pass"},
            {"name": "t2", "status": "fail"},
        ]).encode()

        response = qa_client.post(
            "/api/v1/qa/generate-report",
            data=self._base_form_data(),
            files={"test_result_file": ("results.json", test_data, "application/json")},
        )
        assert response.status_code == 200

    def test_generate_report_calls_pipeline(
        self, qa_client: TestClient, qa_mock_pipeline: MagicMock
    ) -> None:
        qa_client.post(
            "/api/v1/qa/generate-report",
            data=self._base_form_data(),
        )
        qa_mock_pipeline.qa_generate_report.assert_called_once()

    def test_generate_report_missing_required_form_returns_422(
        self, qa_client: TestClient
    ) -> None:
        """필수 폼 필드가 없으면 422."""
        response = qa_client.post(
            "/api/v1/qa/generate-report",
            data={},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/v1/qa/run-pipeline (multipart form)
# ---------------------------------------------------------------------------

class TestQARunPipelineEndpoint:
    """Stage 1~3 일괄 실행 엔드포인트 테스트."""

    def test_run_pipeline_returns_200(self, qa_client: TestClient) -> None:
        response = qa_client.post(
            "/api/v1/qa/run-pipeline",
            data={"raw_issue": "로그인 오류 발생"},
        )
        assert response.status_code == 200

    def test_run_pipeline_has_elaboration(self, qa_client: TestClient) -> None:
        response = qa_client.post(
            "/api/v1/qa/run-pipeline",
            data={"raw_issue": "로그인 오류 발생"},
        )
        data = response.json()
        assert "elaboration" in data

    def test_run_pipeline_has_feasibility(self, qa_client: TestClient) -> None:
        response = qa_client.post(
            "/api/v1/qa/run-pipeline",
            data={"raw_issue": "로그인 오류 발생"},
        )
        data = response.json()
        assert "feasibility" in data

    def test_run_pipeline_has_report(self, qa_client: TestClient) -> None:
        response = qa_client.post(
            "/api/v1/qa/run-pipeline",
            data={"raw_issue": "로그인 오류 발생"},
        )
        data = response.json()
        assert "report" in data

    def test_run_pipeline_elaboration_has_elaborated_spec(
        self, qa_client: TestClient
    ) -> None:
        response = qa_client.post(
            "/api/v1/qa/run-pipeline",
            data={"raw_issue": "로그인 오류 발생"},
        )
        data = response.json()
        assert "elaborated_spec" in data["elaboration"]

    def test_run_pipeline_feasibility_has_verdict(
        self, qa_client: TestClient
    ) -> None:
        response = qa_client.post(
            "/api/v1/qa/run-pipeline",
            data={"raw_issue": "로그인 오류 발생"},
        )
        data = response.json()
        assert "verdict" in data["feasibility"]

    def test_run_pipeline_report_has_report_markdown(
        self, qa_client: TestClient
    ) -> None:
        response = qa_client.post(
            "/api/v1/qa/run-pipeline",
            data={"raw_issue": "로그인 오류 발생"},
        )
        data = response.json()
        assert "report_markdown" in data["report"]

    def test_run_pipeline_with_test_file(self, qa_client: TestClient) -> None:
        """테스트 결과 파일 첨부 시 정상 처리."""
        csv_data = b"name,status\nTest A,pass\nTest B,fail\n"
        response = qa_client.post(
            "/api/v1/qa/run-pipeline",
            data={"raw_issue": "로그인 오류 발생"},
            files={"test_result_file": ("results.csv", csv_data, "text/csv")},
        )
        assert response.status_code == 200

    def test_run_pipeline_all_stages_called(
        self, qa_client: TestClient, qa_mock_pipeline: MagicMock
    ) -> None:
        """3단계가 모두 호출되는지 확인."""
        qa_client.post(
            "/api/v1/qa/run-pipeline",
            data={"raw_issue": "로그인 오류 발생"},
        )
        qa_mock_pipeline.qa_elaborate.assert_called_once()
        qa_mock_pipeline.qa_assess_feasibility.assert_called_once()
        qa_mock_pipeline.qa_generate_report.assert_called_once()


# ---------------------------------------------------------------------------
# GET /api/v1/qa/validation-criteria
# ---------------------------------------------------------------------------

class TestQAValidationCriteriaEndpoint:
    """검증 기준 조회 엔드포인트 테스트."""

    def test_validation_criteria_returns_200(self, qa_client: TestClient) -> None:
        response = qa_client.get("/api/v1/qa/validation-criteria")
        assert response.status_code == 200

    def test_validation_criteria_has_test_scope(self, qa_client: TestClient) -> None:
        response = qa_client.get("/api/v1/qa/validation-criteria")
        data = response.json()
        assert "test_scope" in data

    def test_validation_criteria_has_required_fields(
        self, qa_client: TestClient
    ) -> None:
        response = qa_client.get("/api/v1/qa/validation-criteria")
        data = response.json()
        required_fields = {
            "reproducibility_required",
            "measurability_required",
            "acceptance_criteria_required",
            "test_scope",
            "automation_required",
            "manual_acceptable",
            "custom_rules",
            "raw_yaml",
        }
        assert required_fields.issubset(data.keys())

    def test_validation_criteria_test_scope_value(
        self, qa_client: TestClient
    ) -> None:
        response = qa_client.get("/api/v1/qa/validation-criteria")
        data = response.json()
        assert data["test_scope"] == "integration"

    def test_validation_criteria_boolean_fields(
        self, qa_client: TestClient
    ) -> None:
        """boolean 필드가 bool 타입인지 확인."""
        response = qa_client.get("/api/v1/qa/validation-criteria")
        data = response.json()
        assert isinstance(data["reproducibility_required"], bool)
        assert isinstance(data["measurability_required"], bool)
        assert isinstance(data["automation_required"], bool)
        assert isinstance(data["manual_acceptable"], bool)

    def test_validation_criteria_calls_pipeline(
        self, qa_client: TestClient, qa_mock_pipeline: MagicMock
    ) -> None:
        qa_client.get("/api/v1/qa/validation-criteria")
        qa_mock_pipeline.get_validation_criteria.assert_called_once()
