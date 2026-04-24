# Operator runbook — placement outreach system

This document is for **operators** running the MicroDegree HR placement outreach stack (FastAPI backend + dashboard). It reflects the **current** API and scheduler behavior in this repository.

**Authentication:** When `ADMIN_API_KEY` is set in the backend environment, most operator-facing write APIs require `X-API-Key` or `X-Admin-Key` with that value. The dashboard should set `VITE_ADMIN_API_KEY` to match for browser calls. OAuth callback routes do **not** use this header (Google redirect).

Replace `API` below with your backend base URL (for example `https://api.example.com` or `http://127.0.0.1:8010`).

---

## 1. Startup

### 1.1 Environment

1. Copy `backend/.env.example` to `backend/.env` (and optionally maintain a repo-root `.env`; backend values override non-empty keys from the root file).
2. **Required for production-style operation**
   - `APP_ENV` — use `production` (or any value other than `dev` / `development` / `local`) only when the following are all set; otherwise the API will **refuse to start**.
   - `DATABASE_URL` — SQLite path or PostgreSQL URL.
   - `ADMIN_API_KEY` — long random secret; enables API key checks on protected routers (HR, assignments, analytics, campaign manager, notifications, etc.).
   - `SESSION_SECRET_KEY` — long random secret for browser sessions and OAuth state signing (do **not** rely on dev defaults in production).
   - `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` — Gmail OAuth for sending.
   - `FRONTEND_URL` — dashboard origin used after OAuth (for example `https://dashboard.example.com`).
   - `CORS_ALLOW_ORIGINS` (comma-separated) **or** `CORS_ALLOW_ORIGIN_REGEX` — must include the dashboard origin in non-local deployments.

3. **Optional**
   - `PORT` — listen port (Dockerfile defaults to `8010`).
   - `ALEMBIC_UPGRADE_ON_START=1` — run `alembic upgrade head` once at API startup (failures are logged; process continues).
   - `ALEMBIC_DATABASE_URL` — direct Postgres URL for migrations if `DATABASE_URL` points at a pooler that breaks Alembic.
   - `DISABLE_SCHEDULER=1` — start API **without** background jobs (see [Emergency disable](#9-emergency-disable-procedures)).
   - `LOG_LEVEL` — default `INFO`.
   - `DEBUG` — must stay **off** in production (`1`/`true`/`yes` mounts `/debug/*` and can seed test campaigns in the scheduler).

### 1.2 Docker (typical)

```bash
docker compose up -d --build
```

Backend listens on host port **8010** mapped to container `PORT` (default `8010`). See `DEPLOYMENT.md` for OAuth redirect URI registration (`https://<backend>/oauth/gmail/callback`).

### 1.3 Local (development)

From `backend/` with venv activated:

```bash
uvicorn main:app --host 0.0.0.0 --port 8010
```

### 1.4 What starts with the API

On successful lifespan startup:

- Database init runs (non-blocking unless you use blocking DB init options documented in `.env.example`).
- Unless `DISABLE_SCHEDULER` is set, **APScheduler** starts with:
  - **campaign_send** — every **2** minutes (jitter) — sends due `EmailCampaign` rows.
  - **gmail_monitor** — every **5** minutes — inbox / reply-related monitoring.
  - **reply_tracker** — every **5** minutes — reply detection pipeline.
  - **student_email_health** — every **5** minutes — refresh student send health signals.
  - **sheet_sync_job** — every **2** minutes — push new replies / failures / bounces to Google Sheets.

**Note:** Scheduled **HR lifecycle** job is not registered in code (commented out); HR lifecycle can still be triggered manually via admin endpoint (below).

---

## 2. Health checks

Use these for load balancers, uptime monitors, and on-call triage.

| Check | Method | Path | Purpose |
|--------|--------|------|---------|
| Liveness + DB | `GET` | `/health/` | `SELECT 1`; returns `{"status":"ok","db":"ok"}` or fails if DB unreachable. |
| Scheduler running | `GET` | `/health/scheduler/status` | `{"scheduler":"running"}` / `"stopped"` / `"unknown"`. |
| Same (alias) | `GET` | `/scheduler/status` | Identical payload for dashboard compatibility. |
| Scheduler metrics | `GET` | `/health/scheduler/metrics` | In-process: `running`, per-job `last_started_at_utc`, `last_finished_at_utc`, `last_duration_ms`, `last_ok`, `last_error`, plus `missed_runs`, `job_errors`, `last_event_at_utc`. |
| Sheet sync depth | `GET` | `/health/sheet-sync/status` | Pending counts, ages, `health` (`ok` / `warning` / `critical`), `stuck_suspected`. Tuned by `SHEET_SYNC_WARN_MINUTES`, `SHEET_SYNC_CRIT_MINUTES`, `SHEET_SYNC_STUCK_MINUTES` (defaults 10 / 30 / 20). |
| Sheet sync trigger clock | `GET` | `/health/sheet-sync/trigger` | Last async sheet-sync trigger timestamp (diagnostics). |
| Config snapshot (no secrets) | `GET` | `/health/config` | `environment`, `api_port`, `scheduler_enabled`, `cors_configured`. |

**Suggested probes**

- **Liveness:** `GET /health/` every 10–30s.
- **Deep:** `GET /health/scheduler/status` + `GET /health/sheet-sync/status` every 1–5m for dashboards or paging.

---

## 3. Normal outreach flow

High-level sequence (conceptual):

1. **Students** — Active students with Gmail / app credentials and templates configured (`/students` API; key required when `ADMIN_API_KEY` is set).
2. **HR directory** — Valid HR contacts (`/hr` …).
3. **Assignments** — Link students to HRs (`POST /assignments`). Campaign rows are generated for the pair where policy allows.
4. **OAuth** — Each student sending via Gmail API must complete Gmail OAuth (`/oauth/gmail/start` — key required when configured).
5. **Initial send** — Operator or dashboard triggers `POST /outreach/send` with `student_id` and `hr_id` or `hr_email`. Alias: `POST /followup1/send` (same body shape as outreach send).
6. **Monitor** — `GET /outreach/logs` or alias `GET /email-logs` for recent sends; analytics under `/analytics/summary` and related routes.
7. **Scheduler** — Picks **scheduled** campaigns that are due, respects student email health and paused HRs, sends via `process_email_campaign` (Gmail API path when OAuth is available).

**IST window:** When `ENFORCE_IST_SEND_WINDOW` is enabled (`1`/`true`/`yes`), the scheduler’s normal job respects the configured IST business window (see `app.config` / code for hours). Admin **`POST /campaigns/run_once`** bypasses window and scheduled time (see below — requires admin key).

**Campaign group pause:** To stop a named campaign group from being sent, `POST /campaign-manager/{campaign_id}/pause` (resume: `POST .../resume`). This router is not behind the same API-key dependency as `/outreach`; secure it at the network layer or ensure your deployment model accounts for that.

---

## 4. Follow-up workflow

### 4.1 Feature flags (`backend/.env`)

| Variable | Default | Meaning |
|----------|---------|---------|
| `FOLLOWUPS_ENABLED` | off | Must be `1`/`true`/`yes` for follow-up campaign rows beyond the initial email to be generated and for scheduler to pick **follow-up** email types (not only `initial`). |
| `FOLLOWUPS_DRY_RUN` | **on** (`true`) | When on, `POST /followups/send` runs eligibility and returns a **dry_run** payload — **no email**, no claim for real send. Set to `0`/`false`/`no` only when you intend real sends. |

Restart the API after changing these (they are read at import time).

### 4.2 Read-only checks

- `GET /followups/eligible` — list who is eligible for manual follow-up orchestration (read-only).
- `GET /followups/preview?student_id=...&hr_id=...` — subject/body preview and eligibility reasons (read-only).

### 4.3 Manual send

- `POST /followups/send?student_id=<uuid>&hr_id=<uuid>`

Behavior:

- If `FOLLOWUPS_ENABLED` is off → **409** `Follow-ups disabled`.
- If not eligible or send in progress → **409** with a reason.
- If `FOLLOWUPS_DRY_RUN` is on → **200** with `dry_run: true` and `would_send` (no Gmail send).
- Otherwise the row is **claimed** (`pending`/`scheduled` → `processing`); exactly one operator wins; others get **409** `Another operator already claimed this send`.

### 4.4 Automated sends

With `FOLLOWUPS_ENABLED` on, the **campaign_send** job includes follow-up email types in its query. With it off, only `initial` campaigns are selected.

---

## 5. Stale processing reconciliation

Sometimes a follow-up row stays in **`processing`** (browser closed, worker crash, unknown Gmail outcome). Operators can list and repair without sending mail from reconcile endpoints.

### 5.1 List stale rows

`GET /followups/reconcile/stale?threshold_minutes=15&limit=200`

- Read-only.
- Returns follow-up rows (`followup_1` / `followup_2` / `followup_3`) in `processing` where `processing_started_at` is older than the threshold.

### 5.2 Mark as sent (unknown outcome, treat as delivered)

`POST /followups/reconcile/mark-sent?campaign_id=<uuid>&threshold_minutes=15`

- Row must be stale enough (same threshold semantics) or API returns **409** `Not stale enough to reconcile`.
- Sets status to **`sent`**; clears processing timestamps. **Does not** call Gmail.
- Audit action: `followup_reconciled_mark_sent` (best-effort).

Use when you have **evidence** the email actually left (for example Sent folder) but the DB never updated.

### 5.3 Pause (unknown outcome, stop retries)

`POST /followups/reconcile/pause?campaign_id=<uuid>&threshold_minutes=15`

- Sets status to **`paused`** with a documented error string; clears processing timestamps. **Does not** send.
- Audit action: `followup_reconciled_pause` (best-effort).

Use when outcome is unknown and you want the row out of **`processing`** without claiming it as sent.

---

## 6. Common failures and responses

| Symptom | Likely cause | What to do |
|---------|----------------|------------|
| **403 Forbidden** on outreach/students/followups | Missing or wrong `X-API-Key` / `X-Admin-Key` | Set header to `ADMIN_API_KEY`; redeploy dashboard env if needed. |
| **503** `Database temporarily unavailable` | Pooler timeout, DB restart, network | Check Postgres/Supabase; verify `DATABASE_URL`; retry; see DB pool env vars in `app/database/config.py`. |
| **409** on follow-up send: disabled | `FOLLOWUPS_ENABLED` not set | Set env to `1`, restart. |
| **409** on follow-up send: dry run | `FOLLOWUPS_DRY_RUN` still true | Set to `false`, restart, **only** after deliberate approval. |
| **409** `Another operator already claimed` | Two operators sent same pair | Expected safety; refresh UI; one send proceeds. |
| **409** `Send already in progress` | Eligibility sees in-flight state | Wait or reconcile stale `processing` (section 5). |
| **400** invalid UUIDs on follow-up routes | Bad query params | Fix `student_id` / `hr_id` format. |
| Campaigns **expired** with `stale campaign >24h` | `scheduled_at` too old | Regenerate or reschedule campaigns; investigate why sends did not run. |
| **`gmail_auth_block`** / paused sends | Recent SMTP auth failure path | Wait cooldown (~10 minutes per code paths) or fix student credentials/OAuth. |
| Sheet sync **warning/critical** on `/health/sheet-sync/status` | Pending export backlog or stuck sync | Inspect logs for `sheet_sync`; check Google API quotas and service account / OAuth used for sheets; see section 7. |
| OAuth redirect errors | `FRONTEND_URL` / redirect URI mismatch | Align Google Cloud **Authorized redirect URIs** with `DEPLOYMENT.md`; set `FRONTEND_URL` to real dashboard. |

**Audit trail:** `GET /audit/` with `X-Admin-Key` lists recent events (when admin key is configured). Avoid calling `POST /audit/clear` unless you fully intend to wipe logs.

---

## 7. Scheduler unhealthy playbook

### 7.1 Quick signals

1. `GET /health/scheduler/status` → expect `"running"`.
2. `GET /health/scheduler/metrics` → check:
   - `running: true`
   - Per-job `last_ok`, `last_error`, `last_duration_ms` (very large duration may indicate stuck work).
   - `missed_runs` / `job_errors` increasing → job exceptions or overloaded scheduler.

3. `GET /health/sheet-sync/status` → if `health` is `critical` or `stuck_suspected` is true, treat sheet pipeline as degraded even if scheduler process is up.

### 7.2 Logs

Search API logs for:

- `Campaign scheduler disabled`
- `scheduler job missed` / `scheduler job error`
- `sheet_sync job failed`
- `run_campaign_job: database unavailable`
- `Internal server error` in send loop

### 7.3 Safe mitigations

- **Stop automatic sends only:** set `DISABLE_SCHEDULER=1`, restart API. Manual `POST /outreach/send` may still send depending on product use — coordinate with policy.
- **One-shot catch-up (admin):** `POST /campaigns/run_once?limit=5` with `X-Admin-Key` runs the campaign job with **ignored** IST window and **ignored** `scheduled_at`, **no** inter-email delay — use sparingly for incident recovery.
- **Gmail / reply jobs:** `POST /campaigns/gmail_monitor/run_once` and rely on reply tracker job metrics; fix underlying Gmail or DB issues first.

### 7.4 Process stuck / zombie

If the container is wedged: restart the backend service. On startup, scheduler should reattach with a fresh thread pool (`max_workers=4`). Ensure **only one** scheduler-enabled API instance runs against the same DB if you use row locking semantics (Postgres `FOR UPDATE SKIP LOCKED`); multiple instances can be supported for campaign sends but increase complexity — monitor `job_errors` and DB contention.

---

## 8. Backup and restore

### 8.1 SQLite (dev / small deployments)

**Backup**

```http
POST /admin/backup/sqlite
X-API-Key: <ADMIN_API_KEY>
```

Or alias `POST /admin/backup`. Response includes `backup_file` name under the backend `backups/` directory.

**Download**

```http
GET /admin/backup/sqlite/download/<filename>
X-API-Key: <ADMIN_API_KEY>
```

**Restore**

1. Stop the API.
2. Replace the SQLite file referenced by `DATABASE_URL` with a copied `.db` backup (keep a copy of the current file first).
3. Start the API.

Paths are relative to the process working directory (Docker: typically `/app`).

### 8.2 PostgreSQL (production)

The application does **not** perform `pg_dump` for you. Use your provider’s backups or run `pg_dump` / PITR on a schedule. Store dumps encrypted and off-box.

**Restore** (generic): restore to a new instance or database, point `DATABASE_URL` at it, run Alembic to head if needed (`ALEMBIC_DATABASE_URL` for direct connection), then cut over traffic.

### 8.3 Sheet mirror rebuild (data consistency)

For severe sheet drift, operators with repo access may use the script path documented around `app/scripts/rebuild_sheet_mirror.py` (calls `rebuild_sheet_full`). Run only with engineering approval; it wipes and rebuilds mirrored tabs.

---

## 9. Emergency disable procedures

Use these to reduce blast radius during incidents. **Restart the API** after env changes unless your platform hot-reloads env (most do not for Python).

| Goal | Action |
|------|--------|
| **Stop all scheduled jobs** | Set `DISABLE_SCHEDULER=1`, restart. |
| **Stop follow-up generation / automated follow-ups** | Set `FOLLOWUPS_ENABLED=0` (or unset), restart. Scheduler then only considers `initial` campaigns. |
| **Stop real manual follow-up sends** | Set `FOLLOWUPS_DRY_RUN=1` (or default), restart. Manual endpoint returns dry-run payload only. |
| **Pause a campaign group** | `POST /campaign-manager/{id}/pause` (see section 3). |
| **Read-only API** | Not a single flag — combine `DISABLE_SCHEDULER=1` with network blocks (ingress firewall) or a maintenance page in front of the dashboard; revoking `ADMIN_API_KEY` breaks the dashboard until rotated. |

**Post-incident:** Re-enable flags in reverse order; verify `/health/*` and send a **test** dry-run follow-up before turning off `FOLLOWUPS_DRY_RUN`.

---

## 10. Quick reference — operator endpoints

All `X-API-Key` / `X-Admin-Key` values are the configured `ADMIN_API_KEY` unless your deployment uses a split (this codebase uses one key for both header types on protected routes).

| Action | Request |
|--------|---------|
| Health | `GET /health/` |
| Scheduler | `GET /health/scheduler/status`, `GET /health/scheduler/metrics` |
| Sheet sync health | `GET /health/sheet-sync/status` |
| Send initial / next due outreach | `POST /outreach/send` |
| Follow-up eligible list | `GET /followups/eligible` |
| Follow-up preview | `GET /followups/preview?student_id=&hr_id=` |
| Follow-up send | `POST /followups/send?student_id=&hr_id=` |
| List stale processing | `GET /followups/reconcile/stale` |
| Reconcile sent / paused | `POST /followups/reconcile/mark-sent`, `POST /followups/reconcile/pause` |
| SQLite backup | `POST /admin/backup/sqlite` |
| Admin campaign run | `POST /campaigns/run_once` (**X-Admin-Key**) |

---

## 11. Demo / synthetic data cleanup (database)

Use `app/scripts/cleanup_demo_data.py` to **preview** rows that look like seeds, fixtures, or disposable-domain tests, export a snapshot, then optionally delete them in **FK-safe order** (responses → notifications → `email_campaigns` → assignments → interviews → `hr_ignores` → `student_templates` → `campaigns` → students / `hr_contacts`, plus optional `blocked_hrs` / `audit_logs`).

Heuristics live in `app/services/demo_data_heuristics.py` (`is_demo`, disposable domains, synthetic local parts, placeholder names/companies). **Default `--min-score 50`** avoids removing `test@` on a real domain unless you lower the threshold. Safest narrow pass: `--only-is-demo`.

From `backend/` with `DATABASE_URL` set:

```bash
# Preview only (no writes)
python -m app.scripts.cleanup_demo_data

# Preview + JSONL/CSV backup under ./cleanup_export/
python -m app.scripts.cleanup_demo_data --export-dir ./cleanup_export

# Narrow: only is_demo=true rows
python -m app.scripts.cleanup_demo_data --only-is-demo --export-dir ./cleanup_export

# Never delete these UUIDs
python -m app.scripts.cleanup_demo_data --protect-student-ids "<uuid>" --protect-hr-ids "<uuid>"

# Destructive (requires explicit acknowledgement)
python -m app.scripts.cleanup_demo_data --apply --i-understand --export-dir ./cleanup_export
```

HR list scores and analytics summaries are **computed on read**; no separate “recompute” job runs after cleanup.

### 11.1 Whitelist-only student purge (recommended over heuristics)

Script: `app/scripts/cleanup_keep_whitelist.py`. You pass an explicit **keep** list (built-in default names plus optional `--keep-file` / `--keep-names`, or `--no-default-keep` for a custom list only). Every **other** student row is removed with FK-safe deletes of that student’s assignments, `email_campaigns`, responses, interviews, `hr_ignores`, `student_templates`, and related `campaigns` rows. **HR contacts are not deleted.**

```bash
# Preview (no writes): students to KEEP vs REMOVE + linked counts
python -m app.scripts.cleanup_keep_whitelist preview

# Custom keep file (one name or student UUID per line) and no built-in defaults
python -m app.scripts.cleanup_keep_whitelist preview --no-default-keep --keep-file ./my_keep.txt

# Apply: snapshot first, then delete (blocked if any keep token is unmatched / ambiguous)
python -m app.scripts.cleanup_keep_whitelist apply --export-dir ./cleanup_export --i-understand
```

Matching is **normalized full-name equality** (case/spacing-insensitive) or a **student UUID** line. Unmatched tokens show **substring suggestions** in preview only. Apply is refused until every token resolves to exactly one student.

### 11.2 Whitelist HR purge (real HRs + outreach anchor)

Script: `app/scripts/cleanup_keep_hr_whitelist.py`. **Default:** auto-keep every `hr_id` that appears in assignments, `email_campaigns`, or `responses` for students matching the same **built-in real student name list** as §11.1 (`student_whitelist_cleanup.DEFAULT_STUDENT_KEEP_NAMES`). Union with **explicit** keeps: `--keep-file` / `--keep-emails` (normalized email or `hr_contacts` UUID per entry). All **other** `hr_contacts` rows are deleted with FK-safe cleanup of their assignments, campaigns, responses, interviews, `hr_ignores`, orphan `campaigns`, and matching **`blocked_hrs`** (unless disabled). **Students are never deleted.**

```bash
python -m app.scripts.cleanup_keep_hr_whitelist preview

python -m app.scripts.cleanup_keep_hr_whitelist preview --keep-emails "recruiter@company.com,<uuid>"

python -m app.scripts.cleanup_keep_hr_whitelist preview --no-student-anchor --keep-file ./hrs_to_keep.txt

python -m app.scripts.cleanup_keep_hr_whitelist apply --export-dir ./cleanup_export --i-understand
```

Apply is refused if the final **keep set is empty** or any **explicit** keep token does not match an HR. Unmatched **student anchor** names only shrink the anchor set (warning); they do not block apply by themselves.

### 11.3 Restore ``hr_contacts`` from a whitelist snapshot

If HR rows were removed by mistake, re-insert them from the backup folder created by ``cleanup_keep_hr_whitelist apply`` (contains ``hr_contacts_to_remove.jsonl`` or ``.csv``, plus ``manifest.json``).

Script: `app/scripts/restore_hr_contacts_from_snapshot.py`. It **only inserts** missing contacts (original **UUID** and normalized **email** from the snapshot). It **does not update** existing rows. Skips when the **id** or **email** already exists (idempotent). Uses a savepoint per insert so a rare DB constraint race does not abort the whole batch.

```bash
python -m app.scripts.restore_hr_contacts_from_snapshot preview --snapshot-dir ./cleanup_export/hr_whitelist_cleanup_20260422_180139

python -m app.scripts.restore_hr_contacts_from_snapshot restore --snapshot-dir ./cleanup_export/hr_whitelist_cleanup_20260422_180139 --i-understand
```

Restored columns beyond the snapshot are defaults only (`status=active`, `is_valid=true`, `is_demo=false`). Re-link assignments / campaigns separately if those rows were deleted too (not covered by this script).

### 11.4 Synthetic HR-only purge (explicit patterns)

Script: `app/scripts/cleanup_synthetic_hr_only.py`. Deletes **only** `hr_contacts` whose email/name/company match a **fixed allow-list of synthetic patterns** (see `app/services/synthetic_hr_cleanup.py` — local-part prefixes `tb0_`, `tb1_`, `od1_`, `od2_`, `dm_`, `xx_`, `x_` with an exception for `x_user*`, exact domains `samecorp.com`, `corp2.com`, `acme.com`, `blk.com`, and exact placeholder names/companies such as `C0`, `Co`, `Good`, single-letter `A`…`Z` where listed). **No substring domain matching** on real hosts (e.g. `exactlycorp.com`, `unacademy.com`, `talkdesk.com`).

```bash
python -m app.scripts.cleanup_synthetic_hr_only preview

python -m app.scripts.cleanup_synthetic_hr_only apply --export-dir ./cleanup_export --i-understand
```

Preview prints counts **by primary pattern** and sample rows, then a **referential integrity audit** (synthetic HRs remaining, orphan assignments/campaigns, broken `email_campaigns` FKs). Apply writes `synthetic_hr_cleanup_*` under `--export-dir`, runs the same FK-safe HR cascade as §11.2, **commits**, then prints a **post-apply audit** (same checks). Programmatic checks live in `app/services/synthetic_hr_audit.py`; CI regression uses `tests/fixtures/ci_safe_hr_profiles.json` (profiles must never match synthetic patterns).

---

## 12. Related documentation

- `DEPLOYMENT.md` — Docker, OAuth redirect URIs, high-level backup notes.
- `docs/API_CONFIGURATION.md` — CORS and frontend `VITE_*` variables.
- `docs/SECRET_ROTATION_RUNBOOK.md` — Rotating `ADMIN_API_KEY`, `SESSION_SECRET_KEY`, Google OAuth, and DB credentials with minimal impact.
- `docs/GO_LIVE_CHECKLIST.md` — Pre–go-live verification, smoke tests, and rollback readiness.
- `backend/.env.example` — Environment variable templates and comments.
