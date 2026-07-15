"""Tests for slots API helper."""

from __future__ import annotations

from datetime import date

from api.agent import timeutil
from api.integrations.calendar import InMemoryCalendar, list_available_slots, slot_end


def test_list_available_slots_excludes_busy():
    day = timeutil.next_weekday(timeutil.clinic_now(), 0)
    ten = timeutil.combine_clinic(day, 10, 0)
    cal = InMemoryCalendar(busy=[(ten, slot_end(ten))])
    slots = list_available_slots(day, cal)
    assert ten not in slots
    assert len(slots) > 0


def test_list_available_slots_weekend_empty():
    cal = InMemoryCalendar()
    saturday = date(2026, 7, 18)  # a Saturday
    assert saturday.weekday() == 5
    assert list_available_slots(saturday, cal) == []
