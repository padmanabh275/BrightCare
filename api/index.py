"""BrightCare FastAPI application."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from api.agent.audit import audit_log
from api.agent.bookings import get_booking_store
from api.agent.fsm import agent
from api.agent.nlu import WEEKDAYS, is_valid_email
from api.agent.rate_limit import chat_rate_limiter
from api.agent.session import ConversationState, session_store
from api.agent import timeutil
from api.config import get_settings
from api.integrations.calendar import get_calendar, list_available_slots
from api.integrations.emailer import send_patient_letter, smtp_configured
from api.integrations.health_probes import run_all_probes
from api.integrations.telegram_bot import telegram_runtime
from api.jobs.reminders import run_reminders, run_waitlist_check
from api.notes import generate_consultation_artifacts
from api.telegram_app import miniapp_confirm, miniapp_request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    if settings.telegram_mode == "polling" and settings.telegram_bot_token:
        telegram_runtime.start_polling()
    elif settings.telegram_mode == "webhook":
        logger.info("Telegram webhook mode — POST /telegram/webhook")
        await telegram_runtime.register_webhook()
        await telegram_runtime.configure_menu_button()
    else:
        logger.warning("Telegram bot not started (missing token or mode)")
    yield
    await telegram_runtime.stop()


app = FastAPI(title="BrightCare Clinic API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _verify_clerk_token(token: str) -> None:
    settings = get_settings()
    if not settings.clerk_jwks_url:
        return
    import jwt
    from jwt import PyJWKClient

    jwks_client = PyJWKClient(settings.clerk_jwks_url)
    signing_key = jwks_client.get_signing_key_from_jwt(token)
    jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        options={"verify_aud": False},
    )


def _verify_jobs_secret(header: str | None) -> None:
    settings = get_settings()
    if not settings.jobs_secret:
        return
    if header != settings.jobs_secret:
        raise HTTPException(status_code=403, detail="Invalid jobs secret")


async def _agent_handle(chat_id: str, text: str):
    if not chat_rate_limiter.allow(chat_id):
        from api.agent.fsm import AgentReply

        return AgentReply(
            "You're sending messages too quickly — please wait a moment and try again."
        )
    return await agent.handle(chat_id, text)


@app.get("/health")
def health() -> dict[str, Any]:
    settings = get_settings()
    return {
        "ok": True,
        "service": "brightcare",
        "clinic_timezone": settings.clinic_timezone,
        "telegram_mode": settings.telegram_mode,
        "bot_running": telegram_runtime.running,
    }


@app.get("/api/status")
async def status(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    settings = get_settings()
    if settings.clerk_jwks_url:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="Unauthorized")
        try:
            _verify_clerk_token(authorization.split(" ", 1)[1])
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=401, detail="Invalid token") from exc

    probes = await run_all_probes()
    sessions = session_store.all_sessions()
    active = [s for s in sessions if s.state != ConversationState.IDLE]
    booking_store = get_booking_store()
    return {
        "clinic_timezone": settings.clinic_timezone,
        "clinic_name": settings.clinic_name,
        "bot": {
            "running": telegram_runtime.running or settings.telegram_mode == "webhook",
            "mode": settings.telegram_mode,
            "username": settings.telegram_bot_username,
        },
        "integrations": {
            "calendar": probes["calendar"]["ok"],
            "calendar_mode": "google"
            if settings.google_service_account_file and settings.google_calendar_id
            else "memory",
            "email": probes["email"]["ok"],
            "openai": probes["openai"]["ok"],
            "telegram": probes["telegram"]["ok"],
        },
        "integration_details": probes,
        "active_sessions": len(active),
        "sessions": [s.to_status() for s in sessions][:20],
        "recent_events": audit_log.recent()[:20],
        "recent_bookings": [b.to_public() for b in booking_store.list_recent(15)],
    }


@app.get("/api/telegram/slots")
async def telegram_slots(
    weekday: str = Query(default="monday"),
) -> dict[str, Any]:
    """Return available 30-min slot starts for the next occurrence of weekday."""
    name = weekday.strip().lower()
    if name not in WEEKDAYS:
        raise HTTPException(status_code=400, detail="weekday must be monday..friday")
    day = timeutil.next_weekday(timeutil.clinic_now(), WEEKDAYS[name])
    cal = get_calendar()
    slots = list_available_slots(day, cal)
    return {
        "weekday": name,
        "date": day.isoformat(),
        "slots": [
            {
                "start": s.isoformat(),
                "label": timeutil.format_slot_short(s),
            }
            for s in slots
        ],
    }


@app.get("/api/telegram/appointments")
async def telegram_appointments(
    chat_id: str = Query(..., min_length=1),
) -> dict[str, Any]:
    """Masked appointment history for a Telegram chat."""
    records = get_booking_store().list_for_chat(chat_id, limit=10)
    return {
        "appointments": [r.to_public() for r in records],
    }


@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, str]:
    settings = get_settings()
    if settings.telegram_webhook_secret:
        if x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
            raise HTTPException(status_code=403, detail="Bad webhook secret")
    update = await request.json()
    await telegram_runtime.handle_update(update)
    return {"ok": "true"}


@app.post("/api/telegram/book")
async def telegram_book(payload: dict[str, Any]) -> dict[str, Any]:
    """Telegram Mini App booking: request availability or confirm."""
    chat_id = str(payload.get("chat_id") or "").strip()
    if not chat_id:
        raise HTTPException(status_code=400, detail="chat_id required")

    action = str(payload.get("action") or "request").lower()
    if action == "confirm":
        return await miniapp_confirm(chat_id)

    weekday = str(payload.get("weekday") or "monday").lower()
    time_hhmm = str(payload.get("time") or "14:00")
    email = str(payload.get("email") or "").strip()
    if not email:
        raise HTTPException(status_code=400, detail="email required")
    return await miniapp_request(chat_id, weekday, time_hhmm, email)


@app.post("/api/dev/chat")
async def dev_chat(payload: dict[str, Any]) -> dict[str, Any]:
    """Local testing without Telegram: {\"chat_id\", \"text\"}."""
    chat_id = str(payload.get("chat_id") or "dev")
    text = str(payload.get("text") or "")
    reply = await _agent_handle(chat_id, text)
    return {
        "reply": reply.text,
        "propose": reply.propose_buttons_for.isoformat()
        if reply.propose_buttons_for
        else None,
    }


@app.post("/api/jobs/reminders")
async def jobs_reminders(
    x_jobs_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    _verify_jobs_secret(x_jobs_secret)
    return await run_reminders()


@app.post("/api/jobs/waitlist")
async def jobs_waitlist(
    x_jobs_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    _verify_jobs_secret(x_jobs_secret)
    return await run_waitlist_check()


@app.post("/api/notes/generate")
async def notes_generate(
    payload: dict[str, Any],
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Staff: turn raw consultation notes into summary + actions + patient email."""
    _require_clerk(authorization)

    notes = str(payload.get("notes") or "")
    patient_name = str(payload.get("patient_name") or "").strip() or None
    try:
        result = generate_consultation_artifacts(notes, patient_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


def _require_clerk(authorization: str | None) -> None:
    settings = get_settings()
    if not settings.clerk_jwks_url:
        return
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        _verify_clerk_token(authorization.split(" ", 1)[1])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=401, detail="Invalid token") from exc


@app.post("/api/notes/send")
async def notes_send(
    payload: dict[str, Any],
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Staff: send approved patient email draft via SMTP."""
    _require_clerk(authorization)

    patient_email = str(payload.get("patient_email") or "").strip()
    subject = str(payload.get("subject") or "").strip()
    body = str(payload.get("body") or "").strip()

    if not is_valid_email(patient_email):
        raise HTTPException(status_code=400, detail="Valid patient_email required")
    if not subject or not body:
        raise HTTPException(status_code=400, detail="subject and body required")
    if not smtp_configured():
        raise HTTPException(
            status_code=503,
            detail="SMTP is not configured — set SMTP_USER and SMTP_APP_PASSWORD",
        )

    status = send_patient_letter(patient_email, subject, body)
    audit_log.add(
        chat_id="staff",
        intent="notes_email_sent" if status == "sent" else f"notes_email_{status}",
        state=None,
        email_status=status,
        message=f"To {patient_email[:3]}…",
    )

    if status == "failed":
        raise HTTPException(
            status_code=502,
            detail="Could not send email — check SMTP credentials and try again",
        )
    if status == "skipped":
        raise HTTPException(status_code=503, detail="Email sending skipped")

    return {"status": "sent", "to": patient_email}
