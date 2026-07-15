"""Tests for cloud credential materialization."""

from __future__ import annotations

import json
from pathlib import Path

from api.config import get_settings, materialize_google_credentials


def test_materialize_json_env(tmp_path: Path, monkeypatch):
    payload = {"type": "service_account", "client_email": "sa@test.iam.gserviceaccount.com"}
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", json.dumps(payload))
    path = materialize_google_credentials(tmp_path)
    assert path is not None
    assert Path(path).is_file()
    assert json.loads(Path(path).read_text(encoding="utf-8"))["type"] == "service_account"
    get_settings.cache_clear()
