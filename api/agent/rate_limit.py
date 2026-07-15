"""Per-chat rate limiting for agent messages."""

from __future__ import annotations

import time
from collections import defaultdict


class ChatRateLimiter:
    def __init__(self, max_per_minute: int = 10) -> None:
        self.max_per_minute = max_per_minute
        self._hits: dict[str, list[float]] = defaultdict(list)

    def allow(self, chat_id: str) -> bool:
        now = time.time()
        hits = self._hits[chat_id]
        hits[:] = [t for t in hits if now - t < 60.0]
        if len(hits) >= self.max_per_minute:
            return False
        hits.append(now)
        return True

    def reset(self, chat_id: str | None = None) -> None:
        if chat_id is None:
            self._hits.clear()
        else:
            self._hits.pop(chat_id, None)


chat_rate_limiter = ChatRateLimiter()
