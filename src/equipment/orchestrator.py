from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import httpx

from src.equipment.models import (
    Command,
    CommandStatus,
    DeviceState,
    DeviceStatus,
    HeartbeatPayload,
    SequenceStatus,
)
from src.equipment.repository import EquipmentRepository
from src.logger import get_logger

logger = get_logger(__name__)


class EquipmentOrchestrator:
    MAX_RETRIES = 3

    def __init__(self, repo: EquipmentRepository) -> None:
        self._repo = repo
        self._http: httpx.AsyncClient | None = None

    async def start(self) -> None:
        self._http = httpx.AsyncClient(timeout=30.0)

    async def stop(self) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None

    async def execute_sequence(self, sequence_id: str) -> None:
        seq = await self._repo.get_sequence(sequence_id)
        if seq is None:
            raise ValueError(f"Sequence {sequence_id} not found")

        await self._repo.update_sequence_status(sequence_id, SequenceStatus.RUNNING)

        for i, step in enumerate(seq.steps):
            await self._repo.update_sequence_status(
                sequence_id, SequenceStatus.RUNNING, current_step_index=i
            )
            command = Command(
                id=str(uuid.uuid4()),
                sequence_id=sequence_id,
                device_id=step.device_id,
                command_type=step.command_type,
                params=step.params,
            )
            command = await self._repo.create_command(command)

            success = await self._execute_command_with_retry(command, step.timeout_seconds)
            if not success:
                await self._repo.update_sequence_status(sequence_id, SequenceStatus.ERROR)
                await self.emergency_stop(f"Step {i} failed: {command.error_message}")
                return

        await self._repo.update_sequence_status(sequence_id, SequenceStatus.DONE)

    async def _execute_command_with_retry(self, command: Command, timeout: int) -> bool:
        device = await self._repo.get_device(command.device_id)
        if device is None:
            await self._repo.update_command_status(
                command.id, CommandStatus.ERROR, "Device not found"
            )
            return False

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                url = f"http://{device.ip_address}:{device.port}/execute"
                await self._repo.update_command_status(command.id, CommandStatus.RUNNING)
                client = self._http or httpx.AsyncClient()
                resp = await client.post(
                    url,
                    json={
                        "command_id": command.id,
                        "command_type": command.command_type,
                        "params": command.params,
                    },
                    timeout=30,
                )
                resp.raise_for_status()

                # 에이전트는 비동기 실행 → 완료 콜백까지 폴링 대기
                completed = await self._wait_for_completion(command.id, timeout)
                if completed:
                    return True

                # 타임아웃: 재시도
                if attempt == self.MAX_RETRIES:
                    await self._repo.update_command_status(
                        command.id, CommandStatus.ERROR, "Timeout",
                        completed_at=datetime.now(timezone.utc),
                    )
                    return False

            except Exception as exc:
                if attempt == self.MAX_RETRIES:
                    await self._repo.update_command_status(
                        command.id, CommandStatus.ERROR, str(exc),
                        completed_at=datetime.now(timezone.utc),
                    )
                    return False
                await asyncio.sleep(2 ** attempt)

        return False

    async def _wait_for_completion(self, command_id: str, timeout: int) -> bool:
        """명령 완료(done/error) 콜백이 DB에 반영될 때까지 폴링."""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            cmd = await self._repo.get_command(command_id)
            if cmd and cmd.status == CommandStatus.DONE:
                return True
            if cmd and cmd.status == CommandStatus.ERROR:
                return False
            await asyncio.sleep(1)
        return False

    async def handle_command_result(
        self,
        command_id: str,
        status: CommandStatus,
        error_message: str | None = None,
    ) -> None:
        await self._repo.update_command_status(
            command_id, status, error_message, completed_at=datetime.now(timezone.utc)
        )

    async def handle_heartbeat(self, payload: HeartbeatPayload) -> None:
        await self._repo.update_device_status(
            payload.device_id, payload.status, last_heartbeat=datetime.now(timezone.utc)
        )
        state = DeviceState(
            device_id=payload.device_id,
            status=payload.status,
            temperature=payload.temperature,
            voltage=payload.voltage,
            current=payload.current,
            extra=payload.extra,
        )
        await self._repo.upsert_device_state(state)

    async def emergency_stop(self, reason: str = "E-STOP") -> None:
        devices = await self._repo.list_devices()
        async with httpx.AsyncClient(timeout=5.0) as client:
            for device in devices:
                if device.status not in (DeviceStatus.OFFLINE, DeviceStatus.ESTOP):
                    try:
                        await client.post(
                            f"http://{device.ip_address}:{device.port}/estop",
                            json={"reason": reason},
                        )
                    except Exception:
                        pass
                    await self._repo.update_device_status(device.id, DeviceStatus.ESTOP)
