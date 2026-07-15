"""In-memory audit ring buffer for dashboard / debugging."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class AuditEvent:
    ts: str
    chat_id: str
    intent: str | None = None
    state: str | None = None
    proposed_slot: str | None = None
    booking_id: str | None = None
    email_status: str | None = None
    message: str | None = None


class AuditLog:
    def __init__(self, maxlen: int = 50) -> None:
        self._events: deque[AuditEvent] = deque(maxlen=maxlen)

    def add(self, **kwargs: Any) -> None:
        ts = kwargs.pop("ts", None) or datetime.now(timezone.utc).isoformat()
        chat_id = kwargs.get("chat_id", "")
        if chat_id and len(str(chat_id)) > 4:
            kwargs["chat_id"] = f"…{str(chat_id)[-4:]}"
        self._events.appendleft(AuditEvent(ts=ts, **kwargs))

    def recent(self) -> list[dict[str, Any]]:
        return [asdict(e) for e in self._events]


audit_log = AuditLog()
