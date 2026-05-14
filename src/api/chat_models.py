"""
채팅 API 요청/응답 Pydantic 모델.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    title: str = Field(default="", max_length=200, description="세션 제목 (비워두면 첫 메시지로 자동 생성)")


class SessionResponse(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int


class MessageResponse(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    context_doc_ids: list[str]
    created_at: datetime


class ChatStreamRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000, description="사용자 질문")
    top_k: int = Field(default=5, ge=1, le=20, description="RAG 검색 결과 수")
