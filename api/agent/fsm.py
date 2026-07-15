"""Conversation FSM for BrightCare booking."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime

from api.agent import business, timeutil
from api.agent.audit import audit_log
from api.agent.bookings import BookingStatus, get_booking_store
from api.agent.nlu import IntentResult, is_valid_email, parse_intent
from api.agent.session import ConversationState, Session, session_store
from api.integrations import calendar as cal_mod
from api.integrations.calendar import CalendarClient, is_within_business_hours, slot_end
from api.integrations.emailer import send_cancellation_email, send_confirmation_email

logger = logging.getLogger(__name__)


@dataclass
class AgentReply:
    text: str
    propose_buttons_for: datetime | None = None


class BookingAgent:
    def __init__(self, calendar: CalendarClient | None = None) -> None:
        self.calendar = calendar

    def _cal(self) -> CalendarClient:
        return self.calendar or cal_mod.get_calendar()

    def _persist(self, session: Session) -> None:
        session_store.save(session)

    async def handle(self, chat_id: str, text: str) -> AgentReply:
        session = session_store.get(chat_id)
        session.updated_at = timeutil.clinic_now()
        nlu = parse_intent(text)

        if nlu.email and is_valid_email(nlu.email):
            session.email = nlu.email.strip()

        audit_log.add(
            chat_id=chat_id,
            intent=nlu.intent,
            state=session.state.value,
            proposed_slot=session.proposed_slot.isoformat() if session.proposed_slot else None,
            message=text[:120],
        )

        reply: AgentReply

        if session.state == ConversationState.AWAITING_CANCEL_CONFIRM:
            reply = await self._handle_cancel_confirm(session, nlu, text)
            self._persist(session)
            return reply

        if session.state == ConversationState.AWAITING_RESCHEDULE:
            reply = await self._handle_reschedule_turn(session, nlu, text)
            self._persist(session)
            return reply

        # Confirmation must resolve to proposed slot while waiting
        if session.state in {
            ConversationState.AWAITING_SLOT_CONFIRM,
            ConversationState.AWAITING_ALT_CONFIRM,
        }:
            if nlu.intent == "confirm" or _looks_yes(text):
                reply = await self._book_proposed(session)
                self._persist(session)
                return reply
            if nlu.intent == "decline" or _looks_no(text):
                session.state = ConversationState.IDLE
                session.proposed_slot = None
                if session.reschedule_event_id:
                    session.reschedule_event_id = None
                    reply = AgentReply("Okay — keeping your current appointment.")
                else:
                    reply = AgentReply("No problem — what time would you like instead?")
                self._persist(session)
                return reply
            when = (
                timeutil.format_slot_short(session.proposed_slot)
                if session.proposed_slot
                else "that time"
            )
            reply = AgentReply(
                f"Reply yes to book {when}, or no to cancel.",
                propose_buttons_for=session.proposed_slot,
            )
            self._persist(session)
            return reply

        # Stale yes/no when nothing is pending
        if (_looks_yes(text) or nlu.intent == "confirm") and session.proposed_slot is None:
            if session.state not in {
                ConversationState.AWAITING_CANCEL_CONFIRM,
                ConversationState.AWAITING_RESCHEDULE,
            }:
                reply = AgentReply(
                    "There's nothing pending to confirm. Tell me a day and time "
                    '(e.g. "Can I book Monday at 2pm?").'
                )
                self._persist(session)
                return reply
        if (_looks_no(text) or nlu.intent == "decline") and session.state == ConversationState.IDLE:
            reply = AgentReply("Nothing to cancel — how can I help?")
            self._persist(session)
            return reply

        if session.state == ConversationState.AWAITING_EMAIL:
            if nlu.email and is_valid_email(nlu.email):
                session.email = nlu.email.strip()
                if session.proposed_slot:
                    session.state = (
                        ConversationState.AWAITING_ALT_CONFIRM
                        if session.requested_slot
                        and session.proposed_slot != session.requested_slot
                        else ConversationState.AWAITING_SLOT_CONFIRM
                    )
                    when = timeutil.format_slot_short(session.proposed_slot)
                    day = timeutil.to_clinic(session.proposed_slot).strftime("%A")
                    reply = AgentReply(
                        f"Thanks — got {session.email}. Shall I book {day} {when}?",
                        propose_buttons_for=session.proposed_slot,
                    )
                    self._persist(session)
                    return reply
                session.state = ConversationState.IDLE
                reply = AgentReply(
                    "Thanks, I've saved your email. What day and time should we book?"
                )
                self._persist(session)
                return reply
            if nlu.intent in {"provide_email", "book", "unclear", "confirm"}:
                reply = AgentReply(
                    "I need a valid email for confirmation (e.g. name@example.com)."
                )
                self._persist(session)
                return reply

        if nlu.intent == "greeting":
            reply = AgentReply(
                f"Hello! Welcome to {business.CLINIC_NAME}. "
                f"I can book a {business.SLOT_MINUTES}-minute appointment "
                f"({business.HOURS_BLURB}) or answer questions about the clinic."
            )
            self._persist(session)
            return reply

        if nlu.intent == "cancel":
            reply = await self._start_cancel(session)
            self._persist(session)
            return reply

        if nlu.intent == "reschedule":
            reply = await self._start_reschedule(session)
            self._persist(session)
            return reply

        if nlu.intent == "waitlist":
            reply = await self._join_waitlist(session)
            self._persist(session)
            return reply

        if nlu.intent == "faq":
            faq = business.match_faq(text)
            reply = AgentReply(faq or business.FAQ_ANSWERS["hours"])
            self._persist(session)
            return reply

        if nlu.intent == "provide_email" and session.email:
            reply = AgentReply(f"Thanks — I've noted {session.email}. How can I help?")
            self._persist(session)
            return reply

        if nlu.intent == "book" or (nlu.requested_start and nlu.intent != "unclear"):
            reply = await self._handle_booking_request(session, nlu)
            self._persist(session)
            return reply

        faq = business.match_faq(text)
        if faq:
            reply = AgentReply(faq)
            self._persist(session)
            return reply

        reply = AgentReply(
            "I can help book an appointment (e.g. “Can I book Monday at 2pm?”), "
            "cancel or reschedule, or answer questions about location, parking, hours, or walk-ins."
        )
        self._persist(session)
        return reply

    async def _start_cancel(self, session: Session) -> AgentReply:
        store = get_booking_store()
        booking = store.get_active_booking(session.chat_id)
        if not booking and session.last_booking_id:
            booking = store.get_active_booking(session.chat_id)
        if not booking:
            return AgentReply(
                "I don't see an upcoming appointment on file. "
                "If you booked elsewhere, message the clinic directly."
            )
        when = timeutil.format_slot_short(booking.start)
        day = timeutil.to_clinic(booking.start).strftime("%A")
        session.pending_cancel_event_id = booking.event_id
        session.state = ConversationState.AWAITING_CANCEL_CONFIRM
        return AgentReply(
            f"Your appointment is {day} {when}. Reply yes to cancel it, or no to keep it."
        )

    async def _handle_cancel_confirm(
        self, session: Session, nlu: IntentResult, text: str
    ) -> AgentReply:
        if nlu.intent == "decline" or _looks_no(text):
            session.state = ConversationState.IDLE
            session.pending_cancel_event_id = None
            return AgentReply("Okay — your appointment stays as booked.")

        if not (nlu.intent == "confirm" or _looks_yes(text)):
            return AgentReply("Reply yes to cancel your appointment, or no to keep it.")

        event_id = session.pending_cancel_event_id
        if not event_id:
            session.state = ConversationState.IDLE
            return AgentReply("I lost track of which appointment to cancel. Try again?")

        store = get_booking_store()
        booking = store.get_active_booking(session.chat_id)
        if not booking or booking.event_id != event_id:
            session.state = ConversationState.IDLE
            session.pending_cancel_event_id = None
            return AgentReply("That appointment is no longer active.")

        cal = self._cal()
        if not cal.delete_appointment(event_id):
            return AgentReply(
                "I couldn't cancel the calendar event just now. Please try again shortly."
            )

        store.update_status(event_id, BookingStatus.CANCELLED)
        send_cancellation_email(booking.email, booking.start)
        when = timeutil.format_slot_short(booking.start)
        day = timeutil.to_clinic(booking.start).strftime("%A")

        audit_log.add(
            chat_id=session.chat_id,
            intent="cancelled",
            state=ConversationState.IDLE.value,
            booking_id=event_id,
        )

        session.state = ConversationState.IDLE
        session.pending_cancel_event_id = None
        session.last_booking_id = None
        return AgentReply(f"Done — your {day} {when} appointment has been cancelled.")

    async def _start_reschedule(self, session: Session) -> AgentReply:
        store = get_booking_store()
        booking = store.get_active_booking(session.chat_id)
        if not booking:
            return AgentReply(
                "I don't see an upcoming appointment to reschedule. "
                'Want to book one? Try "Can I book Monday at 2pm?"'
            )
        when = timeutil.format_slot_short(booking.start)
        day = timeutil.to_clinic(booking.start).strftime("%A")
        session.reschedule_event_id = booking.event_id
        session.state = ConversationState.AWAITING_RESCHEDULE
        session.proposed_slot = None
        return AgentReply(
            f"Your current appointment is {day} {when}. "
            "What new day and time would you like? (e.g. Tuesday at 3pm)"
        )

    async def _handle_reschedule_turn(
        self, session: Session, nlu: IntentResult, text: str
    ) -> AgentReply:
        if nlu.intent == "decline" or _looks_no(text):
            session.state = ConversationState.IDLE
            session.reschedule_event_id = None
            return AgentReply("Okay — keeping your current appointment.")

        if session.proposed_slot and (nlu.intent == "confirm" or _looks_yes(text)):
            return await self._complete_reschedule(session)

        if nlu.requested_start or nlu.intent == "book":
            if not nlu.requested_start:
                return AgentReply(
                    "What day and time should we move it to? (e.g. Wednesday at 11am)"
                )
            requested = timeutil.to_clinic(nlu.requested_start)
            if requested.weekday() not in business.BUSINESS_WEEKDAYS:
                return AgentReply(
                    f"We're closed on weekends. {business.HOURS_BLURB}"
                )
            if not is_within_business_hours(requested):
                return AgentReply(
                    f"{timeutil.format_slot_short(requested)} isn't within business hours. "
                    f"{business.HOURS_BLURB}"
                )
            cal = self._cal()
            event_id = session.reschedule_event_id
            if not event_id:
                session.state = ConversationState.IDLE
                return AgentReply("I lost track of your appointment. Try reschedule again?")

            if cal.is_slot_free(requested):
                session.proposed_slot = requested
                session.state = ConversationState.AWAITING_SLOT_CONFIRM
                when = timeutil.format_slot(requested)
                return AgentReply(
                    f"I can move your appointment to {when} — shall I confirm?",
                    propose_buttons_for=requested,
                )

            nearest = cal_mod.nearest_available(requested, cal)
            if nearest is None:
                session.waitlist_date = requested.date().isoformat()
                day_name = requested.strftime("%A")
                return AgentReply(
                    f"No openings on {day_name} at or after "
                    f"{timeutil.format_slot_short(requested)}. "
                    "Try another day, or reply 'notify me' for the waitlist."
                )
            session.proposed_slot = nearest
            session.state = ConversationState.AWAITING_ALT_CONFIRM
            return AgentReply(
                f"{timeutil.format_slot_short(requested)} isn't available. "
                f"Nearest is {timeutil.format_slot_short(nearest)} — book that instead?",
                propose_buttons_for=nearest,
            )

        return AgentReply(
            "Tell me the new day and time (e.g. Friday at 2pm), or say no to keep your slot."
        )

    async def _complete_reschedule(self, session: Session) -> AgentReply:
        event_id = session.reschedule_event_id
        if not event_id or not session.proposed_slot:
            session.state = ConversationState.IDLE
            return AgentReply("I don't have a new time to reschedule to.")

        store = get_booking_store()
        booking = store.get_active_booking(session.chat_id)
        if not booking or booking.event_id != event_id:
            session.state = ConversationState.IDLE
            session.reschedule_event_id = None
            return AgentReply("That appointment is no longer active.")

        new_start = timeutil.to_clinic(session.proposed_slot)
        cal = self._cal()
        if not cal.reschedule_appointment(event_id, new_start, booking.email):
            return AgentReply(
                "That slot isn't available anymore. Pick another time?"
            )

        store.update_start(event_id, new_start, BookingStatus.BOOKED)
        send_confirmation_email(booking.email, new_start, booking_id=event_id)

        when = timeutil.format_slot_short(new_start)
        day = new_start.strftime("%A")
        session.state = ConversationState.IDLE
        session.proposed_slot = None
        session.reschedule_event_id = None

        audit_log.add(
            chat_id=session.chat_id,
            intent="rescheduled",
            state=session.state.value,
            proposed_slot=new_start.isoformat(),
            booking_id=event_id,
        )

        return AgentReply(f"Done — moved to {day} {when}. Anything else?")

    async def _join_waitlist(self, session: Session) -> AgentReply:
        target_date = None
        if session.waitlist_date:
            from datetime import date

            target_date = date.fromisoformat(session.waitlist_date)
        elif session.requested_slot:
            target_date = timeutil.to_clinic(session.requested_slot).date()
        else:
            return AgentReply(
                "Which day should I watch for openings? Try booking first, "
                "then say 'notify me' if that day is full."
            )

        if not is_valid_email(session.email):
            session.state = ConversationState.AWAITING_EMAIL
            return AgentReply(
                "I'll need your email for waitlist alerts. What's the best address?"
            )

        store = get_booking_store()
        store.add_waitlist(session.chat_id, target_date, session.email)
        day_name = target_date.strftime("%A")
        return AgentReply(
            f"You're on the waitlist for {day_name}. I'll message you if a slot opens."
        )

    async def _handle_booking_request(self, session: Session, nlu: IntentResult) -> AgentReply:
        if not nlu.requested_start:
            return AgentReply(
                "Sure — what day and time work for you? We're open "
                f"{business.HOURS_BLURB}"
            )

        requested = timeutil.to_clinic(nlu.requested_start)
        session.requested_slot = requested

        if requested.weekday() not in business.BUSINESS_WEEKDAYS:
            return AgentReply(
                f"We're closed on weekends. {business.HOURS_BLURB} Want a weekday slot?"
            )

        if not is_within_business_hours(requested):
            return AgentReply(
                f"{timeutil.format_slot_short(requested)} isn't within business hours. "
                f"{business.HOURS_BLURB}"
            )

        cal = self._cal()
        if cal.is_slot_free(requested):
            session.proposed_slot = requested
            if not is_valid_email(session.email):
                session.state = ConversationState.AWAITING_EMAIL
                return AgentReply(
                    f"{timeutil.format_slot(requested)} looks free. "
                    "What's the best email for your confirmation?"
                )
            session.state = ConversationState.AWAITING_SLOT_CONFIRM
            when = timeutil.format_slot(requested)
            return AgentReply(
                f"{when} is available — shall I book that?",
                propose_buttons_for=requested,
            )

        nearest = cal_mod.nearest_available(requested, cal)
        if nearest is None:
            session.state = ConversationState.IDLE
            session.proposed_slot = None
            session.waitlist_date = requested.date().isoformat()
            day_name = requested.strftime("%A")
            return AgentReply(
                f"No openings remain on {day_name} at or after "
                f"{timeutil.format_slot_short(requested)}. "
                "Want another day, or reply 'notify me' to join the waitlist?"
            )

        session.proposed_slot = nearest
        req_s = timeutil.format_slot_short(requested)
        near_s = timeutil.format_slot_short(nearest)
        day_name = requested.strftime("%A")
        if not is_valid_email(session.email):
            session.state = ConversationState.AWAITING_EMAIL
            return AgentReply(
                f"{req_s} {day_name} isn't available. The nearest opening is {near_s} — "
                "what's your email so I can confirm if you'd like that?"
            )
        session.state = ConversationState.AWAITING_ALT_CONFIRM
        return AgentReply(
            f"{req_s} {day_name} isn't available. The nearest opening is {near_s} — shall I book that?",
            propose_buttons_for=nearest,
        )

    async def _book_proposed(self, session: Session) -> AgentReply:
        if session.reschedule_event_id and session.state in {
            ConversationState.AWAITING_SLOT_CONFIRM,
            ConversationState.AWAITING_ALT_CONFIRM,
        }:
            return await self._complete_reschedule(session)

        if session.booking_in_progress:
            return AgentReply("I'm already booking that slot — one moment.")

        if not session.proposed_slot:
            session.state = ConversationState.IDLE
            return AgentReply("I don't have a slot to confirm. What day and time should we try?")

        if not is_valid_email(session.email):
            session.state = ConversationState.AWAITING_EMAIL
            return AgentReply(
                "Before I book, I need a valid email for confirmation (e.g. name@example.com)."
            )

        lock = session_store.lock_for(session.chat_id)
        async with lock:
            if session.booking_in_progress:
                return AgentReply("I'm already booking that slot — one moment.")
            if not session.proposed_slot:
                return AgentReply(
                    "I don't have a slot to confirm. What day and time should we try?"
                )
            session.booking_in_progress = True
            try:
                reply = await self._complete_booking(session)
                if reply.text.startswith("I couldn't create") or "Calendar ID not found" in reply.text or "Share the calendar" in reply.text:
                    session.state = ConversationState.IDLE
                    session.proposed_slot = None
                    session.requested_slot = None
                return reply
            finally:
                session.booking_in_progress = False

    async def _complete_booking(self, session: Session) -> AgentReply:
        assert session.proposed_slot is not None
        assert session.email is not None
        start = timeutil.to_clinic(session.proposed_slot)
        cal = self._cal()

        if not cal.is_slot_free(start, slot_end(start)):
            nearest = cal_mod.nearest_available(start, cal)
            session.proposed_slot = nearest
            session.state = (
                ConversationState.AWAITING_ALT_CONFIRM if nearest else ConversationState.IDLE
            )
            if nearest is None:
                return AgentReply(
                    "That slot was just taken and nothing else is left today. Try another day?"
                )
            return AgentReply(
                f"That slot was just taken. The nearest opening is "
                f"{timeutil.format_slot_short(nearest)} — shall I book that?",
                propose_buttons_for=nearest,
            )

        try:
            event_id = cal.create_appointment(start, session.email)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Calendar create failed")
            detail = str(exc).strip()
            if "Share the calendar" in detail or "Calendar ID not found" in detail:
                return AgentReply(detail)
            return AgentReply(
                "I couldn't create the calendar event just now. Please try again in a moment."
            )

        email_status = send_confirmation_email(session.email, start, booking_id=event_id)
        session.last_booking_id = event_id
        get_booking_store().add_booking(
            session.chat_id, event_id, start, session.email
        )
        session.state = ConversationState.BOOKED
        when = timeutil.format_slot(start)
        day = start.strftime("%A")
        short = timeutil.format_slot_short(start)

        audit_log.add(
            chat_id=session.chat_id,
            intent="booked",
            state=session.state.value,
            proposed_slot=start.isoformat(),
            booking_id=event_id,
            email_status=email_status,
        )

        session.state = ConversationState.IDLE
        session.proposed_slot = None
        session.requested_slot = None

        extra = ""
        if email_status == "failed":
            extra = " (I couldn't send the email confirmation — please check with the clinic.)"
        elif email_status == "skipped":
            extra = " (Email confirmation was skipped — SMTP isn't configured.)"

        return AgentReply(
            f"Done — you're booked for {day} {short}. Anything else?{extra}"
        )


def _looks_yes(text: str) -> bool:
    return bool(re.search(r"^\s*(yes|yeah|yep|y|sure|ok|okay|book it)\s*[!.]?\s*$", text, re.I))


def _looks_no(text: str) -> bool:
    return bool(re.search(r"^\s*(no|nope|nah|cancel)\s*[!.]?\s*$", text, re.I))


agent = BookingAgent()
