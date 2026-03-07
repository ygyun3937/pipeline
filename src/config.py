"""
파이프라인 전체에서 사용되는 설정값 관리 모듈.
pydantic-settings를 이용해 .env 파일에서 자동으로 값을 로드한다.
"""

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """애플리케이션 설정. 환경변수 또는 .env 파일에서 로드된다."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

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

    # ---- Claude Agent SDK 설정 ----
    anthropic_model: str = Field(
        default="claude-agent-sdk",
        description="사용 중인 Claude 모델명 (헬스체크 표시용)",
    )
    generation_max_retries: int = Field(
        default=3, description="답변 생성 최대 재시도 횟수"
    )
    generation_retry_wait_min: float = Field(
        default=1.0, description="재시도 최소 대기 시간(초)"
    )
    generation_retry_wait_max: float = Field(
        default=10.0, description="재시도 최대 대기 시간(초)"
    )

    # ---- 임베딩 설정 (로컬 ONNX 다국어 모델, API 키/PyTorch 불필요) ----
    embedding_model: str = Field(
        default="sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
        description="FastEmbed 로컬 임베딩 모델 (ONNX 기반, 한국어 지원 다국어 모델 sentence-transformers/paraphrase-multilingual-mpnet-base-v2)",
    )
    embedding_batch_size: int = Field(
        default=100, description="임베딩 배치 처리 크기"
    )

    # ---- ChromaDB 설정 ----
    chroma_persist_dir: str = Field(
        default="./data/chroma_db",
        description="ChromaDB 영구 저장 경로",
    )
    chroma_collection_name: str = Field(
        default="issue_documents",
        description="ChromaDB 컬렉션 이름",
    )

    # ---- 청킹 설정 (한국어 문서 최적화) ----
    chunk_size: int = Field(
        default=800, description="청크 최대 문자 수 (한국어 특성상 800 권장)"
    )
    chunk_overlap: int = Field(default=150, description="청크 간 겹침 문자 수")

    # ---- 검색 설정 ----
    retrieval_top_k: int = Field(default=5, description="검색 결과 최대 개수")
    retrieval_score_threshold: float = Field(
        default=0.4, description="유사도 임계값 (0.0 ~ 1.0, 0.4로 상향 조정)"
    )

    # ---- API 서버 설정 ----
    api_host: str = Field(default="0.0.0.0", description="API 서버 호스트")
    api_port: int = Field(default=8000, description="API 서버 포트")
    api_debug: bool = Field(default=False, description="디버그 모드")
    api_log_level: str = Field(default="info", description="uvicorn 로그 레벨")

    # ---- 문서 경로 ----
    raw_documents_dir: str = Field(
        default="./data/raw", description="원본 문서 디렉토리"
    )
    processed_documents_dir: str = Field(
        default="./data/processed", description="처리된 문서 디렉토리"
    )

    # ---- 로깅 설정 ----
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", description="애플리케이션 로그 레벨"
    )
    log_format: Literal["json", "text"] = Field(
        default="text", description="로그 출력 형식"
    )

    # ---- QA 워크플로우 설정 ----
    qa_reports_dir: str = Field(
        default="./data/qa_reports",
        description="QA 리포트 저장 디렉토리",
    )
    qa_validation_criteria_path: str = Field(
        default="./data/config/validation_criteria.yaml",
        description="QA 검증 기준 YAML 파일 경로",
    )
    qa_elaboration_top_k: int = Field(
        default=5, description="이슈 구체화 시 RAG 검색 결과 수"
    )
    qa_report_filename_prefix: str = Field(
        default="QA_REPORT", description="QA 리포트 파일명 접두사"
    )

    @property
    def chroma_persist_path(self) -> Path:
        """ChromaDB 절대 경로 반환."""
        return Path(self.chroma_persist_dir).resolve()

    @property
    def raw_documents_path(self) -> Path:
        """원본 문서 디렉토리 절대 경로 반환."""
        return Path(self.raw_documents_dir).resolve()

    @property
    def processed_documents_path(self) -> Path:
        """처리된 문서 디렉토리 절대 경로 반환."""
        return Path(self.processed_documents_dir).resolve()

    @property
    def qa_reports_path(self) -> Path:
        """QA 리포트 디렉토리 절대 경로 반환."""
        return Path(self.qa_reports_dir).resolve()

    @property
    def qa_validation_criteria_path_resolved(self) -> Path:
        """QA 검증 기준 파일 절대 경로 반환."""
        return Path(self.qa_validation_criteria_path).resolve()


def get_settings() -> Settings:
    """
    싱글턴 패턴으로 설정 인스턴스를 반환한다.
    함수 호출마다 새 인스턴스를 생성하지 않고 캐싱된 값을 반환한다.
    """
    return _settings_cache


# 모듈 로드 시 한 번만 초기화 (캐싱)
_settings_cache: Settings = Settings()  # type: ignore[call-arg]
