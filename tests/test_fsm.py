"""FSM conversation script tests."""

from __future__ import annotations

import pytest

from api.agent.fsm import BookingAgent
from api.agent.session import ConversationState, session_store
from api.agent import timeutil
from api.integrations.calendar import InMemoryCalendar, slot_end


@pytest.mark.asyncio
async def test_monday_2pm_taken_suggest_3pm_yes_books():
    day = timeutil.next_weekday(timeutil.clinic_now(), 0)  # next Monday
    # Ensure we don't pick a past Monday earlier today edge — next_weekday returns today if Monday
    two_pm = timeutil.combine_clinic(day, 14, 0)
    two_thirty = timeutil.combine_clinic(day, 14, 30)
    three_pm = timeutil.combine_clinic(day, 15, 0)
    cal = InMemoryCalendar(
        busy=[
            (two_pm, slot_end(two_pm)),
            (two_thirty, slot_end(two_thirty)),
        ]
    )
    agent = BookingAgent(calendar=cal)

    chat = "test-user-1"
    # Seed email first so confirm path books immediately
    r0 = await agent.handle(chat, "my email is patient@example.com")
    assert "noted" in r0.text.lower() or "saved" in r0.text.lower() or "email" in r0.text.lower()

    session = session_store.get(chat)
    session.email = "patient@example.com"

    r1 = await agent.handle(chat, "Can I book Monday at 2pm?")
    assert "isn't available" in r1.text
    assert "3:00pm" in r1.text or "3pm" in r1.text.lower()
    assert session_store.get(chat).state.value == "awaiting_alt_confirm"
    assert session_store.get(chat).proposed_slot == three_pm

    r2 = await agent.handle(chat, "yes")
    assert "Done" in r2.text
    assert "3:00pm" in r2.text
    assert len(cal.events) == 1
    assert cal.events[0]["start"] == three_pm


@pytest.mark.asyncio
async def test_outside_hours_rejected():
    cal = InMemoryCalendar()
    agent = BookingAgent(calendar=cal)
    chat = "hours-user"
    session_store.get(chat).email = "a@b.com"
    reply = await agent.handle(chat, "Book Monday at 8am")
    assert "business hours" in reply.text.lower() or "09:00" in reply.text


@pytest.mark.asyncio
async def test_bad_email_keeps_awaiting():
    day = timeutil.next_weekday(timeutil.clinic_now(), 0)
    start = timeutil.combine_clinic(day, 10, 0)
    cal = InMemoryCalendar()
    agent = BookingAgent(calendar=cal)
    chat = "email-user"
    # Free slot path asks for email
    r1 = await agent.handle(chat, "Can I book Monday at 10am?")
    assert session_store.get(chat).state == ConversationState.AWAITING_EMAIL
    r2 = await agent.handle(chat, "not-an-email")
    assert session_store.get(chat).state == ConversationState.AWAITING_EMAIL
    assert "valid email" in r2.text.lower()
