"""
대화 세션 데이터 모델.

ChatSession  : 대화 세션 메타데이터
ChatMessage  : 개별 메시지 (user / assistant)
MessageRole  : 메시지 발신자 역할 열거형
FeedbackType : 메시지 피드백 (thumbs_up / thumbs_down)
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


class FeedbackType(str, Enum):
    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"


class ChatMessage(BaseModel):
    id: str
    session_id: str
    role: MessageRole
    content: str
    context_doc_ids: list[str] = Field(default_factory=list)
    feedback: FeedbackType | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "role": self.role.value,
            "content": self.content,
            "context_doc_ids": self.context_doc_ids,
            "feedback": self.feedback.value if self.feedback else None,
            "created_at": self.created_at.isoformat(),
        }


class ChatSession(BaseModel):
    id: str
    title: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    message_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "message_count": self.message_count,
        }
