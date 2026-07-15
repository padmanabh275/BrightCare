"""Clinic-timezone helpers."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from api.config import get_settings


def clinic_tz() -> ZoneInfo:
    return get_settings().clinic_tz


def clinic_now() -> datetime:
    return datetime.now(clinic_tz())


def ensure_aware(dt: datetime, tz: ZoneInfo | None = None) -> datetime:
    zone = tz or clinic_tz()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=zone)
    return dt.astimezone(zone)


def to_clinic(dt: datetime) -> datetime:
    return ensure_aware(dt).astimezone(clinic_tz())


def as_utc(dt: datetime) -> datetime:
    return ensure_aware(dt).astimezone(timezone.utc)


def combine_clinic(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=clinic_tz())


def day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    """UTC start/end covering a clinic-local calendar day."""
    start = combine_clinic(day, 0, 0)
    end = start + timedelta(days=1)
    return as_utc(start), as_utc(end)


def format_slot(dt: datetime) -> str:
    local = to_clinic(dt)
    # Example: Monday 15:00 SGT
    abbrev = local.tzname() or get_settings().clinic_timezone
    return f"{local.strftime('%A %H:%M')} {abbrev}"


def format_slot_short(dt: datetime) -> str:
    local = to_clinic(dt)
    hour = local.hour % 12 or 12
    ampm = "am" if local.hour < 12 else "pm"
    return f"{hour}:{local.minute:02d}{ampm}"


def next_weekday(from_dt: datetime, weekday: int) -> date:
    """Next occurrence of weekday (Mon=0) at or after from_dt's date in clinic TZ."""
    local = to_clinic(from_dt)
    days_ahead = (weekday - local.weekday()) % 7
    return (local + timedelta(days=days_ahead)).date()


def upcoming_business_days(count: int = 10, from_dt: datetime | None = None) -> list[date]:
    """Next `count` Mon–Fri clinic dates starting today (or from_dt)."""
    from api.agent import business

    local = to_clinic(from_dt or clinic_now())
    days: list[date] = []
    cursor = local.date()
    while len(days) < count:
        if cursor.weekday() in business.BUSINESS_WEEKDAYS:
            days.append(cursor)
        cursor = cursor + timedelta(days=1)
    return days


def format_day_label(day: date) -> str:
    """e.g. Mon 20 Jul."""
    return f"{day.strftime('%a')} {day.day} {day.strftime('%b')}"
