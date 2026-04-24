"""
In-process application metrics (counters + simple latency rings).

Exposes Prometheus text via ``prometheus_text()`` for scraping behind auth
(see ``GET /admin/metrics/prometheus``).
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

_lock = threading.Lock()

_counters: dict[str, int] = {
    "http_requests_total": 0,
    "http_request_errors_total": 0,
    "smtp_send_success_total": 0,
    "smtp_send_failure_total": 0,
    "followup_send_attempt_total": 0,
    "followup_send_success_total": 0,
    "followup_send_failure_total": 0,
    "reply_ingestion_runs_total": 0,
    "reply_ingestion_replies_total": 0,
}

# latency samples in ms (bounded)
_MAX_LAT = 2000
_smtp_lat_ms: deque[float] = deque(maxlen=_MAX_LAT)
_followup_lat_ms: deque[float] = deque(maxlen=_MAX_LAT)
_reply_job_lat_ms: deque[float] = deque(maxlen=512)
_http_lat_ms: deque[float] = deque(maxlen=_MAX_LAT)


def inc(name: str, delta: int = 1) -> None:
    with _lock:
        _counters[name] = int(_counters.get(name, 0)) + int(delta)


def observe_latency(bucket: str, ms: float) -> None:
    v = float(ms)
    with _lock:
        if bucket == "smtp":
            _smtp_lat_ms.append(v)
        elif bucket == "followup_send":
            _followup_lat_ms.append(v)
        elif bucket == "reply_job":
            _reply_job_lat_ms.append(v)
        elif bucket == "http":
            _http_lat_ms.append(v)


def record_http_request(method: str, status_code: int, duration_ms: float) -> None:
    observe_latency("http", duration_ms)
    inc("http_requests_total")
    if int(status_code) >= 500:
        inc("http_request_errors_total")


def snapshot() -> dict[str, Any]:
    with _lock:
        def _pct(samples: deque[float], p: float) -> float | None:
            if not samples:
                return None
            arr = sorted(samples)
            idx = min(len(arr) - 1, int(round((len(arr) - 1) * p)))
            return round(float(arr[idx]), 2)

        return {
            "counters": dict(_counters),
            "latency_ms": {
                "http_p50": _pct(_http_lat_ms, 0.50),
                "http_p95": _pct(_http_lat_ms, 0.95),
                "smtp_p50": _pct(_smtp_lat_ms, 0.50),
                "smtp_p95": _pct(_smtp_lat_ms, 0.95),
                "followup_send_p50": _pct(_followup_lat_ms, 0.50),
                "followup_send_p95": _pct(_followup_lat_ms, 0.95),
                "reply_job_p50": _pct(_reply_job_lat_ms, 0.50),
                "reply_job_p95": _pct(_reply_job_lat_ms, 0.95),
            },
            "sample_counts": {
                "http": len(_http_lat_ms),
                "smtp": len(_smtp_lat_ms),
                "followup_send": len(_followup_lat_ms),
                "reply_job": len(_reply_job_lat_ms),
            },
            "generated_at_unix": time.time(),
        }


def prometheus_text() -> str:
    """Minimal Prometheus exposition (no external dependency)."""
    snap = snapshot()
    lines: list[str] = []
    for k, v in sorted(snap["counters"].items()):
        safe = k.replace("-", "_")
        lines.append(f"# HELP {safe} Application counter {k}")
        lines.append(f"# TYPE {safe} counter")
        lines.append(f"{safe} {int(v)}")
    lat = snap.get("latency_ms") or {}
    for name, val in sorted(lat.items()):
        if val is None:
            continue
        safe = f"app_latency_ms_{name}"
        lines.append(f"# HELP {safe} Observed latency percentile (ms)")
        lines.append(f"# TYPE {safe} gauge")
        lines.append(f"{safe} {float(val)}")
    return "\n".join(lines) + "\n"
