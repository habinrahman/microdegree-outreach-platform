# Incident severity matrix & failure mode analysis (FMEA)

## Severity matrix (suggested)

| Sev | User / data impact | Response time target | Examples |
|-----|-------------------|----------------------|----------|
| **SEV1** | Confidentiality breach, mass mis-send, or total outage | Immediate page, freeze sends | Key leak, wrong DB pointed in prod |
| **SEV2** | Major feature down (no sends / no replies) or high data corruption risk | < 1h | Scheduler dead, Postgres hard down |
| **SEV3** | Partial degradation, workaround exists | < 4h | Sheet sync stuck, single student OAuth |
| **SEV4** | Cosmetic / minor | Best effort | UI glitch, non-prod |

## FMEA (abbreviated)

| ID | Component | Failure mode | Detection | Mitigation |
|----|-----------|--------------|-----------|------------|
| F1 | Postgres / pooler | Connection drops mid-send | 503 logs, scheduler errors | Pool pre-ping, direct URL for admin, retry |
| F2 | SMTP / Gmail | Auth or rate block | `smtp_send_failure_total`, health flags | Cooldown, deliverability pause, fix creds |
| F3 | IMAP reply job | Hang or timeout | Reply job latency, low reply rate alert | Lower `max_students`, fix network |
| F4 | Scheduler process | Crashed / not started | `scheduler_stalled` | `DISABLE_SCHEDULER` check, restart, metrics |
| F5 | Sheet sync | API quota / lock | `/health/sheet-sync/status` stuck | Backoff, reduce frequency |
| F6 | Human / script | Bad bulk delete | Integrity checks, exports | PITR, snapshot restore |
| F7 | Single campaign | Stuck `processing` | `stuck_processing_jobs` alert | Scheduler auto-pause stale rows |

## Error budget (product)

- **SLO example:** 99.5% of outbound sends succeed (non-bounce, non-5xx app) per calendar month.
- **Implementation:** `GET /admin/reliability` exposes a **24h proxy** only; bind monthly SLO in Prometheus/Grafana from exported counters once persistent store exists.

## Communications

- Post customer-impacting incidents in internal channel with: severity, blast radius, current mitigation, ETA for resolution, owner.
