from __future__ import annotations

import asyncio
import os
import random
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

AGENT_DEVICE_ID: str = os.environ.get("AGENT_DEVICE_ID", "MOCK-01")
AGENT_DEVICE_NAME: str = os.environ.get("AGENT_DEVICE_NAME", "Mock 충방전기 A")
AGENT_PORT: int = int(os.environ.get("AGENT_PORT", "8081"))
AGENT_DEVICE_TYPE: str = os.environ.get("AGENT_DEVICE_TYPE", "charger")
CENTRAL_BACKEND_URL: str = os.environ.get("CENTRAL_BACKEND_URL", "http://localhost:8000")
SIMULATE_ERROR_RATE: float = float(os.environ.get("SIMULATE_ERROR_RATE", "0.0"))
# SIMULATE_ANOMALY=true 시 충전 중 온도가 50°C까지 상승하여 이상 감지 트리거
SIMULATE_ANOMALY: bool = os.environ.get("SIMULATE_ANOMALY", "false").lower() == "true"


@dataclass
class AgentState:
    status: str = "idle"
    current_command_id: str | None = None
    temperature: float = 25.0
    voltage: float = 0.0
    current: float = 0.0
    _sim_task: asyncio.Task | None = field(default=None, repr=False, compare=False)


_state = AgentState()


class ExecuteRequest(BaseModel):
    command_id: str
    command_type: str
    params: dict = {}


class EstopRequest(BaseModel):
    reason: str = ""


async def _simulate_command(command_id: str, command_type: str, params: dict) -> None:
    try:
        if random.random() < SIMULATE_ERROR_RATE:
            raise RuntimeError("Simulated random error")

        if command_type == "charge":
            steps = 10
            for i in range(steps + 1):
                if _state.status == "estop":
                    return
                while _state.status == "paused":
                    await asyncio.sleep(0.2)
                _state.voltage = round(i * (4.2 / steps), 3)
                _state.current = params.get("current", 1.0)
                # 이상 시뮬레이션: 충전 후반에 온도 50°C로 상승 (warning 임계값 45°C 초과)
                if SIMULATE_ANOMALY:
                    _state.temperature = round(25.0 + i * (25.0 / steps), 1)
                await asyncio.sleep(0.5)

        elif command_type == "discharge":
            steps = 10
            for i in range(steps + 1):
                if _state.status == "estop":
                    return
                while _state.status == "paused":
                    await asyncio.sleep(0.2)
                _state.voltage = round(4.2 - i * ((4.2 - 2.8) / steps), 3)
                _state.current = -abs(params.get("current", 1.0))
                await asyncio.sleep(0.5)

        elif command_type == "measure":
            await asyncio.sleep(2)
            _state.temperature = round(25.0 + random.uniform(-2, 5), 2)
            _state.voltage = round(random.uniform(2.8, 4.2), 3)
            _state.current = round(random.uniform(-2, 2), 3)

        elif command_type == "reset":
            await asyncio.sleep(1)
            _state.voltage = 0.0
            _state.current = 0.0
            _state.temperature = 25.0

        result_status = "done"
        error_message = None
    except asyncio.CancelledError:
        return
    except Exception as e:
        result_status = "error"
        error_message = str(e)

    if _state.status != "estop":
        _state.status = result_status
        _state.current_command_id = None

    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                f"{CENTRAL_BACKEND_URL}/api/v1/equipment/commands/{command_id}/result",
                json={
                    "command_id": command_id,
                    "status": result_status,
                    "error_message": error_message,
                },
                timeout=5.0,
            )
        except Exception:
            pass


async def _heartbeat_loop() -> None:
    async with httpx.AsyncClient() as client:
        while True:
            try:
                await client.post(
                    f"{CENTRAL_BACKEND_URL}/api/v1/equipment/devices/{AGENT_DEVICE_ID}/heartbeat",
                    json={
                        "device_id": AGENT_DEVICE_ID,
                        "status": _state.status,
                        "temperature": _state.temperature,
                        "voltage": _state.voltage,
                        "current": _state.current,
                    },
                    timeout=3.0,
                )
            except Exception:
                pass
            await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_heartbeat_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title=AGENT_DEVICE_NAME, lifespan=lifespan)


@app.post("/execute")
async def execute(req: ExecuteRequest):
    _state.status = "running"
    _state.current_command_id = req.command_id
    if _state._sim_task and not _state._sim_task.done():
        _state._sim_task.cancel()
    _state._sim_task = asyncio.create_task(
        _simulate_command(req.command_id, req.command_type, req.params)
    )
    return {"status": "started", "command_id": req.command_id}


@app.post("/pause")
async def pause():
    _state.status = "paused"
    return {"status": "paused"}


@app.post("/resume")
async def resume():
    _state.status = "running"
    return {"status": "running"}


@app.post("/estop")
async def estop(req: EstopRequest):
    _state.status = "estop"
    if _state._sim_task and not _state._sim_task.done():
        _state._sim_task.cancel()
    return {"status": "estop", "reason": req.reason}


@app.post("/reset")
async def reset():
    _state.status = "idle"
    _state.voltage = 0.0
    _state.current = 0.0
    _state.current_command_id = None
    return {"status": "idle"}


@app.get("/status")
async def status():
    return {
        "device_id": AGENT_DEVICE_ID,
        "status": _state.status,
        "temperature": _state.temperature,
        "voltage": _state.voltage,
        "current": _state.current,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.agent.main:app", host="0.0.0.0", port=int(os.environ.get("AGENT_PORT", "8081")))
