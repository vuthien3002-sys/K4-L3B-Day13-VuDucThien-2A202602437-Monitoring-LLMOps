"""Dashboard 6 panel đọc data/logs.jsonl theo contract config/dashboard.yaml.

Chạy:  python scripts/dashboard.py            rồi mở http://127.0.0.1:8050
Lưu 1 bản HTML tĩnh:  python scripts/dashboard.py --snapshot dashboard.html

Chỉ dùng thư viện chuẩn + PyYAML (đã có trong requirements.txt); biểu đồ vẽ bằng
Chart.js tải từ CDN nên không cần cài thêm gói nào vào venv của API.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from statistics import mean
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio
from app.metrics import percentile
from scripts.validate_dashboard import load_dashboard_config

DEFAULT_CONFIG = REPO_ROOT / "config" / "dashboard.yaml"
DEFAULT_LOGS = REPO_ROOT / "data" / "logs.jsonl"


def parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def load_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


def _pct(part: int, whole: int) -> float | None:
    return round(part / whole * 100, 2) if whole else None


def _breached(value: Any, operator: str, limit: float) -> bool | None:
    values = list(value.values()) if isinstance(value, dict) else [value]
    values = [v for v in values if v is not None]
    if not values:
        return None
    if operator == "lte":
        return any(v > limit for v in values)
    return any(v < limit for v in values)


def build_dashboard(records: list[dict], config: dict, now: datetime) -> dict:
    """Tính 6 panel trong cửa sổ time_range_minutes, bucket theo phút (UTC)."""
    dash = config["dashboard"]
    window = int(dash["time_range_minutes"])
    last_minute = now.astimezone(timezone.utc).replace(second=0, microsecond=0)
    minutes = [last_minute - timedelta(minutes=window - 1 - i) for i in range(window)]
    start = minutes[0]

    by_minute: dict[datetime, list[dict]] = defaultdict(list)
    in_window: list[dict] = []
    for rec in records:
        ts = parse_ts(rec.get("ts"))
        if ts is None or ts < start or ts >= last_minute + timedelta(minutes=1):
            continue
        by_minute[ts.replace(second=0, microsecond=0)].append(rec)
        in_window.append(rec)

    def events(recs: list[dict], name: str) -> list[dict]:
        return [r for r in recs if r.get("event") == name]

    def values(recs: list[dict], field: str) -> list:
        return [r[field] for r in recs if isinstance(r.get(field), (int, float))]

    series: dict[str, list] = defaultdict(list)
    cost_cum = tokens_in_cum = tokens_out_cum = 0.0
    for minute in minutes:
        recs = by_minute.get(minute, [])
        sent = events(recs, "response_sent")
        received = events(recs, "request_received")
        failed = events(recs, "request_failed")
        lat, ttft = values(sent, "latency_ms"), values(sent, "ttft_ms")
        tool_events = [r for r in recs if isinstance(r.get("tool_success"), bool)]

        series["latency_p50"].append(percentile(lat, 50) if lat else None)
        series["latency_p95"].append(percentile(lat, 95) if lat else None)
        series["latency_p99"].append(percentile(lat, 99) if lat else None)
        series["ttft_p95"].append(percentile(ttft, 95) if ttft else None)
        series["traffic"].append(len(received))
        series["error_rate_pct"].append(_pct(len(failed), len(received)))
        series["tool_success_rate_pct"].append(
            _pct(sum(r["tool_success"] for r in tool_events), len(tool_events))
        )
        cost = sum(values(sent, "cost_usd"))
        cost_cum += cost
        series["cost_per_minute"].append(round(cost, 6))
        series["cost_cumulative"].append(round(cost_cum, 6))
        t_in, t_out = sum(values(sent, "tokens_in")), sum(values(sent, "tokens_out"))
        tokens_in_cum += t_in
        tokens_out_cum += t_out
        series["tokens_in"].append(t_in)
        series["tokens_out"].append(t_out)
        series["tokens_in_cumulative"].append(tokens_in_cum)
        series["tokens_out_cumulative"].append(tokens_out_cum)
        quality = values(sent, "quality_score")
        series["quality_mean"].append(_round(mean(quality)) if quality else None)

    sent = events(in_window, "response_sent")
    received = events(in_window, "request_received")
    failed = events(in_window, "request_failed")
    lat, ttft = values(sent, "latency_ms"), values(sent, "ttft_ms")
    tool_events = [r for r in in_window if isinstance(r.get("tool_success"), bool)]
    quality = values(sent, "quality_score")

    # Key của summary trùng tên aggregation trong dashboard.yaml để so threshold
    summaries = {
        "latency": {
            "p50": percentile(lat, 50) if lat else None,
            "p95": percentile(lat, 95) if lat else None,
            "p99": percentile(lat, 99) if lat else None,
            "ttft_p95": percentile(ttft, 95) if ttft else None,
        },
        "traffic": {
            "count": len(received),
            "rate_per_minute": round(len(received) / window, 2),
        },
        "errors": {
            "error_rate_pct": _pct(len(failed), len(received)) if received else 0.0,
            "count_by_value": dict(Counter(r.get("error_type") or "unknown" for r in failed)),
            "tool_success_rate_pct": _pct(
                sum(r["tool_success"] for r in tool_events), len(tool_events)
            ),
        },
        "cost": {
            "sum_by_minute": series["cost_per_minute"][-1],
            "total": round(sum(values(sent, "cost_usd")), 6),
        },
        "tokens": {
            "sum_by_field": {
                "tokens_in": sum(values(sent, "tokens_in")),
                "tokens_out": sum(values(sent, "tokens_out")),
            },
        },
        "quality": {"mean": _round(mean(quality)) if quality else None},
    }

    panels = []
    for panel in dash["panels"]:
        threshold = panel["threshold"]
        summary = summaries[panel["id"]]
        panels.append(
            {
                "id": panel["id"],
                "title": panel["title"],
                "unit": panel["unit"],
                "query": panel["query"],
                "threshold": threshold,
                "summary": summary,
                "breached": _breached(
                    summary.get(threshold["aggregation"]),
                    threshold["operator"],
                    threshold["value"],
                ),
            }
        )

    return {
        "title": dash["title"],
        "time_range_minutes": window,
        "refresh_seconds": dash["refresh_seconds"],
        "generated_at": now.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "window_start": start.strftime("%H:%M UTC"),
        "window_end": (last_minute + timedelta(minutes=1)).strftime("%H:%M UTC"),
        "record_count": len(in_window),
        "labels": [m.strftime("%H:%M") for m in minutes],
        "series": series,
        "panels": panels,
    }


PAGE = """<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="__REFRESH__">
<title>__TITLE__</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  :root { --bg:#f6f7f9; --card:#fff; --text:#1d2330; --muted:#667085; --line:#e4e7ec;
          --ok:#1a7f4b; --ok-bg:#e6f4ec; --bad:#b42318; --bad-bg:#fdecea; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
         font: 14px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
  header { padding:16px 24px; border-bottom:1px solid var(--line); background:var(--card);
           display:flex; flex-wrap:wrap; gap:8px 24px; align-items:baseline; }
  h1 { font-size:18px; margin:0; }
  .meta { color:var(--muted); font-size:13px; }
  .meta b { color:var(--text); font-weight:600; }
  main { display:grid; grid-template-columns:repeat(auto-fit, minmax(420px, 1fr));
         gap:16px; padding:16px 24px 32px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:10px;
          padding:14px 16px; min-width:0; }
  .head { display:flex; justify-content:space-between; gap:8px; align-items:flex-start; }
  h2 { font-size:15px; margin:0; }
  .unit { color:var(--muted); font-size:12px; margin-top:2px; }
  .badge { font-size:12px; font-weight:600; padding:2px 8px; border-radius:999px; white-space:nowrap; }
  .ok { color:var(--ok); background:var(--ok-bg); }
  .bad { color:var(--bad); background:var(--bad-bg); }
  .na { color:var(--muted); background:var(--bg); }
  .stats { display:flex; flex-wrap:wrap; gap:4px 16px; margin:10px 0 6px; font-size:13px; }
  .stats span { color:var(--muted); }
  .stats b { font-variant-numeric: tabular-nums; }
  .threshold { font-size:12px; color:var(--bad); margin-bottom:6px; }
  .chart { position:relative; height:220px; }
  code { font-size:11px; color:var(--muted); display:block; margin-top:8px; overflow-wrap:anywhere; }
  @media (max-width: 480px) { main { grid-template-columns:1fr; padding:12px; } header { padding:12px; } }
</style>
</head>
<body>
<header>
  <h1 id="title"></h1>
  <div class="meta">Time range: <b id="range"></b></div>
  <div class="meta">Refresh: <b id="refresh"></b></div>
  <div class="meta">Nguồn: <b>data/logs.jsonl</b> (<span id="count"></span> log records)</div>
  <div class="meta">Cập nhật: <b id="generated"></b></div>
</header>
<main id="grid"></main>
<script>
const D = __DATA__;
const OPS = { lte: "\\u2264", gte: "\\u2265" };
const fmt = (v, d = 2) => v === null || v === undefined ? "–"
  : (typeof v === "number" ? v.toLocaleString("en-US", { maximumFractionDigits: d }) : v);

document.getElementById("title").textContent = D.title;
document.getElementById("range").textContent =
  `last ${D.time_range_minutes} minutes (${D.window_start} – ${D.window_end})`;
document.getElementById("refresh").textContent = `${D.refresh_seconds}s`;
document.getElementById("count").textContent = D.record_count;
document.getElementById("generated").textContent = D.generated_at;

const S = D.series;
const line = (label, data, color, extra = {}) =>
  ({ type: "line", label, data, borderColor: color, backgroundColor: color, pointRadius: 2,
     borderWidth: 2, spanGaps: false, tension: 0.2, ...extra });
const bar = (label, data, color, extra = {}) =>
  ({ type: "bar", label, data, backgroundColor: color, borderWidth: 0, ...extra });
const limit = (p, axis = "y") =>
  line(`Threshold ${p.threshold.aggregation} ${OPS[p.threshold.operator]} ${p.threshold.value}`,
       D.labels.map(() => p.threshold.value), "#d92d20",
       { borderDash: [6, 4], pointRadius: 0, borderWidth: 1.5, yAxisID: axis });

const PANELS = {
  latency: p => ({
    stats: { P50: p.summary.p50, P95: p.summary.p95, P99: p.summary.p99, "TTFT P95": p.summary.ttft_p95 },
    datasets: [line("P50", S.latency_p50, "#98a2b3"), line("P95", S.latency_p95, "#2e6ef7"),
               line("P99", S.latency_p99, "#7a5af8"), line("TTFT P95", S.ttft_p95, "#12b76a"), limit(p)],
    y: { title: "ms" },
  }),
  traffic: p => ({
    stats: { "Total requests": p.summary.count, "Avg req/min": p.summary.rate_per_minute },
    datasets: [bar("Requests / minute", S.traffic, "#2e6ef7"), limit(p)],
    y: { title: "requests / minute" },
  }),
  errors: p => ({
    stats: { "Error rate %": p.summary.error_rate_pct,
             "Retrieval success %": p.summary.tool_success_rate_pct,
             "Breakdown": Object.entries(p.summary.count_by_value).map(([k, v]) => `${k}: ${v}`).join(", ") || "none" },
    datasets: [line("Error rate %", S.error_rate_pct, "#d92d20", { borderColor: "#f04438" }),
               line("Retrieval success %", S.tool_success_rate_pct, "#12b76a"), limit(p)],
    y: { title: "%", min: 0, max: 100 },
  }),
  cost: p => ({
    stats: { "Total USD": p.summary.total, "Last minute USD": p.summary.sum_by_minute },
    datasets: [bar("USD / minute", S.cost_per_minute, "#fdb022"),
               line("Cumulative USD", S.cost_cumulative, "#dc6803", { yAxisID: "y1" }), limit(p, "y1")],
    y: { title: "USD / minute" }, y1: { title: "cumulative USD" },
  }),
  tokens: p => ({
    stats: { "tokens_in": p.summary.sum_by_field.tokens_in, "tokens_out": p.summary.sum_by_field.tokens_out },
    datasets: [bar("tokens_in / min", S.tokens_in, "#84adff", { stack: "t" }),
               bar("tokens_out / min", S.tokens_out, "#2e6ef7", { stack: "t" }),
               line("Cumulative tokens_in", S.tokens_in_cumulative, "#6172f3", { yAxisID: "y1" }),
               line("Cumulative tokens_out", S.tokens_out_cumulative, "#3538cd", { yAxisID: "y1" }),
               limit(p, "y1")],
    y: { title: "tokens / minute", stacked: true }, y1: { title: "cumulative tokens" }, xStacked: true,
  }),
  quality: p => ({
    stats: { "Mean quality": p.summary.mean },
    datasets: [line("Mean quality_score", S.quality_mean, "#7a5af8"), limit(p)],
    y: { title: "score (0–1)", min: 0, max: 1 },
  }),
};

const grid = document.getElementById("grid");
for (const p of D.panels) {
  const spec = PANELS[p.id](p);
  const card = document.createElement("section");
  card.className = "card";
  const badge = p.breached === null ? ["na", "NO DATA"] : p.breached ? ["bad", "BREACH"] : ["ok", "OK"];
  card.innerHTML = `
    <div class="head">
      <div><h2></h2><div class="unit"></div></div>
      <span class="badge ${badge[0]}">${badge[1]}</span>
    </div>
    <div class="stats"></div>
    <div class="threshold"></div>
    <div class="chart"><canvas></canvas></div>
    <code></code>`;
  card.querySelector("h2").textContent = p.title;
  card.querySelector(".unit").textContent = `Unit: ${p.unit}`;
  card.querySelector(".threshold").textContent =
    `Threshold: ${p.threshold.aggregation} ${OPS[p.threshold.operator]} ${p.threshold.value} ${p.unit}`;
  card.querySelector("code").textContent = p.query;
  const stats = card.querySelector(".stats");
  for (const [k, v] of Object.entries(spec.stats)) {
    const el = document.createElement("div");
    el.innerHTML = "<span></span> <b></b>";
    el.querySelector("span").textContent = k;
    el.querySelector("b").textContent = fmt(v, 6);
    stats.appendChild(el);
  }
  grid.appendChild(card);

  const scales = {
    x: { title: { display: true, text: "minute (UTC)" }, stacked: !!spec.xStacked, ticks: { maxTicksLimit: 12 } },
    y: { title: { display: true, text: spec.y.title }, beginAtZero: true, stacked: !!spec.y.stacked,
         min: spec.y.min, max: spec.y.max },
  };
  if (spec.y1) scales.y1 = { position: "right", beginAtZero: true, grid: { drawOnChartArea: false },
                             title: { display: true, text: spec.y1.title } };
  new Chart(card.querySelector("canvas"), {
    data: { labels: D.labels, datasets: spec.datasets },
    options: { responsive: true, maintainAspectRatio: false, animation: false,
               interaction: { mode: "index", intersect: false },
               plugins: { legend: { labels: { boxWidth: 12, font: { size: 11 } } } }, scales },
  });
}
</script>
</body>
</html>
"""


def render_html(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return (
        PAGE.replace("__DATA__", payload)
        .replace("__REFRESH__", str(data["refresh_seconds"]))
        .replace("__TITLE__", data["title"])
    )


def main() -> None:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Dashboard 6 panel từ data/logs.jsonl")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--logs", type=Path, default=DEFAULT_LOGS)
    parser.add_argument("--port", type=int, default=8050)
    parser.add_argument("--snapshot", type=Path, help="Ghi 1 file HTML tĩnh rồi thoát")
    args = parser.parse_args()

    config = load_dashboard_config(args.config)

    def page() -> str:
        return render_html(build_dashboard(load_records(args.logs), config, datetime.now(timezone.utc)))

    if args.snapshot:
        args.snapshot.write_text(page(), encoding="utf-8")
        print(f"Đã ghi {args.snapshot}")
        return

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - tên method do http.server quy định
            if self.path.split("?")[0] not in ("/", "/index.html"):
                self.send_error(404)
                return
            body = page().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: Any) -> None:
            return None

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Dashboard: http://127.0.0.1:{args.port}  (Ctrl+C để dừng)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
