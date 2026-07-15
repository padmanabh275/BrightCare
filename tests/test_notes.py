"""Consultation notes assistant tests."""

from __future__ import annotations

from unittest.mock import patch

from api.notes import generate_consultation_artifacts
from api.integrations.emailer import send_patient_letter


def test_notes_requires_substance():
    try:
        generate_consultation_artifacts("too short")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_notes_heuristic_without_openai(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from api.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()

    notes = (
        "Patient presents with mild sore throat for 3 days. "
        "No fever. Exam shows erythematous pharynx. "
        "Advise fluids, rest, and follow up if worse."
    )
    result = generate_consultation_artifacts(notes, "Alex")
    assert "summary" in result
    assert len(result["action_items"]) >= 1
    assert "BrightCare" in result["patient_email"]["body"]
    assert "Alex" in result["patient_email"]["body"] or "Alex" in result["summary"]


def test_send_patient_letter_skipped_when_smtp_off(monkeypatch):
    monkeypatch.setenv("SMTP_USER", "")
    monkeypatch.setenv("SMTP_APP_PASSWORD", "")
    monkeypatch.setenv("SMTP_FROM", "")
    monkeypatch.setenv("RESEND_API_KEY", "")
    monkeypatch.setenv("EMAIL_FROM", "")
    from api.config import get_settings

    get_settings.cache_clear()
    assert send_patient_letter("a@b.com", "Hi", "Body") == "skipped"
    get_settings.cache_clear()


def test_send_patient_letter_sent(monkeypatch):
    monkeypatch.setenv("SMTP_USER", "clinic@test.com")
    monkeypatch.setenv("SMTP_APP_PASSWORD", "app-pass")
    monkeypatch.setenv("SMTP_FROM", "clinic@test.com")
    monkeypatch.setenv("RESEND_API_KEY", "")
    from api.config import get_settings

    get_settings.cache_clear()

    class FakeSMTP:
        def __init__(self, *_a, **_k) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def starttls(self) -> None:
            pass

        def login(self, *_a) -> None:
            pass

        def sendmail(self, *_a) -> None:
            pass

    with patch("api.integrations.emailer.smtplib.SMTP", FakeSMTP):
        assert send_patient_letter("patient@test.com", "Subject", "Hello") == "sent"
    get_settings.cache_clear()


def test_send_patient_letter_via_resend(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("EMAIL_FROM", "BrightCare <onboarding@resend.dev>")
    monkeypatch.setenv("SMTP_USER", "")
    monkeypatch.setenv("SMTP_APP_PASSWORD", "")
    from api.config import get_settings

    get_settings.cache_clear()

    class FakeResponse:
        status_code = 200
        text = "{}"

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            return FakeResponse()

    with patch("api.integrations.emailer.httpx.Client", FakeClient):
        assert send_patient_letter("patient@test.com", "Subject", "Hello") == "sent"
    get_settings.cache_clear()
