# Minimal SRE architecture — MicroDegree Outreach

## Components

| Layer | Implementation |
|-------|----------------|
| **Logs** | Stdout JSON-friendly text with `[cid=…]` correlation ID (`app/observability/logging_setup.py`, `main.py` middleware). |
| **Metrics** | In-process counters + latency rings (`app/services/observability_metrics.py`). Prometheus text at `GET /admin/metrics/prometheus` when `METRICS_EXPORT_ENABLED=1` (same auth as other `/admin/*`). |
| **Health** | `GET /health/*` liveness, scheduler metrics, sheet-sync drift. |
| **Reliability API** | `GET /admin/reliability` — queues, SMTP 24h rollups, bounce/reply signals, anomaly rules, SLO proxy, DLQ/retry notes. |
| **UI** | Dashboard **System reliability** (`/system-reliability`). |

## External integration (recommended)

1. **Log shipper** (Vector / Fluent Bit / CloudWatch) → central store; alert on error rate + `cid` search.
2. **Prometheus** scrapes `/admin/metrics/prometheus` from internal network with `X-API-Key`.
3. **Pager / Slack** webhook driven by Prometheus alert rules (bounce spike, scheduler up, etc.).

## Correlation model

- HTTP: `X-Correlation-ID` in → echoed on response; propagated to logs.
- Jobs: background threads may omit `cid` (logs show `-`); for critical jobs set context at entry if needed.

## Trace semantics (campaign journey)

Logical path: **assignment → email_campaign rows → send/fail → follow-up eligibility → reply_tracker → terminal status**. Use `student_id`, `hr_id`, `email_campaigns.id`, and audit `meta.correlation_id` where populated.
