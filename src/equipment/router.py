from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from src.api.dependencies import get_equipment_repo, get_orchestrator
from src.equipment.models import (
    AnomalyResponse,
    Command,
    CommandResultPayload,
    Device,
    DeviceRegisterRequest,
    DeviceResponse,
    EstopRequest,
    HeartbeatPayload,
    Sequence,
    SequenceCreateRequest,
    SequenceResponse,
    SequenceStatus,
    CommandStep,
)
from src.equipment.orchestrator import EquipmentOrchestrator
from src.equipment.repository import EquipmentRepository

router = APIRouter(prefix="/api/v1/equipment", tags=["Equipment"])


def _device_to_response(device: Device) -> DeviceResponse:
    return DeviceResponse(
        id=device.id,
        name=device.name,
        ip_address=device.ip_address,
        port=device.port,
        device_type=device.device_type,
        status=device.status,
        last_heartbeat=device.last_heartbeat,
    )


def _sequence_to_response(seq: Sequence) -> SequenceResponse:
    return SequenceResponse(
        id=seq.id,
        name=seq.name,
        status=seq.status,
        created_by=seq.created_by,
        created_at=seq.created_at,
        current_step_index=seq.current_step_index,
        total_steps=len(seq.steps),
    )


@router.post("/devices", response_model=DeviceResponse)
async def register_device(
    body: DeviceRegisterRequest,
    repo: EquipmentRepository = Depends(get_equipment_repo),
) -> DeviceResponse:
    device = Device(
        id=body.id,
        name=body.name,
        ip_address=body.ip_address,
        port=body.port,
        device_type=body.device_type,
    )
    device = await repo.register_device(device)
    return _device_to_response(device)


@router.get("/devices", response_model=list[DeviceResponse])
async def list_devices(
    repo: EquipmentRepository = Depends(get_equipment_repo),
) -> list[DeviceResponse]:
    devices = await repo.list_devices()
    return [_device_to_response(d) for d in devices]


@router.get("/devices/{device_id}", response_model=DeviceResponse)
async def get_device(
    device_id: str,
    repo: EquipmentRepository = Depends(get_equipment_repo),
) -> DeviceResponse:
    device = await repo.get_device(device_id)
    if device is None:
        raise HTTPException(status_code=404, detail=f"Device {device_id} not found")
    return _device_to_response(device)


@router.post("/devices/{device_id}/heartbeat")
async def device_heartbeat(
    device_id: str,
    body: HeartbeatPayload,
    orchestrator: EquipmentOrchestrator = Depends(get_orchestrator),
) -> dict:
    body.device_id = device_id
    await orchestrator.handle_heartbeat(body)
    return {"ok": True}


@router.post("/sequences", response_model=SequenceResponse)
async def create_sequence(
    body: SequenceCreateRequest,
    repo: EquipmentRepository = Depends(get_equipment_repo),
) -> SequenceResponse:
    steps = [
        CommandStep(
            device_id=s.device_id,
            command_type=s.command_type,
            params=s.params,
            timeout_seconds=s.timeout_seconds,
        )
        for s in body.steps
    ]
    seq = Sequence(
        id=str(uuid.uuid4()),
        name=body.name,
        steps=steps,
        created_by=body.created_by,
    )
    seq = await repo.create_sequence(seq)
    return _sequence_to_response(seq)


@router.post("/sequences/{sequence_id}/execute")
async def execute_sequence(
    sequence_id: str,
    repo: EquipmentRepository = Depends(get_equipment_repo),
) -> dict:
    seq = await repo.get_sequence(sequence_id)
    if seq is None:
        raise HTTPException(status_code=404, detail=f"Sequence {sequence_id} not found")
    await repo.update_sequence_status(sequence_id, SequenceStatus.PENDING_APPROVAL, current_step_index=0)
    return {"sequence_id": sequence_id, "status": "pending_approval"}


@router.post("/sequences/{sequence_id}/approve")
async def approve_sequence(
    sequence_id: str,
    repo: EquipmentRepository = Depends(get_equipment_repo),
    orchestrator: EquipmentOrchestrator = Depends(get_orchestrator),
) -> dict:
    seq = await repo.get_sequence(sequence_id)
    if seq is None:
        raise HTTPException(status_code=404, detail=f"Sequence {sequence_id} not found")
    if seq.status != SequenceStatus.PENDING_APPROVAL:
        raise HTTPException(status_code=400, detail=f"Sequence is not pending approval (status: {seq.status})")
    await repo.update_sequence_status(sequence_id, SequenceStatus.PENDING, current_step_index=0)
    asyncio.create_task(orchestrator.execute_sequence(sequence_id))
    return {"sequence_id": sequence_id, "status": "approved"}


@router.post("/sequences/{sequence_id}/reject")
async def reject_sequence(
    sequence_id: str,
    repo: EquipmentRepository = Depends(get_equipment_repo),
) -> dict:
    seq = await repo.get_sequence(sequence_id)
    if seq is None:
        raise HTTPException(status_code=404, detail=f"Sequence {sequence_id} not found")
    if seq.status != SequenceStatus.PENDING_APPROVAL:
        raise HTTPException(status_code=400, detail=f"Sequence is not pending approval (status: {seq.status})")
    await repo.update_sequence_status(sequence_id, SequenceStatus.CANCELLED)
    return {"sequence_id": sequence_id, "status": "rejected"}


@router.get("/sequences/{sequence_id}", response_model=SequenceResponse)
async def get_sequence(
    sequence_id: str,
    repo: EquipmentRepository = Depends(get_equipment_repo),
) -> SequenceResponse:
    seq = await repo.get_sequence(sequence_id)
    if seq is None:
        raise HTTPException(status_code=404, detail=f"Sequence {sequence_id} not found")
    return _sequence_to_response(seq)


@router.get("/sequences", response_model=list[SequenceResponse])
async def list_sequences(
    repo: EquipmentRepository = Depends(get_equipment_repo),
) -> list[SequenceResponse]:
    seqs = await repo.list_sequences()
    return [_sequence_to_response(s) for s in seqs]


@router.post("/commands/{command_id}/result")
async def command_result(
    command_id: str,
    body: CommandResultPayload,
    orchestrator: EquipmentOrchestrator = Depends(get_orchestrator),
) -> dict:
    await orchestrator.handle_command_result(
        command_id, body.status, body.error_message
    )
    return {"ok": True}


@router.post("/estop")
async def emergency_stop(
    body: EstopRequest,
    orchestrator: EquipmentOrchestrator = Depends(get_orchestrator),
) -> dict:
    await orchestrator.emergency_stop(body.reason)
    return {"ok": True, "reason": body.reason}


@router.get("/anomalies", response_model=list[AnomalyResponse])
async def list_anomalies(
    device_id: str | None = None,
    limit: int = 50,
    repo: EquipmentRepository = Depends(get_equipment_repo),
) -> list[AnomalyResponse]:
    anomalies = await repo.list_anomalies(device_id=device_id, limit=limit)
    return [
        AnomalyResponse(
            id=a.id,
            device_id=a.device_id,
            metric=a.metric,
            value=a.value,
            threshold=a.threshold,
            severity=a.severity,
            detected_at=a.detected_at,
            rag_analysis=a.rag_analysis,
        )
        for a in anomalies
    ]


@router.get("/devices/{device_id}/state")
async def get_device_state(
    device_id: str,
    repo: EquipmentRepository = Depends(get_equipment_repo),
) -> dict:
    state = await repo.get_device_state(device_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"State for device {device_id} not found")
    return {
        "device_id": state.device_id,
        "status": state.status,
        "temperature": state.temperature,
        "voltage": state.voltage,
        "current": state.current,
        "extra": state.extra,
        "measured_at": state.measured_at,
    }
