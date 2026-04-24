# Route authorization matrix

Policy: **deny-by-default** for business routes. `ADMIN_API_KEY` unset → `require_api_key` / router-level API dependencies are no-ops (local dev only). **Production** (`APP_ENV` / `ENV` / `ENVIRONMENT` not in `dev`, `development`, `local`) requires `DATABASE_URL`, `SESSION_SECRET_KEY`, and `ADMIN_API_KEY` at process start (see `app/main.py`).

Headers:

- **Operator:** `X-API-Key` or `X-Admin-Key` matching `ADMIN_API_KEY`.
- **Admin-only:** same secret; `require_admin` accepts **either** header (aligned with `require_api_key`).

---

## Public (no API key)

| Method | Path | Notes |
|--------|------|--------|
| GET | `/` | API banner |
| GET | `/docs`, `/redoc`, `/openapi.json` | FastAPI docs |
| GET | `/health/` | Liveness + DB ping |
| GET | `/health/scheduler/status` | Scheduler heartbeat |
| GET | `/health/scheduler/metrics` | Scheduler metrics |
| GET | `/health/sheet-sync/status` | Sheet sync lag |
| GET | `/health/sheet-sync/trigger` | Last async trigger (diagnostic) |
| GET | `/health/config` | Non-secret config snapshot |
| GET | `/scheduler/status` | Alias of scheduler status |
| GET | `/oauth/gmail/callback` | Google OAuth redirect |
| GET | `/auth/callback` | OAuth redirect (session flow) |

---

## Operator (`require_api_key` or router default dependency)

All routes below require a valid key when `ADMIN_API_KEY` is set.

| Prefix / area | Router module |
|---------------|----------------|
| `/students` | `students.py` |
| `/hr`, `/hrs` (same `hr` router mounted twice) | `hr.py` |
| `/hrs` legacy listing/upload | `hrs_legacy.py` |
| `/hr-contacts` | `hr_contacts_compat.py` (optional `include_health`, `tier` query; `GET /hr-contacts/{id}/health`) |
| `/assignments` | `assignments.py` |
| `/outreach` | `outreach.py` |
| `/responses` | `responses.py` |
| `/campaigns` (list/patch email campaigns) | `campaigns.py` |
| `/campaign-manager` | `campaign_manager.py` |
| `/replies` | `replies.py` |
| `/analytics` | `analytics.py` |
| `/notifications` (GET list, POST mark read) | `notifications.py` |
| `/interviews` | `interviews.py` |
| `/admin` (logs, `GET /admin/backup-health`, `GET /admin/deliverability-health`, `GET /admin/fixture-audit`, `GET /admin/reliability`, `GET /admin/metrics/prometheus` when enabled, backup create, **backup download**) | `backups_admin.py`, `reliability_admin.py` |
| `/followups` (including reconcile) | `followups.py` |
| `/queue/priority` (`diversified` query for Phase 2 re-rank), `/queue/priority/summary`, `/queue/priority/scheduler-hook` | `priority_queue.py` |
| `/oauth/gmail/start` | `gmail_oauth.py` (per-route dependency) |
| `/auth/google` | `gmail_oauth.py` `auth_router` (per-route) |
| `/blocked-hrs` | `blocked_hr.py` |
| `/notifications` (compat path) | `routes/notifications.py` |
| GET | `/email-logs` | `main.py` alias |
| POST | `/followup1/send` | `main.py` alias |
| `/debug/*` | `debug.py` (only if `DEBUG=1` / true / yes) |

---

## Admin-only (`require_admin` on router or routes)

Stricter operations; same `ADMIN_API_KEY` via `X-API-Key` or `X-Admin-Key`.

| Prefix | Router module | Notes |
|--------|----------------|--------|
| `/audit` | `audit.py` | List + **`POST /audit/clear`** (destructive) |
| `/campaigns` | `campaigns_admin.py` | `run_once`, `gmail_monitor/run_once`, `hr_lifecycle/run_once` — **overlaps prefix** with operator `/campaigns`; paths are distinct (`/run_once`, etc.) |

`POST /notifications/` (create notification) uses **both** router-level `require_api_key` and route-level `require_admin` (same key satisfies both).

---

## WebSocket

| Path | Policy |
|------|--------|
| `/ws/logs` | **Production:** `api_key` query param must equal `ADMIN_API_KEY`. **Dev:** if key unset, open; if set, must match. |

---

## Intentionally public OAuth callbacks

Google cannot send `X-API-Key`. Callbacks validate `state` / session and exchange `code` server-side.

---

## Implementation reference (this repo)

- `app/main.py` — production env enforcement; WebSocket policy in production
- `app/auth.py` — `is_production_runtime`, `require_admin` accepts `X-API-Key` or `X-Admin-Key`
- `app/services/oauth_state.py` — no OAuth signing secret fallback in production
- Router-level `require_api_key`: `hr`, `assignments`, `responses`, `analytics`, `campaign_manager`, `blocked_hr`, `interviews`, `hrs_legacy`, `hr_contacts_compat`, `notifications`, `routes/notifications`, `debug`
- Router-level `require_admin`: `audit`, `campaigns_admin`
- `app/routers/backups_admin.py` — `GET .../download/{filename}` requires API key (same secret as router)
