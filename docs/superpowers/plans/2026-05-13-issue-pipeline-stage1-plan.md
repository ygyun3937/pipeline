# Issue Pipeline Stage 1 — 구현 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**목표:** LLM 없이 챗봇(Stage 2~4)을 위한 데이터 구조를 설계·구현·정합화한다.
Stage 1 완료 시 Stage 2 챗봇 개발이 즉시 착수 가능한 상태여야 한다.

**설계 문서:** `docs/superpowers/specs/2026-05-13-issue-pipeline-chatbot-design.md`

---

## 전체 Task 목록

| Task | 내용 | 의존성 |
|------|------|--------|
| Task 1 | 이슈 문서 양식 표준화 및 기존 문서 마이그레이션 | 없음 |
| Task 2 | ChromaDB 메타데이터 스키마 확장 | Task 1 |
| Task 3 | 배터리 validation_criteria_battery.yaml 작성 | 없음 |
| Task 4 | 배터리 이슈 문서 확충 (목표 30건) | Task 1 |
| Task 5 | 대화 세션 DB 모델 사전 설계 (Stage 2 대비) | Task 2 |
| Task 6 | 스트리밍 지원 가능 구조로 Generator 리팩토링 | Task 2 |
| Task 7 | API 인터페이스 정합화 및 문서화 | Task 5, 6 |
| Task 8 | 전체 테스트 업데이트 및 커버리지 확인 | Task 1~7 |

---

## Task 1: 이슈 문서 양식 표준화

**목적:** 모든 이슈 문서에 표준 YAML 헤더를 적용. ChromaDB 메타데이터 정합성 확보.

**Files:**
- Modify: `data/raw/BATTERY-2024-001~004.md` — YAML 헤더 추가
- Modify: `data/raw/BUG-2024-001.md`, `BUG-2024-042.md` — YAML 헤더 추가
- Modify: `data/raw/INCIDENT-2024-008.md` — YAML 헤더 추가
- Create: `docs/issue-template-battery.md` — 배터리 이슈 문서 작성 가이드
- Create: `docs/issue-template-software.md` — 소프트웨어 이슈 문서 작성 가이드

**표준 헤더 형식:**
```markdown
---
id: BATTERY-2024-001
domain: battery
severity: critical
status: resolved
alarm_code: OVP-001
tags: [overvoltage, cc-charge, cell-voltage]
created_at: 2024-03-15
resolved_at: 2024-03-16
---
```

**완료 조건:**
- 모든 기존 `data/raw/` 문서에 표준 헤더 적용
- 헤더 없는 문서 인덱싱 시 경고 로그 출력

---

## Task 2: ChromaDB 메타데이터 스키마 확장

**목적:** 설계 문서 5-2절 스키마를 `embedder.py`에 반영.
챗봇의 도메인 필터링, 출처 표시, 재랭킹에 필요한 메타데이터 추가.

**Files:**
- Modify: `src/ingestion/document_loader.py` — YAML 헤더 파싱 추가
- Modify: `src/embedding/embedder.py` — 확장 메타데이터 저장
- Modify: `src/retrieval/retriever.py` — 메타데이터 필터 파라미터 추가
- Modify: `tests/test_embedder.py` — 메타데이터 검증 테스트
- Modify: `tests/test_retriever.py` — 필터 기반 검색 테스트

**핵심 변경:**
```python
# document_loader.py: YAML 헤더 파싱
def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """YAML 헤더 파싱. 없으면 빈 dict 반환."""
    ...

# embedder.py: 확장 메타데이터 저장
metadata = {
    "doc_id": doc.metadata.get("id", source_file),
    "domain": doc.metadata.get("domain", "unknown"),
    "severity": doc.metadata.get("severity", "unknown"),
    "status": doc.metadata.get("status", "unknown"),
    "alarm_code": doc.metadata.get("alarm_code", ""),
    "section": _detect_section(chunk_text),
    "file_hash": file_hash,
    "chunk_index": idx,
    "source_file": source_file,
    "tags": ",".join(doc.metadata.get("tags", [])),
}

# retriever.py: 필터 지원
def search(
    self,
    query: str,
    top_k: int | None = None,
    filter: dict | None = None,   # 신규
) -> RetrievalResults:
    ...
```

**완료 조건:**
- 기존 테스트 전부 통과
- 필터 기반 검색 테스트 통과
- 헤더 없는 문서도 기존 방식으로 인덱싱 가능 (하위 호환)

---

## Task 3: validation_criteria_battery.yaml 작성

**목적:** 배터리 도메인 전용 QA 검증 기준 분리.
소프트웨어 기준과 혼용 시 정확도 저하 방지.

**Files:**
- Create: `data/config/validation_criteria_battery.yaml`
- Modify: `src/config.py` — `qa_validation_criteria_battery_path` 설정 추가
- Modify: `src/pipeline.py` — `domain` 파라미터 기반 기준 선택
- Modify: `src/api/qa_router.py` — `domain` 파라미터 수신

**기준 파일 구조:**
```yaml
domain: battery
version: "1.0"
description: "배터리/충방전 검사 장비 이슈 QA 검증 기준"
criteria:
  - id: BAT-001
    name: 재현 가능성
    description: 동일 조건(전압/전류/온도/SOC)에서 알람 재현 가능한가
    weight: 0.30
    testable_threshold: 0.7
  - id: BAT-002
    name: 측정 장비 접근성
    description: 전압/전류/온도 측정 장비 확보 가능한가
    weight: 0.25
    testable_threshold: 0.7
  - id: BAT-003
    name: 안전 환경 확보
    description: IEC 62133/UL 2580 기준 테스트 환경 구성 가능한가
    weight: 0.25
    testable_threshold: 0.6
  - id: BAT-004
    name: 데이터 로깅 가능성
    description: 충방전 전 구간 데이터 수집 및 저장 가능한가
    weight: 0.20
    testable_threshold: 0.7
verdict_thresholds:
  testable: 0.75
  partially_testable: 0.45
  not_testable: 0.0
```

**완료 조건:**
- `domain=battery` 파라미터로 배터리 기준 선택
- `domain=software` (기본값) 시 기존 기준 유지
- 테스트 통과

---

## Task 4: 배터리 이슈 문서 확충

**목적:** RAG 품질 향상을 위한 배터리 도메인 문서 30건 구축.
챗봇이 답변할 수 있는 케이스 커버리지 확대.

**목표 문서 목록:**
```
OVP 계열 (5건):
  BATTERY-2024-001  ✅ 기존 (OVP — CC 충전 과전압)
  BATTERY-2024-005  CC/CV 전환 실패로 인한 OVP
  BATTERY-2024-006  고온 환경에서의 OVP 오감지
  BATTERY-2024-007  다채널 OVP 동시 발생
  BATTERY-2024-008  노화 셀 OVP 임계값 재설정

OCP 계열 (5건):
  BATTERY-2024-002  ✅ 기존 (OCP — 과전류 보호)
  BATTERY-2024-009  방전 중 순간 과전류
  BATTERY-2024-010  배선 접촉 불량으로 인한 OCP
  BATTERY-2024-011  부하 급증 OCP
  BATTERY-2024-012  다채널 OCP 연쇄 발생

OTP 계열 (5건):
  BATTERY-2024-003  ✅ 기존 (OTP — 온도 이상)
  BATTERY-2024-013  냉각 시스템 고장 OTP
  BATTERY-2024-014  고율 방전 OTP
  BATTERY-2024-015  온도 센서 오감지 OTP
  BATTERY-2024-016  외부 환경 온도 상승 OTP

CIB 계열 (4건):
  BATTERY-2024-004  ✅ 기존 (CIB — 셀 불균형)
  BATTERY-2024-017  노화 편차 셀 불균형
  BATTERY-2024-018  Passive 밸런싱 불량
  BATTERY-2024-019  신규 팩 초기 불균형

포메이션/에이징/수명 (8건):
  BATTERY-2024-020  포메이션 사이클 용량 이상
  BATTERY-2024-021  에이징 온도 편차
  BATTERY-2024-022  사이클 수명 조기 열화
  BATTERY-2024-023  DCIR 급증 이상
  BATTERY-2024-024  쿨롱 효율 저하
  BATTERY-2024-025  dQ/dV 피크 이상
  BATTERY-2024-026  SOH 추정 오차
  BATTERY-2024-027  자가방전 이상

기타 UVP (3건):
  BATTERY-2024-028  과방전 UVP
  BATTERY-2024-029  기생 부하 UVP
  BATTERY-2024-030  방전 컷오프 미동작
```

**완료 조건:**
- 30건 이상 표준 양식 적용 완료
- 전체 인덱싱 성공 (`uv run python scripts/index_documents.py`)
- ChromaDB 청크 수 200개 이상

---

## Task 5: 대화 세션 DB 모델 사전 설계

**목적:** Stage 2 챗봇 개발 시 즉시 사용 가능한 세션 구조 준비.
Stage 1에서는 모델 정의 + 마이그레이션 스크립트만 작성 (실제 서버 실행 불필요).

**Files:**
- Create: `src/chat/__init__.py`
- Create: `src/chat/models.py` — Pydantic 모델 + SQLite 스키마
- Create: `src/chat/session_store.py` — 세션 CRUD 인터페이스 (추상)
- Create: `scripts/init_chat_db.py` — DB 초기화 스크립트
- Create: `tests/test_chat_models.py` — 모델 검증 테스트

**핵심 모델:**
```python
# src/chat/models.py
class ChatSession(BaseModel):
    session_id: str
    user_id: str | None = None
    domain_filter: str | None = None
    title: str = ""
    created_at: datetime
    last_active_at: datetime

class ChatMessage(BaseModel):
    message_id: str
    session_id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime
    context_doc_ids: list[str] = []
    retrieval_score: float | None = None
    model_used: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

class ChatFeedback(BaseModel):
    feedback_id: str
    message_id: str
    rating: Literal[1, -1]
    comment: str | None = None
    created_at: datetime
```

**완료 조건:**
- 모델 검증 테스트 통과
- `scripts/init_chat_db.py` 실행 시 SQLite DB 생성 성공
- Stage 2에서 import 후 즉시 사용 가능한 구조

---

## Task 6: 스트리밍 지원 구조로 Generator 리팩토링

**목적:** Stage 2 챗봇의 스트리밍 응답(SSE)을 위해 Generator를 미리 준비.
현재 일반 응답은 그대로 유지하고 스트리밍 메서드를 추가한다.

**Files:**
- Modify: `src/llm/base.py` — `complete_stream()` 추상 메서드 추가
- Modify: `src/llm/claude_client.py` — 스트리밍 구현
- Modify: `src/llm/anthropic_client.py` — 스트리밍 구현
- Modify: `src/llm/ollama_client.py` — 스트리밍 구현
- Modify: `src/generation/generator.py` — `generate_stream()` 메서드 추가
- Modify: `tests/test_generator.py` — 스트리밍 메서드 테스트 추가

**핵심 변경:**
```python
# src/llm/base.py
class LLMClient(Protocol):
    async def complete(self, system: str, user: str) -> str: ...
    async def complete_stream(                              # 신규
        self, system: str, user: str
    ) -> AsyncGenerator[str, None]: ...

# src/generation/generator.py
async def generate_stream(
    self,
    question: str,
    retrieval_results: RetrievalResults,
) -> AsyncGenerator[str, None]:
    """Stage 2 챗봇 SSE용 스트리밍 생성."""
    ...
```

**완료 조건:**
- 기존 `generate()` 테스트 전부 통과 (회귀 없음)
- `generate_stream()` 단위 테스트 통과
- 모든 LLMClient 구현체에 `complete_stream()` 추가 완료

---

## Task 7: API 인터페이스 정합화 및 문서화

**목적:** Stage 2에서 추가될 챗봇 엔드포인트 인터페이스를 미리 정의.
실제 구현 없이 라우터 스켈레톤 + OpenAPI 스키마만 작성.

**Files:**
- Create: `src/api/chat_models.py` — 챗봇 요청/응답 Pydantic 모델
- Create: `src/api/chat_router.py` — 스켈레톤 라우터 (501 Not Implemented)
- Modify: `src/api/main.py` — chat_router 등록 (비활성 플래그 지원)
- Modify: `src/config.py` — `enable_chat_api: bool = False` 플래그 추가

**스켈레톤 엔드포인트:**
```python
# src/api/chat_router.py
@router.post("/sessions", response_model=ChatSessionResponse)
async def create_session(...):
    raise HTTPException(501, "챗봇 API는 Stage 2에서 활성화됩니다.")

@router.post("/message", response_model=ChatMessageResponse)
async def send_message(...):
    raise HTTPException(501, "챗봇 API는 Stage 2에서 활성화됩니다.")
```

**완료 조건:**
- `GET /docs` (Swagger)에서 챗봇 API 스키마 확인 가능
- `ENABLE_CHAT_API=false`(기본)일 때 501 반환
- 기존 API 동작 영향 없음

---

## Task 8: 전체 테스트 업데이트 및 커버리지 확인

**목적:** Stage 1 완료 상태에서 전체 테스트 통과 확인.
Stage 2 진입 전 회귀 없음 보장.

**Files:**
- Modify: 필요한 모든 기존 테스트 파일
- Create: 누락된 테스트 추가

**완료 조건:**
```bash
uv run pytest tests/ -v --tb=short
# → 전체 PASSED, FAILED 0

uv run pytest tests/ --cov=src --cov-report=term-missing
# → 핵심 모듈 커버리지 80% 이상
```

---

## Stage 1 완료 기준 (Definition of Done)

```
□ 모든 data/raw/ 문서에 표준 YAML 헤더 적용
□ ChromaDB 메타데이터 스키마 확장 완료
□ validation_criteria_battery.yaml 작성 완료
□ 배터리 이슈 문서 30건 이상 인덱싱 성공
□ 대화 세션 DB 모델 정의 완료
□ 스트리밍 지원 구조 완료 (LLMClient + Generator)
□ 챗봇 API 스켈레톤 Swagger 노출 확인
□ 전체 테스트 PASSED
□ CLAUDE.md Stage 1 완료 날짜 기록
```

Stage 1 완료 → Stage 2 (챗봇 개발) 즉시 착수 가능.
