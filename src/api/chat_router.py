"""
채팅 세션 및 SSE 스트리밍 라우터.

엔드포인트:
    POST   /api/v1/chat/sessions                    — 세션 생성
    GET    /api/v1/chat/sessions                    — 세션 목록
    GET    /api/v1/chat/sessions/{session_id}       — 세션 조회
    DELETE /api/v1/chat/sessions/{session_id}       — 세션 삭제
    GET    /api/v1/chat/sessions/{session_id}/messages — 메시지 목록
    POST   /api/v1/chat/sessions/{session_id}/stream   — SSE 스트리밍 질문

SSE 이벤트 형식:
    data: {"type": "text",  "text": "<청크>"}\n\n
    data: {"type": "done",  "session_id": "...", "message_id": "...", "context_count": N}\n\n
    data: {"type": "error", "detail": "<메시지>"}\n\n
"""
from __future__ import annotations

import json
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from src.api.chat_models import (
    ChatStreamRequest,
    CreateSessionRequest,
    MessageResponse,
    SessionResponse,
)
from src.api.dependencies import get_chat_repo, get_pipeline
from src.chat.models import MessageRole
from src.chat.repository import ChatRepository
from src.logger import get_logger
from src.pipeline import IssuePipeline

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/chat", tags=["Chat"])


# ---- 세션 관리 ----

@router.post("/sessions", response_model=SessionResponse, status_code=201, summary="세션 생성")
async def create_session(
    body: CreateSessionRequest,
    repo: ChatRepository = Depends(get_chat_repo),
) -> SessionResponse:
    session = await repo.create_session(title=body.title)
    return SessionResponse(**session.to_dict())


@router.get("/sessions", response_model=list[SessionResponse], summary="세션 목록")
async def list_sessions(
    limit: int = 20,
    repo: ChatRepository = Depends(get_chat_repo),
) -> list[SessionResponse]:
    sessions = await repo.list_sessions(limit=limit)
    return [SessionResponse(**s.to_dict()) for s in sessions]


@router.get("/sessions/{session_id}", response_model=SessionResponse, summary="세션 조회")
async def get_session(
    session_id: str,
    repo: ChatRepository = Depends(get_chat_repo),
) -> SessionResponse:
    session = await repo.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
    return SessionResponse(**session.to_dict())


@router.delete("/sessions/{session_id}", status_code=204, summary="세션 삭제")
async def delete_session(
    session_id: str,
    repo: ChatRepository = Depends(get_chat_repo),
) -> None:
    deleted = await repo.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")


@router.get(
    "/sessions/{session_id}/messages",
    response_model=list[MessageResponse],
    summary="메시지 목록",
)
async def get_messages(
    session_id: str,
    repo: ChatRepository = Depends(get_chat_repo),
) -> list[MessageResponse]:
    session = await repo.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
    messages = await repo.get_messages(session_id)
    return [MessageResponse(**m.to_dict()) for m in messages]


# ---- SSE 스트리밍 ----

@router.post("/sessions/{session_id}/stream", summary="SSE 스트리밍 질문")
async def stream_chat(
    session_id: str,
    body: ChatStreamRequest,
    repo: ChatRepository = Depends(get_chat_repo),
    pipeline: IssuePipeline = Depends(get_pipeline),
) -> StreamingResponse:
    """
    사용자 질문을 RAG로 처리하고 SSE 스트림으로 응답한다.

    응답 형식 (text/event-stream):
        data: {"type": "text",  "text": "..."}\n\n  — 텍스트 청크
        data: {"type": "done",  ...}\n\n             — 완료
        data: {"type": "error", "detail": "..."}\n\n — 오류
    """
    session = await repo.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

    return StreamingResponse(
        _stream_generator(session_id, body, repo, pipeline),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _stream_generator(
    session_id: str,
    body: ChatStreamRequest,
    repo: ChatRepository,
    pipeline: IssuePipeline,
) -> AsyncGenerator[str, None]:
    """SSE 이벤트를 생성하는 내부 async generator."""
    question = body.question.strip()
    full_answer = ""
    context_doc_ids: list[str] = []

    try:
        # 1. RAG 검색 + 스트리밍 생성기 획득
        stream_gen, retrieval_results = await pipeline.stream_query(
            question=question, top_k=body.top_k
        )
        context_doc_ids = [
            r.document.metadata.get("doc_id", "")
            for r in retrieval_results.results
            if r.document.metadata.get("doc_id")
        ]

        # 2. 스트리밍
        async for chunk in stream_gen:
            full_answer += chunk
            yield _sse({"type": "text", "text": chunk})

        # 3. 메시지 저장 (user → assistant)
        await repo.add_message(session_id, MessageRole.USER, question)
        asst_msg = await repo.add_message(
            session_id,
            MessageRole.ASSISTANT,
            full_answer,
            context_doc_ids=context_doc_ids,
        )

        # 4. 세션 제목 자동 설정 (첫 메시지인 경우)
        session = await repo.get_session(session_id)
        if session and session.title == "새 대화":
            title = question[:50] + ("..." if len(question) > 50 else "")
            await repo.update_session_title(session_id, title)

        yield _sse({
            "type": "done",
            "session_id": session_id,
            "message_id": asst_msg.id,
            "context_count": len(retrieval_results.results),
        })

    except Exception as exc:
        logger.error("스트리밍 오류: session=%s, error=%s", session_id, exc)
        yield _sse({"type": "error", "detail": str(exc)})


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
