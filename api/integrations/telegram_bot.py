"""Telegram long-polling and webhook helpers."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import OrderedDict
from datetime import datetime
from typing import Any

import httpx

from api.agent.fsm import AgentReply, BookingAgent, agent as default_agent
from api.agent.session import session_store
from api.agent.timeutil import format_slot_short, to_clinic
from api.config import get_settings

logger = logging.getLogger(__name__)

API = "https://api.telegram.org"


class _UpdateDedupe:
    """Remember recent update_ids so the same Telegram update isn't handled twice."""

    def __init__(self, maxlen: int = 500) -> None:
        self._seen: OrderedDict[int, None] = OrderedDict()
        self._maxlen = maxlen

    def saw(self, update_id: int) -> bool:
        if update_id in self._seen:
            return True
        self._seen[update_id] = None
        while len(self._seen) > self._maxlen:
            self._seen.popitem(last=False)
        return False


class TelegramRuntime:
    def __init__(self, booking_agent: BookingAgent | None = None) -> None:
        self.agent = booking_agent or default_agent
        self.running = False
        self._task: asyncio.Task | None = None
        self._offset = 0
        self._dedupe = _UpdateDedupe()
        self._chat_locks: dict[str, asyncio.Lock] = {}

    @property
    def token(self) -> str | None:
        return get_settings().telegram_bot_token

    def _url(self, method: str) -> str:
        return f"{API}/bot{self.token}/{method}"

    def _lock_for(self, chat_id: str) -> asyncio.Lock:
        if chat_id not in self._chat_locks:
            self._chat_locks[chat_id] = asyncio.Lock()
        return self._chat_locks[chat_id]

    async def _handle_message(self, chat_id: str, text: str) -> AgentReply:
        if not chat_rate_limiter.allow(chat_id):
            return AgentReply(
                "You're sending messages too quickly — please wait a moment."
            )
        return await self.agent.handle(chat_id, text)

    async def send_message(
        self,
        chat_id: int | str,
        text: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        if not self.token:
            logger.warning("No TELEGRAM_BOT_TOKEN; drop message: %s", text)
            return
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_notification": False,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(self._url("sendMessage"), json=payload)
            if resp.status_code >= 400:
                logger.error("Telegram send failed: %s %s", resp.status_code, resp.text)

    async def _answer_callback(self, callback_id: str, text: str | None = None) -> None:
        if not self.token:
            return
        payload: dict[str, Any] = {"callback_query_id": callback_id}
        if text:
            payload["text"] = text[:180]
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                await client.post(self._url("answerCallbackQuery"), json=payload)
        except Exception:  # noqa: BLE001
            logger.debug("answerCallbackQuery failed", exc_info=True)

    async def _clear_inline_keyboard(self, chat_id: str, message_id: int) -> None:
        if not self.token:
            return
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                await client.post(
                    self._url("editMessageReplyMarkup"),
                    json={
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "reply_markup": {"inline_keyboard": []},
                    },
                )
        except Exception:  # noqa: BLE001
            logger.debug("editMessageReplyMarkup failed", exc_info=True)

    def webapp_keyboard(self) -> dict[str, Any] | None:
        """Persistent reply keyboard that opens the Mini App."""
        url = get_settings().telegram_webapp_url
        if not url:
            return None
        return {
            "keyboard": [
                [{"text": "📅 Book appointment", "web_app": {"url": url}}],
                [{"text": "💬 Chat to book"}, {"text": "❓ Help"}],
            ],
            "resize_keyboard": True,
            "is_persistent": True,
        }

    def webapp_inline_keyboard(self) -> dict[str, Any] | None:
        """One-tap inline Open App button (easier than hunting the reply keyboard)."""
        url = get_settings().telegram_webapp_url
        if not url:
            return None
        return {
            "inline_keyboard": [
                [{"text": "📱 Open booking app", "web_app": {"url": url}}],
            ]
        }

    async def configure_menu_button(self) -> None:
        """Set Telegram menu button (☰) to open the Mini App."""
        url = get_settings().telegram_webapp_url
        if not self.token or not url:
            if not url:
                logger.info("TELEGRAM_WEBAPP_URL not set — menu button skipped")
            return
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    self._url("setChatMenuButton"),
                    json={
                        "menu_button": {
                            "type": "web_app",
                            "text": "Book",
                            "web_app": {"url": url},
                        }
                    },
                )
                logger.info("setChatMenuButton: %s", resp.text[:200])
        except Exception:  # noqa: BLE001
            logger.exception("setChatMenuButton failed")

    def confirm_keyboard(self, slot: datetime) -> dict[str, Any]:
        local = to_clinic(slot)
        label = format_slot_short(local)
        return {
            "inline_keyboard": [
                [
                    {
                        "text": f"Book {label}",
                        "callback_data": f"confirm:{local.isoformat()}",
                    },
                    {"text": "Cancel", "callback_data": "decline"},
                ]
            ]
        }

    async def ensure_polling_exclusive(self) -> None:
        """Drop any webhook so getUpdates can run without 409 conflicts."""
        if not self.token:
            return
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    self._url("deleteWebhook"),
                    json={"drop_pending_updates": False},
                )
                logger.info("deleteWebhook: %s", resp.text[:200])
        except Exception:  # noqa: BLE001
            logger.exception("deleteWebhook failed")

    async def register_webhook(self) -> None:
        """Register Telegram webhook for deploy mode (TELEGRAM_MODE=webhook)."""
        settings = get_settings()
        if not self.token:
            logger.warning("Cannot setWebhook — TELEGRAM_BOT_TOKEN missing")
            return
        base = (settings.public_base_url or "").rstrip("/")
        if not base:
            logger.warning("Cannot setWebhook — set PUBLIC_BASE_URL (HTTPS)")
            return
        webhook_url = f"{base}/telegram/webhook"
        payload: dict[str, Any] = {
            "url": webhook_url,
            "allowed_updates": ["message", "callback_query"],
            "drop_pending_updates": False,
        }
        if settings.telegram_webhook_secret:
            payload["secret_token"] = settings.telegram_webhook_secret
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(self._url("setWebhook"), json=payload)
                logger.info("setWebhook (%s): %s", webhook_url, resp.text[:300])
        except Exception:  # noqa: BLE001
            logger.exception("setWebhook failed")

    async def handle_update(self, update: dict[str, Any]) -> None:
        update_id = update.get("update_id")
        if isinstance(update_id, int) and self._dedupe.saw(update_id):
            logger.info("Skipping duplicate update_id=%s", update_id)
            return

        if "callback_query" in update:
            await self._handle_callback(update["callback_query"])
            return

        message = update.get("message") or update.get("edited_message")
        if not message:
            return

        chat_id = str(message["chat"]["id"])

        if message.get("web_app_data"):
            await self._handle_web_app_data(chat_id, message["web_app_data"])
            return

        text = message.get("text")
        if not text:
            return

        stripped = text.strip()
        lowered = stripped.lower()

        if stripped.startswith("/start") or stripped.startswith("/app") or stripped.startswith("/book"):
            await self._handle_start(chat_id)
            return

        if lowered in {"💬 chat to book", "chat to book"}:
            await self.send_message(
                chat_id,
                'Sure — tell me a date and time (e.g. "Can I book 2026-07-20 at 2pm?").',
            )
            return

        if lowered in {"❓ help", "help", "/help"}:
            await self._handle_help(chat_id)
            return

        async with self._lock_for(chat_id):
            reply = await self._handle_message(chat_id, text)
            markup = (
                self.confirm_keyboard(reply.propose_buttons_for)
                if reply.propose_buttons_for
                else None
            )
            await self.send_message(chat_id, reply.text, reply_markup=markup)

    async def _handle_start(self, chat_id: str) -> None:
        settings = get_settings()
        app_url = settings.telegram_webapp_url
        if app_url:
            welcome = (
                "Welcome to BrightCare Clinic!\n\n"
                "Tap Open booking app below to pick a date and time in one tap — "
                "or type here (e.g. “Can I book 2026-07-20 at 2pm?” or “Monday at 2pm”).\n\n"
                "You can also use the Book button next to the message box.\n\n"
                "Mon–Fri 09:00–18:00 · 12 Orchard Rd"
            )
            # Prefer inline Open App (clear CTA); also attach reply keyboard for later
            await self.send_message(
                chat_id,
                welcome,
                reply_markup=self.webapp_inline_keyboard(),
            )
            kb = self.webapp_keyboard()
            if kb:
                await self.send_message(
                    chat_id,
                    "Tip: use 📅 Book appointment anytime from the keyboard below.",
                    reply_markup=kb,
                )
        else:
            welcome = (
                "Welcome to BrightCare Clinic!\n\n"
                "The in-chat booking app isn’t configured yet "
                "(staff needs TELEGRAM_WEBAPP_URL).\n\n"
                'For now, chat here — e.g. "Can I book 2026-07-20 at 2pm?"\n\n'
                "Mon–Fri 09:00–18:00 · 12 Orchard Rd"
            )
            await self.send_message(chat_id, welcome)

    async def _handle_help(self, chat_id: str) -> None:
        app_url = get_settings().telegram_webapp_url
        lines = [
            "BrightCare help",
            "",
            "• Book: say “Can I book Tuesday at 3pm?” or “2026-07-20 at 14:00”",
            "• Cancel: “cancel my appointment”",
            "• Reschedule: “reschedule my appointment”",
            "• FAQ: location, parking, hours, walk-ins",
        ]
        if app_url:
            lines.insert(2, "• Or tap Open booking app / Book menu")
        await self.send_message(
            chat_id,
            "\n".join(lines),
            reply_markup=self.webapp_inline_keyboard(),
        )

    async def _handle_web_app_data(self, chat_id: str, data: dict[str, Any]) -> None:
        """Optional: handle Telegram.WebApp.sendData from the mini app."""
        raw = data.get("data") or ""
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"text": raw}
        action = payload.get("action", "request")
        if action == "confirm":
            reply = await self._handle_message(chat_id, "yes")
        elif action == "request":
            date_iso = str(payload.get("date") or "").strip()
            weekday = payload.get("weekday", "monday")
            time = payload.get("time", "2pm")
            email = payload.get("email", "")
            if email:
                session_store.get(chat_id).email = email
            day_part = date_iso or weekday
            reply = await self._handle_message(
                chat_id, f"Can I book {day_part} at {time}?"
            )
        else:
            reply = await self._handle_message(chat_id, str(raw))
        markup = (
            self.confirm_keyboard(reply.propose_buttons_for)
            if reply.propose_buttons_for
            else None
        )
        await self.send_message(chat_id, reply.text, reply_markup=markup)

    async def _handle_callback(self, cq: dict[str, Any]) -> None:
        callback_id = str(cq.get("id") or "")
        message = cq.get("message") or {}
        chat_id = str((message.get("chat") or {}).get("id") or "")
        message_id = message.get("message_id")
        data = cq.get("data") or ""

        # Acknowledge immediately so Telegram stops retrying the tap
        await self._answer_callback(callback_id)
        if message_id is not None and chat_id:
            await self._clear_inline_keyboard(chat_id, int(message_id))

        if not chat_id:
            return

        async with self._lock_for(chat_id):
            if data.startswith("confirm:"):
                slot_iso = data[len("confirm:") :]
                session = session_store.get(chat_id)
                # Bind the button's slot into session so "yes" books the right time
                try:
                    session.proposed_slot = datetime.fromisoformat(slot_iso)
                except ValueError:
                    pass
                reply = await self._handle_message(chat_id, "yes")
            elif data == "decline":
                reply = await self._handle_message(chat_id, "no")
            else:
                reply = await self._handle_message(chat_id, data)

            markup = (
                self.confirm_keyboard(reply.propose_buttons_for)
                if reply.propose_buttons_for
                else None
            )
            await self.send_message(chat_id, reply.text, reply_markup=markup)

    async def _poll_loop(self) -> None:
        self.running = True
        await self.ensure_polling_exclusive()
        await self.configure_menu_button()
        logger.info("Telegram polling started")
        while self.running:
            if not self.token:
                await asyncio.sleep(5)
                continue
            try:
                async with httpx.AsyncClient(timeout=60) as client:
                    resp = await client.get(
                        self._url("getUpdates"),
                        params={
                            "timeout": 25,
                            "offset": self._offset,
                            "allowed_updates": '["message","callback_query"]',
                        },
                    )
                    if resp.status_code == 409:
                        logger.warning(
                            "Telegram 409 Conflict — another poller/webhook is active. "
                            "Stop other API processes, then retry deleteWebhook."
                        )
                        await self.ensure_polling_exclusive()
                        await asyncio.sleep(5)
                        continue
                    data = resp.json()
                    if not data.get("ok"):
                        logger.error("getUpdates not ok: %s", data)
                        await asyncio.sleep(3)
                        continue
                    for update in data.get("result", []):
                        self._offset = int(update["update_id"]) + 1
                        try:
                            await self.handle_update(update)
                        except Exception:  # noqa: BLE001
                            logger.exception("Error handling update")
            except asyncio.CancelledError:
                break
            except Exception:  # noqa: BLE001
                logger.exception("Polling error")
                await asyncio.sleep(3)
        self.running = False
        logger.info("Telegram polling stopped")

    def start_polling(self) -> None:
        if self._task and not self._task.done():
            return
        self.running = True
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


telegram_runtime = TelegramRuntime()
