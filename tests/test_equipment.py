"""EquipmentOrchestrator + router 단위 테스트."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch as _patch

import pytest
from fastapi.testclient import TestClient

from src.api.dependencies import get_equipment_repo, get_orchestrator
from src.api.main import app
from src.equipment.models import (
    Command,
    CommandStatus,
    Device,
    DeviceStatus,
    Sequence,
    SequenceStatus,
)


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def mock_repo():
    repo = MagicMock()
    repo.initialize = AsyncMock(return_value=None)
    repo.close = AsyncMock(return_value=None)
    repo.register_device = AsyncMock(side_effect=lambda d: d)
    repo.get_device = AsyncMock(return_value=None)
    repo.list_devices = AsyncMock(return_value=[])
    repo.create_sequence = AsyncMock(side_effect=lambda s: s)
    repo.get_sequence = AsyncMock(return_value=None)
    repo.list_sequences = AsyncMock(return_value=[])
    repo.update_sequence_status = AsyncMock(return_value=None)
    repo.create_command = AsyncMock(side_effect=lambda c: c)
    repo.get_command = AsyncMock(return_value=None)
    repo.update_command_status = AsyncMock(return_value=None)
    repo.log_event = AsyncMock(return_value=None)
    repo.upsert_device_state = AsyncMock(return_value=None)
    repo.get_device_state = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_orchestrator():
    orch = MagicMock()
    orch.start = AsyncMock(return_value=None)
    orch.stop = AsyncMock(return_value=None)
    orch.execute_sequence = AsyncMock(return_value=None)
    orch.handle_command_result = AsyncMock(return_value=None)
    orch.handle_heartbeat = AsyncMock(return_value=None)
    orch.emergency_stop = AsyncMock(return_value=None)
    return orch


@pytest.fixture
def mock_pipeline():
    pipeline = MagicMock()
    pipeline.get_index_stats = MagicMock(return_value={"total_chunks": 0})
    return pipeline


@pytest.fixture
def client(mock_repo, mock_orchestrator, mock_pipeline):
    app.dependency_overrides[get_equipment_repo] = lambda: mock_repo
    app.dependency_overrides[get_orchestrator] = lambda: mock_orchestrator

    mock_chat_repo = MagicMock()
    mock_chat_repo.initialize = AsyncMock(return_value=None)
    mock_chat_repo.close = AsyncMock(return_value=None)
    mock_chat_repo._pool = MagicMock()
    mock_missed_logger = MagicMock()

    with (
        _patch("src.api.main.IssuePipeline.from_settings", return_value=mock_pipeline),
        _patch("src.api.main.ChatRepository", return_value=mock_chat_repo),
        _patch("src.api.main.MissedQueryLogger.create", new=AsyncMock(return_value=mock_missed_logger)),
        _patch("src.api.main.EquipmentRepository", return_value=mock_repo),
        _patch("src.api.main.EquipmentOrchestrator", return_value=mock_orchestrator),
    ):
        with TestClient(app) as c:
            yield c

    app.dependency_overrides.clear()


# ── Tests ──────────────────────────────────────────────────────────────────

def test_register_device_and_list(client, mock_repo):
    device = Device(
        id="CHG-A-01",
        name="충전기 A",
        ip_address="192.168.1.10",
        port=8080,
        device_type="charger",
        status=DeviceStatus.OFFLINE,
        last_heartbeat=None,
    )
    mock_repo.register_device = AsyncMock(return_value=device)
    mock_repo.list_devices = AsyncMock(return_value=[device])

    resp = client.post("/api/v1/equipment/devices", json={
        "id": "CHG-A-01",
        "name": "충전기 A",
        "ip_address": "192.168.1.10",
        "port": 8080,
        "device_type": "charger",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "CHG-A-01"
    assert data["device_type"] == "charger"

    resp = client.get("/api/v1/equipment/devices")
    assert resp.status_code == 200
    items = resp.json()
    assert isinstance(items, list)
    assert items[0]["id"] == "CHG-A-01"


def test_create_sequence(client, mock_repo):
    now = datetime.now(timezone.utc)
    from src.equipment.models import CommandStep
    seq = Sequence(
        id="seq-001",
        name="테스트 시퀀스",
        steps=[CommandStep(device_id="CHG-A-01", command_type="charge", params={})],
        status=SequenceStatus.PENDING,
        created_by="tester",
        created_at=now,
    )
    mock_repo.create_sequence = AsyncMock(return_value=seq)

    resp = client.post("/api/v1/equipment/sequences", json={
        "name": "테스트 시퀀스",
        "steps": [{"device_id": "CHG-A-01", "command_type": "charge"}],
        "created_by": "tester",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "테스트 시퀀스"
    assert data["status"] == SequenceStatus.PENDING.value
    assert data["total_steps"] == 1


def test_execute_sequence_starts_task(client, mock_repo, mock_orchestrator):
    from src.equipment.models import CommandStep
    now = datetime.now(timezone.utc)
    seq = Sequence(
        id="seq-001",
        name="시퀀스",
        steps=[CommandStep(device_id="CHG-A-01", command_type="charge", params={})],
        status=SequenceStatus.PENDING,
        created_at=now,
    )
    mock_repo.get_sequence = AsyncMock(return_value=seq)

    resp = client.post("/api/v1/equipment/sequences/seq-001/execute")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "started"
    assert data["sequence_id"] == "seq-001"


def test_heartbeat_updates_state(client, mock_orchestrator):
    resp = client.post("/api/v1/equipment/devices/CHG-A-01/heartbeat", json={
        "device_id": "CHG-A-01",
        "status": "running",
        "temperature": 35.5,
        "voltage": 4.1,
        "current": 2.0,
    })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    mock_orchestrator.handle_heartbeat.assert_called_once()


def test_estop_calls_emergency_stop(client, mock_orchestrator):
    resp = client.post("/api/v1/equipment/estop", json={"reason": "수동 비상 정지"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["reason"] == "수동 비상 정지"
    mock_orchestrator.emergency_stop.assert_called_once_with("수동 비상 정지")


def test_command_result_callback(client, mock_orchestrator):
    resp = client.post("/api/v1/equipment/commands/cmd-001/result", json={
        "command_id": "cmd-001",
        "status": "done",
    })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    mock_orchestrator.handle_command_result.assert_called_once_with(
        "cmd-001", CommandStatus.DONE, None
    )
