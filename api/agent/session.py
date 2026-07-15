"""Conversation sessions with optional SQLite persistence."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from api.agent import timeutil


class ConversationState(str, Enum):
    IDLE = "idle"
    AWAITING_EMAIL = "awaiting_email"
    AWAITING_SLOT_CONFIRM = "awaiting_slot_confirm"
    AWAITING_ALT_CONFIRM = "awaiting_alt_confirm"
    AWAITING_CANCEL_CONFIRM = "awaiting_cancel_confirm"
    AWAITING_RESCHEDULE = "awaiting_reschedule"
    BOOKED = "booked"


@dataclass
class Session:
    chat_id: str
    state: ConversationState = ConversationState.IDLE
    email: str | None = None
    proposed_slot: datetime | None = None
    requested_slot: datetime | None = None
    patient_name: str | None = None
    updated_at: datetime | None = None
    booking_in_progress: bool = False
    last_booking_id: str | None = None
    pending_cancel_event_id: str | None = None
    reschedule_event_id: str | None = None
    waitlist_date: str | None = None

    def to_status(self) -> dict[str, Any]:
        return {
            "chat_id": _mask_chat(self.chat_id),
            "state": self.state.value,
            "has_email": bool(self.email),
            "proposed_slot": self.proposed_slot.isoformat() if self.proposed_slot else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


def _mask_chat(chat_id: str) -> str:
    if len(chat_id) <= 4:
        return "***"
    return f"…{chat_id[-4:]}"


def _dt_to_json(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _dt_from_json(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def get(self, chat_id: str) -> Session:
        if chat_id not in self._sessions:
            self._sessions[chat_id] = Session(chat_id=chat_id)
        return self._sessions[chat_id]

    def all_sessions(self) -> list[Session]:
        return list(self._sessions.values())

    def lock_for(self, chat_id: str) -> asyncio.Lock:
        if chat_id not in self._locks:
            self._locks[chat_id] = asyncio.Lock()
        return self._locks[chat_id]

    def save(self, session: Session) -> None:
        self._sessions[session.chat_id] = session

    def clear_all(self) -> None:
        self._sessions.clear()
        self._locks.clear()


class SqliteSessionStore(SessionStore):
    def __init__(self, db_path: Path) -> None:
        super().__init__()
        self._path = db_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._db_lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._db_lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS sessions (
                        chat_id TEXT PRIMARY KEY,
                        payload TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

    def _row_to_session(self, row: sqlite3.Row) -> Session:
        data = json.loads(row["payload"])
        return Session(
            chat_id=str(data["chat_id"]),
            state=ConversationState(data.get("state", "idle")),
            email=data.get("email"),
            proposed_slot=_dt_from_json(data.get("proposed_slot")),
            requested_slot=_dt_from_json(data.get("requested_slot")),
            patient_name=data.get("patient_name"),
            updated_at=_dt_from_json(data.get("updated_at")),
            booking_in_progress=bool(data.get("booking_in_progress")),
            last_booking_id=data.get("last_booking_id"),
            pending_cancel_event_id=data.get("pending_cancel_event_id"),
            reschedule_event_id=data.get("reschedule_event_id"),
            waitlist_date=data.get("waitlist_date"),
        )

    def _session_payload(self, session: Session) -> str:
        return json.dumps(
            {
                "chat_id": session.chat_id,
                "state": session.state.value,
                "email": session.email,
                "proposed_slot": _dt_to_json(session.proposed_slot),
                "requested_slot": _dt_to_json(session.requested_slot),
                "patient_name": session.patient_name,
                "updated_at": _dt_to_json(session.updated_at),
                "booking_in_progress": session.booking_in_progress,
                "last_booking_id": session.last_booking_id,
                "pending_cancel_event_id": session.pending_cancel_event_id,
                "reschedule_event_id": session.reschedule_event_id,
                "waitlist_date": session.waitlist_date,
            }
        )

    def get(self, chat_id: str) -> Session:
        if chat_id in self._sessions:
            return self._sessions[chat_id]
        with self._db_lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT payload FROM sessions WHERE chat_id = ?", (chat_id,)
                ).fetchone()
            finally:
                conn.close()
        if row:
            session = self._row_to_session(row)
            self._sessions[chat_id] = session
            return session
        session = Session(chat_id=chat_id)
        self._sessions[chat_id] = session
        return session

    def save(self, session: Session) -> None:
        self._sessions[session.chat_id] = session
        with self._db_lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO sessions (chat_id, payload, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(chat_id) DO UPDATE SET
                        payload = excluded.payload,
                        updated_at = excluded.updated_at
                    """,
                    (
                        session.chat_id,
                        self._session_payload(session),
                        (session.updated_at or timeutil.clinic_now()).isoformat(),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def all_sessions(self) -> list[Session]:
        with self._db_lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT payload FROM sessions ORDER BY updated_at DESC LIMIT 50"
                ).fetchall()
            finally:
                conn.close()
        sessions = [self._row_to_session(r) for r in rows]
        for s in sessions:
            self._sessions[s.chat_id] = s
        return sessions

    def clear_all(self) -> None:
        super().clear_all()
        with self._db_lock:
            conn = self._connect()
            try:
                conn.execute("DELETE FROM sessions")
                conn.commit()
            finally:
                conn.close()


def _build_session_store() -> SessionStore:
    from api.config import get_settings

    settings = get_settings()
    if settings.session_store == "memory":
        return SessionStore()
    db_path = settings.data_dir / "sessions.db"
    return SqliteSessionStore(db_path)


session_store = _build_session_store()
