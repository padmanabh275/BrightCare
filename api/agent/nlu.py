"""OpenAI-backed intent / slot extraction."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any, Literal

from api.agent import timeutil
from api.config import get_settings

logger = logging.getLogger(__name__)

Intent = Literal[
    "greeting",
    "faq",
    "book",
    "confirm",
    "decline",
    "provide_email",
    "cancel",
    "reschedule",
    "waitlist",
    "unclear",
]

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


@dataclass
class IntentResult:
    intent: Intent
    email: str | None = None
    requested_start: datetime | None = None
    faq_topic: str | None = None
    raw: dict[str, Any] | None = None


def extract_email(text: str) -> str | None:
    match = EMAIL_RE.search(text)
    return match.group(0) if match else None


def is_valid_email(value: str | None) -> bool:
    if not value:
        return False
    return bool(EMAIL_RE.fullmatch(value.strip()))


def _parse_time_token(token: str) -> time | None:
    token = token.strip().lower().replace(" ", "")
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?(am|pm)?$", token)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    ampm = m.group(3)
    if ampm == "pm" and hour < 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    if not ampm and hour <= 7:
        # Heuristic: bare 1–7 likely pm in clinic context
        hour += 12
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def heuristic_parse(text: str) -> IntentResult:
    lowered = text.strip().lower()
    email = extract_email(text)

    if re.search(r"\b(yes|yeah|yep|sure|ok|okay|book it|confirm)\b", lowered):
        return IntentResult(intent="confirm", email=email)
    if re.search(r"\b(no|nope|never ?mind|don't)\b", lowered) and "cancel my" not in lowered:
        return IntentResult(intent="decline", email=email)
    if re.search(r"\b(cancel my|cancel the|cancel appointment|cancel booking)\b", lowered):
        return IntentResult(intent="cancel", email=email)
    if re.search(r"\b(reschedule|move my|change my appointment)\b", lowered):
        return IntentResult(intent="reschedule", email=email)
    if re.search(r"\b(notify me|waitlist|alert me)\b", lowered):
        return IntentResult(intent="waitlist", email=email)
    if email and len(lowered.split()) <= 3:
        return IntentResult(intent="provide_email", email=email)
    if re.search(r"\b(hi|hello|hey|good morning|good afternoon)\b", lowered):
        return IntentResult(intent="greeting", email=email)

    # FAQ-ish (but not cancel/reschedule actions)
    if any(
        k in lowered
        for k in ("where", "address", "park", "walk-in", "walkin", "hour", "open")
    ):
        return IntentResult(intent="faq", email=email)
    if "cancel" in lowered and "cancel my" not in lowered and "cancel the" not in lowered:
        return IntentResult(intent="faq", email=email)

    requested: datetime | None = None
    weekday = None
    for name, idx in WEEKDAYS.items():
        if name in lowered:
            weekday = idx
            break

    time_match = re.search(
        r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b",
        lowered,
        flags=re.IGNORECASE,
    )
    if weekday is not None and time_match:
        t = _parse_time_token(time_match.group(1))
        if t:
            day = timeutil.next_weekday(timeutil.clinic_now(), weekday)
            requested = timeutil.combine_clinic(day, t.hour, t.minute)

    if requested or re.search(r"\b(book|appointment|schedule|available|slot)\b", lowered):
        return IntentResult(intent="book", email=email, requested_start=requested)

    if email:
        return IntentResult(intent="provide_email", email=email)
    return IntentResult(intent="unclear", email=email)


def parse_intent(text: str) -> IntentResult:
    settings = get_settings()
    if not settings.openai_api_key:
        return heuristic_parse(text)

    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        now = timeutil.clinic_now()
        system = (
            "You extract booking intents for BrightCare Clinic. "
            f"Clinic timezone is {settings.clinic_timezone}. "
            f"Current clinic-local datetime is {now.isoformat()}. "
            "Return ONLY compact JSON with keys: "
            "intent (greeting|faq|book|confirm|decline|provide_email|cancel|reschedule|waitlist|unclear), "
            "email (string|null), "
            "weekday (monday..sunday|null), "
            "time (HH:MM 24h|null), "
            "faq_topic (string|null). "
            "Resolve relative weekdays to the next occurrence from current clinic date. "
            "Do not invent times."
        )
        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
        result = _from_llm_json(data, text)
        if result.intent == "unclear":
            fallback = heuristic_parse(text)
            if fallback.intent in {"cancel", "reschedule", "waitlist"}:
                return fallback
        return result
    except Exception:  # noqa: BLE001
        logger.exception("OpenAI NLU failed; using heuristics")
        return heuristic_parse(text)


def _from_llm_json(data: dict[str, Any], original: str) -> IntentResult:
    intent = data.get("intent") or "unclear"
    if intent not in {
        "greeting",
        "faq",
        "book",
        "confirm",
        "decline",
        "provide_email",
        "cancel",
        "reschedule",
        "waitlist",
        "unclear",
    }:
        intent = "unclear"
    email = data.get("email") or extract_email(original)
    requested = None
    weekday_name = (data.get("weekday") or "").lower() or None
    time_str = data.get("time")
    if weekday_name in WEEKDAYS and time_str:
        try:
            parts = str(time_str).split(":")
            hour, minute = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
            day = timeutil.next_weekday(timeutil.clinic_now(), WEEKDAYS[weekday_name])
            requested = timeutil.combine_clinic(day, hour, minute)
        except (ValueError, IndexError):
            requested = None
    if intent == "book" and requested is None:
        # Fall back to heuristic time parse
        fallback = heuristic_parse(original)
        requested = fallback.requested_start
    return IntentResult(
        intent=intent,  # type: ignore[arg-type]
        email=email,
        requested_start=requested,
        faq_topic=data.get("faq_topic"),
        raw=data,
    )
