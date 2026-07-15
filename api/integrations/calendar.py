"""Google Calendar integration with clinic-timezone slot rules."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Protocol

from api.agent import business, timeutil
from api.config import get_settings

logger = logging.getLogger(__name__)


class CalendarClient(Protocol):
    def is_slot_free(self, start: datetime, end: datetime | None = None) -> bool: ...

    def create_appointment(
        self,
        start: datetime,
        patient_email: str,
        summary: str | None = None,
    ) -> str: ...

    def delete_appointment(self, event_id: str) -> bool: ...

    def reschedule_appointment(
        self,
        event_id: str,
        new_start: datetime,
        patient_email: str | None = None,
    ) -> bool: ...

    def ping(self) -> bool: ...


def iter_slot_starts(day: date) -> list[datetime]:
    """Valid 30-minute starts for a clinic-local day (09:00 … 17:30)."""
    if day.weekday() not in business.BUSINESS_WEEKDAYS:
        return []
    starts: list[datetime] = []
    cursor = timeutil.combine_clinic(day, business.OPEN_HOUR, 0)
    last = timeutil.combine_clinic(
        day, business.LAST_START_HOUR, business.LAST_START_MINUTE
    )
    step = timedelta(minutes=business.SLOT_MINUTES)
    while cursor <= last:
        starts.append(cursor)
        cursor += step
    return starts


def slot_end(start: datetime) -> datetime:
    start = timeutil.to_clinic(start)
    return start + timedelta(minutes=business.SLOT_MINUTES)


def is_within_business_hours(start: datetime) -> bool:
    start = timeutil.to_clinic(start)
    if start.weekday() not in business.BUSINESS_WEEKDAYS:
        return False
    if start.minute not in (0, 30):
        return False
    opens = timeutil.combine_clinic(start.date(), business.OPEN_HOUR, 0)
    last = timeutil.combine_clinic(
        start.date(), business.LAST_START_HOUR, business.LAST_START_MINUTE
    )
    return opens <= start.replace(second=0, microsecond=0) <= last


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def find_nearest_slot(
    requested_start: datetime,
    busy_periods: list[tuple[datetime, datetime]],
) -> datetime | None:
    """Soonest free 30-min start >= requested, same clinic day; else None."""
    requested = timeutil.to_clinic(requested_start)
    day = requested.date()
    for start in iter_slot_starts(day):
        if start < requested:
            continue
        end = slot_end(start)
        if any(overlaps(start, end, b0, b1) for b0, b1 in busy_periods):
            continue
        return start
    return None


def _normalize_busy(
    busy_periods: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    out: list[tuple[datetime, datetime]] = []
    for b0, b1 in busy_periods:
        out.append((timeutil.to_clinic(b0), timeutil.to_clinic(b1)))
    return out


class InMemoryCalendar:
    """Test double that tracks busy intervals in process memory."""

    def __init__(self, busy: list[tuple[datetime, datetime]] | None = None) -> None:
        self.busy: list[tuple[datetime, datetime]] = _normalize_busy(busy or [])
        self.events: list[dict] = []

    def ping(self) -> bool:
        return True

    def get_busy_for_day(self, day: date) -> list[tuple[datetime, datetime]]:
        day_start = timeutil.combine_clinic(day, 0, 0)
        day_end = day_start + timedelta(days=1)
        return [
            (a, b)
            for a, b in self.busy
            if overlaps(a, b, day_start, day_end)
        ]

    def is_slot_free(self, start: datetime, end: datetime | None = None) -> bool:
        start = timeutil.to_clinic(start)
        end = timeutil.to_clinic(end) if end else slot_end(start)
        if not is_within_business_hours(start):
            return False
        return not any(overlaps(start, end, b0, b1) for b0, b1 in self.busy)

    def create_appointment(
        self,
        start: datetime,
        patient_email: str,
        summary: str | None = None,
    ) -> str:
        start = timeutil.to_clinic(start)
        end = slot_end(start)
        if not self.is_slot_free(start, end):
            raise RuntimeError("Slot is no longer available")
        event_id = f"evt-{len(self.events) + 1}"
        self.busy.append((start, end))
        self.events.append(
            {
                "id": event_id,
                "start": start,
                "end": end,
                "email": patient_email,
                "summary": summary or f"{business.CLINIC_NAME} appointment",
            }
        )
        return event_id

    def delete_appointment(self, event_id: str) -> bool:
        for i, evt in enumerate(self.events):
            if evt["id"] != event_id:
                continue
            start = evt["start"]
            end = evt["end"]
            self.busy = [
                (a, b) for a, b in self.busy if not (a == start and b == end)
            ]
            del self.events[i]
            return True
        return False

    def reschedule_appointment(
        self,
        event_id: str,
        new_start: datetime,
        patient_email: str | None = None,
    ) -> bool:
        new_start = timeutil.to_clinic(new_start)
        new_end = slot_end(new_start)
        if not is_within_business_hours(new_start):
            return False
        for evt in self.events:
            if evt["id"] != event_id:
                continue
            old_start, old_end = evt["start"], evt["end"]
            self.busy = [
                (a, b) for a, b in self.busy if not (a == old_start and b == old_end)
            ]
            if any(overlaps(new_start, new_end, b0, b1) for b0, b1 in self.busy):
                self.busy.append((old_start, old_end))
                return False
            evt["start"] = new_start
            evt["end"] = new_end
            if patient_email:
                evt["email"] = patient_email
            self.busy.append((new_start, new_end))
            return True
        return False


class GoogleCalendarClient:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.google_service_account_file or not settings.google_calendar_id:
            raise RuntimeError(
                "GOOGLE_SERVICE_ACCOUNT_FILE and GOOGLE_CALENDAR_ID are required"
            )
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        scopes = ["https://www.googleapis.com/auth/calendar"]
        creds = service_account.Credentials.from_service_account_file(
            settings.google_service_account_file, scopes=scopes
        )
        self._service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        self._calendar_id = settings.google_calendar_id
        self._tz_name = settings.clinic_timezone

    def ping(self) -> bool:
        try:
            self._service.calendars().get(calendarId=self._calendar_id).execute()
            return True
        except Exception:  # noqa: BLE001
            logger.exception("Calendar ping failed")
            return False

    def get_busy_for_day(self, day: date) -> list[tuple[datetime, datetime]]:
        start_utc, end_utc = timeutil.day_bounds_utc(day)
        body = {
            "timeMin": start_utc.isoformat().replace("+00:00", "Z"),
            "timeMax": end_utc.isoformat().replace("+00:00", "Z"),
            "timeZone": self._tz_name,
            "items": [{"id": self._calendar_id}],
        }
        result = self._service.freebusy().query(body=body).execute()
        calendars = result.get("calendars", {})
        entry = calendars.get(self._calendar_id, {})
        if entry.get("errors"):
            raise RuntimeError(
                "Google Calendar not accessible to the service account "
                f"({self._calendar_id}). Share the calendar with the service "
                "account email (permission: Make changes to events), then restart."
            )
        busy_raw = entry.get("busy", [])
        periods: list[tuple[datetime, datetime]] = []
        for item in busy_raw:
            b0 = datetime.fromisoformat(item["start"].replace("Z", "+00:00"))
            b1 = datetime.fromisoformat(item["end"].replace("Z", "+00:00"))
            periods.append((timeutil.to_clinic(b0), timeutil.to_clinic(b1)))
        return periods

    def is_slot_free(self, start: datetime, end: datetime | None = None) -> bool:
        start = timeutil.to_clinic(start)
        end = timeutil.to_clinic(end) if end else slot_end(start)
        if not is_within_business_hours(start):
            return False
        busy = self.get_busy_for_day(start.date())
        return not any(overlaps(start, end, b0, b1) for b0, b1 in busy)

    def create_appointment(
        self,
        start: datetime,
        patient_email: str,
        summary: str | None = None,
    ) -> str:
        start = timeutil.to_clinic(start)
        end = slot_end(start)
        if not self.is_slot_free(start, end):
            raise RuntimeError("Slot is no longer available")
        body = {
            "summary": summary or f"{business.CLINIC_NAME} appointment",
            "description": f"Patient email: {patient_email}",
            "start": {
                "dateTime": start.isoformat(),
                "timeZone": self._tz_name,
            },
            "end": {
                "dateTime": end.isoformat(),
                "timeZone": self._tz_name,
            },
            # Attendee invites often fail for service accounts without domain-wide
            # delegation; keep email in description and send confirmation via SMTP.
        }
        try:
            created = (
                self._service.events()
                .insert(calendarId=self._calendar_id, body=body, sendUpdates="none")
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            if "404" in msg or "notFound" in msg:
                raise RuntimeError(
                    "Google Calendar ID not found for this service account. "
                    "Open Google Calendar → Settings → share with your service "
                    "account email as 'Make changes to events', and set "
                    "GOOGLE_CALENDAR_ID to that calendar's ID."
                ) from exc
            raise
        return created.get("id", "unknown")

    def delete_appointment(self, event_id: str) -> bool:
        try:
            self._service.events().delete(
                calendarId=self._calendar_id, eventId=event_id
            ).execute()
            return True
        except Exception:  # noqa: BLE001
            logger.exception("Calendar delete failed for %s", event_id)
            return False

    def reschedule_appointment(
        self,
        event_id: str,
        new_start: datetime,
        patient_email: str | None = None,
    ) -> bool:
        new_start = timeutil.to_clinic(new_start)
        new_end = slot_end(new_start)
        body: dict = {
            "start": {"dateTime": new_start.isoformat(), "timeZone": self._tz_name},
            "end": {"dateTime": new_end.isoformat(), "timeZone": self._tz_name},
        }
        if patient_email:
            body["description"] = f"Patient email: {patient_email}"
        try:
            self._service.events().patch(
                calendarId=self._calendar_id,
                eventId=event_id,
                body=body,
            ).execute()
            return True
        except Exception:  # noqa: BLE001
            logger.exception("Calendar reschedule failed for %s", event_id)
            return False


_calendar: CalendarClient | None = None


def get_calendar() -> CalendarClient:
    global _calendar
    if _calendar is not None:
        return _calendar
    settings = get_settings()
    if settings.google_service_account_file and settings.google_calendar_id:
        try:
            _calendar = GoogleCalendarClient()
            return _calendar
        except Exception:  # noqa: BLE001
            logger.exception("Falling back to in-memory calendar")
    _calendar = InMemoryCalendar()
    return _calendar


def set_calendar(client: CalendarClient | None) -> None:
    global _calendar
    _calendar = client


def nearest_available(requested_start: datetime, client: CalendarClient | None = None) -> datetime | None:
    cal = client or get_calendar()
    requested = timeutil.to_clinic(requested_start)
    if hasattr(cal, "get_busy_for_day"):
        busy = cal.get_busy_for_day(requested.date())  # type: ignore[attr-defined]
    else:
        # Fallback: probe each slot
        busy = []
        for start in iter_slot_starts(requested.date()):
            if not cal.is_slot_free(start):
                busy.append((start, slot_end(start)))
    return find_nearest_slot(requested, busy)


def list_available_slots(day: date, client: CalendarClient | None = None) -> list[datetime]:
    """All free 30-min starts on a clinic-local weekday."""
    cal = client or get_calendar()
    if day.weekday() not in business.BUSINESS_WEEKDAYS:
        return []
    if hasattr(cal, "get_busy_for_day"):
        busy = cal.get_busy_for_day(day)  # type: ignore[attr-defined]
    else:
        busy = []
        for start in iter_slot_starts(day):
            if not cal.is_slot_free(start):
                busy.append((start, slot_end(start)))
    free: list[datetime] = []
    for start in iter_slot_starts(day):
        end = slot_end(start)
        if any(overlaps(start, end, b0, b1) for b0, b1 in busy):
            continue
        free.append(start)
    return free
