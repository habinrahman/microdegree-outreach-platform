# SRE runbook — operations

## Daily

- Open **System reliability** UI or `GET /admin/reliability`.
- Confirm `alerts` empty or only `info`.
- Check `smtp_rollups_24h.success_rate_pct_24h` vs `slo_panel.target_monthly_send_success`.

## Weekly

- Review `GET /health/sheet-sync/status` health level.
- Run `GET /admin/backup-health` (see disaster recovery runbook).
- Spot-check Prometheus scrape if enabled.

## Anomaly codes (built-in rules)

| Code | Meaning | First action |
|------|---------|----------------|
| `bounce_spike_1h` | Many `BOUNCE`/`BOUNCED` rows in 1h | Pause sends (`DELIVERABILITY_LAYER`), inspect HR list + SMTP errors. |
| `reply_rate_collapse` | Replies / sent very low with volume | Check IMAP / reply_tracker logs; credential expiry. |
| `scheduler_stalled` | `campaign_send` job not finishing | Restart API workers; inspect DB connectivity; see scheduler metrics. |
| `scheduler_last_job_failed` | Last tick failed | Read app logs with `[cid=…]`. |
| `followup_backlog_growth` | Large follow-up queue | Check `FOLLOWUPS_ENABLED`, IST window, student health flags. |
| `queue_starvation_suspected` | Due rows but almost no sends | Window / pause / OAuth / app passwords. |
| `stuck_processing_jobs` | Rows in `processing` too long | Investigate worker crashes; rows may be auto-paused by scheduler. |

## Dead letter queue (DLQ)

- **Primary:** `email_campaigns` with `status=failed` and `error` / `failure_type`.
- **Policy:** No automatic infinite retry on SMTP failure; operator or script resets specific rows after root-cause fix.

## Prometheus scrape

```bash
curl -sS -H "X-API-Key: $ADMIN_API_KEY" "https://api.example.com/admin/metrics/prometheus"
```

Requires `METRICS_EXPORT_ENABLED=1`.

## Regression tests

- `tests/test_correlation_id_middleware.py`
- `tests/test_sre_reliability_payload.py`
- `tests/test_metrics_prometheus_endpoint.py`
