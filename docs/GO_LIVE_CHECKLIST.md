# Pre–go-live checklist — controlled deployment

Use this for a **first production** or **controlled cutover** (staging → prod, new region, or major upgrade). Check boxes as you complete each item. Adjust scope if the API is VPN-only or internet-facing.

**Related docs:** `DEPLOYMENT.md`, `docs/OPERATOR_RUNBOOK.md`, `docs/ROUTE_AUTH_MATRIX.md`, `docs/REVERSE_PROXY_SECURITY.md`, `docs/SECRET_ROTATION_RUNBOOK.md`, `docs/API_CONFIGURATION.md`.

---

## 1. Environment variables verified

- [ ] **`APP_ENV`** (or `ENV` / `ENVIRONMENT`) set to production profile **only** when ready: non-`dev`/`development`/`local` values require **`DATABASE_URL`**, **`SESSION_SECRET_KEY`**, and **`ADMIN_API_KEY`** at startup (no fallbacks).
- [ ] **`DATABASE_URL`** correct for target cluster (Postgres URL or SQLite path); pooler vs direct URL understood.
- [ ] **`ALEMBIC_DATABASE_URL`** set if migrations need a non-pooler URL; **`ALEMBIC_UPGRADE_ON_START`** decision documented.
- [ ] **`ADMIN_API_KEY`** strong, unique, stored in secrets manager; matches **`VITE_ADMIN_API_KEY`** in dashboard build pipeline.
- [ ] **`SESSION_SECRET_KEY`** strong, unique; not reused from other systems.
- [ ] **`GOOGLE_CLIENT_ID`** / **`GOOGLE_CLIENT_SECRET`** match the Google Cloud **Web** OAuth client; **Authorized redirect URIs** include `https://<api-host>/oauth/gmail/callback` (and any `/auth/callback` host you use).
- [ ] **`FRONTEND_URL`** is the real dashboard origin used after OAuth redirects.
- [ ] **`CORS_ALLOW_ORIGINS`** or **`CORS_ALLOW_ORIGIN_REGEX`** includes only intended dashboard origins (not dev defaults in prod).
- [ ] **`DEBUG`** unset or `0` / `false` / `no` (no `/debug/*`, no scheduler DEBUG seed).
- [ ] **`DISABLE_SCHEDULER`** — intentional: `0` for normal prod with in-process scheduler, or `1` if another worker owns jobs (document who runs sends).
- [ ] **`FOLLOWUPS_ENABLED`** — explicit `1`/`true`/`yes` only if follow-ups are in scope for this release.
- [ ] **`FOLLOWUPS_DRY_RUN`** — explicit choice (default in code is dry-run **on**; see section 5).
- [ ] **`LOG_LEVEL`** appropriate (`INFO` typical).
- [ ] **`PORT`** / container port alignment with load balancer target port.
- [ ] Optional: **`ENFORCE_IST_SEND_WINDOW`**, sheet sync thresholds, **`FRONTEND_URL`** for email footers if applicable — reviewed.

---

## 2. Backups tested

- [ ] **Postgres:** Provider snapshot or `pg_dump` run **successfully** to durable storage; restore drill done at least once on a **non-prod** clone (or documented owner + RTO/RPO).
- [ ] **SQLite (if used):** `POST /admin/backup/sqlite` with `X-API-Key` succeeds; file appears under `backups/`; **`GET /admin/backup/sqlite/download/{file}`** requires the same key; copy artifact off-box.
- [ ] Backup **retention** and **encryption** at rest defined (who can read dumps).
- [ ] No reliance on Google Sheets as **authoritative** recovery (mirror only); see operator runbook / DR notes.

---

## 3. Health endpoints green

From outside the cluster (or via LB), without auth unless noted:

- [ ] **`GET /health/`** → `200`, `db: ok`.
- [ ] **`GET /health/scheduler/status`** → `scheduler: running` (unless `DISABLE_SCHEDULER=1` by design).
- [ ] **`GET /health/scheduler/metrics`** → `running: true`, no unbounded `job_errors` / `missed_runs` spike vs baseline.
- [ ] **`GET /health/sheet-sync/status`** → `health` not `critical` for sustained period; `stuck_suspected` understood if `true`.
- [ ] **`GET /health/config`** → `scheduler_enabled`, `cors_configured`, `environment` match expectations.
- [ ] **`GET /scheduler/status`** (alias) matches scheduler status above.

---

## 4. Auth checks verified

With **`ADMIN_API_KEY`** set as in production:

- [ ] **`GET /analytics/summary`** with `X-API-Key` → `200`; without key → `403`.
- [ ] **`GET /students`** (or a safe list endpoint) → `200` with key; `403` without.
- [ ] **`GET /audit/`** with `X-API-Key` or `X-Admin-Key` → `200` (admin router).
- [ ] **`POST /audit/clear`** — **not** run in prod as a test; confirm only authorized operators know it exists.
- [ ] **`GET /oauth/gmail/start?student_id=<uuid>`** with key → `auth_url` returned.
- [ ] **`GET /oauth/gmail/callback`** — no API key (browser redirect); smoke with test user in lower env first.
- [ ] **Dashboard** loads and API calls succeed (browser sends `VITE_ADMIN_API_KEY` as `X-API-Key`).
- [ ] **`/ws/logs`** in production: connection **fails** without `api_key` query param; **succeeds** with correct key (if used).
- [ ] Proxy / WAF: if using **dual-key** rotation window, both keys tested (see `docs/SECRET_ROTATION_RUNBOOK.md`).

---

## 5. Dry-run disabled / enabled intentionally

**Outbound / safety flags:**

- [ ] **`FOLLOWUPS_DRY_RUN`** — documented decision:
  - **`true`:** manual `POST /followups/send` returns `dry_run: true` (no Gmail send) — safe for rehearsal.
  - **`false`:** real sends after claim — only after explicit sign-off.
- [ ] Team trained: **200 + `dry_run: true`** is **not** a sent email.
- [ ] **`FOLLOWUPS_ENABLED`** matches release scope (`0` = no follow-up rows in scheduler selection beyond initial).

**Other “dry” surfaces:**

- [ ] No accidental **`DEBUG=1`** in prod env.
- [ ] Admin **`POST /campaigns/run_once`** — restricted to break-glass; not used for “dry” normal ops without awareness it sends/for bypasses window.

---

## 6. Follow-up dry run validated (if follow-ups in scope)

- [ ] With **`FOLLOWUPS_ENABLED=1`** and **`FOLLOWUPS_DRY_RUN=1`**: `POST /followups/send?student_id=&hr_id=` returns **`dry_run: true`** and `would_send` payload for a known test pair.
- [ ] **`GET /followups/eligible`** and **`GET /followups/preview`** behave as expected for test data.
- [ ] After intentional **`FOLLOWUPS_DRY_RUN=0`**: single controlled send test in **non-prod** first; then one canary pair in prod if policy allows.
- [ ] Reconcile paths documented: **`GET /followups/reconcile/stale`**, **`POST .../mark-sent`**, **`POST .../pause`** — operators know when to use them.

---

## 7. Operator access verified

- [ ] **VPN / IP allowlist** (if used): operators can reach API and dashboard from approved networks.
- [ ] **TLS**: browser shows valid certificate for API and dashboard hosts.
- [ ] **Role access:** at least two operators confirm login + key (or SSO if added later) — no single-person dependency.
- [ ] **Runbooks bookmarked:** `docs/OPERATOR_RUNBOOK.md`, emergency disable (`DISABLE_SCHEDULER`, `FOLLOWUPS_*`), `docs/GO_LIVE_CHECKLIST.md` (this file).
- [ ] **On-call channel** and escalation path defined for “sends stopped” / “DB down” / “OAuth broken”.

---

## 8. Rollback steps ready

- [ ] **Previous container image** (or git tag) identified and deployable in &lt; 15 minutes.
- [ ] **Previous secrets revision** in vault retained until post-release stable.
- [ ] **Database:** migration rollback strategy documented (Alembic downgrade **or** restore-from-backup — which applies).
- [ ] **DNS / LB:** ability to point traffic back to prior stack or drain new stack.
- [ ] **Feature flags:** list of env vars to revert (`FOLLOWUPS_ENABLED`, `FOLLOWUPS_DRY_RUN`, `DISABLE_SCHEDULER`) in one place.
- [ ] **Rollback owner** named (who executes, who approves).

---

## 9. Monitoring checks after launch

First **30–120 minutes** after traffic shift:

- [ ] **Error rate** — API 5xx, 503 DB errors, Gmail / sheet sync errors in logs.
- [ ] **Health probes** — LB target health stable; `/health/` not flapping.
- [ ] **Scheduler metrics** — `GET /health/scheduler/metrics` periodically; jobs finishing (`last_ok`), no error storm.
- [ ] **Sheet sync** — `/health/sheet-sync/status` not stuck `critical` without explanation.
- [ ] **DB** — connection count, CPU, disk; pool exhaustion alerts if configured.
- [ ] **OAuth** — no spike in failed callbacks in logs.
- [ ] **Audit** — `GET /audit/?limit=50` shows expected actions (optional sanity).

---

## 10. First-day smoke test checklist

Perform with a **non-demo** student/HR pair only if policy allows; otherwise use dedicated test accounts.

| # | Check | Pass |
|---|--------|------|
| 1 | Dashboard opens; analytics loads | [ ] |
| 2 | `GET /health/` + scheduler + sheet-sync status from operator laptop | [ ] |
| 3 | Gmail OAuth start for one student completes; student shows connected | [ ] |
| 4 | One **initial** outreach path: preview or send per your procedure (`POST /outreach/send` or scheduler-driven) | [ ] |
| 5 | **`/email-logs`** or **`/outreach/logs`** shows recent activity | [ ] |
| 6 | If follow-ups live: dry-run send, then (if approved) single real send or scheduler observation | [ ] |
| 7 | Sheet mirror: confirm new reply/failure row appears on sheet within expected lag (if sheet sync enabled) | [ ] |
| 8 | **`POST /admin/backup/sqlite`** or confirm provider backup job ran (Postgres) | [ ] |
| 9 | No unexpected **`POST /audit/clear`** or mass deletes | [ ] |
| 10 | End-of-day: scheduler still running; no critical sheet-sync stuck | [ ] |

---

## 11. Sign-off

| Role | Name | Date | Signature / note |
|------|------|------|-------------------|
| Engineering | | | |
| Operations | | | |
| Product / owner | | | |

---

## Appendix — quick command snippets

Replace host and keys.

```http
GET https://api.example.com/health/
```

```http
GET https://api.example.com/analytics/summary
X-API-Key: <ADMIN_API_KEY>
```

```http
POST https://api.example.com/followups/send?student_id=<uuid>&hr_id=<uuid>
X-API-Key: <ADMIN_API_KEY>
```

(Expect `dry_run: true` in body when `FOLLOWUPS_DRY_RUN` is enabled.)
