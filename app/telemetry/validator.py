from __future__ import annotations

from typing import Iterable, List, Set

from app.telemetry.events import EventType, SessionEvent
from agents.tools import TOOLS


def valid_tool_names() -> Set[str]:
    return {tool.name for tool in TOOLS}


def validate_event_sequence(events: Iterable[SessionEvent]) -> List[str]:
    errors: List[str] = []
    allowed_tools = valid_tool_names()
    pending_calls = set()

    for idx, event in enumerate(events):
        if event.event_type == EventType.TOOL_CALL:
            if not event.tool_name or event.tool_name not in allowed_tools:
                errors.append(f"event[{idx}] invalid tool name: {event.tool_name}")
            if not event.tool_call_id:
                errors.append(f"event[{idx}] missing tool_call_id for tool_call")
            else:
                pending_calls.add(event.tool_call_id)

        if event.event_type == EventType.TOOL_RESULT:
            if not event.tool_call_id:
                errors.append(f"event[{idx}] missing tool_call_id for tool_result")
            elif event.tool_call_id not in pending_calls:
                errors.append(
                    f"event[{idx}] tool_result has no matching prior tool_call_id: {event.tool_call_id}"
                )

    return errors
