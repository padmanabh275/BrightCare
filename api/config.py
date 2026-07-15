"""Environment configuration for BrightCare."""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()
load_dotenv(".env.local")


@dataclass(frozen=True)
class Settings:
    clinic_timezone: str
    clinic_tz: ZoneInfo
    openai_api_key: str | None
    openai_model: str
    telegram_bot_token: str | None
    telegram_bot_username: str | None
    telegram_mode: str
    telegram_webhook_secret: str | None
    public_base_url: str | None
    google_calendar_id: str | None
    google_service_account_file: str | None
    smtp_host: str
    smtp_port: int
    smtp_user: str | None
    smtp_app_password: str | None
    smtp_from: str | None
    clerk_jwks_url: str | None
    clinic_name: str
    telegram_webapp_url: str | None
    database_url: str | None
    data_dir: Path
    session_store: str
    jobs_secret: str | None


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def materialize_google_credentials(data_dir: Path) -> str | None:
    """
    Resolve a service-account JSON path for local or cloud.

    Prefer GOOGLE_SERVICE_ACCOUNT_FILE if the file exists.
    Else write GOOGLE_SERVICE_ACCOUNT_JSON (raw JSON or base64) into data_dir.
    """
    existing = _env("GOOGLE_SERVICE_ACCOUNT_FILE")
    if existing and Path(existing).is_file():
        return existing

    raw = _env("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        return existing

    data_dir.mkdir(parents=True, exist_ok=True)
    target = data_dir / "credentials.json"
    text = raw
    # Heuristic: if it's not starting with '{', try base64
    if not text.lstrip().startswith("{"):
        try:
            text = base64.b64decode(text).decode("utf-8")
        except Exception:  # noqa: BLE001
            pass
    target.write_text(text, encoding="utf-8")
    return str(target)


@lru_cache
def get_settings() -> Settings:
    tz_name = _env("CLINIC_TIMEZONE", "Asia/Singapore") or "Asia/Singapore"
    try:
        clinic_tz = ZoneInfo(tz_name)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Invalid CLINIC_TIMEZONE={tz_name!r}") from exc

    mode = (_env("TELEGRAM_MODE") or "polling").lower()
    if mode not in {"polling", "webhook"}:
        mode = "polling"

    data_dir = Path(_env("DATA_DIR", "data") or "data")
    sa_file = materialize_google_credentials(data_dir)
    database_url = _env("DATABASE_URL") or _env("NEON_DATABASE_URL")

    # Auto-select postgres sessions when Neon URL is present
    session_store = (_env("SESSION_STORE") or "").lower()
    if not session_store:
        session_store = "postgres" if database_url else "sqlite"

    smtp_user = _env("SMTP_USER")
    return Settings(
        clinic_timezone=tz_name,
        clinic_tz=clinic_tz,
        openai_api_key=_env("OPENAI_API_KEY"),
        openai_model=_env("OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini",
        telegram_bot_token=_env("TELEGRAM_BOT_TOKEN"),
        telegram_bot_username=_env("TELEGRAM_BOT_USERNAME")
        or _env("NEXT_PUBLIC_TELEGRAM_BOT_USERNAME"),
        telegram_mode=mode,
        telegram_webhook_secret=_env("TELEGRAM_WEBHOOK_SECRET"),
        public_base_url=_env("PUBLIC_BASE_URL"),
        google_calendar_id=_env("GOOGLE_CALENDAR_ID"),
        google_service_account_file=sa_file,
        smtp_host=_env("SMTP_HOST", "smtp.gmail.com") or "smtp.gmail.com",
        smtp_port=int(_env("SMTP_PORT", "587") or "587"),
        smtp_user=smtp_user,
        smtp_app_password=_env("SMTP_APP_PASSWORD"),
        smtp_from=_env("SMTP_FROM") or smtp_user,
        clerk_jwks_url=_env("CLERK_JWKS_URL"),
        clinic_name=_env("CLINIC_NAME", "BrightCare Clinic") or "BrightCare Clinic",
        telegram_webapp_url=_env("TELEGRAM_WEBAPP_URL")
        or _env("NEXT_PUBLIC_TELEGRAM_WEBAPP_URL"),
        database_url=database_url,
        data_dir=data_dir,
        session_store=session_store,
        jobs_secret=_env("JOBS_SECRET"),
    )
