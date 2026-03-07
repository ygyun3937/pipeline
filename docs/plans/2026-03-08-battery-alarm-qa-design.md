# 배터리 검사 장비 QA 파이프라인 설계

**날짜**: 2026-03-08
**작성자**: Claude (brainstorming 세션)

---

## 개요

기존 소프트웨어 이슈 QA 파이프라인을 배터리 충방전 검사 장비에 적용한다.
장비에서 알람이 발생하면 자동으로 Stage 1~3 QA 파이프라인을 실행하여
원인 분석, 테스트 가능여부 판단, QA 리포트를 생성한다.

**핵심 요구사항:**
- 폐쇄망 / 인터넷 연결 환경 모두 지원 (LLM 백엔드 선택 가능)
- 알람 발생 즉시 자동 처리 (실시간 트리거)
- 장비 API / 시리얼 통신 지원

---

## 시스템 아키텍처

```
[배터리 충방전 장비]
   │  (시리얼 / 장비 내부 API)
   ▼
[alarm_adapter.py]          ← 신규: 폴링 어댑터 스크립트
   │  알람 감지 시 HTTP POST
   ▼
[FastAPI: POST /api/v1/alarm/ingest]  ← 신규 엔드포인트
   │
   ├─ Stage 1: IssueElaborator    (RAG + LLM)
   ├─ Stage 2: FeasibilityAssessor (LLM + YAML 기준)
   └─ Stage 3: QAReportGenerator  (LLM → Markdown 저장)

[RAG]
  ChromaDB ← 배터리 알람 이력 문서 인덱싱 (100~500건)

[LLM 추상 레이어]               ← 신규: 환경별 선택
  llm_backend=claude  → claude_agent_sdk (인터넷 연결)
  llm_backend=ollama  → Ollama 로컬 API (폐쇄망)
```

---

## LLM 백엔드 이중화

### 설정 (.env)

```env
# 인터넷 연결 환경
LLM_BACKEND=claude

# 폐쇄망 환경
LLM_BACKEND=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b
```

### 추상 레이어 구조

```
src/llm/
├── __init__.py
├── base.py          # LLMClient Protocol (공통 인터페이스)
├── claude_client.py # 기존 claude_agent_sdk 래핑
└── ollama_client.py # Ollama OpenAI 호환 API 클라이언트
```

- 기존 `elaboration.py`, `feasibility.py`, `report_generator.py`, `generator.py`는
  LLM 클라이언트를 생성자 주입으로 받아 사용 (코드 변경 최소화)
- `config.py`에 `llm_backend`, `ollama_base_url`, `ollama_model` 필드 추가

---

## 알람 데이터 흐름

### 장비 → 어댑터

`alarm_adapter.py`가 장비 API를 폴링하거나 시리얼 포트를 수신하여
다음 표준 페이로드로 변환:

```json
{
  "alarm_code": "OVP-001",
  "alarm_message": "과전압 보호 동작",
  "voltage": 4.35,
  "current": 2.1,
  "temperature": 45.2,
  "unit_id": "CH-03",
  "test_stage": "CC_CHARGE",
  "elapsed_seconds": 1823
}
```

### 파이프라인 처리

1. **Stage 1 — IssueElaborator**
   - 알람 페이로드를 자연어 이슈 설명으로 변환
   - ChromaDB에서 유사 과거 알람 이력 검색 (RAG)
   - LLM: 원인 가설, 재현 조건, 심각도(Critical/High/Medium/Low) 추정

2. **Stage 2 — FeasibilityAssessor**
   - `validation_criteria.yaml` 배터리 도메인 기준 적용
   - 테스트 가능여부(testable / not-testable / partially-testable) 판정
   - 권장 테스트케이스 목록 생성

3. **Stage 3 — QAReportGenerator**
   - Markdown 리포트 생성 → `data/qa_reports/` 저장
   - API 응답: 리포트 경로 + 요약 + Stage 1~2 결과

---

## 과거 알람 이력 문서 포맷

RAG 검색 기반이 되는 배터리 알람 이력 파일 스키마:

```markdown
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
...

## 조치 방법
...

## 재현 조건
...
```

---

## 신규 파일 목록

| 파일 | 설명 |
|------|------|
| `src/llm/__init__.py` | 패키지 init |
| `src/llm/base.py` | LLMClient Protocol |
| `src/llm/claude_client.py` | Claude 백엔드 |
| `src/llm/ollama_client.py` | Ollama 백엔드 |
| `src/api/alarm_models.py` | 알람 수신 Pydantic 모델 |
| `src/api/alarm_router.py` | `/api/v1/alarm/ingest` 엔드포인트 |
| `alarm_adapter.py` | 장비 어댑터 스크립트 (루트) |
| `data/raw/battery/` | 배터리 알람 이력 문서 저장 디렉토리 |
| `data/config/validation_criteria.yaml` | 배터리 도메인 기준으로 커스터마이징 |

---

## 수정 파일 목록

| 파일 | 변경 내용 |
|------|-----------|
| `src/config.py` | `llm_backend`, `ollama_base_url`, `ollama_model` 필드 추가 |
| `src/generation/generator.py` | LLMClient 주입받도록 리팩토링 |
| `src/qa/elaboration.py` | LLMClient 주입받도록 리팩토링 |
| `src/qa/feasibility.py` | LLMClient 주입받도록 리팩토링 |
| `src/qa/report_generator.py` | LLMClient 주입받도록 리팩토링 |
| `src/pipeline.py` | LLM 백엔드 선택 로직 추가 |
| `src/api/main.py` | `alarm_router` 등록 |
| `pyproject.toml` | `openai>=1.0` 의존성 추가 (Ollama 호환 클라이언트) |

---

## 에러 처리

| 상황 | 처리 방법 |
|------|-----------|
| 장비 연결 끊김 | exponential backoff 재연결 |
| 알람 중복 수신 | `alarm_code + timestamp` 기반 중복 제거 |
| 파이프라인 서버 다운 | 로컬 큐 버퍼링 후 재전송 |
| LLM 응답 실패 | 기존 tenacity 재시도 (백엔드 무관) |
| Ollama 서버 다운 | HTTP 503 반환 + 에러 로그 |
| RAG 결과 없음 | LLM 단독 분석으로 폴백 |
| Stage 3 실패 | Stage 1~2 결과는 API 응답으로 반환 (부분 성공) |

---

## 테스트 전략

| 구분 | 방법 |
|------|------|
| LLM 추상 레이어 | Claude/Ollama 모두 mock으로 단위 테스트 |
| 알람 어댑터 | mock 알람 JSON으로 장비 없이 로컬 테스트 |
| 전체 파이프라인 | 샘플 배터리 알람 이력 10건 인덱싱 후 E2E 테스트 |
| 폐쇄망 검증 | Ollama 설치 후 인터넷 차단 상태에서 동작 확인 |

---

## 권장 Ollama 모델 (폐쇄망)

| 모델 | 크기 | 한국어 품질 | 비고 |
|------|------|------------|------|
| `qwen2.5:7b` | 4.7GB | ★★★★☆ | 추천 |
| `qwen2.5:14b` | 9.0GB | ★★★★★ | 고성능 |
| `exaone3.5:7.8b` | 4.9GB | ★★★★★ | LG AI, 한국어 최적화 |
| `llama3.1:8b` | 4.9GB | ★★★☆☆ | 범용 |
