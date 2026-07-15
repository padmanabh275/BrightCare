"""Staff consultation-note assistant."""

from __future__ import annotations

import json
import logging
from typing import Any

from api.config import get_settings

logger = logging.getLogger(__name__)


def generate_consultation_artifacts(notes: str, patient_name: str | None = None) -> dict[str, Any]:
    """
    From raw consultation notes, produce:
    - professional summary
    - action items
    - patient-friendly email draft
    """
    cleaned = (notes or "").strip()
    if len(cleaned) < 20:
        raise ValueError("Please provide at least a few sentences of consultation notes.")

    settings = get_settings()
    name = (patient_name or "the patient").strip() or "the patient"

    if not settings.openai_api_key:
        return _heuristic_artifacts(cleaned, name)

    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        system = (
            "You are a clinical documentation assistant for BrightCare Clinic. "
            "Given physician consultation notes, return ONLY JSON with keys: "
            "summary (string: professional medical-record style summary, 2-4 paragraphs), "
            "action_items (array of 3-8 short imperative strings for clinician follow-up), "
            "patient_email_subject (string), "
            "patient_email_body (string: clear patient-friendly email, no jargon dump, "
            "include clinic sign-off BrightCare Clinic). "
            "Do not invent diagnoses not supported by the notes. "
            "If details are missing, say so briefly rather than fabricating."
        )
        user = f"Patient name: {name}\n\nConsultation notes:\n{cleaned}"
        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
        return {
            "summary": str(data.get("summary") or "").strip() or cleaned,
            "action_items": _normalize_items(data.get("action_items")),
            "patient_email": {
                "subject": str(
                    data.get("patient_email_subject")
                    or f"Follow-up from your visit — BrightCare Clinic"
                ).strip(),
                "body": str(data.get("patient_email_body") or "").strip()
                or _default_email_body(name, cleaned),
            },
        }
    except Exception:  # noqa: BLE001
        logger.exception("OpenAI notes generation failed; using heuristics")
        return _heuristic_artifacts(cleaned, name)


def _normalize_items(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    items = [str(x).strip() for x in raw if str(x).strip()]
    return items[:12]


def _heuristic_artifacts(notes: str, name: str) -> dict[str, Any]:
    sentences = [s.strip() for s in notes.replace("\n", " ").split(".") if s.strip()]
    summary = (
        f"Consultation summary for {name}.\n\n"
        + (". ".join(sentences[:4]) + ("." if sentences else notes[:400]))
        + "\n\nGenerated locally without OpenAI — review before charting."
    )
    action_items = [
        "Review generated summary against original notes",
        "Confirm medications or dosages with the clinician",
        "Schedule follow-up if clinically indicated",
        "Send patient communication after review",
    ]
    return {
        "summary": summary,
        "action_items": action_items,
        "patient_email": {
            "subject": "Follow-up from your visit — BrightCare Clinic",
            "body": _default_email_body(name, notes),
        },
    }


def _default_email_body(name: str, notes: str) -> str:
    preview = notes.strip().split("\n")[0][:180]
    return (
        f"Dear {name},\n\n"
        "Thank you for visiting BrightCare Clinic. "
        "Here is a brief summary of what we discussed:\n\n"
        f"{preview}\n\n"
        "If you have questions or need to book a follow-up, "
        "message us on Telegram or reply to this email.\n\n"
        "Warm regards,\n"
        "BrightCare Clinic\n"
        "12 Orchard Rd · Mon–Fri 09:00–18:00"
    )
