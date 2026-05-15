# AI 기반 배터리 장비 관리 시스템 통합 계획서

**작성일:** 2026-05-15  
**버전:** 1.1 (스케줄 위임 방식 + 이상 감지 QA 리포트 반영)  
**목적:** 개발 진행 현황 공유 및 향후 방향 정의

---

## 1. 시스템 목표

> 배터리 충방전 검사 장비를 원격 제어하고, 이상 발생 시 AI가 자동으로 원인을 분석하여  
> 운영자가 빠르게 판단·조치할 수 있는 통합 관리 시스템 구축

**핵심 설계 원칙:**
- 중앙 서버는 **스케줄 전달 + 모니터링** 역할 (장비 실행에 개입하지 않음)
- 장비 PC는 수신한 스케줄을 **자율 실행** (네트워크 단절 시에도 지속)
- 이상 감지 시 AI가 **QA 리포트를 자동 생성**하고 챗봇에서 추가 질문 가능

```
장비 → 이상 감지 → AI QA 리포트 자동 생성 → 운영자 챗봇 조회 → 재실행 승인
                            ↑
               과거 알람 이력(RAG) + QA 3단계 파이프라인
```

---

## 2. 전체 시스템 구성

```
┌──────────────────────────────────────────────────────────────┐
│                     웹 대시보드 / 챗봇 UI                      │
│     장비 제어 대시보드             대화형 AI 챗봇               │
└──────────┬──────────────────────────────┬────────────────────┘
           │                              │
┌──────────▼──────────────────────────────▼────────────────────┐
│                     중앙 서버 (FastAPI)                        │
│                                                               │
│  ┌───────────────────────┐   ┌─────────────────────────────┐ │
│  │   장비 제어 모듈        │   │      AI 파이프라인            │ │
│  │  - 스케줄 파일 생성     │◄─►│  - RAG 검색 (ChromaDB)      │ │
│  │  - 승인 플로우          │   │  - QA 3단계 (이상→리포트)    │ │
│  │  - 하트비트 모니터링    │   │  - 챗봇 대화 세션            │ │
│  │  - 이상 감지 → QA 연동 │   └─────────────────────────────┘ │
│  └───────────┬───────────┘             ▲                      │
│              │  스케줄 JSON 전달        │  이슈/알람 이력       │
└──────────────┼──────────────────────────┼─────────────────────┘
               │  REST HTTP               │  Markdown 문서
┌──────────────▼────────────┐  ┌──────────┴──────────────────┐
│  장비 에이전트 (C#)        │  │  이슈 이력 DB                │
│  - 스케줄 수신 + 중계      │  │  (BUG-*, ALARM-*, BATTERY-*)│
│  - 하트비트 5초 전송       │  └─────────────────────────────┘
│  - 이상 감지 1차 체크      │
└──────────────┬────────────┘
               │  스케줄 JSON + 시작신호
               │  (Modbus TCP / 장비 프로토콜)
┌──────────────▼────────────┐
│  장비 PC (충방전기 등)     │
│  - 스케줄 자율 실행        │
│  - 스텝 완료 보고 (옵션)   │
│  - 전체 완료 보고          │
└───────────────────────────┘
```

---

## 3. 개발 진행 단계

### Phase 1 — 지식 기반 구축 ✅ 완료

**목표:** 과거 이슈/알람 이력을 AI가 검색할 수 있는 지식 베이스 구축

| 기능 | 구현 내용 |
|------|-----------|
| 문서 인덱싱 | BUG-*, INCIDENT-*, BATTERY-* Markdown → ChromaDB |
| RAG 검색 | 코사인 유사도 기반 관련 청크 추출 |
| AI 답변 생성 | Claude + 검색 컨텍스트 → 증상/원인/조치 4섹션 답변 |
| LLM 백엔드 이중화 | `LLM_BACKEND=claude` (인터넷) / `ollama` (폐쇄망) |

**핵심 API**
- `POST /api/v1/index` — 문서 인덱싱
- `POST /api/v1/query` — RAG 질문 답변
- `POST /api/v1/search` — 유사 문서 검색만

---

### Phase 2 — 배터리 알람 자동 QA ✅ 완료

**목표:** 장비 알람 발생 시 AI가 자동으로 QA 리포트 생성

| 기능 | 구현 내용 |
|------|-----------|
| 알람 수신 API | `POST /api/v1/alarm/ingest` |
| Stage 1 — 구체화 | 알람 페이로드 → RAG 기반 이슈 상세화, 심각도 추정 |
| Stage 2 — 테스트 가능성 | `validation_criteria.yaml` 기준 판정 |
| Stage 3 — 리포트 | `data/qa_reports/QA_BATTERY_*.md` 자동 저장 |
| 알람 어댑터 | `alarm_adapter.py` — 장비 API 폴링 / 시리얼 수신 |

```
장비 알람 → alarm_adapter.py → POST /alarm/ingest
                                      │
                            Stage 1: 이슈 구체화 (RAG)
                            Stage 2: 테스트 가능성 판정
                            Stage 3: QA 리포트 자동 저장 (MD 파일)
```

**심각도별 처리 기준 (validation_criteria.yaml)**

| 심각도 | 자동화 필수 | 처리 방법 |
|--------|------------|----------|
| Critical | ✓ | 즉각 알림 + QA 리포트 자동 생성 |
| High | - | QA 리포트 자동 생성 |
| Medium | - | QA 리포트 자동 생성 |
| Low | - | 로그만 |

---

### Phase 3 — 대화형 챗봇 ✅ 완료

**목표:** 운영자가 자연어로 이슈를 질문하고 AI가 답변

| 기능 | 구현 내용 |
|------|-----------|
| 채팅 세션 관리 | PostgreSQL 기반 대화 이력 저장 |
| 컨텍스트 유지 | 이전 대화 내용을 AI에 전달 |
| 미답변 질문 추적 | RAG 검색 결과 없는 질문 자동 기록 |
| 이슈 제출 | 사용자가 직접 이슈 내용 제보 |
| 웹 UI | `/chat` 대화 인터페이스 |

---

### Phase 4 — 장비 원격 제어 기반 ✅ 완료 (2026-05-15)

> **현재 구현(v1)**은 중앙 서버가 스텝별로 에이전트에 명령을 주는 방식.  
> **Phase 5**에서 스케줄 위임 방식으로 전환한다.

#### 4-1. 현재 구현 (스텝 단위 방식)

```
중앙 서버: 스텝1 전송 → 완료 대기 → 스텝2 전송 → 완료 대기 → ...
에이전트:  명령 수신 → 실행 → 결과 보고 (스텝마다 반복)
```

| 기능 | 구현 내용 |
|------|-----------|
| 장비 등록/관리 | IP·포트·유형 등록, 상태 관리 |
| 시퀀스 오케스트레이션 | 중앙 서버가 스텝 순서 제어 |
| 하트비트 | 에이전트가 5초마다 상태·센서 데이터 전송 |
| 이상 감지 | 임계값 초과 시 DB 기록 + RAG 분석 |
| E-STOP | 전체 장비 즉시 비상 정지 |

#### 4-2. 사용자 승인 플로우

```
운영자 [실행 버튼]
        │
        ▼
  pending_approval  ← 승인 대기 (대시보드에 표시)
      │       │
   [승인]   [거부]
      │       │
  running  cancelled
      │
   done / error
```

#### 4-3. 장비 에이전트 (C#)

| 구성 | 설명 |
|------|------|
| `IHardwareDriver` | 하드웨어 추상 인터페이스 |
| `MockDriver` | 하드웨어 없이 소프트웨어 시뮬레이션 |
| `ModbusTcpDriver` | EasyModbusTCP 기반 실 장비 연결 |
| `HeartbeatBackgroundService` | 5초 주기 상태 전송 |

---

### Phase 5 — 스케줄 위임 + 이상 감지 QA 연동 🔲 예정

**목표:** 장비 PC가 스케줄을 자율 실행하고, 이상 발생 시 AI가 QA 리포트를 자동 생성

#### 5-1. 스케줄 위임 방식 (핵심 아키텍처 전환)

```
[기존]  중앙 서버 → 스텝1 전송 → 완료 확인 → 스텝2 전송 → ...

[목표]  중앙 서버 → 스케줄 JSON 생성 → 에이전트에 전달 (1회)
        에이전트 → 스케줄 + 시작신호 → 장비 PC 전달
        장비 PC  → 스케줄 전체 자율 실행
        중앙 서버 → 하트비트 모니터링만 (실행에 개입하지 않음)
```

**장점:**
- 네트워크 단절 시에도 장비가 스케줄 계속 실행
- 중앙 서버 부하 감소 (폴링 불필요)
- 산업 현장 실제 운영 방식에 부합

#### 5-2. 스케줄 파일 형식 (JSON)

```json
{
  "schedule_id": "SCH-2026-001",
  "name": "CC 충전 테스트 스케줄",
  "version": "1.0",
  "created_at": "2026-05-15T10:00:00Z",
  "device_id": "CHG-A-01",
  "steps": [
    {
      "step_no": 1,
      "command": "charge",
      "params": {
        "mode": "CC",
        "current_a": 1.0,
        "cutoff_voltage_v": 4.2,
        "timeout_sec": 3600
      },
      "report_on_complete": true
    },
    {
      "step_no": 2,
      "command": "rest",
      "params": {
        "duration_sec": 300
      },
      "report_on_complete": false
    },
    {
      "step_no": 3,
      "command": "discharge",
      "params": {
        "mode": "CC",
        "current_a": 1.0,
        "cutoff_voltage_v": 2.8,
        "timeout_sec": 3600
      },
      "report_on_complete": true
    },
    {
      "step_no": 4,
      "command": "measure",
      "params": {},
      "report_on_complete": true
    }
  ],
  "completion_report": true
}
```

**`report_on_complete` 필드:**
- `true` → 해당 스텝 완료 시 중앙 서버에 진행 상황 보고 (선택)
- `false` → 보고 생략, 전체 완료 시에만 보고
- `completion_report` → 전체 스케줄 완료 시 최종 보고 (항상 true 권장)

#### 5-3. 스케줄 실행 API 변경

| 구분 | 현재 (v1) | 목표 (v2) |
|------|-----------|-----------|
| 실행 방식 | 스텝별 `POST /execute` 반복 | `POST /start-schedule` (JSON 1회 전달) |
| 완료 감지 | 중앙 서버 DB 폴링 | 장비 PC 완료 콜백 |
| 스텝 진행 보고 | 매 스텝 콜백 필수 | `report_on_complete` 옵션 |
| 네트워크 단절 대응 | 시퀀스 중단 | 장비 PC 독립 실행 지속 |

**에이전트 신규 엔드포인트:**
```
POST /start-schedule   { schedule: {...}, device_id: "CHG-A-01" }
POST /stop-schedule    { schedule_id: "SCH-2026-001" }
GET  /schedule-status  → { step_no, status, progress_pct }
```

**중앙 서버 콜백 수신:**
```
POST /api/v1/equipment/schedules/{id}/step-report   (옵션)
POST /api/v1/equipment/schedules/{id}/complete       (완료 시)
```

#### 5-4. 이상 감지 → QA 리포트 자동 생성 (Phase 2 연계)

```
하트비트 수신 (5초)
      │
      ▼
  임계값 초과? ──No──→ 정상
      │ Yes
      ▼
anomaly_logs 기록
      │
      ▼ (백그라운드 — Phase 2 QA 파이프라인 활용)
  Stage 1: 이상 데이터 → 자연어 이슈 설명 변환
           "장비 CHG-A-01, CC충전 중 온도 52.5°C 감지 (임계값 45°C)"
  Stage 2: 테스트 가능성 판정 (validation_criteria.yaml)
  Stage 3: QA 리포트 자동 저장
           data/qa_reports/QA_ANOMALY_{device_id}_{timestamp}.md
      │
      ▼
  anomaly_logs.report_path 업데이트
  대시보드 이상 감지 패널: 리포트 링크 + 요약 표시
  챗봇 세션 자동 생성: 운영자가 추가 질문 가능
```

**이상 → QA 리포트 연계 포인트:**

| 항목 | 내용 |
|------|------|
| 입력 | 장치 ID, 이상 메트릭, 측정값, 임계값, 심각도, 현재 스케줄 정보 |
| RAG 검색 | 과거 동일/유사 알람 이력 문서 (ALARM-*, BATTERY-*) |
| 리포트 내용 | 이상 개요, 예상 원인 (RAG 기반), 즉각 조치, 권장 테스트케이스 |
| 저장 위치 | `data/qa_reports/QA_ANOMALY_*.md` |
| 연동 | 챗봇 세션 자동 생성 → 운영자 추가 질문 가능 |

---

## 4. 3가지 핵심 동작 플로우 (목표 구조 기준)

### 플로우 A — 정상 제어 흐름 (스케줄 위임)

```
1. 운영자: 스케줄 JSON 작성 (충전→휴지→방전→측정)
2. 중앙 서버: 승인 요청 → pending_approval
3. 관리자: [승인]
4. 중앙 서버: 에이전트에 스케줄 JSON + 시작신호 전송 (1회)
5. 에이전트: 스케줄 → 장비 PC에 중계
6. 장비 PC: 스케줄 자율 실행
           ├─ (옵션) 스텝별 진행 보고
           └─ 완료 시 최종 콜백
7. 중앙 서버: 완료 수신 → 시퀀스 DONE 처리
```

### 플로우 B — 이상 감지 흐름 (QA 리포트 자동 생성)

```
1. 장비 PC 실행 중 → 에이전트 하트비트 (5초)
2. 중앙 서버: 임계값 초과 감지
3. anomaly_logs 기록
4. (백그라운드) QA 3단계 파이프라인 실행
   - Stage 1: 이상 데이터 구체화 (RAG: 과거 유사 알람 검색)
   - Stage 2: 테스트 가능성 판정
   - Stage 3: QA 리포트 MD 파일 자동 저장
5. 대시보드: 이상 감지 패널에 리포트 링크 표시
6. 챗봇 세션 자동 생성: "CHG-A-01 온도 이상 분석 결과입니다..."
7. 운영자: 챗봇에서 추가 질문 → E-STOP 또는 스케줄 재실행 결정
```

### 플로우 C — 운영자 챗봇 질문

```
운영자: "지난주 OVP-001 알람 원인이 뭐야?"
  → RAG 검색: ALARM-*, BATTERY-*, QA_ANOMALY_* 이력 문서
  → AI 답변: 과거 유사 사례 기반 원인 분석 + 조치 방법
  → 대화 이력 저장 (재조회 가능)

운영자: "이번 CHG-A-01 이상 리포트 요약해줘"
  → 자동 생성된 QA_ANOMALY_*.md 검색
  → AI 요약 + 권장 조치 답변
```

---

## 5. 기술 스택

| 레이어 | 기술 | 용도 |
|--------|------|------|
| AI/LLM | Claude Sonnet 4.6 | 답변 생성, 이상 분석, QA 리포트 |
| AI/LLM (폐쇄망) | Ollama + qwen2.5 | 인터넷 차단 환경 |
| 벡터 DB | ChromaDB | 이슈/알람/이상 이력 임베딩 저장 |
| 임베딩 | FastEmbed (paraphrase-multilingual) | 다국어 문서 임베딩 |
| API 서버 | FastAPI (Python 3.11) | 중앙 서버 |
| DB | PostgreSQL + asyncpg | 장비/시퀀스/채팅/이상 데이터 |
| 장비 에이전트 | C# ASP.NET Core | 장비 PC 실행 (스케줄 중계) |
| 산업 통신 | Modbus TCP (EasyModbusTCP) | 장비 제어 프로토콜 |
| 프론트엔드 | Jinja2 + Vanilla JS | 대시보드/챗봇 UI |

---

## 6. 구현 현황 요약

| Phase | 내용 | 상태 |
|-------|------|------|
| 1 | RAG 파이프라인, 문서 인덱싱, AI 답변 | ✅ 완료 |
| 2 | 배터리 알람 자동 QA (3단계), 알람 어댑터 | ✅ 완료 |
| 3 | 대화형 챗봇, 미답변 추적, 이슈 제출 | ✅ 완료 |
| 4 | 장비 원격 제어 기반, 승인 플로우, 이상 감지 (스텝 단위 v1) | ✅ 완료 |
| 5-A | 스케줄 위임 방식으로 전환 (에이전트 + 장비 PC 자율 실행) | 🔲 예정 |
| 5-B | 이상 감지 → QA 3단계 → 리포트 파일 생성 | 🔲 예정 |
| 5-C | QA 리포트 → 챗봇 세션 자동 연결 | 🔲 예정 |

---

## 7. Phase 5 개발 항목

### 우선순위 A — 스케줄 위임 전환

| 항목 | 대상 파일 | 내용 |
|------|-----------|------|
| 스케줄 JSON 모델 | `src/equipment/models.py` | `ScheduleFile`, `ScheduleStep` 모델 추가 |
| 에이전트 API 변경 | `agent-csharp/Program.cs` | `POST /start-schedule` 구현 |
| 중앙 서버 라우터 | `src/equipment/router.py` | 스케줄 전달 + 완료 콜백 수신 |
| 오케스트레이터 | `src/equipment/orchestrator.py` | 스텝 폴링 → 콜백 대기 방식으로 변경 |

### 우선순위 B — 이상 감지 QA 리포트 연동

| 항목 | 대상 파일 | 내용 |
|------|-----------|------|
| QA 파이프라인 연결 | `src/equipment/orchestrator.py` | `_run_rag_analysis` → Phase 2 QA 3단계로 교체 |
| 리포트 경로 저장 | `src/equipment/repository.py` | `anomaly_logs.report_path` 컬럼 추가 |
| 대시보드 연동 | `src/api/templates/equipment.html` | 이상 감지 패널에 리포트 링크 추가 |

### 우선순위 C — 챗봇 자동 연결

| 항목 | 내용 |
|------|------|
| 이상 감지 시 챗봇 세션 자동 생성 | anomaly 발생 → `ChatRepository`에 새 세션 + 초기 메시지 |
| 대시보드 → 챗봇 바로가기 | 이상 감지 패널 "챗봇에서 분석보기" 링크 |
| 리포트 문서 자동 인덱싱 | QA_ANOMALY_*.md 생성 시 ChromaDB에 자동 인덱싱 |

### 중기

| 항목 | 내용 |
|------|------|
| 실 Modbus 드라이버 검증 | 실제 장비 레지스터 맵 확인 후 `ModbusTcpDriver.cs` 보정 |
| 다중 장비 스케일 테스트 | 장비 5대 이상 동시 스케줄 실행 검증 |
| 이상 이력 트렌드 분석 | anomaly_logs 누적 데이터 기반 주간 리포트 |
| 승인 권한 관리 | 역할별(운영자/관리자) 승인 권한 구분 |

---

## 8. 테스트 환경 구성

```bash
# 1. 중앙 서버
uv run python scripts/start_server.py --reload

# 2. Mock 에이전트 (정상)
uv run python -m src.agent.main

# 3. Mock 에이전트 (이상 시뮬레이션 — 충전 중 온도 50°C 상승)
SIMULATE_ANOMALY=true AGENT_DEVICE_ID=MOCK-02 AGENT_PORT=8082 \
  uv run python -m src.agent.main

# 4. E2E 데모 (승인 플로우 + 이상 감지)
uv run python scripts/demo_equipment.py

# 접속
# 대시보드:  http://localhost:8000/equipment
# 챗봇:      http://localhost:8000/chat
# API 문서:  http://localhost:8000/docs
```

---

## 9. 관련 문서

| 문서 | 위치 | 내용 |
|------|------|------|
| 통신 프로토콜 명세 | `docs/protocol-spec.md` | REST API + Modbus 레지스터 맵 전체 |
| 장비 제어 계획 | `docs/plans/equipment-control-plan.md` | 장비 제어 단독 상세 (Phase 4) |
| 배터리 QA 설계 | `docs/plans/2026-03-08-battery-alarm-qa-design.md` | Phase 2 설계 상세 |
| C# 에이전트 가이드 | `agent-csharp/README.md` | 빌드·배포·환경변수 |
