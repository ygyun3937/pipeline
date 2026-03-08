"""
alarm_adapter.py 단위 테스트.

테스트 항목:
    1. test_load_alarms_from_json_list       — JSON 배열 파싱
    2. test_load_alarms_from_json_dict       — {alarms:[...]} 구조 파싱
    3. test_load_alarms_from_csv            — CSV 파싱
    4. test_simulate_alarm_returns_valid_payload — 시뮬레이션 알람이 AlarmPayload 스펙 충족
    5. test_dry_run_skips_http              — dry-run 모드에서 HTTP 호출 없음
"""

from __future__ import annotations

import json
import textwrap
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# scripts 디렉토리를 경로에 추가하지 않고 sys.path 조작 없이 직접 임포트
# alarm_adapter는 sys.path.insert를 자체적으로 수행하므로 직접 임포트 가능
import sys
from pathlib import Path

# 프로젝트 루트를 경로에 추가 (alarm_adapter가 내부에서 하지만 테스트에서도 필요)
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.alarm_adapter import (
    ALARM_PAYLOAD_FIELDS,
    BATTERY_ALARM_POOL,
    load_alarms_from_csv,
    load_alarms_from_json,
    send_alarm,
    simulate_alarm,
)
from src.api.alarm_models import AlarmPayload


# ---------------------------------------------------------------------------
# 1. JSON 배열 파싱 테스트
# ---------------------------------------------------------------------------


def test_load_alarms_from_json_list():
    """JSON 배열 형식 파싱이 올바르게 동작해야 한다."""
    data = [
        {"alarm_code": "OVP-001", "alarm_message": "과전압 감지", "voltage": 4.35},
        {"alarm_code": "OCP-001", "alarm_message": "과전류 감지", "current": 12.5},
    ]
    content = json.dumps(data)
    alarms = load_alarms_from_json(content)

    assert len(alarms) == 2
    assert alarms[0]["alarm_code"] == "OVP-001"
    assert alarms[0]["alarm_message"] == "과전압 감지"
    assert alarms[0]["voltage"] == 4.35
    assert alarms[1]["alarm_code"] == "OCP-001"
    assert alarms[1]["current"] == 12.5


# ---------------------------------------------------------------------------
# 2. JSON 딕셔너리 파싱 테스트
# ---------------------------------------------------------------------------


def test_load_alarms_from_json_dict():
    """{alarms: [...]} 구조 파싱이 올바르게 동작해야 한다."""
    data = {
        "alarms": [
            {"alarm_code": "UVP-001", "alarm_message": "저전압 감지", "voltage": 2.45},
            {"alarm_code": "OTP-001", "alarm_message": "과온도 감지", "temperature": 62.3},
        ]
    }
    content = json.dumps(data)
    alarms = load_alarms_from_json(content)

    assert len(alarms) == 2
    assert alarms[0]["alarm_code"] == "UVP-001"
    assert alarms[0]["voltage"] == 2.45
    assert alarms[1]["alarm_code"] == "OTP-001"
    assert alarms[1]["temperature"] == 62.3


def test_load_alarms_from_json_dict_single_alarm():
    """alarm_code와 alarm_message를 가진 단일 딕셔너리도 파싱해야 한다."""
    data = {"alarm_code": "ISOL-001", "alarm_message": "절연 저항 저하"}
    content = json.dumps(data)
    alarms = load_alarms_from_json(content)

    assert len(alarms) == 1
    assert alarms[0]["alarm_code"] == "ISOL-001"


def test_load_alarms_from_json_invalid_raises():
    """지원하지 않는 JSON 구조는 ValueError를 발생시켜야 한다."""
    content = json.dumps({"unknown_key": "value"})
    with pytest.raises(ValueError):
        load_alarms_from_json(content)


# ---------------------------------------------------------------------------
# 3. CSV 파싱 테스트
# ---------------------------------------------------------------------------


def test_load_alarms_from_csv():
    """CSV 형식 파싱이 올바르게 동작해야 한다."""
    csv_content = textwrap.dedent("""\
        alarm_code,alarm_message,voltage,current,temperature,unit_id,test_stage,elapsed_seconds
        OVP-001,과전압 감지,4.35,,,, CC_CHARGE,300
        OCP-001,과전류 감지,,12.5,,,CC_CHARGE,
    """)
    alarms = load_alarms_from_csv(csv_content)

    assert len(alarms) == 2

    first = alarms[0]
    assert first["alarm_code"] == "OVP-001"
    assert first["alarm_message"] == "과전압 감지"
    assert first["voltage"] == pytest.approx(4.35)
    assert first["elapsed_seconds"] == 300
    # voltage가 있는 행에서 current는 비어있으므로 포함되지 않아야 함
    assert "current" not in first

    second = alarms[1]
    assert second["alarm_code"] == "OCP-001"
    assert second["current"] == pytest.approx(12.5)
    # elapsed_seconds가 비어있으므로 포함되지 않아야 함
    assert "elapsed_seconds" not in second


def test_load_alarms_from_csv_numeric_conversion():
    """CSV에서 숫자 필드가 올바른 타입으로 변환되어야 한다."""
    csv_content = textwrap.dedent("""\
        alarm_code,alarm_message,voltage,elapsed_seconds
        TEST-001,테스트,3.7,1800
    """)
    alarms = load_alarms_from_csv(csv_content)

    assert len(alarms) == 1
    alarm = alarms[0]
    assert isinstance(alarm["voltage"], float)
    assert isinstance(alarm["elapsed_seconds"], int)
    assert alarm["voltage"] == pytest.approx(3.7)
    assert alarm["elapsed_seconds"] == 1800


# ---------------------------------------------------------------------------
# 4. 시뮬레이션 알람 AlarmPayload 스펙 충족 테스트
# ---------------------------------------------------------------------------


def test_simulate_alarm_returns_valid_payload():
    """simulate_alarm()이 반환한 딕셔너리는 AlarmPayload 스펙을 충족해야 한다."""
    for _ in range(20):  # 여러 번 실행하여 랜덤성 커버
        alarm = simulate_alarm()

        # AlarmPayload로 유효성 검증 (예외가 발생하지 않아야 함)
        payload = AlarmPayload(**alarm)

        # 필수 필드 확인
        assert payload.alarm_code
        assert payload.alarm_message

        # 선택 필드는 None이거나 올바른 타입이어야 함
        assert payload.voltage is None or isinstance(payload.voltage, float)
        assert payload.current is None or isinstance(payload.current, float)
        assert payload.temperature is None or isinstance(payload.temperature, float)
        assert payload.unit_id is None or isinstance(payload.unit_id, str)
        assert payload.test_stage is None or isinstance(payload.test_stage, str)
        assert payload.elapsed_seconds is None or isinstance(payload.elapsed_seconds, int)


def test_simulate_alarm_comes_from_pool():
    """simulate_alarm()이 BATTERY_ALARM_POOL 항목을 기반으로 알람을 생성해야 한다."""
    pool_codes = {item["alarm_code"] for item in BATTERY_ALARM_POOL}

    for _ in range(50):
        alarm = simulate_alarm()
        assert alarm["alarm_code"] in pool_codes


def test_simulate_alarm_fields_are_alarm_payload_fields():
    """simulate_alarm()이 반환하는 딕셔너리의 키는 AlarmPayload 필드여야 한다."""
    for _ in range(20):
        alarm = simulate_alarm()
        for key in alarm:
            assert key in ALARM_PAYLOAD_FIELDS, f"알 수 없는 필드: {key}"


# ---------------------------------------------------------------------------
# 5. dry-run 모드에서 HTTP 호출 없음 테스트
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_skips_http():
    """dry_run=True 일 때 httpx 클라이언트의 post 메서드를 호출하지 않아야 한다."""
    mock_client = MagicMock()
    mock_client.post = AsyncMock()

    payload = {
        "alarm_code": "OVP-001",
        "alarm_message": "과전압 감지",
        "voltage": 4.35,
        "test_stage": "CC_CHARGE",
    }

    await send_alarm(
        client=mock_client,
        api_url="http://localhost:8000",
        payload=payload,
        dry_run=True,
    )

    # dry_run=True이므로 HTTP post가 호출되지 않아야 함
    mock_client.post.assert_not_called()


@pytest.mark.asyncio
async def test_non_dry_run_calls_http():
    """dry_run=False 일 때 httpx 클라이언트의 post 메서드를 호출해야 한다."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"severity": "High", "verdict": "testable"})

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    payload = {
        "alarm_code": "OVP-001",
        "alarm_message": "과전압 감지",
    }

    await send_alarm(
        client=mock_client,
        api_url="http://localhost:8000",
        payload=payload,
        dry_run=False,
    )

    mock_client.post.assert_called_once_with(
        "http://localhost:8000/api/v1/alarm/ingest",
        json=payload,
        timeout=60.0,
    )


@pytest.mark.asyncio
async def test_send_alarm_handles_connection_error(capsys):
    """연결 오류 발생 시 예외를 전파하지 않고 오류 메시지를 출력해야 한다."""
    import httpx

    mock_client = MagicMock()
    mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

    payload = {"alarm_code": "TEST-001", "alarm_message": "테스트"}

    # 예외가 발생하지 않아야 함
    await send_alarm(
        client=mock_client,
        api_url="http://localhost:8000",
        payload=payload,
        dry_run=False,
    )

    captured = capsys.readouterr()
    assert "Connection refused" in captured.out


@pytest.mark.asyncio
async def test_send_alarm_handles_timeout(capsys):
    """타임아웃 발생 시 예외를 전파하지 않고 오류 메시지를 출력해야 한다."""
    import httpx

    mock_client = MagicMock()
    mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

    payload = {"alarm_code": "TEST-001", "alarm_message": "테스트"}

    await send_alarm(
        client=mock_client,
        api_url="http://localhost:8000",
        payload=payload,
        dry_run=False,
    )

    captured = capsys.readouterr()
    assert "시간 초과" in captured.out
