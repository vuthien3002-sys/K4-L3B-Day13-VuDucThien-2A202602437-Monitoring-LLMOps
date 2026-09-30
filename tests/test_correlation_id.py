from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import httpx
import pytest

from app import logging_config
from app.main import app

CHAT_BODY = {
    "user_id": "student-01",
    "session_id": "session-01",
    "feature": "qa",
    "message": "My email is student@vinuni.edu.vn and phone 0987654321",
}


@pytest.fixture(autouse=True)
def log_path(monkeypatch, tmp_path: Path) -> Path:
    # Không ghi test log vào data/logs.jsonl thật mà validator đang đọc
    path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", path)
    return path


def _post_chat(headers: dict[str, str] | None = None) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/chat", json=CHAT_BODY, headers=headers or {})

    return asyncio.run(send())


def test_generates_correlation_id_and_response_time_header() -> None:
    response = _post_chat()

    request_id = response.headers["x-request-id"]
    assert re.fullmatch(r"req-[0-9a-f]{8}", request_id)
    assert response.json()["correlation_id"] == request_id
    assert float(response.headers["x-response-time-ms"]) >= 0


def test_reuses_valid_incoming_request_id() -> None:
    response = _post_chat({"x-request-id": "req-1a2b3c4d"})

    assert response.headers["x-request-id"] == "req-1a2b3c4d"
    assert response.json()["correlation_id"] == "req-1a2b3c4d"


def test_replaces_invalid_incoming_request_id() -> None:
    response = _post_chat({"x-request-id": "not-a-valid-id"})

    assert response.headers["x-request-id"] != "not-a-valid-id"
    assert re.fullmatch(r"req-[0-9a-f]{8}", response.headers["x-request-id"])


def test_api_logs_are_enriched_and_scrubbed(log_path: Path) -> None:
    response = _post_chat()

    raw = log_path.read_text(encoding="utf-8")
    assert "student@vinuni.edu.vn" not in raw
    assert "0987654321" not in raw
    assert "student-01" not in raw

    api_events = [e for e in map(json.loads, raw.splitlines()) if e.get("service") == "api"]
    assert {e["event"] for e in api_events} >= {"request_received", "response_sent"}
    for event in api_events:
        assert event["correlation_id"] == response.headers["x-request-id"]
        assert event["session_id"] == "session-01"
        assert event["feature"] == "qa"
        assert event["model"]
        assert event["env"]
        assert re.fullmatch(r"[0-9a-f]{12}", event["user_id_hash"])
