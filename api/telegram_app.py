"""Telegram Mini App booking API helpers."""

from __future__ import annotations

from api.agent.fsm import AgentReply, BookingAgent, agent as default_agent
from api.agent.session import ConversationState, session_store


def _human_time(hhmm: str) -> str:
    """Convert 14:00 → 2pm for NLU-friendly text."""
    parts = hhmm.strip().split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0
    h12 = hour % 12 or 12
    ampm = "am" if hour < 12 else "pm"
    if minute:
        return f"{h12}:{minute:02d}{ampm}"
    return f"{h12}{ampm}"


async def miniapp_request(
    chat_id: str,
    weekday: str,
    time_hhmm: str,
    email: str,
    booking_agent: BookingAgent | None = None,
) -> dict[str, str | None]:
    """Check slot / propose alternate; may require confirm step."""
    bot = booking_agent or default_agent
    session = session_store.get(chat_id)
    session.email = email.strip()

    text = f"Can I book {weekday} at {_human_time(time_hhmm)}?"
    reply: AgentReply = await bot.handle(chat_id, text)

    if session.state in {
        ConversationState.AWAITING_SLOT_CONFIRM,
        ConversationState.AWAITING_ALT_CONFIRM,
    }:
        return {
            "status": "confirm",
            "message": reply.text,
            "proposed_slot": session.proposed_slot.isoformat()
            if session.proposed_slot
            else None,
        }
    if "Done" in reply.text and "booked" in reply.text.lower():
        return {"status": "booked", "message": reply.text, "proposed_slot": None}
    if session.state == ConversationState.AWAITING_EMAIL:
        return {"status": "need_email", "message": reply.text, "proposed_slot": None}
    return {"status": "error", "message": reply.text, "proposed_slot": None}


async def miniapp_confirm(
    chat_id: str,
    booking_agent: BookingAgent | None = None,
) -> dict[str, str | None]:
    bot = booking_agent or default_agent
    reply = await bot.handle(chat_id, "yes")
    if "Done" in reply.text:
        return {"status": "booked", "message": reply.text, "proposed_slot": None}
    session = session_store.get(chat_id)
    if session.state in {
        ConversationState.AWAITING_SLOT_CONFIRM,
        ConversationState.AWAITING_ALT_CONFIRM,
    }:
        return {
            "status": "confirm",
            "message": reply.text,
            "proposed_slot": session.proposed_slot.isoformat()
            if session.proposed_slot
            else None,
        }
    return {"status": "error", "message": reply.text, "proposed_slot": None}
