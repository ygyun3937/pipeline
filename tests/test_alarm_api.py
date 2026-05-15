import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch as _patch

from src.api.main import app
from src.api.dependencies import get_pipeline


@pytest.fixture
def mock_pipeline():
    pipeline = MagicMock()
    pipeline.qa_elaborate = AsyncMock(return_value=MagicMock(
        severity_estimate="High",
        elaborated_spec="OVP-001 과전압 보호 동작 분석",
        symptoms="전압 4.35V 초과",
        root_cause_hypothesis="충전 전류 과다",
        reproduction_steps="CC 충전 2단계 진행",
        expected_vs_actual="예상: 4.2V / 실제: 4.35V",
        affected_components=["BMS", "충전 회로"],
        model_name="test-model",
    ))
    pipeline.qa_assess_feasibility = AsyncMock(return_value=MagicMock(
        verdict="testable",
        reasoning="재현 가능한 조건 존재",
        reproducibility_score=4,
        measurability_score=5,
        acceptance_clarity_score=4,
        test_scope_fit=True,
        recommended_test_cases=["OVP 임계값 경계 테스트"],
        model_name="test-model",
    ))
    pipeline.qa_generate_report = AsyncMock(return_value=MagicMock(
        report_path="/data/qa_reports/QA_REPORT_test.md",
        report_markdown="# QA 리포트",
        issue_id="ALARM-OVP001",
        model_name="test-model",
    ))
    pipeline.get_validation_criteria = MagicMock(return_value=MagicMock(
        reproducibility_required=True,
        measurability_required=True,
        acceptance_criteria_required=True,
        test_scope="integration",
        automation_required=False,
        manual_acceptable=True,
        custom_rules=[],
        raw_yaml={},
    ))
    return pipeline


@pytest.fixture
def client(mock_pipeline):
    app.dependency_overrides[get_pipeline] = lambda: mock_pipeline

    mock_repo = MagicMock()
    mock_repo.initialize = AsyncMock(return_value=None)
    mock_repo.close = AsyncMock(return_value=None)
    mock_repo._pool = MagicMock()
    mock_missed_logger = MagicMock()

    with (
        _patch("src.api.main.IssuePipeline.from_settings", return_value=mock_pipeline),
        _patch("src.api.main.ChatRepository", return_value=mock_repo),
        _patch("src.api.main.MissedQueryLogger.create", new=AsyncMock(return_value=mock_missed_logger)),
    ):
        with TestClient(app) as c:
            yield c
    app.dependency_overrides.clear()


def test_alarm_ingest_minimal(client):
    resp = client.post("/api/v1/alarm/ingest", json={
        "alarm_code": "OVP-001",
        "alarm_message": "과전압 보호 동작",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["alarm_code"] == "OVP-001"
    assert data["severity"] == "High"
    assert data["verdict"] == "testable"
    assert "report_path" in data
    assert "report_summary" in data


def test_alarm_ingest_with_all_measurements(client):
    resp = client.post("/api/v1/alarm/ingest", json={
        "alarm_code": "OTP-002",
        "alarm_message": "과온도 보호 동작",
        "voltage": 3.9,
        "current": 3.0,
        "temperature": 62.5,
        "unit_id": "CH-01",
        "test_stage": "CC_DISCHARGE",
        "elapsed_seconds": 3600,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["alarm_code"] == "OTP-002"


def test_alarm_ingest_missing_alarm_code_returns_422(client):
    resp = client.post("/api/v1/alarm/ingest", json={
        "alarm_message": "알람코드 없음",
    })
    assert resp.status_code == 422


def test_alarm_ingest_missing_alarm_message_returns_422(client):
    resp = client.post("/api/v1/alarm/ingest", json={
        "alarm_code": "E001",
    })
    assert resp.status_code == 422


def test_alarm_ingest_calls_all_three_stages(client, mock_pipeline):
    client.post("/api/v1/alarm/ingest", json={
        "alarm_code": "OCP-003",
        "alarm_message": "과전류 보호",
    })
    mock_pipeline.qa_elaborate.assert_called_once()
    mock_pipeline.qa_assess_feasibility.assert_called_once()
    mock_pipeline.qa_generate_report.assert_called_once()


def test_alarm_ingest_recommended_test_cases(client):
    resp = client.post("/api/v1/alarm/ingest", json={
        "alarm_code": "OVP-001",
        "alarm_message": "과전압",
    })
    data = resp.json()
    assert isinstance(data["recommended_test_cases"], list)
    assert "OVP 임계값 경계 테스트" in data["recommended_test_cases"]
