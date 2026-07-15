"""Email via Resend HTTPS (Render-safe) with Gmail SMTP fallback for local."""

from __future__ import annotations

import base64
import logging
import smtplib
import uuid
from datetime import datetime
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders

import httpx

from api.agent import business, timeutil
from api.integrations.calendar import slot_end
from api.config import get_settings

logger = logging.getLogger(__name__)

RESEND_API = "https://api.resend.com/emails"


def build_ics(
    start: datetime,
    patient_email: str,
    event_uid: str | None = None,
) -> str:
    start = timeutil.to_clinic(start)
    end = slot_end(start)
    uid = event_uid or f"{uuid.uuid4()}@brightcare"
    tzid = get_settings().clinic_timezone
    dt_start = start.strftime("%Y%m%dT%H%M%S")
    dt_end = end.strftime("%Y%m%dT%H%M%S")
    stamp = timeutil.as_utc(timeutil.clinic_now()).strftime("%Y%m%dT%H%M%SZ")
    organizer = get_settings().email_from or "noreply@brightcare.local"
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//BrightCare Clinic//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{stamp}",
        f"DTSTART;TZID={tzid}:{dt_start}",
        f"DTEND;TZID={tzid}:{dt_end}",
        f"SUMMARY:{business.CLINIC_NAME} appointment",
        f"DESCRIPTION:Appointment at {business.CLINIC_NAME}\\, {business.LOCATION}",
        f"LOCATION:{business.LOCATION}",
        f"ORGANIZER:MAILTO:{organizer}",
        f"ATTENDEE:MAILTO:{patient_email}",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(lines) + "\r\n"


def smtp_configured() -> bool:
    s = get_settings()
    return bool(s.smtp_user and s.smtp_app_password and s.email_from)


def resend_configured() -> bool:
    s = get_settings()
    return bool(s.resend_api_key and s.email_from)


def email_configured() -> bool:
    """True if any outbound email transport is ready (prefer Resend on Render)."""
    return resend_configured() or smtp_configured()


def _send_via_resend(
    to_email: str,
    subject: str,
    body: str,
    *,
    ics_filename: str | None = None,
    ics_body: str | None = None,
) -> None:
    settings = get_settings()
    payload: dict[str, object] = {
        "from": settings.email_from,
        "to": [to_email],
        "subject": subject,
        "text": body,
    }
    if ics_filename and ics_body:
        payload["attachments"] = [
            {
                "filename": ics_filename,
                "content": base64.b64encode(ics_body.encode("utf-8")).decode("ascii"),
            }
        ]
    headers = {
        "Authorization": f"Bearer {settings.resend_api_key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(RESEND_API, json=payload, headers=headers)
        if resp.status_code >= 400:
            raise RuntimeError(f"Resend API {resp.status_code}: {resp.text[:300]}")


def _send_via_smtp(
    to_email: str,
    subject: str,
    body: str,
    *,
    ics_filename: str | None = None,
    ics_body: str | None = None,
) -> None:
    settings = get_settings()
    msg = MIMEMultipart()
    msg["From"] = settings.email_from or ""
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    if ics_filename and ics_body:
        part = MIMEBase("text", "calendar", method="PUBLISH", name=ics_filename)
        part.set_payload(ics_body.encode("utf-8"))
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition", "attachment", filename=ics_filename
        )
        part.add_header("Content-Class", "urn:content-classes:calendarmessage")
        msg.attach(part)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
        server.starttls()
        server.login(settings.smtp_user or "", settings.smtp_app_password or "")
        server.sendmail(settings.email_from or "", [to_email], msg.as_string())


def _deliver(
    to_email: str,
    subject: str,
    body: str,
    *,
    ics_filename: str | None = None,
    ics_body: str | None = None,
) -> str:
    """Returns 'sent' | 'skipped' | 'failed'."""
    if not email_configured():
        logger.warning("Email not configured (set RESEND_API_KEY or SMTP_*); skipping")
        return "skipped"

    try:
        if resend_configured():
            _send_via_resend(
                to_email,
                subject,
                body,
                ics_filename=ics_filename,
                ics_body=ics_body,
            )
        else:
            _send_via_smtp(
                to_email,
                subject,
                body,
                ics_filename=ics_filename,
                ics_body=ics_body,
            )
        return "sent"
    except Exception:  # noqa: BLE001
        logger.exception("Failed to send email to %s", to_email)
        return "failed"


def send_confirmation_email(
    patient_email: str,
    start: datetime,
    booking_id: str | None = None,
) -> str:
    """Send confirmation. Returns 'sent' | 'skipped' | 'failed'."""
    start = timeutil.to_clinic(start)
    when = timeutil.format_slot(start)
    subject = f"Your appointment at {business.CLINIC_NAME}"
    body = (
        f"Hello,\n\n"
        f"You're booked at {business.CLINIC_NAME}.\n\n"
        f"When: {when}\n"
        f"Where: {business.LOCATION}\n"
        f"Length: {business.SLOT_MINUTES} minutes\n\n"
        f"To cancel, message the clinic on Telegram.\n\n"
        f"— {business.CLINIC_NAME}\n"
    )
    ics = build_ics(start, patient_email, event_uid=booking_id)
    return _deliver(
        patient_email,
        subject,
        body,
        ics_filename="appointment.ics",
        ics_body=ics,
    )


def send_cancellation_email(
    patient_email: str,
    start: datetime,
) -> str:
    """Send cancellation notice. Returns 'sent' | 'skipped' | 'failed'."""
    start = timeutil.to_clinic(start)
    when = timeutil.format_slot(start)
    subject = f"Appointment cancelled — {business.CLINIC_NAME}"
    body = (
        f"Hello,\n\n"
        f"Your appointment at {business.CLINIC_NAME} has been cancelled.\n\n"
        f"Was: {when}\n"
        f"Where: {business.LOCATION}\n\n"
        f"To book again, message us on Telegram.\n\n"
        f"— {business.CLINIC_NAME}\n"
    )
    return _deliver(patient_email, subject, body)


def send_patient_letter(
    patient_email: str,
    subject: str,
    body: str,
) -> str:
    """Send staff-approved patient communication. Returns 'sent' | 'skipped' | 'failed'."""
    return _deliver(
        patient_email.strip(),
        subject.strip() or f"Message from {business.CLINIC_NAME}",
        body.strip(),
    )
