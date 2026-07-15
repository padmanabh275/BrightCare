"""Lightweight integration health probes for the dashboard."""

from __future__ import annotations

import logging
import smtplib
from typing import Any

import httpx

from api.config import get_settings
from api.integrations.calendar import get_calendar

logger = logging.getLogger(__name__)

API = "https://api.telegram.org"


async def probe_telegram() -> dict[str, Any]:
    settings = get_settings()
    if not settings.telegram_bot_token:
        return {"ok": False, "detail": "TELEGRAM_BOT_TOKEN not set"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{API}/bot{settings.telegram_bot_token}/getMe")
            data = resp.json()
        if data.get("ok"):
            user = data.get("result", {})
            return {"ok": True, "detail": f"@{user.get('username', 'bot')}"}
        return {"ok": False, "detail": data.get("description", "getMe failed")}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Telegram probe failed")
        return {"ok": False, "detail": str(exc)}


def probe_calendar() -> dict[str, Any]:
    settings = get_settings()
    if not settings.google_service_account_file or not settings.google_calendar_id:
        return {"ok": False, "detail": "Using in-memory calendar (env not set)"}
    try:
        cal = get_calendar()
        if cal.ping():
            return {"ok": True, "detail": "Google Calendar reachable"}
        return {"ok": False, "detail": "Calendar ping failed — share calendar with service account"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": str(exc)}


def probe_email() -> dict[str, Any]:
    """Prefer Resend (HTTPS) on Render free; SMTP only works on paid / local."""
    settings = get_settings()
    if settings.resend_api_key:
        if not settings.email_from:
            return {"ok": False, "detail": "RESEND_API_KEY set but EMAIL_FROM / RESEND_FROM missing"}
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    "https://api.resend.com/domains",
                    headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                )
            if resp.status_code < 400:
                return {"ok": True, "detail": "Resend API reachable (HTTPS)"}
            return {"ok": False, "detail": f"Resend API {resp.status_code}: {resp.text[:120]}"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "detail": str(exc)}

    if not settings.smtp_user or not settings.smtp_app_password:
        return {
            "ok": False,
            "detail": "Set RESEND_API_KEY (+ EMAIL_FROM) for Render free, or SMTP_* locally",
        }
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_app_password)
        return {"ok": True, "detail": "SMTP login OK"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": str(exc)}


def probe_openai() -> dict[str, Any]:
    settings = get_settings()
    if not settings.openai_api_key:
        return {"ok": False, "detail": "OPENAI_API_KEY not set (heuristics only)"}
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        models = client.models.list()
        count = len(list(models.data[:1]))
        if count >= 0:
            return {"ok": True, "detail": f"OpenAI API reachable ({settings.openai_model})"}
        return {"ok": False, "detail": "No models returned"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": str(exc)}


async def run_all_probes() -> dict[str, Any]:
    telegram = await probe_telegram()
    calendar = probe_calendar()
    email = probe_email()
    openai = probe_openai()
    return {
        "telegram": telegram,
        "calendar": calendar,
        "email": email,
        "openai": openai,
        "all_ok": all(p["ok"] for p in (telegram, calendar, email, openai)),
    }
