"""FastAPI 의존성 주입 모듈."""
from __future__ import annotations

from fastapi import HTTPException

from src.chat.repository import ChatRepository
from src.missed_queries import MissedQueryLogger
from src.pipeline import IssuePipeline
from src.equipment.repository import EquipmentRepository
from src.equipment.orchestrator import EquipmentOrchestrator

# 파이프라인 싱글턴 (main.py의 lifespan에서 초기화)
_pipeline: IssuePipeline | None = None
_chat_repo: ChatRepository | None = None
_missed_query_logger: MissedQueryLogger | None = None


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


def set_chat_repo(repo: ChatRepository | None) -> None:
    """lifespan에서 ChatRepository 싱글턴을 설정한다."""
    global _chat_repo  # noqa: PLW0603
    _chat_repo = repo


def get_chat_repo() -> ChatRepository:
    """FastAPI 의존성 주입: ChatRepository 인스턴스를 반환한다."""
    if _chat_repo is None:
        raise HTTPException(
            status_code=503,
            detail="채팅 저장소가 초기화되지 않았습니다. 서버를 재시작해주세요.",
        )
    return _chat_repo


def set_missed_query_logger(logger: MissedQueryLogger | None) -> None:
    global _missed_query_logger  # noqa: PLW0603
    _missed_query_logger = logger


def get_missed_query_logger() -> MissedQueryLogger:
    """FastAPI 의존성 주입: MissedQueryLogger 인스턴스를 반환한다."""
    if _missed_query_logger is None:
        raise HTTPException(
            status_code=503,
            detail="미답변 질문 로거가 초기화되지 않았습니다.",
        )
    return _missed_query_logger


_equipment_repo: EquipmentRepository | None = None
_orchestrator: EquipmentOrchestrator | None = None


def set_equipment_repo(repo: EquipmentRepository | None) -> None:
    global _equipment_repo  # noqa: PLW0603
    _equipment_repo = repo


def get_equipment_repo() -> EquipmentRepository:
    if _equipment_repo is None:
        raise HTTPException(status_code=503, detail="EquipmentRepository가 초기화되지 않았습니다.")
    return _equipment_repo


def set_orchestrator(orch: EquipmentOrchestrator | None) -> None:
    global _orchestrator  # noqa: PLW0603
    _orchestrator = orch


def get_orchestrator() -> EquipmentOrchestrator:
    if _orchestrator is None:
        raise HTTPException(status_code=503, detail="EquipmentOrchestrator가 초기화되지 않았습니다.")
    return _orchestrator
