from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from helpers.utils import get_logger

logger = get_logger(__name__)


class EventType(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ERROR = "error"


class SessionEvent(BaseModel):
    schema_version: str = "v1"
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    event_type: EventType
    session_id: str
    user_id: str
    source_lang: str
    target_lang: str
    content: Optional[str] = None
    tool_name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    tool_result: Optional[Any] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


def emit_session_event(event: SessionEvent) -> None:
    logger.info("training_event=%s", event.model_dump_json(exclude_none=True))


def build_user_event(
    *,
    session_id: str,
    user_id: str,
    source_lang: str,
    target_lang: str,
    content: str,
) -> SessionEvent:
    return SessionEvent(
        event_type=EventType.USER,
        session_id=session_id,
        user_id=user_id,
        source_lang=source_lang,
        target_lang=target_lang,
        content=content,
    )


def build_assistant_event(
    *,
    session_id: str,
    user_id: str,
    source_lang: str,
    target_lang: str,
    content: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> SessionEvent:
    return SessionEvent(
        event_type=EventType.ASSISTANT,
        session_id=session_id,
        user_id=user_id,
        source_lang=source_lang,
        target_lang=target_lang,
        content=content,
        metadata=metadata or {},
    )


def build_tool_call_event(
    *,
    session_id: str,
    user_id: str,
    source_lang: str,
    target_lang: str,
    tool_name: str,
    tool_call_id: str,
    tool_args: Optional[Dict[str, Any]],
) -> SessionEvent:
    return SessionEvent(
        event_type=EventType.TOOL_CALL,
        session_id=session_id,
        user_id=user_id,
        source_lang=source_lang,
        target_lang=target_lang,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        tool_args=tool_args or {},
    )


def build_tool_result_event(
    *,
    session_id: str,
    user_id: str,
    source_lang: str,
    target_lang: str,
    tool_name: str,
    tool_call_id: str,
    tool_result: Any,
) -> SessionEvent:
    return SessionEvent(
        event_type=EventType.TOOL_RESULT,
        session_id=session_id,
        user_id=user_id,
        source_lang=source_lang,
        target_lang=target_lang,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        tool_result=tool_result,
    )


def build_error_event(
    *,
    session_id: str,
    user_id: str,
    source_lang: str,
    target_lang: str,
    error_type: str,
    error_message: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> SessionEvent:
    return SessionEvent(
        event_type=EventType.ERROR,
        session_id=session_id,
        user_id=user_id,
        source_lang=source_lang,
        target_lang=target_lang,
        error_type=error_type,
        error_message=error_message,
        metadata=metadata or {},
    )
