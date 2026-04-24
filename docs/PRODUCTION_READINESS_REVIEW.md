# Production readiness review — MicroDegree Outreach

**Role:** Principal engineer, final launch gate.  
**Scope:** Full platform (backend FastAPI, React dashboard, Postgres/SQLite, scheduler, email paths, DR, observability, security, data integrity, operator workflows).  
**Constraint:** No new product features in this review — assessment and recommendations only.

---

## Executive verdict

**Conditional Go for a controlled pilot** (defined cohort, defined SLOs, staffed on-call, known data volume) **if** Postgres + secrets + backups + edge security are correctly configured and a restore drill has passed.

**No-Go as unmanaged multi-tenant SaaS at high scale** without major work: single-node scheduler semantics, per-student SMTP/IMAP scaling limits, in-process metrics, and operational blast radius from email automation are not yet at “hands-off paying customers at 100×” maturity.

**Brutally honest (item 10):** Would I ship this to paying customers? **Yes, only as a B2B / internal automation product with clear operator ownership, a narrow blast radius, and an explicit “human in the loop” for destructive actions and for reputation-sensitive sends.** I would **not** market it as a self-serve mass cold-email platform without rate governance, provider compliance review, and multi-region / multi-worker hardening.

---

## 1. Launch readiness checklist (Go / No-Go)

### Go (all must be true for production pilot)

| # | Criterion | Evidence / owner |
|---|-----------|-------------------|
| G1 | **Postgres** in prod; `DATABASE_URL` not pooler-only for migrations if Alembic is flaky | Config + runbook |
| G2 | **`APP_ENV` / production profile** enforces `DATABASE_URL`, `SESSION_SECRET_KEY`, `ADMIN_API_KEY` | Startup behavior |
| G3 | **OAuth redirect URIs** match deployed backend; `FRONTEND_URL` correct | Google Cloud Console |
| G4 | **CORS** locked (`CORS_ALLOW_ORIGINS` or regex), not dev defaults | `main.py` / env |
| G5 | **Backup:** provider snapshots + tested `pg_dump` path OR proven provider export; **restore drill** documented and executed once | `DISASTER_RECOVERY_RUNBOOK.md` |
| G6 | **Fixture column bootstrap** verified on prod-like DB (`ensure_fixture_columns --verify-only`) | Script exit 0 |
| G7 | **At least one operator** can interpret `GET /admin/reliability`, `/admin/backup-health`, `/health/sheet-sync/status` | Training |
| G8 | **Incident path:** on-call + severity matrix agreed | `INCIDENT_SEVERITY_AND_FMEA.md` |
| G9 | **Security checklist** signed (keys, CORS, `DEBUG=0`, WS logs key in prod) | `SECURITY_CHECKLIST.md` |
| G10 | **Rollback:** previous container/image tag + DB restore path known | DR runbook |

### No-Go (any one blocks “unrestricted” launch)

| # | Criterion |
|---|-----------|
| N1 | Production running with **empty `ADMIN_API_KEY`** (API wide open) |
| N2 | **No off-site encrypted backup** of business-critical DB |
| N3 | **No restore drill** ever performed against a disposable clone |
| N4 | **Edge** without TLS / rate limits on `/oauth/*`, `/admin/*`, `/outreach/*` |
| N5 | **No owner** for email reputation (bounces, complaints, provider limits) when deliverability layer is off or mis-tuned |

---

## 2. Top 10 remaining technical risks (prioritized)

1. **Scheduler + worker coupling** — `process_email_campaign` runs synchronously in scheduler tick; tick capped (~50 campaigns, ~50s wall clock). Throughput and failure isolation are limited; one bad SMTP hang stalls the batch.
2. **Email as a blast radius** — Misconfiguration or compromised operator key → mass send or mass export; reputational and legal exposure exceed typical CRUD apps.
3. **Single-process metrics / correlation** — In-memory metrics reset on restart; multi-worker UVicorn fragments series; no distributed trace store.
4. **Supabase / pooler fragility** — Already a pain point (Alembic/DNS); production must use direct `:5432` for admin jobs and validated pool settings (`DB_POOL_*`, keepalives).
5. **IMAP reply ingestion** — Bounded by `max_students` scan; slow or failing IMAP looks like “reply collapse” alerts; credential rotation is operationally heavy.
6. **Idempotency vs unknown outcome** — Stale `processing` → `paused` is correct for safety but creates **manual** backlog work; operators must understand this.
7. **Data integrity at scale** — Orphan checks exist; FK enforcement depends on SQLite pragma in dev; prod relies on Postgres + discipline; destructive scripts need export-first culture.
8. **Deliverability layer default-off** — Good for backward compat, risky if prod forgets to enable after DNS warmup; mis-tuning can block legitimate sends silently from an operator’s perspective.
9. **Priority queue scan cap** — `PRIORITY_QUEUE_MAX_ASSIGNMENTS_SCAN` (default 4000) is a **silent correctness/performance tradeoff**; at large assignment tables, ranking is approximate or expensive.
10. **Audit log integrity** — Append-only by convention, not cryptographic; DB admin can mutate; no WORM guarantee.

---

## 3. Single points of failure (SPoF) analysis

| Component | SPoF? | Notes |
|-----------|-------|------|
| **Primary Postgres** | Yes | Mitigate: HA provider, PITR, frequent logical backups, runbook for failover to new instance. |
| **Single API + embedded scheduler** | Yes | One process restart kills scheduled ticks briefly; no leader election for scheduler. Multi-instance **without** scheduler split risks duplicate sends unless redesigned. |
| **Per-student Gmail SMTP + IMAP** | Yes | Student mailbox unavailable → sends/replies for that identity stop; no cross-mailbox failover. |
| **Google OAuth / token** | Partial | Per-student tokens; bulk failure if Google policy or consent changes. |
| **Operator `ADMIN_API_KEY`** | Yes | Key compromise = full API access to sensitive routes; no RBAC granularity. |
| **Sheet sync dependency** | Partial | Drift alerts exist; failure degrades analytics export, not necessarily sending. |
| **In-process observability** | Yes | Restart = metric loss; alerting should use external scrape + persistence. |

---

## 4. Capacity / scaling bottlenecks

| Layer | Bottleneck | First symptom |
|-------|------------|---------------|
| **DB pool** | Default `pool_size=5`, `max_overflow=10` | Connection pool timeouts under concurrent API + scheduler + IMAP. |
| **Scheduler tick** | Max ~50 sends/tick + intentional sleeps | Backlog grows when due rate > send rate. |
| **SMTP sequential sends** | Sleep jitter between sends in scheduler loop | Wall-clock throughput ceiling. |
| **IMAP** | Sequential per student in `check_replies` | Reply latency grows with student count. |
| **API heavy endpoints** | Large limits on HR list (`up to 10000`), campaigns/replies | Memory and slow JSON responses. |
| **Priority queue** | O(assignments scanned) with cap | Latency or stale ranking at very large `assignments`. |
| **Frontend** | Large tables without virtualization everywhere | Browser memory at huge datasets. |

---

## 5. Failure injection scenarios (“chaos” drills)

| # | Injection | Expected observe | Pass criteria |
|---|-----------|-------------------|----------------|
| C1 | Kill API mid-send (`SIGKILL`) | Some campaigns `processing` then stale → `paused` | No duplicate **sent** emails after recovery; operators know how to unstick. |
| C2 | Block Postgres egress 60s | 503 on DB routes; scheduler logs `db_unavailable` | Process recovers without manual migration; no unbounded retry storm. |
| C3 | Invalid SMTP password for one student | Sends fail; health may flag | Other students unaffected; alerting visible in reliability JSON. |
| C4 | Spike synthetic bounces | `bounce_spike_1h` alert path | Deliverability / ops runbook followed; sends pause or narrow. |
| C5 | Set `ENFORCE_IST_SEND_WINDOW` and run outside window | Scheduler returns `outside_ist_send_window` | No sends; UI/ops understand. |
| C6 | Revoke Google OAuth consent (one user) | OAuth start fails gracefully | Documented re-link path. |
| C7 | Fill disk on backup host | `pg_dump` fails loudly | Manifest shows failure; alert on missing fresh backup. |
| C8 | Double-click “send” / duplicate API | Idempotency / claim semantics | At most one outbound for same campaign row state machine. |

---

## 6. Operational maturity scorecard (0–3 each; 3 = mature)

| Area | Score | Rationale |
|------|-------|-----------|
| **Outreach engine** | 2 | Solid state machine + idempotency thinking; throughput bounded by design. |
| **Follow-ups** | 2 | Eligibility + explicit sends; complexity is real but tested in places. |
| **Priority queue** | 1–2 | Read-side ranking good; scheduler integration optional; scan caps are a tradeoff. |
| **Scheduler** | 1 | Works; not horizontally safe; coarse timeouts. |
| **Deliverability** | 1 | Layer exists; default off; heuristics not provider-grade alone. |
| **Backup / DR** | 2 | Runbooks + scripts; PITR still operator + provider dependent. |
| **Observability / SRE** | 1–2 | Good “single pane” JSON + correlation; lacks persistent TSDB/alert wiring in product. |
| **Security** | 2 | Baseline good; RBAC, CSP, edge limits still deployment-owned. |
| **Data integrity** | 2 | Checks + fixture discipline; DB-level audit immutability missing. |
| **Operator workflows** | 2 | Admin tools improving; destructive ops still CLI-first (good for safety). |

**Average ~1.8 — “strong internal tool / cautious pilot SaaS.”**

---

## 7. What breaks first at **10×** scale (order)

1. **Scheduler backlog** vs SMTP/IMAP wall time.  
2. **DB pool** contention (API + jobs + analytics).  
3. **Sheet sync** lag / quota if exports grow linearly with volume.  
4. **Operator cognitive load** (replies triage, stuck `processing`, fixture discipline).

---

## 8. What breaks first at **100×** scale

1. **Architecture:** single-process scheduler + synchronous sends — need **queue + workers** (Redis/SQS) and **idempotent consumers**.  
2. **Email provider limits** — Gmail/workspace sending caps, abuse automation detection.  
3. **IMAP** — impractical at huge student count without pooling, incremental sync, or provider webhooks.  
4. **Postgres** — hot rows on `email_campaigns`, index tuning, partition strategy.  
5. **Observability** — in-process metrics useless cross-fleet; need centralized metrics/traces.

---

## 9. Over-engineered vs under-engineered

| Over-engineered (relative to current scale risk) | Under-engineered (vs stated ambition) |
|---------------------------------------------------|--------------------------------------|
| Some analytics surface area before core multi-worker send pipeline | Horizontal scheduler + mail worker pool |
| Rich priority/diversity knobs if scheduler doesn’t consume them | Persistent metrics + alert routing to Pager/Slack |
| | Per-tenant rate budgets and abuse detection at API edge |
| | Formal RBAC beyond single API key |
| | Contract tests against live Gmail sandbox (or provider mocks) in CI |

---

## 10. Brutally honest: would you ship to paying customers?

**Ship** if: customers accept **operator-in-the-loop**, volume caps, you own **email compliance** (CAN-SPAM/GDPR/local student-data rules), and incidents are **internal reputation** not consumer-scale backlash.

**Do not ship** as: “Unattended infinite scale cold email as a service” without legal/compliance sign-off, worker-tier architecture, and provider relationship management.

---

## Chaos testing plan (documentary)

**Cadence:** monthly in staging; quarterly table-top + one live micro-chaos in controlled window.

**Themes:** DB outage, SMTP auth failure, clock skew (NTP), partial deploy (old + new binary), backup restore to clone, key rotation drill.

**Success:** runbook times met, no duplicate sends, RTO/RPO within agreed bounds.

---

## Load test plan (documentary)

**Goals:** Measure API p95/p99 under representative dashboards; scheduler throughput (sends/hour) with **dry-run** or sandbox SMTP; DB CPU and pool wait.

**Phases:** 1× baseline → 5× API read traffic → 2× write-heavy (assignment creation) → scheduled send burst in **staging only** with rate caps.

**Abort criteria:** error rate > SLO proxy, pool timeouts, SMTP rate blocks, disk >80% on backup host.

**Tooling:** k6/Locust for HTTP; custom script for scheduler `run_once` with limits; Postgres `pg_stat_statements` if enabled.

---

## Staged launch rollout strategy

| Stage | Audience | Duration | Gates |
|-------|----------|----------|-------|
| **0** | Internal dogfood | 1–2 wk | Zero SEV1/2; restore drill done |
| **1** | Pilot cohort (N students, M sends/day cap) | 2–4 wk | Deliverability on; alerts watched |
| **2** | Expand cohort | 4–8 wk | DB size + cost review; sheet sync healthy |
| **3** | GA** | Only if worker architecture roadmap accepted | |

**GA** here means “broader paying use,” not “public internet anonymous signup.”

---

## Production hardening roadmap

### 30 days (must)

- Edge: TLS, rate limits, WAF rules on auth/admin/outreach.  
- Prometheus scrape + 5 alert rules (scheduler stall, bounce spike, backup freshness, 5xx rate, pool timeouts).  
- Run restore drill; document RTO/RPO with real numbers.  
- Enable `DELIVERABILITY_LAYER` with conservative thresholds after DNS/postmaster review.  
- `pip-audit` / `npm audit` in CI on main.

### 60 days (should)

- Outbound **queue + worker** design (even if single worker initially) to decouple scheduler tick from SMTP latency.  
- DB index review on `email_campaigns` hot paths; `pg_stat_statements` baseline.  
- Audit log DB role: append-only for app role.  
- Load test to 5× current peak; fix first bottleneck.

### 90 days (could / strategic)

- Multi-instance safe sending (lease table or external queue consumer).  
- Replace IMAP polling strategy for large fleets (provider push or centralized mailbox).  
- RBAC (operator vs admin vs read-only auditor).  
- Optional OTel traces for send pipeline.

---

## Assumptions challenged

- **“SQLite in prod is fine for a while.”** — Operational risk; Postgres is the real production substrate for this codebase’s direction.  
- **“API key is enough auth.”** — Fine for small team; not for many operators or external contractors.  
- **“Scheduler metrics green = healthy.”** — Green can mask backlog growth if sends are capped but inserts continue.  
- **“Deliverability heuristics replace Postmaster.”** — They do not; they are a safety net only.  
- **“Tests green = launch ready.”** — Need drills, monitoring, and ownership.

---

## References (existing docs)

- `docs/DISASTER_RECOVERY_RUNBOOK.md`  
- `docs/SRE_ARCHITECTURE.md`, `docs/SRE_RUNBOOK.md`, `docs/INCIDENT_SEVERITY_AND_FMEA.md`  
- `docs/SECURITY_AUDIT.md`, `docs/SECURITY_CHECKLIST.md`  
- `docs/GO_LIVE_CHECKLIST.md`, `DEPLOYMENT.md`, `docs/ROUTE_AUTH_MATRIX.md`  
- `docs/DELIVERABILITY_ARCHITECTURE.md`

---

*This document is a point-in-time gate review. Re-run before major cohort expansion or architectural changes.*
