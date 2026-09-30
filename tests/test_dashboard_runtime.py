from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.dashboard import build_dashboard, render_html
from scripts.validate_dashboard import load_dashboard_config

REPO_ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 30, 10, 30, 20, tzinfo=timezone.utc)


def _ts(minutes_ago: int) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _ok(minutes_ago: int, latency: int, quality: float = 0.9) -> list[dict]:
    return [
        {"event": "request_received", "ts": _ts(minutes_ago)},
        {
            "event": "response_sent",
            "ts": _ts(minutes_ago),
            "latency_ms": latency,
            "ttft_ms": 50,
            "cost_usd": 0.002,
            "tokens_in": 30,
            "tokens_out": 100,
            "quality_score": quality,
            "tool_success": True,
        },
    ]


def _failed(minutes_ago: int) -> list[dict]:
    return [
        {"event": "request_received", "ts": _ts(minutes_ago)},
        {
            "event": "request_failed",
            "ts": _ts(minutes_ago),
            "error_type": "RuntimeError",
            "tool_success": False,
        },
    ]


def _panel(data: dict, panel_id: str) -> dict:
    return next(p for p in data["panels"] if p["id"] == panel_id)


def test_dashboard_builds_six_panels_from_contract() -> None:
    config = load_dashboard_config(REPO_ROOT / "config" / "dashboard.yaml")
    records = _ok(1, 200) + _ok(1, 400) + _ok(0, 5000) + _failed(0)
    # Log ngoài cửa sổ 60 phút không được tính
    records += _ok(90, 99999)

    data = build_dashboard(records, config, NOW)

    assert [p["id"] for p in data["panels"]] == [p["id"] for p in config["dashboard"]["panels"]]
    assert data["time_range_minutes"] == 60
    assert len(data["labels"]) == 60

    latency = _panel(data, "latency")
    assert latency["summary"]["p50"] == 400
    assert latency["summary"]["p99"] == 5000
    assert latency["breached"] is True

    errors = _panel(data, "errors")
    assert errors["summary"]["error_rate_pct"] == 25.0
    assert errors["summary"]["count_by_value"] == {"RuntimeError": 1}
    # Retrieval success tính trên cả response_sent lẫn request_failed
    assert errors["summary"]["tool_success_rate_pct"] == 75.0
    assert errors["breached"] is True

    assert _panel(data, "traffic")["summary"]["count"] == 4
    assert _panel(data, "cost")["summary"]["total"] == 0.006
    assert _panel(data, "tokens")["summary"]["sum_by_field"] == {"tokens_in": 90, "tokens_out": 300}
    assert _panel(data, "quality")["summary"]["mean"] == 0.9
    assert _panel(data, "quality")["breached"] is False


def test_dashboard_zoom_and_challenge_threshold() -> None:
    config = load_dashboard_config(REPO_ROOT / "config" / "dashboard.yaml")
    records = _ok(20, 100) + _ok(2, 2600) + _ok(1, 2700) + _ok(0, 150)
    challenge = {"challenge_id": "demo", "latency_threshold_ms": 2000}

    data = build_dashboard(records, config, NOW, window_minutes=10, challenge=challenge)

    assert data["time_range_minutes"] == 10
    assert data["contract_time_range_minutes"] == 60
    assert len(data["labels"]) == 10
    latency = _panel(data, "latency")
    # Log 20 phút trước nằm ngoài cửa sổ phóng to 10 phút
    assert latency["summary"]["challenge_total"] == 3
    assert latency["summary"]["challenge_over_threshold"] == 2
    # Threshold của contract (3000 ms) không bị thay đổi
    assert latency["threshold"]["value"] == 3000


def test_dashboard_renders_html_with_refresh() -> None:
    config = load_dashboard_config(REPO_ROOT / "config" / "dashboard.yaml")
    html = render_html(build_dashboard(_ok(0, 100), config, NOW))

    assert '<meta http-equiv="refresh" content="30">' in html
    assert "Latency percentiles and TTFT" in html
