"""미답변 질문 조회/관리 라우터."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.api.dependencies import get_missed_query_logger
from src.missed_queries import MissedQueryLogger

router = APIRouter(prefix="/api/v1/missed-queries", tags=["Missed Queries"])


class MissedQueryItem(BaseModel):
    id: str
    question: str
    session_id: str | None
    logged_at: str
    resolved: bool


@router.get("", response_model=list[MissedQueryItem], summary="미답변 질문 목록")
async def list_missed_queries(
    unresolved_only: bool = False,
    logger: MissedQueryLogger = Depends(get_missed_query_logger),
) -> list[MissedQueryItem]:
    """RAG 검색 결과가 없어 답변하지 못한 질문 목록을 반환한다."""
    entries = await logger.list_all(unresolved_only=unresolved_only)
    return [MissedQueryItem(**e) for e in entries]


@router.patch("/{entry_id}/resolve", response_model=MissedQueryItem, summary="해결 처리")
async def resolve_missed_query(
    entry_id: str,
    logger: MissedQueryLogger = Depends(get_missed_query_logger),
) -> MissedQueryItem:
    """해당 항목을 해결됨으로 표시한다 (관련 문서 인덱싱 후 사용)."""
    from fastapi import HTTPException
    ok = await logger.mark_resolved(entry_id)
    if not ok:
        raise HTTPException(status_code=404, detail="항목을 찾을 수 없습니다.")
    entries = await logger.list_all()
    entry = next(e for e in entries if e["id"] == entry_id)
    return MissedQueryItem(**entry)
