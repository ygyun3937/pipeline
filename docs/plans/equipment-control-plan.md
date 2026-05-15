# 장비 제어 시스템 계획서

**작성일:** 2026-05-15  
**버전:** 0.1 (1차 검토)

---

## 1. 개요

배터리 충방전 장비를 중앙 서버에서 통합 제어하고, 실시간 이상을 감지하여 AI가 자동 분석하는 시스템.

| 항목 | 내용 |
|------|------|
| 목적 | 다수의 장비 PC를 중앙 서버 1대로 원격 제어 |
| 핵심 가치 | 이상 감지 → AI(RAG) 자동 분석 → 즉각 대응 |
| 제어 방식 | 중앙 서버 REST → 에이전트 → Modbus TCP → 장비 |
| 승인 방식 | 실행 요청 후 작업자 승인 시 실제 동작 |

---

## 2. 시스템 구성

```
[ 대시보드 (웹 브라우저) ]
         │  HTTP / polling 2초
[ 중앙 서버 (FastAPI) ]          ← RAG 분석 엔진 탑재
         │  REST HTTP
[ 장비 에이전트 (각 PC에 1개) ]  ← C# / Python
         │  Modbus TCP (포트 502)
[ 물리 장비 (충방전기 등) ]
```

### 컴포넌트 역할

| 컴포넌트 | 언어 | 역할 |
|----------|------|------|
| 중앙 서버 | Python (FastAPI) | 장비 등록·관리, 시퀀스 오케스트레이션, 이상 감지, RAG 분석 |
| 장비 에이전트 | **C#** (ASP.NET Core) | 명령 수신 → Modbus TCP 변환, 하트비트 전송 |
| 대시보드 | HTML/JS (Jinja2) | 실시간 모니터링, 승인/거부, E-STOP |
| Mock 에이전트 | Python | 하드웨어 없이 테스트용 시뮬레이터 |

---

## 3. 구현된 기능 (2026-05-15)

### 3-1. 장비 제어 기반 (`66d7a82`)
- 장비 등록 / 목록 조회
- 시퀀스(다단계 명령) 생성 및 실행
- 명령 완료 폴링 — 각 단계 완료 후 다음 단계 진행
- 하트비트 수신 — 장비 상태 + 센서 데이터 갱신
- E-STOP — 전체 장비 즉시 정지

### 3-2. 대시보드 UI (`07f3718`)
- 2초 폴링 기반 실시간 갱신
- 장비 카드 (전압·온도·전류 센서)
- 시퀀스 진행 바
- E-STOP 버튼 (확인 팝업)
- 장비·시퀀스 등록 모달

### 3-3. C# 에이전트 (`a106728`)
- ASP.NET Core Minimal API (포트 8080)
- `IHardwareDriver` 인터페이스로 드라이버 추상화
- `MockDriver` — 소프트웨어 시뮬레이션
- `ModbusTcpDriver` — EasyModbusTCP 기반 실 장비 연결
- `HeartbeatBackgroundService` — 5초 주기 상태 전송

### 3-4. 사용자 승인 플로우 (`beb1cfa`)

```
[실행 버튼 클릭]
    │
    ▼
pending_approval  ← 작업자 확인 단계
    │        │
 [승인]    [거부]
    │        │
running   cancelled
    │
  done / error
```

- `POST /sequences/{id}/execute` → `pending_approval` 상태
- `POST /sequences/{id}/approve` → 실제 실행 시작
- `POST /sequences/{id}/reject` → `cancelled`
- 대시보드에 승인/거부 버튼 표시

### 3-5. 이상 감지 → RAG 자동 분석 (`beb1cfa`)

**임계값:**

| 항목 | Warning | Critical |
|------|---------|----------|
| 온도 | 45 °C | 55 °C |
| 전압 | 4.25 V | 4.35 V |
| 전류 | 3.0 A | 4.0 A |

**처리 흐름:**
1. 하트비트 수신 시 임계값 비교 (쿨다운: 10분/장비/메트릭)
2. 초과 시 `anomaly_logs` DB에 즉시 기록
3. RAG 분석을 백그라운드로 비동기 실행
4. 분석 완료 후 결과를 DB에 저장
5. 대시보드 하단 이상 감지 패널에 실시간 표시

---

## 4. 통신 프로토콜

> 상세 내용: `docs/protocol-spec.md` 참조

### 중앙 서버 ↔ 에이전트 (REST)

| 방향 | 엔드포인트 | 설명 |
|------|-----------|------|
| 서버 → 에이전트 | `POST /execute` | 명령 실행 |
| 서버 → 에이전트 | `POST /estop` | 비상 정지 |
| 에이전트 → 서버 | `POST /devices/{id}/heartbeat` | 상태+센서 전송 (5초) |
| 에이전트 → 서버 | `POST /commands/{id}/result` | 명령 완료 콜백 |

### 에이전트 ↔ 장비 (Modbus TCP)

| 레지스터 | 주소 | 설명 |
|---------|------|------|
| TEMP | 0x0001 | 온도 (×10, °C) |
| VOLT | 0x0002 | 전압 (×1000, V) |
| CURR | 0x0003 | 전류 (×1000, A) |
| CHARGE | 0x0100 | 충전 명령 |
| DISCHARGE | 0x0101 | 방전 명령 |
| ESTOP | 0x0200 | 비상 정지 |

---

## 5. 데이터베이스 테이블

```
devices          — 장비 등록 정보, 상태
sequences        — 다단계 명령 묶음
commands         — 개별 명령 (시퀀스 내 단계별)
command_logs     — 명령 이벤트 로그
device_states    — 최신 센서 데이터 (UPSERT)
anomaly_logs     — 이상 감지 이력 + RAG 분석 결과
```

---

## 6. 향후 개발 항목

### 단기 (즉시 가능)

| 항목 | 설명 |
|------|------|
| 실 Modbus 드라이버 검증 | 실제 장비 레지스터 맵으로 `ModbusTcpDriver.cs` 보정 |
| 이상 알림 | 대시보드 push 알림 or Slack Webhook 연동 |
| 시퀀스 템플릿 | 자주 쓰는 충방전 패턴 저장·불러오기 |

### 중기

| 항목 | 설명 |
|------|------|
| 다중 에이전트 확장 | 장비 PC 10대 이상 연결 시 스케일 확인 |
| 이상 이력 분석 | 누적 anomaly_logs 기반 트렌드 리포트 |
| 자동 재시도 정책 | Critical 이상 시 시퀀스 자동 일시정지 |
| 승인 권한 관리 | 사용자 역할별 승인 권한 구분 |

### 장기

| 항목 | 설명 |
|------|------|
| 예측 분석 | 과거 이상 패턴으로 사전 경고 |
| 자동 보고서 | 1일 1회 장비 상태 + 이상 이력 PDF |

---

## 7. 테스트 방법

```bash
# 1. 중앙 서버
uv run python scripts/start_server.py --reload

# 2. Mock 에이전트 (정상)
uv run python -m src.agent.main

# 3. Mock 에이전트 (이상 시뮬레이션 — 충전 중 온도 50°C 상승)
SIMULATE_ANOMALY=true AGENT_DEVICE_ID=MOCK-02 AGENT_PORT=8082 \
  uv run python -m src.agent.main

# 4. 데모 스크립트 (장비 등록, 시퀀스 생성, 승인 플로우, 이상 감지)
uv run python scripts/demo_equipment.py
```

대시보드: http://localhost:8000/equipment

---

## 8. 파일 구성

```
issue-pipeline/
├── src/
│   ├── equipment/
│   │   ├── models.py        # 데이터 모델 (Device, Sequence, AnomalyLog 등)
│   │   ├── repository.py    # DB CRUD (asyncpg)
│   │   ├── orchestrator.py  # 시퀀스 실행, 이상 감지, RAG 분석
│   │   └── router.py        # REST 엔드포인트
│   ├── agent/
│   │   └── main.py          # Python Mock 에이전트
│   └── api/
│       └── templates/
│           └── equipment.html  # 대시보드
├── agent-csharp/               # C# 실 장비 에이전트
│   ├── Drivers/
│   │   ├── IHardwareDriver.cs
│   │   ├── ModbusTcpDriver.cs  # 실 Modbus 드라이버
│   │   └── MockDriver.cs
│   └── Services/
│       ├── HeartbeatBackgroundService.cs
│       └── CentralServerClient.cs
├── docs/
│   ├── protocol-spec.md        # 통신 프로토콜 상세 명세
│   └── plans/
│       └── equipment-control-plan.md  # 이 문서
└── scripts/
    └── demo_equipment.py       # E2E 데모
```
