"""Slot and nearest-slot calendar rule tests."""

from __future__ import annotations

from datetime import date, datetime

from api.agent import timeutil
from api.integrations.calendar import (
    InMemoryCalendar,
    find_nearest_slot,
    is_within_business_hours,
    iter_slot_starts,
    slot_end,
)


def test_iter_slots_weekday():
    # 2026-07-20 is a Monday
    day = date(2026, 7, 20)
    starts = iter_slot_starts(day)
    assert starts[0] == timeutil.combine_clinic(day, 9, 0)
    assert starts[-1] == timeutil.combine_clinic(day, 17, 30)
    assert len(starts) == 18  # 09:00–17:30 inclusive every 30m


def test_iter_slots_weekend_empty():
    assert iter_slot_starts(date(2026, 7, 19)) == []  # Sunday


def test_outside_hours():
    day = date(2026, 7, 20)
    early = timeutil.combine_clinic(day, 8, 0)
    late = timeutil.combine_clinic(day, 18, 0)
    assert not is_within_business_hours(early)
    assert not is_within_business_hours(late)
    assert is_within_business_hours(timeutil.combine_clinic(day, 14, 0))


def test_nearest_when_2pm_busy():
    day = date(2026, 7, 20)
    requested = timeutil.combine_clinic(day, 14, 0)
    # Block 14:00–15:00 so nearest same-day opening is 15:00 (demo script shape)
    busy = [
        (requested, slot_end(requested)),
        (timeutil.combine_clinic(day, 14, 30), slot_end(timeutil.combine_clinic(day, 14, 30))),
    ]
    nearest = find_nearest_slot(requested, busy)
    assert nearest == timeutil.combine_clinic(day, 15, 0)


def test_nearest_prefers_2130_when_only_2pm_busy():
    day = date(2026, 7, 20)
    requested = timeutil.combine_clinic(day, 14, 0)
    busy = [(requested, slot_end(requested))]
    nearest = find_nearest_slot(requested, busy)
    assert nearest == timeutil.combine_clinic(day, 14, 30)


def test_nearest_none_left_same_day():
    day = date(2026, 7, 20)
    requested = timeutil.combine_clinic(day, 17, 30)
    busy = [(requested, slot_end(requested))]
    assert find_nearest_slot(requested, busy) is None


def test_inmemory_create_blocks_slot():
    day = date(2026, 7, 20)
    start = timeutil.combine_clinic(day, 15, 0)
    cal = InMemoryCalendar()
    assert cal.is_slot_free(start)
    cal.create_appointment(start, "p@example.com")
    assert not cal.is_slot_free(start)
