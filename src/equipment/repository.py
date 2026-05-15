from __future__ import annotations

import json
from datetime import datetime, timezone

import asyncpg

from src.equipment.models import (
    Command,
    CommandLog,
    CommandStatus,
    CommandStep,
    Device,
    DeviceState,
    DeviceStatus,
    Sequence,
    SequenceStatus,
)
from src.logger import get_logger

logger = get_logger(__name__)

_CREATE_DEVICES = """
CREATE TABLE IF NOT EXISTS devices (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    ip_address      TEXT NOT NULL,
    port            INT  NOT NULL,
    device_type     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'offline',
    last_heartbeat  TIMESTAMPTZ
)
"""

_CREATE_SEQUENCES = """
CREATE TABLE IF NOT EXISTS sequences (
    id                  TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    steps               JSONB NOT NULL DEFAULT '[]',
    status              TEXT NOT NULL DEFAULT 'pending',
    created_by          TEXT NOT NULL DEFAULT 'system',
    created_at          TIMESTAMPTZ NOT NULL,
    current_step_index  INT NOT NULL DEFAULT 0
)
"""

_CREATE_COMMANDS = """
CREATE TABLE IF NOT EXISTS commands (
    id              TEXT PRIMARY KEY,
    sequence_id     TEXT REFERENCES sequences(id),
    device_id       TEXT REFERENCES devices(id),
    command_type    TEXT NOT NULL,
    params          JSONB NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'pending',
    retry_count     INT NOT NULL DEFAULT 0,
    issued_at       TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    error_message   TEXT
)
"""

_CREATE_COMMAND_LOGS = """
CREATE TABLE IF NOT EXISTS command_logs (
    id          TEXT PRIMARY KEY,
    command_id  TEXT NOT NULL REFERENCES commands(id) ON DELETE CASCADE,
    event       TEXT NOT NULL,
    payload     JSONB NOT NULL DEFAULT '{}',
    occurred_at TIMESTAMPTZ NOT NULL
)
"""

_CREATE_DEVICE_STATES = """
CREATE TABLE IF NOT EXISTS device_states (
    device_id       TEXT PRIMARY KEY REFERENCES devices(id),
    status          TEXT NOT NULL,
    temperature     FLOAT,
    voltage         FLOAT,
    current_amps    FLOAT,
    extra           JSONB NOT NULL DEFAULT '{}',
    measured_at     TIMESTAMPTZ NOT NULL
)
"""


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_json(raw: object) -> object:
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


def _steps_to_json(steps: list[CommandStep]) -> str:
    return json.dumps([
        {
            "device_id": s.device_id,
            "command_type": s.command_type,
            "params": s.params,
            "timeout_seconds": s.timeout_seconds,
        }
        for s in steps
    ])


def _row_to_device(r: asyncpg.Record) -> Device:
    return Device(
        id=r["id"],
        name=r["name"],
        ip_address=r["ip_address"],
        port=r["port"],
        device_type=r["device_type"],
        status=DeviceStatus(r["status"]),
        last_heartbeat=r["last_heartbeat"],
    )


def _row_to_sequence(r: asyncpg.Record) -> Sequence:
    raw_steps = _parse_json(r["steps"])
    steps = [
        CommandStep(
            device_id=s["device_id"],
            command_type=s["command_type"],
            params=s.get("params", {}),
            timeout_seconds=s.get("timeout_seconds", 300),
        )
        for s in (raw_steps or [])
    ]
    return Sequence(
        id=r["id"],
        name=r["name"],
        steps=steps,
        status=SequenceStatus(r["status"]),
        created_by=r["created_by"],
        created_at=r["created_at"],
        current_step_index=r["current_step_index"],
    )


def _row_to_command(r: asyncpg.Record) -> Command:
    raw_params = _parse_json(r["params"])
    return Command(
        id=r["id"],
        sequence_id=r["sequence_id"],
        device_id=r["device_id"],
        command_type=r["command_type"],
        params=raw_params if isinstance(raw_params, dict) else {},
        status=CommandStatus(r["status"]),
        retry_count=r["retry_count"],
        issued_at=r["issued_at"],
        completed_at=r["completed_at"],
        error_message=r["error_message"],
    )


def _row_to_device_state(r: asyncpg.Record) -> DeviceState:
    raw_extra = _parse_json(r["extra"])
    return DeviceState(
        device_id=r["device_id"],
        status=DeviceStatus(r["status"]),
        temperature=r["temperature"],
        voltage=r["voltage"],
        current=r["current_amps"],
        extra=raw_extra if isinstance(raw_extra, dict) else {},
        measured_at=r["measured_at"],
    )


class EquipmentRepository:
    def __init__(self, postgres_url: str) -> None:
        self._url = postgres_url
        self._pool: asyncpg.Pool | None = None

    async def initialize(self) -> None:
        self._pool = await asyncpg.create_pool(self._url)
        async with self._pool.acquire() as conn:
            await conn.execute(_CREATE_DEVICES)
            await conn.execute(_CREATE_SEQUENCES)
            await conn.execute(_CREATE_COMMANDS)
            await conn.execute(_CREATE_COMMAND_LOGS)
            await conn.execute(_CREATE_DEVICE_STATES)
        logger.info("EquipmentRepository 초기화 완료: %s", self._url)

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    def _pool_or_raise(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("EquipmentRepository가 초기화되지 않았습니다. initialize()를 먼저 호출하세요.")
        return self._pool

    # ── Device ────────────────────────────────────────────────────────────────

    async def register_device(self, device: Device) -> Device:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO devices(id, name, ip_address, port, device_type, status, last_heartbeat) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7) "
                "ON CONFLICT (id) DO UPDATE SET name=$2, ip_address=$3, port=$4, device_type=$5",
                device.id, device.name, device.ip_address, device.port,
                device.device_type, device.status.value, device.last_heartbeat,
            )
        return device

    async def get_device(self, device_id: str) -> Device | None:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM devices WHERE id=$1", device_id)
        return _row_to_device(row) if row else None

    async def list_devices(self) -> list[Device]:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM devices ORDER BY name")
        return [_row_to_device(r) for r in rows]

    async def update_device_status(
        self,
        device_id: str,
        status: DeviceStatus,
        last_heartbeat: datetime | None = None,
    ) -> None:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE devices SET status=$1, last_heartbeat=COALESCE($2, last_heartbeat) WHERE id=$3",
                status.value, last_heartbeat, device_id,
            )

    # ── Sequence ──────────────────────────────────────────────────────────────

    async def create_sequence(self, sequence: Sequence) -> Sequence:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO sequences(id, name, steps, status, created_by, created_at, current_step_index) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7)",
                sequence.id, sequence.name, _steps_to_json(sequence.steps),
                sequence.status.value, sequence.created_by,
                sequence.created_at, sequence.current_step_index,
            )
        return sequence

    async def get_sequence(self, sequence_id: str) -> Sequence | None:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM sequences WHERE id=$1", sequence_id)
        return _row_to_sequence(row) if row else None

    async def list_sequences(self, limit: int = 50) -> list[Sequence]:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM sequences ORDER BY created_at DESC LIMIT $1", limit
            )
        return [_row_to_sequence(r) for r in rows]

    async def update_sequence_status(
        self,
        sequence_id: str,
        status: SequenceStatus,
        current_step_index: int | None = None,
    ) -> None:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE sequences SET status=$1, "
                "current_step_index=COALESCE($2, current_step_index) WHERE id=$3",
                status.value, current_step_index, sequence_id,
            )

    # ── Command ───────────────────────────────────────────────────────────────

    async def create_command(self, command: Command) -> Command:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO commands(id, sequence_id, device_id, command_type, params, "
                "status, retry_count, issued_at, completed_at, error_message) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
                command.id, command.sequence_id, command.device_id,
                command.command_type, json.dumps(command.params),
                command.status.value, command.retry_count,
                command.issued_at, command.completed_at, command.error_message,
            )
        return command

    async def get_command(self, command_id: str) -> Command | None:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM commands WHERE id=$1", command_id)
        return _row_to_command(row) if row else None

    async def get_commands_by_sequence(self, sequence_id: str) -> list[Command]:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM commands WHERE sequence_id=$1 ORDER BY issued_at", sequence_id
            )
        return [_row_to_command(r) for r in rows]

    async def update_command_status(
        self,
        command_id: str,
        status: CommandStatus,
        error_message: str | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE commands SET status=$1, error_message=COALESCE($2, error_message), "
                "completed_at=COALESCE($3, completed_at) WHERE id=$4",
                status.value, error_message, completed_at, command_id,
            )

    # ── CommandLog ────────────────────────────────────────────────────────────

    async def log_event(self, log: CommandLog) -> None:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO command_logs(id, command_id, event, payload, occurred_at) "
                "VALUES ($1,$2,$3,$4,$5)",
                log.id, log.command_id, log.event,
                json.dumps(log.payload), log.occurred_at,
            )

    # ── DeviceState ───────────────────────────────────────────────────────────

    async def upsert_device_state(self, state: DeviceState) -> None:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO device_states(device_id, status, temperature, voltage, "
                "current_amps, extra, measured_at) VALUES ($1,$2,$3,$4,$5,$6,$7) "
                "ON CONFLICT (device_id) DO UPDATE SET status=$2, temperature=$3, "
                "voltage=$4, current_amps=$5, extra=$6, measured_at=$7",
                state.device_id, state.status.value, state.temperature,
                state.voltage, state.current, json.dumps(state.extra), state.measured_at,
            )

    async def get_device_state(self, device_id: str) -> DeviceState | None:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM device_states WHERE device_id=$1", device_id
            )
        return _row_to_device_state(row) if row else None
