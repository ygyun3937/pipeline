"""장비 제어 모듈 — 데이터 모델 및 Pydantic 스키마."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ── Enums ──────────────────────────────────────────────────────────────────

class DeviceStatus(str, Enum):
    IDLE = "idle"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    ERROR = "error"
    ESTOP = "estop"
    OFFLINE = "offline"


class CommandStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


class SequenceStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


# ── Domain dataclasses ─────────────────────────────────────────────────────

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Device:
    id: str
    name: str
    ip_address: str
    port: int
    device_type: str
    status: DeviceStatus = DeviceStatus.OFFLINE
    last_heartbeat: datetime | None = None


@dataclass
class DeviceState:
    device_id: str
    status: DeviceStatus
    temperature: float | None = None
    voltage: float | None = None
    current: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    measured_at: datetime = field(default_factory=_utcnow)


@dataclass
class CommandStep:
    """시퀀스 내 단일 명령 스펙."""
    device_id: str
    command_type: str
    params: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: int = 300


@dataclass
class Command:
    id: str
    sequence_id: str
    device_id: str
    command_type: str
    params: dict[str, Any]
    status: CommandStatus = CommandStatus.PENDING
    retry_count: int = 0
    issued_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None


@dataclass
class Sequence:
    id: str
    name: str
    steps: list[CommandStep]
    status: SequenceStatus = SequenceStatus.PENDING
    created_by: str = "system"
    created_at: datetime = field(default_factory=_utcnow)
    current_step_index: int = 0


@dataclass
class CommandLog:
    id: str
    command_id: str
    event: str
    payload: dict[str, Any]
    occurred_at: datetime = field(default_factory=_utcnow)


# ── API Request / Response Pydantic models ─────────────────────────────────

class DeviceRegisterRequest(BaseModel):
    id: str = Field(..., description="장비 고유 ID (예: CHG-A-01)")
    name: str = Field(..., description="장비 이름")
    ip_address: str = Field(..., description="장비 PC IP 주소")
    port: int = Field(default=8080, description="장비 에이전트 포트")
    device_type: str = Field(..., description="장비 유형 (예: charger, chamber)")


class DeviceResponse(BaseModel):
    id: str
    name: str
    ip_address: str
    port: int
    device_type: str
    status: DeviceStatus
    last_heartbeat: datetime | None


class CommandStepRequest(BaseModel):
    device_id: str
    command_type: str
    params: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = 300


class SequenceCreateRequest(BaseModel):
    name: str
    steps: list[CommandStepRequest]
    created_by: str = "system"


class SequenceResponse(BaseModel):
    id: str
    name: str
    status: SequenceStatus
    created_by: str
    created_at: datetime
    current_step_index: int
    total_steps: int


class CommandResponse(BaseModel):
    id: str
    sequence_id: str
    device_id: str
    command_type: str
    params: dict[str, Any]
    status: CommandStatus
    retry_count: int
    issued_at: datetime | None
    completed_at: datetime | None
    error_message: str | None


class EstopRequest(BaseModel):
    reason: str = "수동 비상 정지"


class HeartbeatPayload(BaseModel):
    """장비 에이전트 → 중앙 백엔드 하트비트."""
    device_id: str
    status: DeviceStatus
    temperature: float | None = None
    voltage: float | None = None
    current: float | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class CommandResultPayload(BaseModel):
    """장비 에이전트 → 중앙 백엔드 명령 결과."""
    command_id: str
    status: CommandStatus
    error_message: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
