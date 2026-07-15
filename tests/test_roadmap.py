"""Tests for cancel/reschedule flows and booking history."""

from __future__ import annotations

import pytest

from api.agent.bookings import BookingStatus, get_booking_store
from api.agent.fsm import BookingAgent
from api.agent.session import ConversationState, session_store
from api.agent import timeutil
from api.integrations.calendar import InMemoryCalendar, slot_end


@pytest.mark.asyncio
async def test_cancel_flow():
    day = timeutil.next_weekday(timeutil.clinic_now(), 0)
    start = timeutil.combine_clinic(day, 15, 0)
    cal = InMemoryCalendar()
    agent = BookingAgent(calendar=cal)
    chat = "cancel-user"

    session_store.get(chat).email = "patient@example.com"
    event_id = cal.create_appointment(start, "patient@example.com")
    get_booking_store().add_booking(chat, event_id, start, "patient@example.com")

    r1 = await agent.handle(chat, "cancel my appointment")
    assert "Reply yes" in r1.text
    assert session_store.get(chat).state == ConversationState.AWAITING_CANCEL_CONFIRM

    r2 = await agent.handle(chat, "yes")
    assert "cancelled" in r2.text.lower()
    assert len(cal.events) == 0
    booking = get_booking_store().get_active_booking(chat)
    assert booking is None


@pytest.mark.asyncio
async def test_reschedule_flow():
    day = timeutil.next_weekday(timeutil.clinic_now(), 0)
    start = timeutil.combine_clinic(day, 14, 0)
    new_slot = timeutil.combine_clinic(day, 16, 0)
    cal = InMemoryCalendar()
    agent = BookingAgent(calendar=cal)
    chat = "reschedule-user"

    session_store.get(chat).email = "patient@example.com"
    event_id = cal.create_appointment(start, "patient@example.com")
    get_booking_store().add_booking(chat, event_id, start, "patient@example.com")

    r1 = await agent.handle(chat, "reschedule my appointment")
    assert "current appointment" in r1.text.lower()
    assert session_store.get(chat).state == ConversationState.AWAITING_RESCHEDULE

    r2 = await agent.handle(chat, "Can I book Monday at 4pm?")
    assert "confirm" in r2.text.lower() or "shall" in r2.text.lower()

    r3 = await agent.handle(chat, "yes")
    assert "Done" in r3.text
    assert cal.events[0]["start"] == new_slot


@pytest.mark.asyncio
async def test_waitlist_on_full_day():
    from api.integrations.calendar import iter_slot_starts

    day = timeutil.next_weekday(timeutil.clinic_now(), 0)
    cal = InMemoryCalendar()
    for start in iter_slot_starts(day):
        cal.busy.append((start, slot_end(start)))

    agent = BookingAgent(calendar=cal)
    chat = "waitlist-user"
    session_store.get(chat).email = "w@example.com"

    r1 = await agent.handle(chat, "Can I book Monday at 2pm?")
    assert "waitlist" in r1.text.lower() or "notify me" in r1.text.lower()

    r2 = await agent.handle(chat, "notify me")
    assert "waitlist" in r2.text.lower()
