# 배터리 검사 장비 QA 파이프라인 구현 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 배터리 충방전 검사 장비에서 알람 발생 시 RAG + LLM으로 자동 QA 리포트를 생성하며, Claude API(인터넷)와 Ollama(폐쇄망) 두 가지 LLM 백엔드를 설정 한 줄로 전환 가능하도록 구축한다.

**Architecture:** `src/llm/` 패키지에 LLMClient Protocol을 두고 ClaudeClient / OllamaClient가 구현한다. 기존 generator/elaboration/feasibility/report_generator는 LLMClient를 생성자 주입으로 받아 교체한다. 알람 발생 시 `alarm_adapter.py`(폴링 스크립트)가 표준 페이로드를 POST하면 `/api/v1/alarm/ingest` 엔드포인트가 Stage 1~3을 순서대로 실행해 리포트를 저장한다.

**Tech Stack:** FastAPI, Pydantic V2, ChromaDB, FastEmbed, openai SDK(Ollama 호환), claude_agent_sdk(기존), pyserial(선택적), httpx

---

## Task 1: LLM 추상 레이어 (`src/llm/`)

**Files:**
- Create: `src/llm/__init__.py`
- Create: `src/llm/base.py`
- Create: `src/llm/claude_client.py`
- Create: `src/llm/ollama_client.py`
- Create: `tests/test_llm_clients.py`

### Step 1: 테스트 작성

```python
# tests/test_llm_clients.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.llm.claude_client import ClaudeClient
from src.llm.ollama_client import OllamaClient


class TestClaudeClient:
    def test_model_name(self):
        client = ClaudeClient()
        assert client.model_name == "claude-agent-sdk"

    @pytest.mark.asyncio
    async def test_complete_returns_string(self):
        client = ClaudeClient()
        mock_msg = MagicMock()
        mock_msg.result = "테스트 응답"

        async def fake_query(*args, **kwargs):
            yield mock_msg

        with patch("src.llm.claude_client.query", side_effect=fake_query):
            result = await client.complete("시스템 프롬프트", "사용자 메시지")
        assert result == "테스트 응답"


class TestOllamaClient:
    def test_model_name(self):
        client = OllamaClient(base_url="http://localhost:11434", model="qwen2.5:7b")
        assert client.model_name == "qwen2.5:7b"

    @pytest.mark.asyncio
    async def test_complete_returns_string(self):
        client = OllamaClient(base_url="http://localhost:11434", model="qwen2.5:7b")

        mock_choice = MagicMock()
        mock_choice.message.content = "Ollama 응답"
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]

        client._openai.chat.completions.create = AsyncMock(return_value=mock_resp)

        result = await client.complete("시스템", "메시지")
        assert result == "Ollama 응답"
```

### Step 2: 테스트 실패 확인

```bash
uv run pytest tests/test_llm_clients.py -v
```
Expected: FAIL (모듈 없음)

### Step 3: 구현

```python
# src/llm/__init__.py
from src.llm.base import LLMClient
from src.llm.claude_client import ClaudeClient
from src.llm.ollama_client import OllamaClient

__all__ = ["LLMClient", "ClaudeClient", "OllamaClient"]
```

```python
# src/llm/base.py
from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMClient(Protocol):
    """LLM 백엔드 공통 인터페이스."""

    @property
    def model_name(self) -> str: ...

    async def complete(self, system_prompt: str, user_message: str) -> str:
        """시스템 프롬프트와 사용자 메시지를 받아 LLM 응답 텍스트를 반환한다."""
        ...
```

```python
# src/llm/claude_client.py
from __future__ import annotations

import os

from claude_agent_sdk import ClaudeAgentOptions, query

from src._agent_lock import AGENT_ENV_LOCK as _AGENT_ENV_LOCK
from src.logger import get_logger

logger = get_logger(__name__)


class ClaudeClient:
    """claude_agent_sdk를 사용하는 LLM 클라이언트 (인터넷 연결 환경)."""

    @property
    def model_name(self) -> str:
        return "claude-agent-sdk"

    async def complete(self, system_prompt: str, user_message: str) -> str:
        async with _AGENT_ENV_LOCK:
            claudecode_env = os.environ.pop("CLAUDECODE", None)
            try:
                answer = ""
                async for message in query(
                    prompt=user_message,
                    options=ClaudeAgentOptions(
                        allowed_tools=[],
                        system_prompt=system_prompt,
                    ),
                ):
                    if hasattr(message, "result") and message.result:
                        answer = message.result
                return answer
            finally:
                if claudecode_env is not None:
                    os.environ["CLAUDECODE"] = claudecode_env
```

```python
# src/llm/ollama_client.py
from __future__ import annotations

from openai import AsyncOpenAI

from src.logger import get_logger

logger = get_logger(__name__)


class OllamaClient:
    """Ollama OpenAI 호환 API를 사용하는 LLM 클라이언트 (폐쇄망 환경)."""

    def __init__(self, base_url: str, model: str) -> None:
        self._model = model
        self._openai = AsyncOpenAI(
            base_url=f"{base_url.rstrip('/')}/v1",
            api_key="ollama",  # Ollama는 인증 불필요, 더미값
        )
        logger.info("OllamaClient 초기화: base_url=%s, model=%s", base_url, model)

    @property
    def model_name(self) -> str:
        return self._model

    async def complete(self, system_prompt: str, user_message: str) -> str:
        resp = await self._openai.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )
        return resp.choices[0].message.content or ""
```

### Step 4: 테스트 통과 확인

```bash
uv run pytest tests/test_llm_clients.py -v
```
Expected: PASS

### Step 5: 커밋

```bash
git add src/llm/ tests/test_llm_clients.py
git commit -m "feat: LLM 추상 레이어 추가 (ClaudeClient, OllamaClient)"
```

---

## Task 2: Config에 LLM 백엔드 설정 추가

**Files:**
- Modify: `src/config.py`
- Modify: `tests/test_config.py` (있으면)

### Step 1: 테스트 작성

```python
# tests/test_config.py 에 추가 (또는 새로 작성)
from src.config import Settings


def test_default_llm_backend_is_claude():
    s = Settings()
    assert s.llm_backend == "claude"


def test_ollama_settings_defaults():
    s = Settings()
    assert s.ollama_base_url == "http://localhost:11434"
    assert s.ollama_model == "qwen2.5:7b"


def test_llm_backend_from_env(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "ollama")
    s = Settings()
    assert s.llm_backend == "ollama"
```

### Step 2: 테스트 실패 확인

```bash
uv run pytest tests/test_config.py -v -k "llm"
```
Expected: FAIL

### Step 3: 구현 (`src/config.py`에 추가)

`# ---- Claude Agent SDK 설정 ----` 블록 앞에 다음을 삽입:

```python
    # ---- LLM 백엔드 설정 ----
    llm_backend: Literal["claude", "ollama"] = Field(
        default="claude",
        description="LLM 백엔드 선택: claude(인터넷) | ollama(폐쇄망)",
    )
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="Ollama 서버 URL (llm_backend=ollama 시 사용)",
    )
    ollama_model: str = Field(
        default="qwen2.5:7b",
        description="Ollama 모델명 (예: qwen2.5:7b, exaone3.5:7.8b)",
    )
```

### Step 4: 테스트 통과 확인

```bash
uv run pytest tests/test_config.py -v -k "llm"
```
Expected: PASS

### Step 5: 커밋

```bash
git add src/config.py tests/test_config.py
git commit -m "feat: config에 LLM 백엔드 설정 추가 (llm_backend, ollama_base_url, ollama_model)"
```

---

## Task 3: 기존 LLM 호출 모듈 리팩토링

기존 4개 모듈에서 `claude_agent_sdk` 직접 호출을 제거하고 `LLMClient` 주입으로 교체한다.

**Files:**
- Modify: `src/generation/generator.py`
- Modify: `src/qa/elaboration.py`
- Modify: `src/qa/feasibility.py`
- Modify: `src/qa/report_generator.py`

**핵심 변경 패턴:**

기존:
```python
from claude_agent_sdk import ClaudeAgentOptions, query
from src._agent_lock import AGENT_ENV_LOCK as _AGENT_ENV_LOCK

class SomeClass:
    def __init__(self, ...):
        ...

    async def _query_agent(self, user_message: str) -> str:
        async with _AGENT_ENV_LOCK:
            claudecode_env = os.environ.pop("CLAUDECODE", None)
            try:
                answer = ""
                async for message in query(prompt=user_message, options=ClaudeAgentOptions(...)):
                    if hasattr(message, "result") and message.result:
                        answer = message.result
                return answer
            finally:
                if claudecode_env is not None:
                    os.environ["CLAUDECODE"] = claudecode_env
```

변경 후:
```python
from src.llm.base import LLMClient

class SomeClass:
    def __init__(self, ..., llm_client: LLMClient) -> None:
        self._llm = llm_client

    # _query_agent 메서드 삭제
    # await self._query_agent(msg) → await self._llm.complete(SYSTEM_PROMPT, msg)
```

### Step 1: `src/generation/generator.py` 수정

1. `from claude_agent_sdk import ...` 제거
2. `from src._agent_lock import ...` 제거
3. `import os` 제거 (다른 곳에서 안 쓰면)
4. `from src.llm.base import LLMClient` 추가
5. `__init__`에 `llm_client: LLMClient` 파라미터 추가, `self._llm = llm_client`
6. `self.model_name = "claude-agent-sdk"` → `self.model_name = llm_client.model_name`
7. `_query_agent` 메서드 삭제
8. `await self._query_agent(user_message)` → `await self._llm.complete(SYSTEM_PROMPT, user_message)`

### Step 2: `src/qa/elaboration.py` 수정

동일 패턴. `ELABORATION_SYSTEM_PROMPT` 사용:
```python
await self._llm.complete(ELABORATION_SYSTEM_PROMPT, user_message)
```

### Step 3: `src/qa/feasibility.py` 수정

동일 패턴. `FEASIBILITY_SYSTEM_PROMPT` 사용.

### Step 4: `src/qa/report_generator.py` 수정

동일 패턴. `REPORT_SYSTEM_PROMPT` 사용.

### Step 5: 기존 테스트가 여전히 통과하는지 확인

기존 테스트들은 `_query_agent`를 `patch.object`로 mock했으므로 수정 필요.
`patch.object(obj, "_query_agent", ...)` → `patch.object(obj._llm, "complete", ...)`

```bash
uv run pytest tests/test_qa_elaboration.py tests/test_qa_feasibility.py tests/test_qa_report_generator.py tests/test_generation.py -v
```

실패하는 테스트들을 모두 `patch.object(obj._llm, "complete", new=AsyncMock(return_value="...응답..."))` 패턴으로 수정한다.

### Step 6: 전체 테스트 통과 확인

```bash
uv run pytest tests/ -v --ignore=tests/test_retriever.py -q
```
Expected: PASS (기존 3개 retriever 실패는 무시)

### Step 7: 커밋

```bash
git add src/generation/generator.py src/qa/elaboration.py src/qa/feasibility.py src/qa/report_generator.py tests/
git commit -m "refactor: LLMClient 주입 방식으로 리팩토링 (claude_agent_sdk 직접 의존 제거)"
```

---

## Task 4: Pipeline에 LLM 백엔드 선택 로직 추가

**Files:**
- Modify: `src/pipeline.py`

### Step 1: `from_settings`에 LLM 팩토리 추가

`src/pipeline.py`의 `from_settings` 메서드에서 generator 생성 전에:

```python
# src/pipeline.py 상단 임포트에 추가
from src.llm import ClaudeClient, LLMClient, OllamaClient

# from_settings 내부, generator 생성 전에 추가
# LLM 백엔드 선택
if cfg.llm_backend == "ollama":
    llm_client: LLMClient = OllamaClient(
        base_url=cfg.ollama_base_url,
        model=cfg.ollama_model,
    )
    logger.info("LLM 백엔드: Ollama (%s @ %s)", cfg.ollama_model, cfg.ollama_base_url)
else:
    llm_client = ClaudeClient()
    logger.info("LLM 백엔드: Claude Agent SDK")

# generator 생성 시 llm_client 전달
generator = IssueAnswerGenerator(
    llm_client=llm_client,
    max_retries=cfg.generation_max_retries,
    ...
)
```

### Step 2: `_get_elaborator`, `_get_feasibility_assessor`, `_get_report_generator` 수정

각 팩토리 메서드에서 `self._llm_client`를 생성자에 전달:

```python
def __init__(self, ...) -> None:
    ...
    self._llm_client: LLMClient | None = None  # from_settings에서 주입

# from_settings에서
pipeline = cls(...)
pipeline._llm_client = llm_client
```

또는 더 간단하게 `__init__`에 `llm_client` 파라미터 추가.

### Step 3: 테스트 — LLM 백엔드 전환 확인

```python
# tests/test_pipeline_llm.py
from unittest.mock import patch
from src.config import Settings
from src.pipeline import IssuePipeline
from src.llm import OllamaClient, ClaudeClient


def test_ollama_backend_selected(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "ollama")
    # Settings 재로드
    with patch("src.config._settings_cache", Settings()):
        pipeline = IssuePipeline.from_settings(Settings())
    assert isinstance(pipeline._llm_client, OllamaClient)


def test_claude_backend_selected(tmp_path):
    pipeline = IssuePipeline.from_settings(Settings())
    assert isinstance(pipeline._llm_client, ClaudeClient)
```

```bash
uv run pytest tests/test_pipeline_llm.py -v
```

### Step 4: 커밋

```bash
git add src/pipeline.py tests/test_pipeline_llm.py
git commit -m "feat: pipeline에 LLM 백엔드 선택 로직 추가 (claude/ollama 전환)"
```

---

## Task 5: 알람 수신 API

**Files:**
- Create: `src/api/alarm_models.py`
- Create: `src/api/alarm_router.py`
- Modify: `src/api/main.py`
- Create: `tests/test_alarm_api.py`

### Step 1: 테스트 작성

```python
# tests/test_alarm_api.py
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

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
        report_content="# QA 리포트",
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


def test_alarm_ingest_with_measurements(client):
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


def test_alarm_ingest_missing_required_field(client):
    resp = client.post("/api/v1/alarm/ingest", json={
        "alarm_message": "알람코드 없음",
    })
    assert resp.status_code == 422
```

### Step 2: 테스트 실패 확인

```bash
uv run pytest tests/test_alarm_api.py -v
```
Expected: FAIL

### Step 3: 모델 구현

```python
# src/api/alarm_models.py
from __future__ import annotations

from pydantic import BaseModel, Field


class AlarmPayload(BaseModel):
    """장비 알람 수신 페이로드."""

    alarm_code: str = Field(..., description="알람 코드 (예: OVP-001)")
    alarm_message: str = Field(..., description="알람 메시지")
    voltage: float | None = Field(None, description="발생 시점 전압(V)")
    current: float | None = Field(None, description="발생 시점 전류(A)")
    temperature: float | None = Field(None, description="발생 시점 온도(°C)")
    unit_id: str | None = Field(None, description="장비 유닛/채널 ID")
    test_stage: str | None = Field(None, description="테스트 단계 (예: CC_CHARGE)")
    elapsed_seconds: int | None = Field(None, description="테스트 시작 후 경과 시간(초)")


class AlarmReportResponse(BaseModel):
    """알람 QA 리포트 응답."""

    alarm_code: str
    severity: str
    verdict: str
    reasoning: str
    recommended_test_cases: list[str]
    report_path: str
    report_summary: str
```

### Step 4: 라우터 구현

```python
# src/api/alarm_router.py
from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.alarm_models import AlarmPayload, AlarmReportResponse
from src.api.dependencies import get_pipeline
from src.logger import get_logger
from src.pipeline import IssuePipeline
from src.qa.test_result_parser import TestResultSet

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/alarm", tags=["Alarm QA"])


def _build_raw_issue(payload: AlarmPayload) -> str:
    """AlarmPayload를 Stage 1 입력용 자연어 이슈 설명으로 변환한다."""
    lines = [
        f"알람 코드: {payload.alarm_code}",
        f"알람 메시지: {payload.alarm_message}",
    ]
    if payload.unit_id:
        lines.append(f"채널/유닛: {payload.unit_id}")
    if payload.test_stage:
        lines.append(f"테스트 단계: {payload.test_stage}")
    if payload.elapsed_seconds is not None:
        lines.append(f"경과 시간: {payload.elapsed_seconds}초")
    measurements = []
    if payload.voltage is not None:
        measurements.append(f"전압 {payload.voltage}V")
    if payload.current is not None:
        measurements.append(f"전류 {payload.current}A")
    if payload.temperature is not None:
        measurements.append(f"온도 {payload.temperature}°C")
    if measurements:
        lines.append(f"측정값: {', '.join(measurements)}")
    return "\n".join(lines)


@router.post(
    "/ingest",
    response_model=AlarmReportResponse,
    summary="배터리 알람 자동 QA 처리",
)
async def ingest_alarm(
    payload: AlarmPayload,
    pipeline: IssuePipeline = Depends(get_pipeline),
) -> AlarmReportResponse:
    """
    장비 알람 발생 시 Stage 1~3 QA 파이프라인을 자동 실행한다.

    1. 알람 페이로드 → 자연어 이슈 설명 변환
    2. Stage 1: 이슈 구체화 (RAG + LLM)
    3. Stage 2: 테스트 가능여부 판단
    4. Stage 3: QA 리포트 생성 및 저장
    """
    logger.info("알람 수신: %s - %s", payload.alarm_code, payload.alarm_message)

    raw_issue = _build_raw_issue(payload)

    # Stage 1
    elaboration = await pipeline.qa_elaborate(raw_issue)

    # Stage 2
    criteria = pipeline.get_validation_criteria()
    feasibility = await pipeline.qa_assess_feasibility(elaboration, criteria)

    # Stage 3 (테스트 결과 없이 리포트 생성)
    empty_results = TestResultSet(
        source_filename="N/A (알람 자동 처리)",
        format="none",
        total=0,
        passed=0,
        failed=0,
        skipped=0,
        test_cases=[],
        raw_content="",
    )
    report = await pipeline.qa_generate_report(elaboration, feasibility, empty_results)

    logger.info(
        "알람 QA 완료: %s → 심각도=%s, 판정=%s, 리포트=%s",
        payload.alarm_code,
        elaboration.severity_estimate,
        feasibility.verdict,
        report.report_path,
    )

    return AlarmReportResponse(
        alarm_code=payload.alarm_code,
        severity=elaboration.severity_estimate,
        verdict=feasibility.verdict,
        reasoning=feasibility.reasoning,
        recommended_test_cases=feasibility.recommended_test_cases,
        report_path=str(report.report_path),
        report_summary=report.report_content[:500],
    )
```

### Step 5: main.py에 alarm_router 등록

`src/api/main.py`에서 `qa_router` 등록 바로 아래에 추가:

```python
from src.api.alarm_router import router as alarm_router
...
app.include_router(alarm_router)
```

### Step 6: 테스트 통과 확인

```bash
uv run pytest tests/test_alarm_api.py -v
```
Expected: PASS

### Step 7: 커밋

```bash
git add src/api/alarm_models.py src/api/alarm_router.py src/api/main.py tests/test_alarm_api.py
git commit -m "feat: 배터리 알람 자동 QA 엔드포인트 추가 (POST /api/v1/alarm/ingest)"
```

---

## Task 6: 알람 어댑터 스크립트

**Files:**
- Create: `alarm_adapter.py` (프로젝트 루트)
- Create: `tests/test_alarm_adapter.py`

### Step 1: 테스트 작성

```python
# tests/test_alarm_adapter.py
import pytest
from unittest.mock import MagicMock, patch
from alarm_adapter import AlarmAdapter, normalize_payload


def test_normalize_payload_with_all_fields():
    raw = {
        "alarm_code": "OVP-001",
        "alarm_message": "과전압",
        "voltage": 4.35,
        "current": 2.1,
        "temperature": 45.0,
        "unit_id": "CH-03",
        "test_stage": "CC_CHARGE",
        "elapsed_seconds": 1823,
    }
    result = normalize_payload(raw)
    assert result["alarm_code"] == "OVP-001"
    assert result["voltage"] == 4.35


def test_normalize_payload_minimal():
    raw = {"alarm_code": "E001", "alarm_message": "오류"}
    result = normalize_payload(raw)
    assert result["alarm_code"] == "E001"
    assert result.get("voltage") is None


def test_alarm_adapter_deduplication():
    adapter = AlarmAdapter(pipeline_url="http://localhost:8000")
    assert not adapter._is_duplicate("E001", 1000.0)
    adapter._mark_seen("E001", 1000.0)
    assert adapter._is_duplicate("E001", 1000.0)
    assert not adapter._is_duplicate("E001", 2000.0)  # 다른 timestamp
```

### Step 2: 테스트 실패 확인

```bash
uv run pytest tests/test_alarm_adapter.py -v
```
Expected: FAIL

### Step 3: 구현

```python
# alarm_adapter.py
"""
배터리 충방전 장비 알람 어댑터.

사용법:
    # 장비 HTTP API 폴링 모드
    python alarm_adapter.py --equipment-url http://192.168.1.100:8080 --pipeline-url http://localhost:8000

    # 시리얼 포트 수신 모드 (pyserial 필요: uv add pyserial)
    python alarm_adapter.py --serial-port /dev/ttyUSB0 --pipeline-url http://localhost:8000

환경 변수:
    PIPELINE_URL      파이프라인 서버 URL (기본: http://localhost:8000)
    EQUIPMENT_URL     장비 API URL
    SERIAL_PORT       시리얼 포트 경로
    POLL_INTERVAL     폴링 간격(초) (기본: 5)
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def normalize_payload(raw: dict[str, Any]) -> dict[str, Any]:
    """장비별 원시 데이터를 파이프라인 표준 페이로드로 변환한다."""
    return {
        "alarm_code": raw.get("alarm_code") or raw.get("code") or raw.get("error_code", "UNKNOWN"),
        "alarm_message": raw.get("alarm_message") or raw.get("message") or raw.get("description", ""),
        "voltage": raw.get("voltage") or raw.get("volt") or raw.get("V"),
        "current": raw.get("current") or raw.get("curr") or raw.get("A"),
        "temperature": raw.get("temperature") or raw.get("temp") or raw.get("T"),
        "unit_id": raw.get("unit_id") or raw.get("channel") or raw.get("ch"),
        "test_stage": raw.get("test_stage") or raw.get("stage") or raw.get("mode"),
        "elapsed_seconds": raw.get("elapsed_seconds") or raw.get("elapsed"),
    }


class AlarmAdapter:
    def __init__(self, pipeline_url: str) -> None:
        self._pipeline_url = pipeline_url.rstrip("/")
        self._seen: dict[str, float] = {}  # alarm_key → timestamp

    def _alarm_key(self, alarm_code: str, timestamp: float) -> str:
        # 동일 코드라도 5분 이상 차이나면 새 알람으로 간주
        bucket = int(timestamp // 300)
        return f"{alarm_code}:{bucket}"

    def _is_duplicate(self, alarm_code: str, timestamp: float) -> bool:
        return self._alarm_key(alarm_code, timestamp) in self._seen

    def _mark_seen(self, alarm_code: str, timestamp: float) -> None:
        self._seen[self._alarm_key(alarm_code, timestamp)] = timestamp

    def send_to_pipeline(self, payload: dict[str, Any]) -> dict[str, Any]:
        resp = httpx.post(
            f"{self._pipeline_url}/api/v1/alarm/ingest",
            json=payload,
            timeout=120.0,
        )
        resp.raise_for_status()
        return resp.json()

    def poll_equipment_api(self, equipment_url: str) -> dict[str, Any] | None:
        """장비 HTTP API에서 최신 알람 조회."""
        try:
            resp = httpx.get(f"{equipment_url}/alarm/latest", timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("active"):
                    return normalize_payload(data)
        except Exception as exc:
            logger.warning("장비 API 조회 실패: %s", exc)
        return None

    def read_serial(self, port: str, baudrate: int = 9600) -> dict[str, Any] | None:
        """시리얼 포트에서 JSON 라인 수신."""
        try:
            import serial  # pyserial
            with serial.Serial(port, baudrate, timeout=1) as ser:
                line = ser.readline().decode("utf-8", errors="ignore").strip()
                if line:
                    return normalize_payload(json.loads(line))
        except ImportError:
            logger.error("pyserial 미설치. 'uv add pyserial' 실행 후 재시도")
        except Exception as exc:
            logger.warning("시리얼 수신 오류: %s", exc)
        return None

    def run_polling(
        self,
        equipment_url: str | None = None,
        serial_port: str | None = None,
        interval: int = 5,
    ) -> None:
        logger.info(
            "알람 어댑터 시작 | pipeline=%s, equipment=%s, serial=%s, interval=%ds",
            self._pipeline_url, equipment_url, serial_port, interval,
        )
        while True:
            try:
                alarm: dict[str, Any] | None = None
                if equipment_url:
                    alarm = self.poll_equipment_api(equipment_url)
                elif serial_port:
                    alarm = self.read_serial(serial_port)

                if alarm:
                    code = alarm.get("alarm_code", "UNKNOWN")
                    ts = time.time()
                    if not self._is_duplicate(code, ts):
                        logger.info("알람 감지: %s", code)
                        result = self.send_to_pipeline(alarm)
                        self._mark_seen(code, ts)
                        logger.info(
                            "QA 처리 완료: 심각도=%s, 판정=%s, 리포트=%s",
                            result.get("severity"),
                            result.get("verdict"),
                            result.get("report_path"),
                        )
                    else:
                        logger.debug("중복 알람 스킵: %s", code)

            except httpx.HTTPError as exc:
                logger.error("파이프라인 서버 오류: %s", exc)
            except Exception as exc:
                logger.error("예상치 못한 오류: %s", exc)

            time.sleep(interval)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="배터리 알람 어댑터")
    parser.add_argument("--pipeline-url", default=os.getenv("PIPELINE_URL", "http://localhost:8000"))
    parser.add_argument("--equipment-url", default=os.getenv("EQUIPMENT_URL"))
    parser.add_argument("--serial-port", default=os.getenv("SERIAL_PORT"))
    parser.add_argument("--interval", type=int, default=int(os.getenv("POLL_INTERVAL", "5")))
    args = parser.parse_args()

    if not args.equipment_url and not args.serial_port:
        parser.error("--equipment-url 또는 --serial-port 중 하나를 지정하세요")

    adapter = AlarmAdapter(pipeline_url=args.pipeline_url)
    adapter.run_polling(
        equipment_url=args.equipment_url,
        serial_port=args.serial_port,
        interval=args.interval,
    )
```

### Step 4: 테스트 통과 확인

```bash
uv run pytest tests/test_alarm_adapter.py -v
```
Expected: PASS

### Step 5: 커밋

```bash
git add alarm_adapter.py tests/test_alarm_adapter.py
git commit -m "feat: 배터리 알람 어댑터 스크립트 추가 (폴링/시리얼 지원)"
```

---

## Task 7: 배터리 도메인 데이터 세팅

**Files:**
- Create: `data/raw/battery/ALARM-2024-001_OVP_과전압보호.md`
- Create: `data/raw/battery/ALARM-2024-002_OTP_과온도보호.md`
- Create: `data/raw/battery/ALARM-2024-003_OCP_과전류보호.md`
- Modify: `data/config/validation_criteria.yaml`

### Step 1: 샘플 알람 이력 문서 작성

```markdown
<!-- data/raw/battery/ALARM-2024-001_OVP_과전압보호.md -->
# ALARM-2024-001: OVP-001 과전압 보호 동작

| 항목 | 내용 |
|------|------|
| 알람코드 | OVP-001 |
| 심각도 | High |
| 발생 단계 | CC 충전 (1823초 경과) |
| 채널 | CH-03 |
| 측정값 | 전압 4.35V / 전류 2.1A / 온도 45.2°C |
| 발생일 | 2024-06-12 |
| 해결일 | 2024-06-13 |

## 원인 분석
충전 알고리즘의 CC→CV 전환 기준 전압값(4.2V)이 BMS 보호 임계값(4.25V)보다
낮게 설정되어야 하나, 펌웨어 버그로 4.35V까지 충전이 계속됨.

## 조치 방법
1. 충전 즉시 중단
2. 펌웨어 v2.3.1 → v2.3.2 업데이트 (CC→CV 전환 전압 4.15V로 수정)
3. BMS 보호 임계값 재검증

## 재현 조건
- 펌웨어 v2.3.1 이하
- CC 충전 중 2단계 전환 시점
- 배터리 용량 90% 이상 도달 시

## 권장 테스트케이스
- 충전 전압 상한 경계값 테스트 (4.20V, 4.25V, 4.30V)
- 펌웨어 버전별 CC→CV 전환 시점 검증
```

비슷한 형식으로 OTP(과온도), OCP(과전류) 문서 2개 더 작성.

### Step 2: validation_criteria.yaml 배터리 도메인으로 커스터마이징

```yaml
# data/config/validation_criteria.yaml
version: "1.0"

reproducibility:
  required: true
  min_steps: 2
  environment_required: true

measurability:
  required: true
  quantitative_criteria_required: true   # 전압/전류/온도 수치 기반 판정
  binary_verdict_required: true

acceptance_criteria:
  required: true
  explicit_criteria_required: true
  min_criteria_count: 2

test_scope:
  level: "integration"
  automation_required: false
  manual_acceptable: true

severity_overrides:
  Critical:
    automation_required: true
    min_steps: 1
  High:
    automation_required: false
    min_steps: 2
  Medium:
    manual_acceptable: true
  Low:
    manual_acceptable: true
    quantitative_criteria_required: false

custom_rules:
  - "알람 발생 시 측정값(전압/전류/온도)은 반드시 QA 리포트에 포함되어야 합니다."
  - "보호 회로(OVP/OCP/OTP) 관련 알람은 항상 'testable' 판정을 받아야 합니다."
  - "펌웨어 버전과 테스트 환경(채널 번호, 배터리 스펙)을 명시해야 합니다."
  - "재현 조건에 배터리 SOC(충전 상태) 범위를 포함해야 합니다."

report:
  language: "ko"
  filename_prefix: "QA_BATTERY"
  sections:
    - "알람 개요"
    - "테스트 가능성 평가"
    - "측정값 분석"
    - "원인 가설"
    - "권장 테스트 케이스"
    - "결론 및 권고사항"
```

### Step 3: 배터리 이력 문서 인덱싱

```bash
# 서버 실행 후
curl -X POST http://localhost:8000/api/v1/index \
  -H "Content-Type: application/json" \
  -d '{"source_dir": "data/raw/battery", "recursive": false}'
```

Expected: `{"files_processed": 3, ...}`

### Step 4: 커밋

```bash
git add data/raw/battery/ data/config/validation_criteria.yaml
git commit -m "data: 배터리 알람 이력 샘플 문서 3건 + validation_criteria 배터리 도메인 설정"
```

---

## Task 8: pyproject.toml 의존성 추가 및 전체 테스트

**Files:**
- Modify: `pyproject.toml`

### Step 1: openai 의존성 추가

```bash
uv add "openai>=1.0"
```

### Step 2: 전체 테스트 실행

```bash
uv run pytest tests/ -v --ignore=tests/test_retriever.py -q
```
Expected: 모든 새 테스트 PASS (기존 3개 retriever 실패 무시)

### Step 3: 최종 커밋

```bash
git add pyproject.toml uv.lock
git commit -m "build: openai 의존성 추가 (Ollama OpenAI 호환 클라이언트)"
```

---

## 검증 — 전체 E2E 시나리오

### 시나리오 A: Claude 백엔드 (인터넷 환경)

```bash
# .env
LLM_BACKEND=claude

# 서버 시작
uv run uvicorn src.api.main:app --port 8000

# 알람 발생 시뮬레이션
curl -X POST http://localhost:8000/api/v1/alarm/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "alarm_code": "OVP-001",
    "alarm_message": "과전압 보호 동작",
    "voltage": 4.35,
    "current": 2.1,
    "temperature": 45.2,
    "unit_id": "CH-03",
    "test_stage": "CC_CHARGE",
    "elapsed_seconds": 1823
  }'
```

### 시나리오 B: Ollama 백엔드 (폐쇄망)

```bash
# 1. Ollama 설치 후 모델 다운로드 (인터넷 연결 시 1회만)
ollama pull qwen2.5:7b

# 2. .env
LLM_BACKEND=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b

# 3. 이후 인터넷 차단 상태에서도 동작
uv run uvicorn src.api.main:app --port 8000

# 4. 알람 어댑터 실행 (장비 API 폴링)
python alarm_adapter.py \
  --equipment-url http://192.168.1.100:8080 \
  --pipeline-url http://localhost:8000 \
  --interval 5
```

### 리포트 확인

```bash
ls data/qa_reports/
cat data/qa_reports/QA_BATTERY_*.md
```
