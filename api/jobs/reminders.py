"""Reminder cron and waitlist notification jobs."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from api.agent import timeutil
from api.agent.bookings import get_booking_store
from api.agent.business import CLINIC_NAME
from api.integrations.calendar import get_calendar, list_available_slots
from api.integrations.emailer import send_confirmation_email
from api.integrations.telegram_bot import telegram_runtime

logger = logging.getLogger(__name__)


async def run_reminders() -> dict[str, Any]:
    """Send 24h and 1h reminders for upcoming booked appointments."""
    store = get_booking_store()
    now = timeutil.clinic_now()
    sent_24h = 0
    sent_1h = 0

    for booking in store.upcoming_for_reminders():
        start = timeutil.to_clinic(booking.start)
        if start <= now:
            continue
        delta = start - now
        when = timeutil.format_slot_short(start)
        day = start.strftime("%A")

        if timedelta(hours=23) <= delta <= timedelta(hours=25) and not booking.reminder_24h_sent:
            msg = (
                f"Reminder: you have an appointment at {CLINIC_NAME} "
                f"tomorrow ({day} {when}). Reply here to cancel or reschedule."
            )
            await telegram_runtime.send_message(booking.chat_id, msg)
            store.mark_reminder_sent(booking.id, "24h")
            sent_24h += 1

        if timedelta(minutes=55) <= delta <= timedelta(hours=1, minutes=5) and not booking.reminder_1h_sent:
            msg = (
                f"Reminder: your appointment at {CLINIC_NAME} is in about an hour "
                f"({day} {when}). See you soon!"
            )
            await telegram_runtime.send_message(booking.chat_id, msg)
            store.mark_reminder_sent(booking.id, "1h")
            sent_1h += 1

    return {"reminders_24h": sent_24h, "reminders_1h": sent_1h}


async def run_waitlist_check() -> dict[str, Any]:
    """Notify waitlisted patients when slots open on their target day."""
    store = get_booking_store()
    cal = get_calendar()
    today = timeutil.clinic_now().date()
    notified = 0

    for offset in range(0, 14):
        target = today + timedelta(days=offset)
        if target.weekday() not in {0, 1, 2, 3, 4}:
            continue
        slots = list_available_slots(target, cal)
        if not slots:
            continue
        entries = store.pending_waitlist_for_date(target)
        for entry in entries[:3]:
            first = slots[0]
            when = timeutil.format_slot_short(first)
            day_name = target.strftime("%A")
            msg = (
                f"Good news — a slot opened on {day_name} at {when}. "
                f'Message me "book {day_name.lower()} at {when}" to grab it.'
            )
            await telegram_runtime.send_message(entry.chat_id, msg)
            store.mark_waitlist_notified(entry.id)
            notified += 1

    return {"waitlist_notified": notified}
