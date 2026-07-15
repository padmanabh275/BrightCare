"""Persistent booking history and waitlist (SQLite)."""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from api.agent import timeutil


class BookingStatus(str, Enum):
    BOOKED = "booked"
    CANCELLED = "cancelled"
    RESCHEDULED = "rescheduled"


@dataclass
class BookingRecord:
    id: int
    chat_id: str
    event_id: str
    start: datetime
    email: str
    status: BookingStatus
    created_at: datetime
    reminder_24h_sent: bool = False
    reminder_1h_sent: bool = False

    def to_public(self) -> dict[str, Any]:
        local = timeutil.to_clinic(self.start)
        return {
            "id": self.id,
            "event_id": self.event_id[:8] + "…" if len(self.event_id) > 8 else self.event_id,
            "start": timeutil.format_slot(local),
            "start_iso": local.isoformat(),
            "status": self.status.value,
            "email_masked": _mask_email(self.email),
        }


@dataclass
class WaitlistEntry:
    id: int
    chat_id: str
    target_date: date
    email: str
    created_at: datetime
    notified: bool = False


def _mask_email(email: str) -> str:
    if "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        return f"**@{domain}"
    return f"{local[0]}…{local[-1]}@{domain}"


class BookingStore:
    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS bookings (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id TEXT NOT NULL,
                        event_id TEXT NOT NULL,
                        start_iso TEXT NOT NULL,
                        email TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'booked',
                        created_at TEXT NOT NULL,
                        reminder_24h_sent INTEGER NOT NULL DEFAULT 0,
                        reminder_1h_sent INTEGER NOT NULL DEFAULT 0
                    );
                    CREATE INDEX IF NOT EXISTS idx_bookings_chat ON bookings(chat_id);
                    CREATE INDEX IF NOT EXISTS idx_bookings_status ON bookings(status);

                    CREATE TABLE IF NOT EXISTS waitlist (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id TEXT NOT NULL,
                        target_date TEXT NOT NULL,
                        email TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        notified INTEGER NOT NULL DEFAULT 0
                    );
                    CREATE INDEX IF NOT EXISTS idx_waitlist_date ON waitlist(target_date);
                    """
                )
                conn.commit()
            finally:
                conn.close()

    def add_booking(
        self,
        chat_id: str,
        event_id: str,
        start: datetime,
        email: str,
    ) -> BookingRecord:
        now = timeutil.clinic_now()
        start_local = timeutil.to_clinic(start)
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    """
                    INSERT INTO bookings (chat_id, event_id, start_iso, email, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chat_id,
                        event_id,
                        start_local.isoformat(),
                        email,
                        BookingStatus.BOOKED.value,
                        now.isoformat(),
                    ),
                )
                conn.commit()
                row_id = int(cur.lastrowid)
            finally:
                conn.close()
        return BookingRecord(
            id=row_id,
            chat_id=chat_id,
            event_id=event_id,
            start=start_local,
            email=email,
            status=BookingStatus.BOOKED,
            created_at=now,
        )

    def update_status(self, event_id: str, status: BookingStatus) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE bookings SET status = ? WHERE event_id = ?",
                    (status.value, event_id),
                )
                conn.commit()
            finally:
                conn.close()

    def update_start(self, event_id: str, new_start: datetime, status: BookingStatus) -> None:
        start_local = timeutil.to_clinic(new_start)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE bookings SET start_iso = ?, status = ? WHERE event_id = ?",
                    (start_local.isoformat(), status.value, event_id),
                )
                conn.commit()
            finally:
                conn.close()

    def get_active_booking(self, chat_id: str) -> BookingRecord | None:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    """
                    SELECT * FROM bookings
                    WHERE chat_id = ? AND status = ?
                    ORDER BY start_iso DESC
                    LIMIT 1
                    """,
                    (chat_id, BookingStatus.BOOKED.value),
                ).fetchone()
            finally:
                conn.close()
        return _row_to_booking(row) if row else None

    def list_for_chat(self, chat_id: str, limit: int = 10) -> list[BookingRecord]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT * FROM bookings
                    WHERE chat_id = ?
                    ORDER BY start_iso DESC
                    LIMIT ?
                    """,
                    (chat_id, limit),
                ).fetchall()
            finally:
                conn.close()
        return [_row_to_booking(r) for r in rows]

    def list_recent(self, limit: int = 20) -> list[BookingRecord]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM bookings ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            finally:
                conn.close()
        return [_row_to_booking(r) for r in rows]

    def upcoming_for_reminders(self) -> list[BookingRecord]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT * FROM bookings
                    WHERE status = ?
                    ORDER BY start_iso ASC
                    """,
                    (BookingStatus.BOOKED.value,),
                ).fetchall()
            finally:
                conn.close()
        return [_row_to_booking(r) for r in rows]

    def mark_reminder_sent(self, booking_id: int, kind: str) -> None:
        col = "reminder_24h_sent" if kind == "24h" else "reminder_1h_sent"
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(f"UPDATE bookings SET {col} = 1 WHERE id = ?", (booking_id,))
                conn.commit()
            finally:
                conn.close()

    def add_waitlist(self, chat_id: str, target_date: date, email: str) -> WaitlistEntry:
        now = timeutil.clinic_now()
        with self._lock:
            conn = self._connect()
            try:
                existing = conn.execute(
                    """
                    SELECT id FROM waitlist
                    WHERE chat_id = ? AND target_date = ? AND notified = 0
                    """,
                    (chat_id, target_date.isoformat()),
                ).fetchone()
                if existing:
                    row = conn.execute(
                        "SELECT * FROM waitlist WHERE id = ?", (existing["id"],)
                    ).fetchone()
                    return _row_to_waitlist(row)

                cur = conn.execute(
                    """
                    INSERT INTO waitlist (chat_id, target_date, email, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (chat_id, target_date.isoformat(), email, now.isoformat()),
                )
                conn.commit()
                row_id = int(cur.lastrowid)
                row = conn.execute("SELECT * FROM waitlist WHERE id = ?", (row_id,)).fetchone()
            finally:
                conn.close()
        return _row_to_waitlist(row)

    def pending_waitlist_for_date(self, target_date: date) -> list[WaitlistEntry]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT * FROM waitlist
                    WHERE target_date = ? AND notified = 0
                    ORDER BY created_at ASC
                    """,
                    (target_date.isoformat(),),
                ).fetchall()
            finally:
                conn.close()
        return [_row_to_waitlist(r) for r in rows]

    def mark_waitlist_notified(self, entry_id: int) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("UPDATE waitlist SET notified = 1 WHERE id = ?", (entry_id,))
                conn.commit()
            finally:
                conn.close()


def _row_to_booking(row: sqlite3.Row) -> BookingRecord:
    return BookingRecord(
        id=int(row["id"]),
        chat_id=str(row["chat_id"]),
        event_id=str(row["event_id"]),
        start=datetime.fromisoformat(row["start_iso"]),
        email=str(row["email"]),
        status=BookingStatus(row["status"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        reminder_24h_sent=bool(row["reminder_24h_sent"]),
        reminder_1h_sent=bool(row["reminder_1h_sent"]),
    )


def _row_to_waitlist(row: sqlite3.Row) -> WaitlistEntry:
    return WaitlistEntry(
        id=int(row["id"]),
        chat_id=str(row["chat_id"]),
        target_date=date.fromisoformat(row["target_date"]),
        email=str(row["email"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        notified=bool(row["notified"]),
    )


_store: BookingStore | None = None


def get_booking_store() -> BookingStore:
    global _store
    if _store is None:
        from api.config import get_settings

        settings = get_settings()
        _store = BookingStore(settings.data_dir / "bookings.db")
    return _store


def reset_booking_store(store: BookingStore | None = None) -> None:
    global _store
    _store = store
