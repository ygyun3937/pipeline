# Issue Pipeline - Project Context

사내 버그/이슈 문서를 RAG(Retrieval-Augmented Generation)로 처리하는 지식 파이프라인.
버그 리포트, 장애 보고서, 배터리 도메인 이슈를 벡터 DB에 인덱싱하고 Claude AI가 자연어 답변을 생성한다.

---

## 아키텍처

```
이슈 문서 (MD/PDF/TXT)
        │
  [1. Ingestion]    DocumentLoader + DocumentChunker
        │            Markdown 섹션(##/###) 경계 기반 청킹
  [2. Embedding]   FastEmbed (ONNX, 다국어, API 키 불필요)
        │            → ChromaDB 로컬 영구 저장
  [3. Retrieval]   코사인 유사도 검색 (IssueRetriever)
        │
  [4. Generation]  Claude (claude-sonnet-4-6) RAG 답변
        │
   FastAPI 응답
```

---

## 프로젝트 구조

```
issue-pipeline/
├── src/
│   ├── pipeline.py          # 핵심 오케스트레이터 (IssuePipeline)
│   ├── config.py            # 환경변수 기반 설정 (Settings)
│   ├── logger.py            # 구조화 로깅
│   ├── ingestion/           # DocumentLoader, DocumentChunker
│   ├── embedding/           # IssueEmbedder → ChromaDB
│   ├── retrieval/           # IssueRetriever (cosine similarity)
│   ├── generation/          # IssueAnswerGenerator (Claude)
│   ├── llm/                 # LLM 백엔드 추상화 (Claude SDK / Anthropic API / Ollama)
│   ├── api/                 # FastAPI (main.py, alarm_router.py, qa_router.py)
│   └── qa/                  # QA 3단계 파이프라인
│       ├── elaboration.py   # Stage 1: 이슈 구체화
│       ├── feasibility.py   # Stage 2: 테스트 가능성 판단
│       └── report_generator.py  # Stage 3: Markdown 리포트 생성
├── data/
│   ├── raw/                 # 원본 이슈 문서 (BUG-*, BATTERY-*, INCIDENT-*)
│   ├── chroma_db/           # ChromaDB 벡터 저장소 (자동 생성)
│   ├── qa_reports/          # QA 리포트 Markdown 출력
│   └── config/
│       └── validation_criteria.yaml  # QA 검증 기준
├── scripts/
│   ├── index_documents.py   # 문서 인덱싱 CLI
│   ├── start_server.py      # FastAPI 서버 시작
│   └── query_cli.py         # 쿼리 테스트 CLI
└── tests/
```

---

## LLM 백엔드

`LLM_BACKEND` 환경변수로 선택:

| 값 | 백엔드 | 비고 |
|----|--------|------|
| `claude` (기본) | Claude Agent SDK | CLAUDECODE 환경 필요 |
| `anthropic` | Anthropic API | `ANTHROPIC_API_KEY` 필수 |
| `ollama` | Ollama 로컬 LLM | `OLLAMA_BASE_URL` 설정 |

---

## QA 파이프라인 (3단계)

모호한 이슈를 구조화된 QA 리포트로 변환:

1. **Stage 1 - 구체화** (`qa_elaborate`): RAG 기반 이슈 상세화, 심각도 추정
2. **Stage 2 - 테스트 가능성** (`qa_assess_feasibility`): `validation_criteria.yaml` 대비 판단
3. **Stage 3 - 리포트** (`qa_generate_report`): `data/qa_reports/QA_REPORT_*.md` 저장

---

## 자주 쓰는 명령어

```bash
# 의존성 설치
uv sync --extra dev

# 문서 인덱싱
uv run python scripts/index_documents.py

# API 서버 시작 (개발 모드)
uv run python scripts/start_server.py --reload

# CLI 쿼리 테스트
uv run python scripts/query_cli.py "로그인 500 에러 원인은?"

# 전체 테스트
uv run pytest tests/ -v

# 커버리지 포함
uv run pytest tests/ --cov=src --cov-report=term-missing
```

---

## API 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/api/v1/query` | RAG 질문 답변 |
| POST | `/api/v1/search` | LLM 없이 유사 문서 검색만 |
| POST | `/api/v1/index` | 문서 인덱싱 트리거 |
| GET  | `/api/v1/stats` | 인덱스 통계 |
| POST | `/api/v1/qa/elaborate` | QA Stage 1: 이슈 구체화 |
| POST | `/api/v1/qa/feasibility` | QA Stage 2: 테스트 가능성 판단 |
| POST | `/api/v1/qa/report` | QA Stage 3: 리포트 생성 |
| GET  | `/api/v1/qa/validation-criteria` | 검증 기준 조회 |
| POST | `/api/v1/alarm/ingest` | 배터리 알람 수신 및 처리 |

---

## 데이터 도메인

두 가지 도메인의 이슈를 동일 파이프라인으로 처리:

- **소프트웨어**: `BUG-YYYY-NNN_*.md`, `INCIDENT-YYYY-NNN_*.md`
- **배터리/충방전**: `BATTERY-YYYY-NNN_*.md` (과전압, 과전류, 온도 이상, 셀 밸런스 등)

권장 파일명 형식: `BUG-2024-001_brief_description.md`

---

## 개발 컨벤션

- **Python 3.11+**, 패키지 관리: `uv`
- **타입 힌트** 필수 (`from __future__ import annotations`)
- **비동기**: API 엔드포인트와 LLM 호출은 `async/await`
- **재시도**: LLM/임베딩 API 호출에 `tenacity` 지수 백오프 적용
- **멱등성**: 동일 파일 재인덱싱 시 MD5 해시로 중복 방지
- **린터**: `ruff` (line-length=100), **타입 체커**: `mypy`
- **테스트**: `pytest` + `pytest-asyncio`, `asyncio_mode = "auto"`

---

## 환경변수 핵심 목록

```bash
ANTHROPIC_API_KEY=        # Anthropic API 키 (anthropic 백엔드 시 필수)
LLM_BACKEND=claude        # claude | anthropic | ollama
ANTHROPIC_MODEL=claude-sonnet-4-6
EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-mpnet-base-v2
CHROMA_PERSIST_DIR=./data/chroma_db
RETRIEVAL_TOP_K=5
RETRIEVAL_SCORE_THRESHOLD=0.4
```

전체 목록은 `.env.example` 참조.

---

## 커스텀 에이전트

배터리/충방전 도메인 전문 작업에는 `battery-equipment-engineer` 에이전트를 사용한다:

```
Task(subagent_type="battery-equipment-engineer", prompt="...")
```

또는 스킬로 호출:

```
/battery-equipment-engineer <작업 내용>
```
