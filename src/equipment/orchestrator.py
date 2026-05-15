from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import httpx

from src.equipment.models import (
    AnomalyLog,
    Command,
    CommandStatus,
    DeviceState,
    DeviceStatus,
    HeartbeatPayload,
    SequenceStatus,
)
from src.equipment.repository import EquipmentRepository
from src.logger import get_logger

if TYPE_CHECKING:
    from src.pipeline import IssuePipeline

logger = get_logger(__name__)

_THRESHOLDS: dict[str, dict[str, float]] = {
    "temperature": {"warning": 45.0, "critical": 55.0},
    "voltage":     {"warning": 4.25,  "critical": 4.35},
    "current":     {"warning": 3.0,   "critical": 4.0},
}
_ANOMALY_COOLDOWN_SECONDS = 600  # 10분


class EquipmentOrchestrator:
    MAX_RETRIES = 3

    def __init__(self, repo: EquipmentRepository, pipeline: IssuePipeline | None = None) -> None:
        self._repo = repo
        self._pipeline = pipeline
        self._http: httpx.AsyncClient | None = None
        self._anomaly_last_seen: dict[str, datetime] = {}  # "device_id:metric" → 마지막 알림 시각

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
        await self._check_thresholds(payload.device_id, state)

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

    # ── 이상 감지 ─────────────────────────────────────────────────────────────

    async def _check_thresholds(self, device_id: str, state: DeviceState) -> None:
        checks = [
            ("temperature", state.temperature),
            ("voltage", state.voltage),
            ("current", state.current),
        ]
        for metric, value in checks:
            if value is None:
                continue
            limits = _THRESHOLDS[metric]
            severity: str | None = None
            threshold: float | None = None
            if value >= limits["critical"]:
                severity, threshold = "critical", limits["critical"]
            elif value >= limits["warning"]:
                severity, threshold = "warning", limits["warning"]

            if severity is None:
                continue

            # 쿨다운: 같은 장비+메트릭은 10분에 1회만 알림
            key = f"{device_id}:{metric}"
            last = self._anomaly_last_seen.get(key)
            now = datetime.now(timezone.utc)
            if last and (now - last).total_seconds() < _ANOMALY_COOLDOWN_SECONDS:
                continue

            self._anomaly_last_seen[key] = now
            anomaly = AnomalyLog(
                id=str(uuid.uuid4()),
                device_id=device_id,
                metric=metric,
                value=value,
                threshold=threshold,  # type: ignore[arg-type]
                severity=severity,
            )
            await self._repo.log_anomaly(anomaly)
            logger.warning(
                "이상 감지 [%s] %s=%.3f (임계값 %.3f, %s)",
                device_id, metric, value, threshold, severity,
            )
            if self._pipeline is not None:
                asyncio.create_task(self._run_rag_analysis(anomaly))

    async def _run_rag_analysis(self, anomaly: AnomalyLog) -> None:
        """비동기로 RAG 분석을 실행하고 결과를 anomaly_logs에 저장한다."""
        units = {"temperature": "°C", "voltage": "V", "current": "A"}
        unit = units.get(anomaly.metric, "")
        question = (
            f"장비 {anomaly.device_id}에서 {anomaly.metric} 이상이 감지되었습니다. "
            f"측정값: {anomaly.value}{unit} (임계값 {anomaly.threshold}{unit}, 심각도: {anomaly.severity}). "
            f"예상 원인과 즉각적인 조치 방법을 알려주세요."
        )
        try:
            result = await self._pipeline.query(question=question, top_k=3)  # type: ignore[union-attr]
            await self._repo.update_anomaly_rag(anomaly.id, result.answer)
            logger.info("RAG 분석 완료: anomaly_id=%s", anomaly.id)
        except Exception as exc:
            logger.error("RAG 분석 실패: anomaly_id=%s, error=%s", anomaly.id, exc)
