# Issue Pipeline

사내 버그/이슈 문서를 RAG(Retrieval-Augmented Generation)로 처리하는 지식 파이프라인입니다.

버그 리포트, 이슈 문서, 장애 보고서를 벡터 DB에 인덱싱하고, 자연어 질문으로 관련 이슈를 검색하여 Claude AI가 답변을 생성합니다.

## 아키텍처

```
이슈 문서 (PDF/MD/TXT)
        |
        v
 [1. Ingestion]
  문서 로딩 + 청킹
  (DocumentLoader, DocumentChunker)
        |
        v
 [2. Embedding]
  OpenAI text-embedding-3-small
  -> ChromaDB 저장
  (IssueEmbedder)
        |
        v
 [3. Retrieval]          <-- 사용자 질문
  코사인 유사도 검색
  (IssueRetriever)
        |
        v
 [4. Generation]
  Claude API (claude-sonnet-4-6)
  RAG 프롬프트 -> 답변 생성
  (IssueAnswerGenerator)
        |
        v
   FastAPI 응답
```

## 기술 스택

| 구분 | 기술 |
|------|------|
| Language | Python 3.11+ |
| Framework | LangChain, FastAPI |
| LLM | Claude (claude-sonnet-4-6) |
| 임베딩 | OpenAI text-embedding-3-small |
| 벡터 DB | ChromaDB (로컬 영구 저장) |
| 패키지 매니저 | uv |

## 프로젝트 구조

```
issue-pipeline/
├── src/
│   ├── ingestion/
│   │   ├── document_loader.py   # PDF/MD/TXT 파일 로딩
│   │   └── chunker.py           # RecursiveCharacterTextSplitter 청킹
│   ├── embedding/
│   │   └── embedder.py          # 임베딩 생성 및 ChromaDB 저장
│   ├── retrieval/
│   │   └── retriever.py         # 코사인 유사도 벡터 검색
│   ├── generation/
│   │   └── generator.py         # Claude API 답변 생성
│   ├── api/
│   │   ├── main.py              # FastAPI 엔드포인트
│   │   └── models.py            # Pydantic 요청/응답 모델
│   ├── pipeline.py              # 파이프라인 오케스트레이터
│   ├── config.py                # 환경변수 기반 설정 관리
│   └── logger.py                # 구조화된 로깅
├── data/
│   ├── raw/                     # 원본 이슈 문서 (여기에 문서 추가)
│   ├── processed/               # 전처리 캐시 (자동 생성)
│   └── chroma_db/               # ChromaDB 데이터 (자동 생성)
├── scripts/
│   ├── index_documents.py       # 문서 인덱싱 CLI
│   ├── start_server.py          # API 서버 시작 CLI
│   └── query_cli.py             # 쿼리 테스트 CLI
├── tests/
│   ├── test_ingestion.py
│   ├── test_retriever.py
│   └── test_api.py
├── .env.example                 # 환경변수 템플릿
├── pyproject.toml
└── README.md
```

## 설치 방법

### 1. 사전 요구사항

- Python 3.11 이상
- [uv](https://docs.astral.sh/uv/) 패키지 매니저

uv가 설치되어 있지 않은 경우:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.local/bin/env
```

### 2. 저장소 클론 및 의존성 설치

```bash
# 프로젝트 디렉토리로 이동
cd /Users/yg/project/cc-project/issue-pipeline

# 의존성 설치 (가상환경 자동 생성)
uv sync

# 개발 의존성 포함 설치 (테스트, 린터 등)
uv sync --extra dev
```

### 3. 환경변수 설정

```bash
# .env 파일 생성
cp .env.example .env

# .env 파일 편집 (필수 값 설정)
vi .env
```

필수 설정값:
```bash
# Anthropic API 키 (https://console.anthropic.com에서 발급)
ANTHROPIC_API_KEY=sk-ant-your-api-key-here

# OpenAI API 키 (임베딩용, https://platform.openai.com에서 발급)
OPENAI_API_KEY=sk-your-openai-api-key-here
```

## 실행 방법

### 1. 이슈 문서 인덱싱

`data/raw/` 디렉토리에 버그 리포트, 이슈 문서를 배치한 후 인덱싱합니다.

지원 파일 형식: `.pdf`, `.md`, `.markdown`, `.txt`

```bash
# 기본 경로(data/raw/) 인덱싱
uv run python scripts/index_documents.py

# 특정 디렉토리 인덱싱
uv run python scripts/index_documents.py --source-dir /path/to/docs

# 하위 디렉토리 포함
uv run python scripts/index_documents.py --recursive

# 실제 처리 전 파일 목록만 확인 (dry-run)
uv run python scripts/index_documents.py --dry-run
```

출력 예시:
```
[Issue Pipeline] 문서 인덱싱 시작
  소스 디렉토리: /path/to/issue-pipeline/data/raw

[인덱싱 완료]
  처리된 파일:  3개
  실패한 파일:  0개
  전체 청크:    47개
  추가된 청크:  47개
  스킵된 청크:  0개 (중복)
  소요 시간:    12.3초

[현재 인덱스 상태]
  컬렉션: issue_documents
  총 청크 수: 47개
```

### 2. API 서버 실행

```bash
# 기본 설정으로 서버 시작 (http://0.0.0.0:8000)
uv run python scripts/start_server.py

# 개발 모드 (파일 변경 시 자동 재시작)
uv run python scripts/start_server.py --reload

# 커스텀 포트 지정
uv run python scripts/start_server.py --port 8080
```

서버 시작 후 아래 URL에서 API를 확인할 수 있습니다:
- API 문서 (Swagger): http://localhost:8000/docs
- 헬스체크: http://localhost:8000/health

### 3. CLI로 직접 쿼리 테스트

API 서버 없이 직접 파이프라인을 호출합니다.

```bash
# 단일 질문
uv run python scripts/query_cli.py "로그인 오류의 원인은 무엇인가요?"

# LLM 없이 검색 결과만 확인
uv run python scripts/query_cli.py --search-only "데이터베이스 연결 오류"

# 대화형 모드
uv run python scripts/query_cli.py --interactive
```

## API 사용 예시

### RAG 질문 답변

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "결제 API에서 타임아웃이 발생하는 원인은 무엇인가요?",
    "top_k": 5,
    "include_context": true
  }'
```

응답:
```json
{
  "question": "결제 API에서 타임아웃이 발생하는 원인은 무엇인가요?",
  "answer": "BUG-2024-042에 따르면, 결제 API 타임아웃의 원인은...",
  "model": "claude-sonnet-4-6",
  "context_count": 3,
  "context": [...],
  "usage": {"input_tokens": 1250, "output_tokens": 380}
}
```

### 유사 문서 검색 (LLM 없음)

```bash
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "DB 연결 풀 고갈", "top_k": 3}'
```

### 문서 인덱싱 (API)

```bash
curl -X POST http://localhost:8000/api/v1/index \
  -H "Content-Type: application/json" \
  -d '{"recursive": false}'
```

### 인덱스 통계 조회

```bash
curl http://localhost:8000/api/v1/stats
```

## 테스트 실행

```bash
# 전체 테스트 실행
uv run pytest tests/ -v

# 커버리지 포함 실행
uv run pytest tests/ --cov=src --cov-report=term-missing

# 특정 테스트만 실행
uv run pytest tests/test_ingestion.py -v
```

## 새 이슈 문서 추가 방법

1. `data/raw/` 디렉토리에 문서 파일 배치
   - 권장 파일명 형식: `BUG-2024-001_brief_description.md`
2. 인덱싱 실행: `uv run python scripts/index_documents.py`
3. 동일 파일은 자동으로 스킵됩니다 (멱등성 보장)

## 주요 설계 결정

### 멱등성 (Idempotency)
동일한 파일을 여러 번 인덱싱해도 중복이 발생하지 않습니다.
파일의 MD5 해시를 기반으로 중복을 감지합니다.

### 재시도 로직
OpenAI 임베딩 API 및 Claude API 호출에 지수 백오프(Exponential Backoff) 재시도가 적용되어
일시적인 API 오류에 자동으로 대응합니다.

### 청킹 전략
이슈 문서의 Markdown 구조(##, ###)를 최우선 분할 기준으로 설정하여
헤더로 구분된 섹션(원인, 해결방법, 재발방지 등)이 청크 경계에서 잘리지 않도록 합니다.

## 환경 설정 전체 목록

`.env.example` 파일을 참조하거나, 아래 표를 확인하세요:

| 변수명 | 기본값 | 설명 |
|--------|--------|------|
| `ANTHROPIC_API_KEY` | (필수) | Anthropic API 키 |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | Claude 모델 ID |
| `OPENAI_API_KEY` | (필수) | OpenAI API 키 (임베딩) |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | 임베딩 모델 |
| `CHROMA_PERSIST_DIR` | `./data/chroma_db` | ChromaDB 저장 경로 |
| `CHROMA_COLLECTION_NAME` | `issue_documents` | 컬렉션 이름 |
| `CHUNK_SIZE` | `1000` | 청크 최대 문자 수 |
| `CHUNK_OVERLAP` | `200` | 청크 간 겹침 문자 수 |
| `RETRIEVAL_TOP_K` | `5` | 검색 결과 최대 수 |
| `RETRIEVAL_SCORE_THRESHOLD` | `0.3` | 유사도 최소 임계값 |
| `API_HOST` | `0.0.0.0` | API 서버 호스트 |
| `API_PORT` | `8000` | API 서버 포트 |
| `LOG_LEVEL` | `INFO` | 로그 레벨 |
