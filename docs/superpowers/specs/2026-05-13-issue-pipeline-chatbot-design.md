# Issue Pipeline 챗봇 시스템 — 설계 문서

**작성일:** 2026-05-13
**상태:** 확정 (Stage 1 진행 중)

---

## 1. 프로젝트 개요

배터리/충방전 검사 장비 및 소프트웨어 이슈 문서를 기반으로,
자연어 질문에 답변하는 RAG 기반 사내 챗봇 시스템.

**타겟 사용자:**
- 1~3단계: 사내 배터리 엔지니어, QA 담당자, 고객 지원팀
- 4단계: 외부 고객사 기술 담당자

**핵심 원칙:**
- Stage 1에서 설계한 데이터 구조가 Stage 2~4까지 하위 호환성을 유지해야 한다
- LLM 백엔드는 교체 가능 (Claude SDK / Anthropic API / Ollama 폐쇄망)
- 데이터 품질이 챗봇 품질을 결정한다 — Stage 1이 가장 중요

---

## 2. 4단계 로드맵

| 단계 | 목표 | 핵심 산출물 | LLM |
|------|------|------------|-----|
| **Stage 1** | 데이터 구조 설계 · 양식 정합화 | 표준 문서 양식, ChromaDB 스키마, API 인터페이스 확정 | ❌ 없음 |
| **Stage 2** | 챗봇 개발 | 대화형 UI, 멀티턴, 스트리밍, 피드백 | ✅ Claude / Ollama |
| **Stage 3** | 전사 배포 | Docker 배포, 사내 인증(SSO/LDAP), 모니터링 | ✅ |
| **Stage 4** | 외부 배포 | 클라우드, 외부 인증, 멀티테넌트, SLA | ✅ |

---

## 3. 시스템 아키텍처 (전체)

```
[이슈 문서]          [배터리 알람]        [챗봇 UI (Stage 2~)]
BUG-*.md             장비 시리얼/HTTP      웹 브라우저
BATTERY-*.md              │                    │
INCIDENT-*.md             ▼                    ▼
     │         [alarm_adapter.py]    [POST /api/v1/chat/message]
     ▼                    │                    │
[Ingestion]               ▼                    ▼
DocumentLoader   [POST /api/v1/alarm/ingest]  [Session Store]
DocumentChunker           │                  대화 히스토리
     │                    │                    │
     ▼                    ▼                    ▼
[Embedding]        [QA Pipeline]        [Retrieval]
FastEmbed          Stage1 구체화         IssueRetriever
     │             Stage2 판단           코사인 유사도
     ▼             Stage3 리포트              │
[ChromaDB]                │                   ▼
벡터 저장소  ◄─────────────┘          [Generation]
                                      LLMClient
                                      (Claude/Anthropic/Ollama)
                                           │
                                           ▼
                                    [FastAPI 응답]
                                    스트리밍 / JSON
```

---

## 4. 기술 스택

| 구분 | 기술 |
|------|------|
| Language | Python 3.11+ |
| Framework | FastAPI + Pydantic V2 |
| LLM | Claude Agent SDK / Anthropic API / Ollama (선택) |
| 임베딩 | FastEmbed (ONNX, 다국어, API 키 불필요) |
| 벡터 DB | ChromaDB (로컬 → Stage 3에서 외부 서버 고려) |
| 세션 저장 (Stage 2~) | Redis 또는 SQLite (규모에 따라 선택) |
| 챗봇 UI (Stage 2~) | React.js SPA 또는 Streamlit (내부용 MVP) |
| 배포 (Stage 3~) | Docker Compose, Caddy 리버스 프록시 |
| 인증 (Stage 3~) | JWT + 사내 LDAP/SSO |
| 패키지 관리 | uv |

---

## 5. 데이터 구조 설계 (Stage 1 핵심)

### 5-1. 이슈 문서 표준 양식

모든 이슈 문서는 아래 헤더 블록을 포함해야 한다.
챗봇이 메타데이터 필터링에 사용하므로 정합성이 필수.

```markdown
---
id: BATTERY-2024-001              # 필수: 도메인-연도-순번
domain: battery                   # 필수: battery | software | incident
severity: critical                # 필수: critical | high | medium | low
status: resolved                  # 필수: resolved | ongoing | investigating
alarm_code: OVP-001               # 배터리 도메인 시 필수
tags: [overvoltage, cc-charge, cell-voltage]  # 검색 보조
created_at: 2024-03-15
resolved_at: 2024-03-16
---

## 증상 (Symptom)
...

## 원인 분석 (Root Cause)
...

## 조치 방법 (Resolution)
...

## 재발 방지 (Prevention)
...

## 관련 이력 (Related Cases)
- BATTERY-2024-000
```

**도메인 분류:**
| domain 값 | 대상 파일 접두사 |
|-----------|----------------|
| `battery` | `BATTERY-*.md` |
| `software` | `BUG-*.md` |
| `incident` | `INCIDENT-*.md` |

---

### 5-2. ChromaDB 메타데이터 스키마

벡터 저장 시 각 청크에 아래 메타데이터를 저장한다.
Stage 2 챗봇의 필터링 및 출처 표시에 사용된다.

```python
metadata = {
    # 문서 식별
    "doc_id": "BATTERY-2024-001",           # 이슈 ID
    "domain": "battery",                     # 도메인 분류
    "severity": "critical",                  # 심각도
    "status": "resolved",                    # 처리 상태
    "alarm_code": "OVP-001",                 # 알람 코드 (배터리)

    # 청크 정보
    "file_hash": "md5_hash_string",          # 멱등성 보장
    "chunk_index": 0,                        # 청크 순번
    "section": "root_cause",                 # 섹션 (symptom|root_cause|resolution|prevention)
    "source_file": "BATTERY-2024-001_overvoltage_cc_charge.md",

    # 시간
    "created_at": "2024-03-15",
    "resolved_at": "2024-03-16",

    # 태그 (쉼표 구분 문자열 — ChromaDB는 list 미지원)
    "tags": "overvoltage,cc-charge,cell-voltage",
}
```

**필터링 예시 (Stage 2 챗봇에서 사용):**
```python
# 배터리 도메인 + 해결된 케이스만 검색
retriever.search(query, filter={"domain": "battery", "status": "resolved"})

# 특정 알람 코드 우선 검색
retriever.search(query, filter={"alarm_code": "OVP-001"})
```

---

### 5-3. QA 리포트 표준 양식

`data/qa_reports/QA_REPORT_*.md` 파일명 및 내용 구조 확정.

**파일명 규칙:**
```
QA_REPORT_{YYYYMMDD}_{HHMMSS}_{microsec}_{SEVERITY}_{VERDICT}.md
예: QA_REPORT_20260308_112839_734445_CRITICAL_PARTIALLY_TESTABLE.md
```

**리포트 내부 구조 (표준):**
```markdown
---
report_id: QA_REPORT_20260308_112839_734445
issue_summary: "DB 서버 가끔 터짐"
severity: CRITICAL
verdict: PARTIALLY_TESTABLE
generated_at: 2026-03-08T11:28:39
---

## 1. 이슈 구체화 결과 (Stage 1)
...

## 2. 테스트 가능여부 판단 (Stage 2)
...

## 3. 테스트 항목 (Stage 3)
...

## 4. 근거 문서
- [BATTERY-2024-001](../../raw/BATTERY-2024-001_overvoltage_cc_charge.md)
```

---

### 5-4. validation_criteria.yaml — 도메인별 분리

현재 소프트웨어 중심 기준을 배터리 도메인 전용으로 분리한다.

```
data/config/
├── validation_criteria.yaml          # 소프트웨어 이슈 (기존)
└── validation_criteria_battery.yaml  # 배터리/장비 이슈 (신규)
```

`validation_criteria_battery.yaml` 핵심 항목:
```yaml
domain: battery
version: "1.0"
criteria:
  - id: BAT-001
    name: 재현 가능성
    description: 동일 조건에서 알람 재현 가능한가
    weight: 0.3
  - id: BAT-002
    name: 측정 장비 접근성
    description: 전압/전류/온도 측정 가능한가
    weight: 0.25
  - id: BAT-003
    name: 안전 환경 확보
    description: IEC/UL 기준 테스트 환경 구성 가능한가
    weight: 0.25
  - id: BAT-004
    name: 데이터 로깅
    description: 충방전 데이터 수집 가능한가
    weight: 0.2
```

---

## 6. API 인터페이스 (전체 — Stage별 확장)

### Stage 1 (현재 확정)

```
# 기본 RAG
POST /api/v1/query              RAG 질문 답변
POST /api/v1/search             유사 문서 검색 (LLM 없음)
POST /api/v1/index              문서 인덱싱
GET  /api/v1/stats              인덱스 통계

# QA 파이프라인
POST /api/v1/qa/elaborate       Stage 1: 이슈 구체화
POST /api/v1/qa/feasibility     Stage 2: 테스트 가능성 판단
POST /api/v1/qa/report          Stage 3: 리포트 생성
GET  /api/v1/qa/validation-criteria  검증 기준 조회

# 배터리 알람
POST /api/v1/alarm/ingest       알람 수신 → 자동 QA
```

### Stage 2 (챗봇 — 신규 설계 예정)

```
# 챗봇 대화
POST /api/v1/chat/message       메시지 전송 (스트리밍 지원)
GET  /api/v1/chat/sessions      세션 목록
POST /api/v1/chat/sessions      새 세션 생성
GET  /api/v1/chat/sessions/{id}/history  대화 히스토리
DELETE /api/v1/chat/sessions/{id}

# 피드백
POST /api/v1/chat/feedback      답변 평가 (thumbs up/down)

# 문서 관리 (인증 필요)
POST /api/v1/documents/upload   문서 업로드
GET  /api/v1/documents          문서 목록
DELETE /api/v1/documents/{id}
```

### Stage 3 (전사 배포 — 인증 추가)

```
POST /api/auth/login            JWT 로그인
POST /api/auth/logout
GET  /api/auth/me
GET  /api/admin/usage           사용량 통계 (관리자)
GET  /api/admin/users           사용자 관리
```

---

## 7. 대화 세션 구조 (Stage 2 대비 설계)

Stage 1에서 DB 스키마를 미리 설계해두어 Stage 2에서 즉시 구현 가능하도록 한다.

```python
# 세션 테이블 (SQLite → Stage 3에서 PostgreSQL 마이그레이션)
class ChatSession:
    session_id: str          # UUID
    user_id: str | None      # Stage 3부터 인증
    created_at: datetime
    last_active_at: datetime
    domain_filter: str | None  # "battery" | "software" | None (전체)
    title: str               # 첫 메시지 기반 자동 생성

class ChatMessage:
    message_id: str          # UUID
    session_id: str          # FK
    role: str                # "user" | "assistant"
    content: str
    created_at: datetime
    # 메타데이터 (assistant 메시지만)
    context_docs: list[str]  # 참조 문서 ID 목록
    retrieval_score: float | None
    model_used: str | None   # "claude-sonnet-4-6" | "qwen2.5:7b"
    input_tokens: int | None
    output_tokens: int | None

class ChatFeedback:
    feedback_id: str
    message_id: str          # FK
    rating: int              # 1 (좋음) | -1 (나쁨)
    comment: str | None
    created_at: datetime
```

---

## 8. 스트리밍 API 설계 (Stage 2 대비)

Stage 1에서 Generator를 스트리밍 지원 가능 구조로 미리 설계한다.

```python
# 현재: 일반 응답
async def generate(question, retrieval_results) -> GenerationResult:
    ...

# Stage 2: 스트리밍 응답 (SSE)
async def generate_stream(question, retrieval_results) -> AsyncGenerator[str, None]:
    async for chunk in llm_client.complete_stream(system, user):
        yield chunk

# FastAPI SSE 엔드포인트 (Stage 2)
@router.post("/chat/message")
async def chat_message(request: ChatRequest):
    return StreamingResponse(
        generate_stream(request.message, session_context),
        media_type="text/event-stream"
    )
```

---

## 9. 테스트 데이터 목표 (Stage 1)

| 도메인 | 현재 | 목표 | 양식 |
|--------|------|------|------|
| 배터리 | 4건 | 30건 이상 | `BATTERY-YYYY-NNN_*.md` |
| 소프트웨어 | 2건 | 10건 이상 | `BUG-YYYY-NNN_*.md` |
| 장애 | 1건 | 5건 이상 | `INCIDENT-YYYY-NNN_*.md` |
| **합계** | **7건** | **45건 이상** | |

배터리 문서 커버리지 목표 (알람 유형별):
- OVP (과전압): 5건
- UVP (과방전): 3건
- OCP (과전류): 5건
- OTP (과온도): 5건
- CIB (셀 불균형): 4건
- 기타 (포메이션, 에이징, 수명): 8건

---

## 10. Stage별 배포 구조

### Stage 1~2 (로컬/단일 서버)
```
uv run python scripts/start_server.py
→ http://localhost:8000
```

### Stage 3 (전사 배포 — Docker Compose)
```
┌─────────────────────────────────┐
│          Ubuntu 서버             │
│                                 │
│  Caddy (리버스 프록시 + HTTPS)   │
│        :80 / :443               │
│             │                   │
│  FastAPI    │   Redis (세션)     │
│  :8000      │   :6379            │
│             │                   │
│  ChromaDB   │   (선택적)         │
│  서버 모드   │                   │
└─────────────────────────────────┘
```

### Stage 4 (외부 배포 — 서버 PC)
```
고객사 또는 자사 서버 PC
        │
   Caddy (리버스 프록시 + HTTPS)
        │
   FastAPI + ChromaDB + Redis
   (Docker Compose, Stage 3와 동일 구조)
```
※ 클라우드 사용 금지 — 대외비 데이터가 외부 네트워크 경유 불가

---

## 11. 보안 설계

| 단계 | 인증 방식 | 비고 |
|------|----------|------|
| Stage 1~2 | 없음 (내부 개발) | localhost만 바인딩 |
| Stage 3 | JWT + 사내 LDAP/SSO | 사내망 한정 |
| Stage 4 | OAuth2 + API Key | 외부 고객사 발급 |

공통 보안 원칙:
- API Key는 환경변수로만 관리 (코드 노출 금지)
- 사용자 입력은 LLM 프롬프트 주입 방지 처리
- QA 리포트에 고객사 민감정보 포함 시 마스킹
