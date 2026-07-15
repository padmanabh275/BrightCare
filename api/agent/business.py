"""BrightCare business constants and FAQ answers."""

from __future__ import annotations

CLINIC_NAME = "BrightCare Clinic"
LOCATION = "12 Orchard Rd"
OPEN_HOUR = 9
CLOSE_HOUR = 18
SLOT_MINUTES = 30
LAST_START_HOUR = 17
LAST_START_MINUTE = 30
BUSINESS_WEEKDAYS = {0, 1, 2, 3, 4}  # Mon–Fri

HOURS_BLURB = "Monday–Friday, 09:00–18:00 (clinic local time). Closed weekends."

FAQ_ANSWERS: dict[str, str] = {
    "location": f"We're at {LOCATION}.",
    "address": f"We're at {LOCATION}.",
    "walk-in": "We don't accept walk-ins — appointments only. I can help you book one.",
    "walkin": "We don't accept walk-ins — appointments only. I can help you book one.",
    "cancel": 'Say "cancel my appointment" and I\'ll help you cancel your booking.',
    "parking": "Yes — parking is available on-site.",
    "hours": f"Our hours are {HOURS_BLURB}",
    "open": f"Our hours are {HOURS_BLURB}",
}


def match_faq(text: str) -> str | None:
    lowered = text.lower()
    for key, answer in FAQ_ANSWERS.items():
        if key in lowered:
            return answer
    if "where" in lowered and ("are" in lowered or "located" in lowered or "address" in lowered):
        return FAQ_ANSWERS["location"]
    if "park" in lowered:
        return FAQ_ANSWERS["parking"]
    return None
