"""Database URL helpers (Neon Postgres + local SQLite fallback)."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator

logger = logging.getLogger(__name__)


def normalize_database_url(url: str) -> str:
    """psycopg expects postgresql://; Neon often issues postgres://."""
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://") :]
    return url


def get_database_url() -> str | None:
    from api.config import _env

    raw = _env("DATABASE_URL") or _env("NEON_DATABASE_URL")
    return normalize_database_url(raw) if raw else None


@contextmanager
def pg_connection() -> Iterator[Any]:
    """Yield a psycopg connection with dict rows."""
    import psycopg
    from psycopg.rows import dict_row

    url = get_database_url()
    if not url:
        raise RuntimeError("DATABASE_URL / NEON_DATABASE_URL is not set")
    conn = psycopg.connect(url, row_factory=dict_row, connect_timeout=15)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_postgres_schema() -> None:
    """Create BrightCare tables on Neon/Postgres if missing."""
    statements = [
        """
        CREATE TABLE IF NOT EXISTS bookings (
            id BIGSERIAL PRIMARY KEY,
            chat_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            start_iso TEXT NOT NULL,
            appointment_date TEXT,
            email TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'booked',
            created_at TEXT NOT NULL,
            reminder_24h_sent BOOLEAN NOT NULL DEFAULT FALSE,
            reminder_1h_sent BOOLEAN NOT NULL DEFAULT FALSE
        )
        """,
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS appointment_date TEXT",
        "CREATE INDEX IF NOT EXISTS idx_bookings_chat ON bookings(chat_id)",
        "CREATE INDEX IF NOT EXISTS idx_bookings_status ON bookings(status)",
        "CREATE INDEX IF NOT EXISTS idx_bookings_appointment_date ON bookings(appointment_date)",
        """
        CREATE TABLE IF NOT EXISTS waitlist (
            id BIGSERIAL PRIMARY KEY,
            chat_id TEXT NOT NULL,
            target_date TEXT NOT NULL,
            email TEXT NOT NULL,
            created_at TEXT NOT NULL,
            notified BOOLEAN NOT NULL DEFAULT FALSE
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_waitlist_date ON waitlist(target_date)",
        """
        CREATE TABLE IF NOT EXISTS sessions (
            chat_id TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        UPDATE bookings
        SET appointment_date = LEFT(start_iso, 10)
        WHERE appointment_date IS NULL AND start_iso IS NOT NULL
        """,
    ]
    with pg_connection() as conn:
        for stmt in statements:
            conn.execute(stmt)
    logger.info("Postgres schema ready (bookings, waitlist, sessions)")
