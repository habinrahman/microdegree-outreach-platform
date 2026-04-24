# Disaster recovery and backup runbook — MicroDegree Outreach

This document complements `DEPLOYMENT.md` and `docs/OPERATOR_RUNBOOK.md`. **Priority:** stop data loss, restore confidentiality, then restore service.

## RPO / RTO risks (minimal architecture)

| Scenario | Typical RPO | Typical RTO | Mitigation |
|----------|-------------|-------------|------------|
| Postgres region outage | 0–24h unless PITR / HA | Hours–1d | Provider automated backups + tested restore to **new** DB + cutover |
| Accidental `DELETE` / bad migration | Last logical backup | Hours | Frequent `pg_dump`, row-level JSONL exports before destructive scripts |
| App-only failure | N/A | Minutes | Roll container / redeploy previous image |
| Supabase pooler / DNS flake | N/A | Minutes | Direct `:5432` URL for admin jobs; retries on app |

**Minimal production architecture**

1. **Managed Postgres** (e.g. Supabase) with **daily snapshots** + **PITR** where available.
2. **Logical exports**: scheduled `python -m app.scripts.pg_dump_backup --verify` (or provider export) to **encrypted object storage** off the app host.
3. **Operator snapshots** before risky cleanup: `python -m app.scripts.export_operator_snapshot --out ./exports/...`.
4. **Integrity job**: `python -m app.scripts.nightly_integrity_verify` in CI or cron; alert on non-zero exit.
5. **Dashboard**: `GET /admin/backup-health` (read-only) for last manifest + integrity flags.

---

## Automated `pg_dump` strategy

- **Tooling:** `python -m app.scripts.pg_dump_backup [--output-dir DIR] [--verify]`
- **Output:** `backups/microdegree_outreach_<UTC_ts>.dump` (custom `-Fc`) + `backup_manifest_<ts>.json`.
- **Verify:** `--verify` runs `pg_restore --list` and writes a second manifest line with `pg_restore_list_ok`.
- **Cron (Linux example):** `0 3 * * * cd /opt/app/backend && . ./venv/bin/activate && PG_DUMP_BIN=/usr/bin/pg_dump python -m app.scripts.pg_dump_backup --verify >> /var/log/pg_backup.log 2>&1`
- **Env:** `BACKUPS_DIR` (optional), `PG_DUMP_BIN`, `PG_RESTORE_BIN`.

**SQLite (dev):** `POST /admin/backup/sqlite` still copies the file and writes a manifest.

---

## Restore drill workflow (quarterly)

1. Take latest `.dump` from object storage to a **clean** jump host.
2. `python -m app.scripts.restore_drill_verify --dump ./microdegree_outreach_YYYYMMDD.dump` → exit 0.
3. Provision a **disposable** Postgres instance (or local Docker).
4. `pg_restore --no-owner --no-acl -d postgresql://.../restore_drill_db ./file.dump` (adjust flags to your security model).
5. Run read-only checks: row counts, `SELECT COUNT(*) FROM students`, spot-check `email_campaigns` recent `sent` rows.
6. Document: who ran it, version, duration, anomalies.

---

## Point-in-time recovery (PITR)

PITR is **provider-specific** (Supabase: Dashboard → Database → Backups / Point in time). General pattern:

1. **Freeze writes:** scale app to zero or enable maintenance.
2. **Restore to a new database** at target time (never overwrite prod in place until validated).
3. **Validate:** connect with read-only user; run app smoke tests against the **new** URL.
4. **Migrations:** run Alembic to expected revision if the restored instance lags head.
5. **Cutover:** atomically switch `DATABASE_URL` (and pooler URL if used) + restart workers.
6. **Reconcile:** any writes that happened on old primary after PITR time may need manual merge — treat as **residual risk**.

---

## Export snapshots (students / HR / campaigns / follow-ups)

Follow-ups live in `email_campaigns` (`email_type` followup\_\*). Export:

```bash
python -m app.scripts.export_operator_snapshot --out ./exports/pre_cleanup_$(date -u +%Y%m%d_%H%M%S)
```

Secrets (e.g. `app_password`, OAuth tokens) are **omitted** from student export — pair with your vault / OAuth re-link procedures.

---

## Panic rollback procedures

| Situation | Action |
|-----------|--------|
| Bad deploy | Revert container/image to last known good; no DB change. |
| Bad migration forward | If down migration is safe, Alembic downgrade on a **clone** first; else restore DB from backup/PITR. |
| Mass accidental delete | Stop app; restore from latest **logical** backup or PITR to new DB; replay missing rows from JSONL export if available. |
| Data corruption suspected | Snapshot current state (even if bad) for forensics; restore from last **verified** backup; run `nightly_integrity_verify`. |

**App-level “stop sending”:** set `DELIVERABILITY_LAYER=1` and tighten env caps, or pause campaign groups in DB / disable scheduler via deployment controls — faster than full restore.

---

## Corruption detection

- **Structural:** `run_corruption_integrity_checks` (orphan assignments, campaigns, responses) — exposed via `GET /admin/backup-health` and `nightly_integrity_verify` CLI.
- **Logical:** use existing audit scripts (`audit_consistency.py`, fixture purge audit) for outreach-specific invariants.

---

## Operator dashboard

- `GET /admin/backup-health` — manifests, integrity, suggested commands.
- Admin UI: **Admin tools** page includes JSON + command hints.

---

## Verification checklist

- [ ] `pg_dump_backup --verify` succeeds against staging DB.
- [ ] `restore_drill_verify` passes on downloaded artifact.
- [ ] Full restore drill completed once per quarter (documented).
- [ ] `nightly_integrity_verify` exits 0 on production clone.
- [ ] Off-site copy of at least one recent `.dump` exists and is **encrypted at rest**.
