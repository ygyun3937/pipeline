"""FastAPI 의존성 주입 모듈."""
from __future__ import annotations

from fastapi import HTTPException

from src.pipeline import IssuePipeline

# 파이프라인 싱글턴 (main.py의 lifespan에서 초기화)
_pipeline: IssuePipeline | None = None


def set_pipeline(pipeline: IssuePipeline | None) -> None:
    """lifespan에서 파이프라인 싱글턴을 설정한다."""
    global _pipeline  # noqa: PLW0603
    _pipeline = pipeline


def get_pipeline() -> IssuePipeline:
    """FastAPI 의존성 주입: 파이프라인 인스턴스를 반환한다."""
    if _pipeline is None:
        raise HTTPException(
            status_code=503,
            detail="파이프라인이 초기화되지 않았습니다. 서버를 재시작해주세요.",
        )
    return _pipeline
