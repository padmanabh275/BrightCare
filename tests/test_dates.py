"""Date / slot selection helpers."""

from __future__ import annotations

from datetime import date

from api.agent import timeutil
from api.agent.nlu import heuristic_parse
from api.agent.business import BUSINESS_WEEKDAYS


def test_upcoming_business_days_are_weekdays():
    days = timeutil.upcoming_business_days(8)
    assert len(days) == 8
    assert all(d.weekday() in BUSINESS_WEEKDAYS for d in days)
    assert days == sorted(days)


def test_heuristic_parse_iso_date():
    result = heuristic_parse("Can I book 2026-07-20 at 2pm?")
    assert result.intent == "book"
    assert result.requested_start is not None
    local = timeutil.to_clinic(result.requested_start)
    assert local.date() == date(2026, 7, 20)
    assert local.hour == 14


def test_format_day_label():
    assert "Jul" in timeutil.format_day_label(date(2026, 7, 20))
