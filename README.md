# Issue Pipeline

사내 버그·이슈 문서를 RAG(Retrieval-Augmented Generation)로 처리하는 지식 파이프라인.  
버그 리포트, 장애 보고서, 배터리 도메인 이슈를 벡터 DB에 인덱싱하고 AI가 자연어 답변을 생성한다.

> **대외비** — 고객 데이터 및 이슈 문서는 외부 서비스에 업로드하지 않는다.  
> 임베딩(FastEmbed ONNX)과 벡터 DB(pgvector)는 완전 로컬 실행이며, LLM은 사내 서버 PC에서 동작한다.

---

## 구현 현황

```mermaid
mindmap
  root((Issue Pipeline))
    RAG 파이프라인
      ✅ 문서 로딩
        MD / TXT / PDF
      ✅ 한국어 청킹
        섹션 경계 기반
      ✅ FastEmbed ONNX
        로컬 임베딩
      ✅ pgvector 저장
        PostgreSQL 17
      ✅ 코사인 유사도 검색
      ✅ 메타데이터 필터
        domain/severity/alarm_code
    LLM 백엔드
      ✅ Anthropic API
        true streaming
      ✅ Ollama 클라이언트
        폐쇄망 준비 완료
      ✅ Claude Agent SDK
      ✅ 멀티턴 히스토리
        complete_with_history
        stream_with_history
    챗봇
      ✅ 세션 관리
        PostgreSQL
      ✅ SSE 스트리밍
      ✅ 피드백 👍👎
      ✅ Query Reformulation
        이전 질문 합쳐 검색
      ✅ 채팅 UI
        Jinja2 + vanilla JS
      ✅ 미답변 질문 추적
        missed_queries 테이블
    QA 파이프라인
      ✅ Stage 1 이슈 구체화
      ✅ Stage 2 테스트 가능성
      ✅ Stage 3 MD 리포트
      ⬜ 미답변 문서 힌트
        LLM이 필요 문서 제안
      ⬜ QA 리포트 UI
        채팅 내 결과 표시
    운영
      ✅ 배터리 알람 수신
      ✅ 이슈 등록 웹폼
      ⬜ 문서 관리 UI
        등록/수정/삭제
      ⬜ 사용자 인증
        부서별 접근 제어
    배포
      ⬜ Ollama 사내 서버 연결
        Stage 3
      ⬜ 전사 배포
      ⬜ 외부 배포
        Stage 4
```

---

## 프로젝트 로드맵

```mermaid
flowchart LR
    S1["Stage 1\n데이터 구조 설계\n✅ 완료"]
    S2["Stage 2\n챗봇 개발\n✅ 완료"]
    S3["Stage 3\n전사 배포"]
    S4["Stage 4\n외부 배포"]

    S1 --> S2 --> S3 --> S4

    style S1 fill:#dcfce7,stroke:#16a34a,stroke-width:2px
    style S2 fill:#dcfce7,stroke:#16a34a,stroke-width:2px
    style S3 fill:#f8fafc,stroke:#94a3b8
    style S4 fill:#f8fafc,stroke:#94a3b8
```

| 단계 | 목표 | LLM | 배포 환경 | 상태 |
|------|------|-----|-----------|------|
| Stage 1 | 데이터 구조 설계·정합화 | Claude Agent SDK (개발용) | 로컬 개발 PC | ✅ 완료 |
| Stage 2 | 챗봇 개발 (세션·스트리밍·피드백·멀티턴) | Anthropic API | 로컬 개발 PC | ✅ 완료 |
| Stage 3 | 전사 배포 | Ollama (사내 서버 PC) | 사내 서버 PC | ⏳ 예정 |
| Stage 4 | 외부 배포 | Ollama (외부 서버 PC) | 외부 서버 PC | ⏳ 예정 |

---

## 시스템 아키텍처

```mermaid
flowchart TD
    subgraph Client["클라이언트"]
        UI["채팅 UI\n/chat"]
        REQ_RAG["RAG API\nPOST /api/v1/query"]
        REQ_QA["QA 파이프라인\nPOST /api/v1/qa/*"]
        REQ_ALARM["배터리 알람\nPOST /api/v1/alarm/ingest"]
    end

    subgraph API["FastAPI (src/api/)"]
        ROUTER_CHAT["chat_router.py\nSSE StreamingResponse"]
        ROUTER_QA["qa_router.py"]
        ROUTER_ALARM["alarm_router.py"]
        ROUTER_SUBMIT["submit_router.py"]
        ROUTER_MISSED["missed_queries_router.py"]
        DEPS["dependencies.py\nSingleton DI"]
    end

    subgraph Pipeline["IssuePipeline (src/pipeline.py)"]
        P_STREAM["stream_query(history)\nQuery Reformulation\n+ RAG 검색"]
        P_QUERY["query()"]
        P_QA["qa_elaborate/feasibility/report"]
    end

    subgraph RAG["RAG 파이프라인"]
        direction LR
        LOADER["DocumentLoader\nYAML 헤더 파싱"]
        CHUNKER["DocumentChunker\n한국어 섹션 경계"]
        EMB["FastEmbed\nONNX 로컬"]
        PGV["pgvector\nsimilarity_search"]
        GEN["IssueAnswerGenerator\ngenerate_stream_with_history"]
        LOADER --> CHUNKER --> EMB --> PGV --> GEN
    end

    subgraph LLM["LLM 백엔드 (src/llm/)"]
        BASE["LLMClient Protocol\ncomplete / stream\ncomplete_with_history\nstream_with_history"]
        ANT["anthropic_client\nAnthropic API"]
        OLL["ollama_client\nOllama 로컬"]
        CLA["claude_client\nAgent SDK"]
        BASE --> ANT & OLL & CLA
    end

    subgraph DB["PostgreSQL 17 + pgvector"]
        PG_VEC[("langchain_pg_embedding\n벡터 저장소")]
        PG_CHAT[("chat_sessions\nchat_messages")]
        PG_MISS[("missed_queries")]
    end

    subgraph QA["QA 파이프라인 (src/qa/)"]
        QA1["elaboration.py\nStage 1: 이슈 구체화"]
        QA2["feasibility.py\nStage 2: 테스트 가능성"]
        QA3["report_generator.py\nStage 3: MD 리포트"]
        QA1 --> QA2 --> QA3
    end

    UI --> ROUTER_CHAT
    REQ_RAG --> ROUTER_QA
    REQ_QA --> ROUTER_QA
    REQ_ALARM --> ROUTER_ALARM

    ROUTER_CHAT --> P_STREAM
    ROUTER_CHAT --> PG_CHAT
    ROUTER_CHAT --> PG_MISS
    ROUTER_QA --> P_QUERY & P_QA
    ROUTER_MISSED --> PG_MISS

    P_STREAM --> PGV
    P_QUERY --> PGV
    GEN --> BASE
    P_QA --> QA1
    QA1 & QA3 --> PGV
    EMB --> PG_VEC
    PGV --> PG_VEC
```

---

## 채팅 SSE 스트리밍 흐름

```mermaid
sequenceDiagram
    actor User as 사용자 (브라우저)
    participant Chat as chat_router.py
    participant Repo as ChatRepository
    participant Miss as MissedQueryLogger
    participant Pipe as IssuePipeline
    participant PGV as pgvector
    participant LLM as LLM 백엔드

    User->>Chat: POST /sessions/{id}/stream\n{ question, top_k }
    Chat->>Repo: get_recent_messages(limit=10)
    Repo-->>Chat: list[ChatTurn] 이전 대화 이력

    Chat->>Pipe: stream_query(question, history)
    Note over Pipe: Query Reformulation\n이전 질문 + 현재 질문 합쳐 검색

    Pipe->>PGV: similarity_search(reformulated_query)
    PGV-->>Pipe: RetrievalResults

    alt 검색 결과 없음
        Pipe-->>Chat: 빈 RetrievalResults
        Chat->>Miss: log(question, session_id)
    end

    Pipe->>LLM: stream_with_history(system, history, user_msg)
    loop SSE 스트리밍
        LLM-->>User: data: {"type":"text","text":"..."}
    end

    LLM-->>User: data: {"type":"done","message_id":"..."}

    Chat->>Repo: add_message(USER, question)
    Chat->>Repo: add_message(ASSISTANT, answer)
```

---

## PostgreSQL 스키마

```mermaid
erDiagram
    chat_sessions {
        TEXT id PK
        TEXT title
        TIMESTAMPTZ created_at
        TIMESTAMPTZ updated_at
    }
    chat_messages {
        TEXT id PK
        TEXT session_id FK
        TEXT role
        TEXT content
        JSONB context_doc_ids
        TEXT feedback
        TIMESTAMPTZ created_at
    }
    missed_queries {
        TEXT id PK
        TEXT question
        TEXT session_id
        TIMESTAMPTZ logged_at
        BOOLEAN resolved
    }
    langchain_pg_collection {
        UUID uuid PK
        TEXT name
        JSONB cmetadata
    }
    langchain_pg_embedding {
        UUID id PK
        UUID collection_id FK
        VECTOR embedding
        TEXT document
        JSONB cmetadata
    }

    chat_sessions ||--o{ chat_messages : "has"
    langchain_pg_collection ||--o{ langchain_pg_embedding : "contains"
```

---

## LLM 백엔드

```mermaid
flowchart LR
    ENV["LLM_BACKEND\n환경변수"]

    ENV -->|claude| CLA["ClaudeClient\nClaude Agent SDK\n개발 환경용"]
    ENV -->|anthropic| ANT["AnthropicClient\nAnthropic API\nANTHROPIC_API_KEY 필요"]
    ENV -->|ollama| OLL["OllamaClient\nOllama 로컬 LLM\nStage 3~4 사내 서버"]

    subgraph Protocol["LLMClient Protocol"]
        M1["complete(system, user) → str"]
        M2["stream(system, user) → AsyncIterator"]
        M3["complete_with_history(system, history, user) → str"]
        M4["stream_with_history(system, history, user) → AsyncIterator"]
    end

    CLA & ANT & OLL --> Protocol
```

| 값 | 백엔드 | 멀티턴 | 스트리밍 | 비고 |
|----|--------|--------|----------|------|
| `claude` (기본) | Claude Agent SDK | 텍스트 직렬화 | pseudo | Claude Code 환경 필요 |
| `anthropic` | Anthropic API | messages 배열 | true | `ANTHROPIC_API_KEY` 필수 |
| `ollama` | Ollama 로컬 LLM | messages 배열 | true | Stage 3~4, 사내 서버 PC |

---

## QA 파이프라인 (3단계)

```mermaid
flowchart LR
    IN["모호한 이슈 입력\n예: '배터리가 이상해요'"]

    subgraph S1["Stage 1 — 구체화"]
        E1["RAG 검색\n유사 이슈 수집"]
        E2["LLM 분석\n증상·원인·심각도 추정"]
        E1 --> E2
    end

    subgraph S2["Stage 2 — 테스트 가능성"]
        F1["validation_criteria.yaml\n알람 13종·단계 6종"]
        F2["LLM 판단\nfeasible / not_feasible\n/ needs_more_info"]
        F1 --> F2
    end

    subgraph S3["Stage 3 — 리포트"]
        R1["Markdown 리포트 생성\nQA_REPORT_*.md 저장"]
    end

    IN --> S1 --> S2 --> S3
    S3 --> OUT["data/qa_reports/\nQA_REPORT_*.md"]
```

---

## 미답변 질문 추적

RAG 검색 결과가 없어 답변하지 못한 질문은 자동으로 `missed_queries` 테이블에 기록된다.  
관리자가 어떤 문서를 추가해야 하는지 파악하는 데 사용한다.

```mermaid
flowchart LR
    Q["사용자 질문"] --> RAG["RAG 검색"]
    RAG -->|결과 있음| ANS["LLM 답변 생성"]
    RAG -->|결과 없음| LOG["missed_queries 기록\n질문 + session_id + 시각"]
    LOG --> NOTI["관리자 확인\nGET /api/v1/missed-queries"]
    NOTI --> ADD["관련 문서 추가\ndata/raw/"]
    ADD --> IDX["재인덱싱\nscripts/index_documents.py"]
    IDX --> RESOLVE["해결 처리\nPATCH .../resolve"]
```

---

## 데이터 수집 시스템 계획

```mermaid
flowchart LR
    subgraph Phase1["Phase 1 — 웹 폼 (현재)"]
        F1["부서 담당자\n브라우저 접속"]
        F2["도메인 선택\n배터리 / 소프트웨어"]
        F3["폼 작성\n증상·원인·조치"]
        F4["자동 생성\nYAML+MD 파일"]
        F5["자동 인덱싱\npgvector"]
        F1 --> F2 --> F3 --> F4 --> F5
    end

    subgraph Phase2["Phase 2 — LLM 파싱 (Ollama 구성 후)"]
        U1["기존 보고서 업로드\nWord / Excel / PDF"]
        U2["LLM 자동 파싱\n표준 템플릿 변환"]
        U3["담당자 검토\n수정 후 확인"]
        U4["인덱싱\npgvector"]
        U1 --> U2 --> U3 --> U4
    end

    Phase1 -.->|Ollama 구성 후 추가| Phase2
```

---

## 기술 스택

| 구분 | 기술 |
|------|------|
| Language | Python 3.11+ |
| Framework | FastAPI, LangChain |
| LLM | Claude Agent SDK / Anthropic API / Ollama |
| 임베딩 | FastEmbed `paraphrase-multilingual-mpnet-base-v2` (로컬 ONNX) |
| 벡터 DB | PostgreSQL 17 + pgvector 0.8.2 |
| 채팅·세션 DB | PostgreSQL 17 (asyncpg) |
| 미답변 추적 | PostgreSQL 17 (missed_queries 테이블) |
| 패키지 매니저 | uv |

---

## 프로젝트 구조

```
issue-pipeline/
├── src/
│   ├── pipeline.py              # 오케스트레이터 (query / stream_query + history / qa_*)
│   ├── config.py                # 환경변수 기반 설정 (postgres_url 포함)
│   ├── logger.py                # 구조화 로깅
│   ├── missed_queries.py        # 미답변 질문 PostgreSQL 추적기
│   ├── ingestion/
│   │   ├── document_loader.py   # YAML 헤더 파싱 + 문서 로딩
│   │   └── chunker.py           # 한국어 섹션 경계 청킹
│   ├── embedding/
│   │   └── embedder.py          # FastEmbed + pgvector 저장 (MD5 멱등성)
│   ├── retrieval/
│   │   └── retriever.py         # 코사인 유사도 검색 + 메타데이터 필터
│   ├── generation/
│   │   └── generator.py         # RAG 답변 (generate_stream / generate_stream_with_history)
│   ├── llm/
│   │   ├── base.py              # LLMClient Protocol (complete/stream/with_history)
│   │   ├── claude_client.py     # Claude Agent SDK
│   │   ├── anthropic_client.py  # Anthropic API (true streaming)
│   │   └── ollama_client.py     # Ollama 로컬 LLM (true streaming)
│   ├── qa/                      # QA 3단계 파이프라인
│   │   ├── elaboration.py       # Stage 1: RAG 기반 이슈 구체화
│   │   ├── feasibility.py       # Stage 2: 테스트 가능성 판단
│   │   ├── report_generator.py  # Stage 3: Markdown 리포트 생성
│   │   └── validation_criteria.py
│   ├── chat/
│   │   ├── models.py            # ChatSession / ChatMessage / FeedbackType
│   │   └── repository.py        # 비동기 PostgreSQL CRUD (asyncpg)
│   └── api/
│       ├── main.py              # 앱 진입점 + lifespan (PostgreSQL 풀 관리)
│       ├── dependencies.py      # Singleton DI
│       ├── chat_router.py       # /api/v1/chat/* + SSE 스트리밍 + 피드백
│       ├── missed_queries_router.py  # /api/v1/missed-queries
│       ├── qa_router.py         # /api/v1/qa/*
│       ├── alarm_router.py      # /api/v1/alarm/ingest
│       ├── submit_router.py     # GET /submit (웹 폼)
│       ├── static/
│       │   └── chat.js          # 채팅 UI (SSE 파싱 + 피드백 버튼)
│       └── templates/
│           ├── base.html
│           └── chat.html        # Jinja2 채팅 UI
├── data/
│   ├── raw/                     # 이슈 문서 34건 (BATTERY-* / BUG-* / INCIDENT-*)
│   └── qa_reports/              # QA 리포트 출력 (*.md)
├── docker-compose.yml           # PostgreSQL + pgvector (포트 5434, 백업용)
└── tests/                       # 335 passed
```

---

## 설치 및 실행

### 1. 의존성 설치

```bash
uv sync --extra dev
```

### 2. PostgreSQL + pgvector 설치 (macOS)

```bash
brew install postgresql@17 pgvector
brew services start postgresql@17

# DB 및 유저 생성
createdb -U $(whoami) issue_pipeline
psql -U $(whoami) -d postgres -c "CREATE USER pipeline WITH PASSWORD 'pipeline';"
psql -U $(whoami) -d issue_pipeline -c "GRANT ALL PRIVILEGES ON DATABASE issue_pipeline TO pipeline;"
psql -U $(whoami) -d issue_pipeline -c "ALTER SCHEMA public OWNER TO pipeline;"
psql -U $(whoami) -d issue_pipeline -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### 3. 환경변수 설정

```bash
cp .env.example .env
```

```bash
# LLM 백엔드 선택
LLM_BACKEND=anthropic          # claude | anthropic | ollama
ANTHROPIC_API_KEY=sk-ant-...

# PostgreSQL (기본값: localhost:5435)
POSTGRES_URL=postgresql://pipeline:pipeline@localhost:5435/issue_pipeline
```

### 4. 문서 인덱싱

```bash
# 신규 문서 추가
uv run python scripts/index_documents.py

# 기존 문서 수정 후 재인덱싱
uv run python scripts/index_documents.py --mode update
```

### 5. 서버 실행

```bash
uv run python scripts/start_server.py
# 채팅 UI → http://localhost:8000/chat
# API 문서 → http://localhost:8000/docs
```

---

## API 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/health` | 서버 상태 확인 |
| GET | `/chat` | 채팅 웹 UI |
| GET | `/submit` | 이슈 등록 웹 폼 |
| GET | `/api/v1/stats` | 인덱스 통계 |
| POST | `/api/v1/query` | RAG 질문 답변 |
| POST | `/api/v1/search` | 유사 문서 검색 (LLM 없음) |
| POST | `/api/v1/index` | 문서 인덱싱 트리거 |
| POST | `/api/v1/qa/elaborate` | QA Stage 1: 이슈 구체화 |
| POST | `/api/v1/qa/feasibility` | QA Stage 2: 테스트 가능성 판단 |
| POST | `/api/v1/qa/report` | QA Stage 3: 리포트 생성 |
| GET  | `/api/v1/qa/validation-criteria` | 검증 기준 조회 |
| POST | `/api/v1/alarm/ingest` | 배터리 알람 수신 및 처리 |
| POST | `/api/v1/chat/sessions` | 대화 세션 생성 |
| GET  | `/api/v1/chat/sessions` | 세션 목록 조회 |
| GET  | `/api/v1/chat/sessions/{id}` | 세션 조회 |
| DELETE | `/api/v1/chat/sessions/{id}` | 세션 삭제 |
| GET  | `/api/v1/chat/sessions/{id}/messages` | 메시지 목록 |
| POST | `/api/v1/chat/sessions/{id}/stream` | SSE 스트리밍 질문 (멀티턴) |
| PATCH | `/api/v1/chat/sessions/{id}/messages/{msg_id}/feedback` | 피드백 (👍/👎) |
| GET  | `/api/v1/missed-queries` | 미답변 질문 목록 |
| PATCH | `/api/v1/missed-queries/{id}/resolve` | 미답변 항목 해결 처리 |

---

## 벡터 메타데이터 스키마

| 필드 | 설명 | 예시 |
|------|------|------|
| `doc_id` | 이슈 문서 ID | `BATTERY-2024-001` |
| `domain` | 도메인 | `battery` / `software` / `incident` |
| `severity` | 심각도 | `critical` / `high` / `medium` / `low` |
| `status` | 상태 | `resolved` / `ongoing` |
| `alarm_code` | 배터리 알람 코드 | `OVP-001` |
| `section` | 청크 섹션 | `증상` / `원인` / `조치` / `재발방지` |
| `tags` | 태그 (쉼표 구분) | `overvoltage,cc-charge,sensor` |
| `file_hash` | MD5 해시 (멱등성) | `abc123...` |

---

## 이슈 문서 작성 가이드

표준 YAML 헤더 필수. 템플릿: [`docs/issue-template-battery.md`](docs/issue-template-battery.md), [`docs/issue-template-software.md`](docs/issue-template-software.md)

```yaml
---
id: BATTERY-2024-001
domain: battery             # battery | software | incident
severity: critical          # critical | high | medium | low
status: resolved            # resolved | ongoing | investigating
alarm_code: OVP-001
tags: [overvoltage, cc-charge]
created_at: 2024-08-12
resolved_at: 2024-08-13
---
```

파일명 규칙: `BATTERY-2024-001_brief_description.md`

---

## 장비 제어 아키텍처 (PC-to-PC 중앙 백엔드)

### 구성 요소 역할 및 기술 스택

| 구성 요소 | 역할 | 기술 스택 |
|---------|------|---------|
| **중앙 서버** | 제어 허브, AI 분석, 이력 저장, 운영자 UI | FastAPI, PostgreSQL+pgvector, RAG(Claude/Ollama), asyncpg |
| **장비 에이전트** | 중앙 서버 ↔ 장비 통신 중계, 로컬 안전 감시 | FastAPI(경량), httpx, pymodbus/pyserial/asyncua |
| **실제 장비** | 물리 동작 수행 | Modbus RTU/TCP, RS-485, OPC-UA, SCPI |

> 장비 에이전트는 AI 없는 순수 통신 프로그램. AI(RAG)는 중앙 서버에서만 동작.

---

### 에이전트 ↔ 장비 PC 프로토콜 정의

에이전트와 실제 장비 사이는 장비 제조사의 통신 규격을 따른다.  
**장비마다 레지스터 주소, 데이터 타입, 명령 코드가 다르므로 반드시 프로토콜 정의서가 필요하다.**

```
장비 에이전트
└── drivers/
    ├── base.py        # HardwareDriver 인터페이스 (공통)
    ├── modbus.py      # Modbus TCP/RTU 구현
    ├── opcua.py       # OPC-UA 구현
    └── mock.py        # 시뮬레이션 (테스트용)
```

**프로토콜 정의 예시 (Modbus 충방전기):**

| 레지스터 | 주소 | 타입 | 설명 | 단위 |
|---------|------|------|------|------|
| 온도 읽기 | 0x0001 | READ | 현재 온도 | °C × 10 |
| 전압 읽기 | 0x0002 | READ | 셀 전압 | mV |
| 전류 읽기 | 0x0003 | READ | 충방전 전류 | mA |
| 충전 시작 | 0x0100 | WRITE | CC-CV 충전 명령 | - |
| 방전 시작 | 0x0101 | WRITE | 정전류 방전 명령 | - |
| E-STOP | 0x0200 | WRITE | 긴급 정지 | - |
| 상태 | 0x0300 | READ | 장비 상태 코드 | - |

```python
# drivers/modbus.py 구현 예시
class ModbusDriver(HardwareDriver):
    async def read_sensors(self) -> SensorData:
        temperature = await self.client.read_register(0x0001) / 10
        voltage     = await self.client.read_register(0x0002) / 1000
        current     = await self.client.read_register(0x0003) / 1000
        return SensorData(temperature, voltage, current)

    async def execute_charge(self, params: dict) -> None:
        await self.client.write_register(0x0100, params.get("target_voltage", 4200))

    async def emergency_stop(self) -> None:
        await self.client.write_register(0x0200, 0x01)
```

---

### Flow 1 — 정상 제어 (시퀀스 실행)

```mermaid
sequenceDiagram
    actor 운영자
    participant SRV as 중앙 서버
    participant AGT as 장비 에이전트
    participant DRV as 드라이버 레이어
    participant HW as 실제 장비

    운영자->>SRV: 시퀀스 생성\nPOST /sequences
    SRV-->>운영자: sequence_id 반환

    운영자->>SRV: 실행 요청\nPOST /sequences/{id}/execute
    SRV->>AGT: POST /execute\n{command_id, command_type, params}
    AGT-->>SRV: {"status": "started"}

    AGT->>DRV: execute_charge(params)
    DRV->>HW: Modbus Write 0x0100\n충전 시작 명령
    HW-->>DRV: ACK

    loop 실행 중 (1초 간격)
        DRV->>HW: Modbus Read 0x0001~0x0003
        HW-->>DRV: 온도/전압/전류
        AGT->>SRV: POST /heartbeat\n{temperature, voltage, current}
        SRV-->>운영자: 대시보드 실시간 갱신
    end

    HW-->>DRV: 완료 상태 코드
    AGT->>SRV: POST /commands/{id}/result\n{status: "done"}
    SRV->>SRV: 다음 스텝 실행
```

---

### Flow 2 — 승인 후 실행 (사용자 확인)

```mermaid
sequenceDiagram
    actor 운영자
    participant SRV as 중앙 서버
    participant AGT as 장비 에이전트
    participant HW as 실제 장비

    운영자->>SRV: 시퀀스 생성
    SRV->>SRV: status = pending_approval
    SRV-->>운영자: 대시보드 승인 대기 표시

    운영자->>SRV: 승인\nPOST /sequences/{id}/approve
    SRV->>SRV: pending_approval → running

    SRV->>AGT: POST /execute
    AGT->>HW: 장비 제어 명령 (Modbus)
    HW-->>AGT: 실행 중

    Note over 운영자,HW: 이후 Flow 1과 동일
```

---

### Flow 3 — 이상 감지 → RAG 분석

```mermaid
sequenceDiagram
    participant HW as 실제 장비
    participant AGT as 장비 에이전트
    participant SRV as 중앙 서버
    participant RAG as RAG 파이프라인
    participant DB as PostgreSQL
    actor 운영자

    HW->>AGT: 센서값 (온도 47°C)
    AGT->>AGT: 로컬 임계값 체크\n45°C 초과 감지

    AGT->>HW: Modbus Write 0x0200\nE-STOP 즉시 차단
    AGT->>SRV: POST /anomaly\n{device_id, type: OVER_TEMP,\nvalue: 47.3, threshold: 45.0}

    SRV->>SRV: 관련 시퀀스 전체 중단

    SRV->>RAG: IssuePipeline.query()\n"CHG-A-01 충전 중 온도 47.3°C 초과"
    RAG->>DB: pgvector 유사 문서 검색\nBATTERY-* 이슈 문서
    DB-->>RAG: 유사 이슈 반환\n(과온도 사례)
    RAG-->>SRV: 원인 / 조치방법 / 유사 이력

    SRV->>DB: 이상 이슈 문서 자동 생성\nEQUIP-2026-001_OVER_TEMP.md
    SRV->>DB: 채팅 세션 자동 생성

    SRV-->>운영자: 대시보드 알림\n+ 챗봇 분석 결과 자동 표시
    운영자->>SRV: 조치 확인 후 reset
```

---

### 전체 구성도

```mermaid
graph TB
    subgraph 운영자["운영자 PC (브라우저)"]
        UI[대시보드 /equipment]
        CHAT[챗봇 /chat]
    end

    subgraph 중앙서버["중앙 서버"]
        API[FastAPI]
        ORC[오케스트레이터\n시퀀스 / 승인 / E-STOP]
        ANOMALY[이상 감지\n임계값 체크]
        RAG[RAG 파이프라인\nClaude / Ollama]
        PG[(PostgreSQL\n이력 / 벡터 / 세션)]
    end

    subgraph 장비PC1["장비 PC-1"]
        AGT1[에이전트\nFastAPI + httpx]
        DRV1[Modbus 드라이버\npymodbus]
        HW1[충방전기]
    end

    subgraph 장비PC2["장비 PC-2"]
        AGT2[에이전트]
        DRV2[RS-485 드라이버\npyserial]
        HW2[온도 챔버]
    end

    UI <-->|HTTP 폴링 2초| API
    CHAT <-->|SSE 스트리밍| API
    API --> ORC
    API --> ANOMALY
    ANOMALY -->|이상 발생| RAG
    RAG --> PG
    ORC --> PG
    ORC <-->|REST HTTP| AGT1
    ORC <-->|REST HTTP| AGT2
    AGT1 -->|하트비트 / 결과 콜백| ANOMALY
    AGT2 -->|하트비트 / 결과 콜백| ANOMALY
    AGT1 --- DRV1 --- HW1
    AGT2 --- DRV2 --- HW2
```

| 항목 | 방식 |
|------|------|
| 중앙 → 에이전트 | REST POST (명령 전달) |
| 에이전트 → 중앙 | REST POST (하트비트, 결과 콜백, 이상 보고) |
| 에이전트 → 장비 | Modbus / RS-485 / OPC-UA (장비별 프로토콜) |
| 이상 차단 | 에이전트 로컬에서 즉시 (중앙 서버 응답 대기 없음) |
| AI 분석 | 중앙 서버에서만 (에이전트에 AI 없음) |
| 재시도 | 타임아웃 시 최대 3회, 이후 ERROR 전환 |
| 오프라인 감지 | 하트비트 30초 무응답 → OFFLINE 상태 전환 |


## 테스트

```bash
# 전체 테스트
uv run pytest tests/ -v

# 커버리지 포함
uv run pytest tests/ --cov=src --cov-report=term-missing
```

현재 기준: **335 passed** (18개 테스트 파일)
