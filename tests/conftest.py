"""pytest fixtures."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("CLINIC_TIMEZONE", "Asia/Singapore")
os.environ["SESSION_STORE"] = "memory"
os.environ["OPENAI_API_KEY"] = ""
os.environ.pop("CLERK_JWKS_URL", None)


@pytest.fixture(autouse=True)
def _reset_singletons():
    from api.agent.bookings import BookingStore, reset_booking_store
    from api.agent.rate_limit import chat_rate_limiter
    from api.agent.session import session_store
    from api.config import get_settings
    from api.integrations.calendar import set_calendar

    get_settings.cache_clear()
    os.environ["OPENAI_API_KEY"] = ""
    session_store.clear_all()
    chat_rate_limiter.reset()
    set_calendar(None)

    with tempfile.TemporaryDirectory() as tmp:
        reset_booking_store(BookingStore(Path(tmp) / "bookings.db"))
        yield
        reset_booking_store(None)

    session_store.clear_all()
    chat_rate_limiter.reset()
    set_calendar(None)
    get_settings.cache_clear()
