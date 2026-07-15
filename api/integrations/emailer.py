"""Email confirmation via Gmail SMTP with optional .ics attachment."""

from __future__ import annotations

import logging
import smtplib
import uuid
from datetime import datetime
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders

from api.agent import business, timeutil
from api.integrations.calendar import slot_end
from api.config import get_settings

logger = logging.getLogger(__name__)


def build_ics(
    start: datetime,
    patient_email: str,
    event_uid: str | None = None,
) -> str:
    start = timeutil.to_clinic(start)
    end = slot_end(start)
    uid = event_uid or f"{uuid.uuid4()}@brightcare"
    # Floating local times with TZID for clinic timezone
    tzid = get_settings().clinic_timezone
    dt_start = start.strftime("%Y%m%dT%H%M%S")
    dt_end = end.strftime("%Y%m%dT%H%M%S")
    stamp = timeutil.as_utc(timeutil.clinic_now()).strftime("%Y%m%dT%H%M%SZ")
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
        f"ORGANIZER:MAILTO:{get_settings().smtp_from or 'noreply@brightcare.local'}",
        f"ATTENDEE:MAILTO:{patient_email}",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(lines) + "\r\n"


def smtp_configured() -> bool:
    s = get_settings()
    return bool(s.smtp_user and s.smtp_app_password and s.smtp_from)


def send_confirmation_email(
    patient_email: str,
    start: datetime,
    booking_id: str | None = None,
) -> str:
    """Send confirmation. Returns 'sent' | 'skipped' | 'failed'."""
    settings = get_settings()
    if not smtp_configured():
        logger.warning("SMTP not configured; skipping email")
        return "skipped"

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

    msg = MIMEMultipart()
    msg["From"] = settings.smtp_from or ""
    msg["To"] = patient_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    ics = build_ics(start, patient_email, event_uid=booking_id)
    part = MIMEBase("text", "calendar", method="PUBLISH", name="appointment.ics")
    part.set_payload(ics.encode("utf-8"))
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename="appointment.ics")
    part.add_header("Content-Class", "urn:content-classes:calendarmessage")
    msg.attach(part)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
            server.starttls()
            server.login(settings.smtp_user or "", settings.smtp_app_password or "")
            server.sendmail(settings.smtp_from or "", [patient_email], msg.as_string())
        return "sent"
    except Exception:  # noqa: BLE001
        logger.exception("Failed to send confirmation email")
        return "failed"


def send_cancellation_email(
    patient_email: str,
    start: datetime,
) -> str:
    """Send cancellation notice. Returns 'sent' | 'skipped' | 'failed'."""
    settings = get_settings()
    if not smtp_configured():
        return "skipped"

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

    msg = MIMEMultipart()
    msg["From"] = settings.smtp_from or ""
    msg["To"] = patient_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
            server.starttls()
            server.login(settings.smtp_user or "", settings.smtp_app_password or "")
            server.sendmail(settings.smtp_from or "", [patient_email], msg.as_string())
        return "sent"
    except Exception:  # noqa: BLE001
        logger.exception("Failed to send cancellation email")
        return "failed"


def send_patient_letter(
    patient_email: str,
    subject: str,
    body: str,
) -> str:
    """Send staff-approved patient communication. Returns 'sent' | 'skipped' | 'failed'."""
    settings = get_settings()
    if not smtp_configured():
        logger.warning("SMTP not configured; skipping patient letter")
        return "skipped"

    msg = MIMEMultipart()
    msg["From"] = settings.smtp_from or ""
    msg["To"] = patient_email.strip()
    msg["Subject"] = subject.strip() or f"Message from {business.CLINIC_NAME}"
    msg.attach(MIMEText(body.strip(), "plain"))

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
            server.starttls()
            server.login(settings.smtp_user or "", settings.smtp_app_password or "")
            server.sendmail(
                settings.smtp_from or "",
                [patient_email.strip()],
                msg.as_string(),
            )
        return "sent"
    except Exception:  # noqa: BLE001
        logger.exception("Failed to send patient letter to %s", patient_email)
        return "failed"
