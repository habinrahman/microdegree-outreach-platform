# Secret rotation runbook

Rotate credentials **without unnecessary downtime** by using rolling restarts, overlapping validity where the platform allows it, and a clear order of operations. This app reads secrets from the environment at **process start** (and some config at import time); there is **no** hot reload of `ADMIN_API_KEY` or `SESSION_SECRET_KEY` inside a running worker.

**Scope:** `ADMIN_API_KEY`, `SESSION_SECRET_KEY`, Google OAuth (`GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`), database credentials (`DATABASE_URL`, optional `ALEMBIC_DATABASE_URL`).

**Related:** `docs/ROUTE_AUTH_MATRIX.md` (auth headers), `DEPLOYMENT.md` (env layout), production hardening in `app/main.py` / `app/auth.py`.

---

## Principles (all rotations)

1. **Prepare** new values in a secrets manager (or encrypted store); do not paste into chat or tickets.
2. **Stage** new secrets in the orchestrator (Kubernetes Secret, ECS task definition revision, etc.) before pointing live traffic at them.
3. **Roll** instances one-by-one (or use a second deployment slot) so at least one healthy replica always serves traffic.
4. **Update clients** that embed the operator key (e.g. dashboard `VITE_ADMIN_API_KEY`) in the **same change window** as the API, or accept a short window of 403s (see below).
5. **Verify** health (`GET /health/`), a read-only authenticated call, and OAuth start in staging first when possible.
6. **Revoke** old credentials only after all nodes and clients use the new values and metrics look normal.

---

## 1. `ADMIN_API_KEY` (operator + admin)

**Used for:** `X-API-Key` / `X-Admin-Key` on protected routes; WebSocket `/ws/logs?api_key=` in production; signing fallback for Gmail OAuth state when `SESSION_SECRET_KEY` is unset (production should set both).

**Single-key reality:** The application accepts **one** `ADMIN_API_KEY` per process. True zero-blip rotation requires the **edge** to accept two keys temporarily, or a **very fast** coordinated update.

### Option A — Near–zero downtime (recommended when exposed to browsers)

1. Configure your **API gateway / reverse proxy** (if you have one) to accept **either** the current or the next `ADMIN_API_KEY` on the `X-API-Key` / `X-Admin-Key` check for a defined window (e.g. 24 hours). *This is outside the app codebase.*
2. Deploy new key at the gateway; confirm traffic succeeds with **new** key from a test client.
3. Rolling-restart all API pods/containers with `ADMIN_API_KEY=<new>` in env.
4. Redeploy or rebuild the **frontend** with `VITE_ADMIN_API_KEY=<new>` (build-time env for Vite).
5. Remove the **old** key from the gateway allowlist after all clients and backends are confirmed on the new key.

### Option B — App-only (no dual-key at gateway)

1. Pick a **low-traffic** window (still “no prolonged outage” — only brief errors).
2. Update secret store: `ADMIN_API_KEY=<new>`.
3. Rolling-restart API replicas (new processes pick up new key).
4. Immediately deploy dashboard (or config) with matching `VITE_ADMIN_API_KEY`.
5. Operators with old tabs may see **403** until refresh; duration = restart + deploy time (often under a few minutes).

### Verification

```http
GET /health/
X-API-Key: <new>
```

```http
GET /analytics/summary
X-API-Key: <new>
```

### Rollback

Restore previous `ADMIN_API_KEY` in secrets + rolling restart + redeploy frontend to previous build/env.

---

## 2. `SESSION_SECRET_KEY`

**Used for:** Starlette `SessionMiddleware` (cookie encryption for `/auth/*` session flow); Gmail OAuth state signing uses `SESSION_SECRET_KEY` or falls back to `ADMIN_API_KEY` (`app/services/oauth_state.py`).

**Effect of rotation:**

- **Session cookies** issued before rotation become invalid → users mid-**session** OAuth (`/auth/google` → `/auth/callback`) may need to **start again**.
- **Signed OAuth state** (`/oauth/gmail/start` → `/oauth/gmail/callback`) is verified with the secret at callback time; **in-flight** flows started before rotation can fail with “Invalid or expired OAuth state” if the callback hits a process that only knows the new secret while the state was signed with the old one.

### Safe rotation procedure (minimal user impact)

1. **Announce** a short maintenance window for “Reconnect Gmail” if you use session-based OAuth heavily.
2. Ensure **no** long-lived OAuth handoffs are in progress (or accept rare failures).
3. Set `SESSION_SECRET_KEY=<new>` in secrets (keep `ADMIN_API_KEY` unchanged during this step if you want OAuth state to still verify via fallback — **not recommended in production** where both should be strong and independent).
4. **Preferred in production:** Rotate `SESSION_SECRET_KEY` while keeping a stable `ADMIN_API_KEY` only if your deployment previously relied on ADMIN for state signing; the code prefers `SESSION_SECRET_KEY` when set. For a clean rotation, rotate **SESSION** alone first so new state uses SESSION; then avoid depending on ADMIN for state.
5. Rolling-restart all API instances.
6. Ask operators to **retry** Gmail connect if a callback fails once.

### Coordinated rotation (SESSION + ADMIN)

If you rotate **both** in one release, in-flight OAuth state and sessions break until users retry. Sequence:

1. Complete in-flight OAuth attempts.
2. Update both secrets in the store.
3. Single rolling restart wave (or two waves: SESSION first, then ADMIN after OAuth stable — only needed if you rely on ADMIN for state in an emergency).

### Rollback

Restore old `SESSION_SECRET_KEY`, rolling restart. Users sign in to OAuth again if needed.

---

## 3. Google OAuth (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`)

**Used for:** Gmail OAuth web client; token exchange on callback.

**Typical behavior:** Rotating **only** the **client secret** in Google Cloud Console and in your env usually **does not** invalidate existing **refresh tokens** already stored in `students.gmail_refresh_token`. Operators should still smoke-test one student after rotation.

### Rotate client secret (same client ID)

1. In [Google Cloud Console](https://console.cloud.google.com/) → APIs & Services → Credentials → your **Web client** → add a **new** secret (or rotate per Google’s UI), **copy the new secret**.
2. Update `GOOGLE_CLIENT_SECRET` in your secrets store (keep `GOOGLE_CLIENT_ID` unchanged unless you are also migrating clients).
3. Rolling-restart all API instances.
4. **Smoke test:** `GET /oauth/gmail/start?student_id=<uuid>` with `X-API-Key`, then complete callback for a **test** student (non-prod first if available).
5. Remove/disable the **old** client secret in Google Console after traffic is stable.

**Downtime note:** Between step 2 and 3, old pods still have the old secret; new pods have the new secret. Use a **single** rolling wave so you do not mix old/new secret across replicas during token exchange (or accept one failed exchange if a user hits a pod during the wave — rare).

### Rotate client ID (new OAuth client)

This is a **migration**, not a simple secret rotate:

1. Create a **new** OAuth client; configure redirect URIs per `DEPLOYMENT.md`.
2. Deploy `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` for the new client to **all** instances in one rolling wave.
3. Existing refresh tokens were issued to the **old** client and are **not** valid for the new client ID → **every** student must complete Gmail OAuth again to obtain new refresh tokens.

Plan communication and support load before rotating client ID.

### Rollback

Re-deploy previous `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`; rolling restart. If client ID changed, students may need to reconnect again.

---

## 4. Database credentials (`DATABASE_URL`, `ALEMBIC_DATABASE_URL`)

**Used for:** SQLAlchemy engine / pools; Alembic may use `ALEMBIC_DATABASE_URL` when set.

### Postgres (recommended pattern)

1. **Create** a new DB role (or new password on a dedicated role) with the **same** privileges as the current app user (`GRANT` same schema/table rights, default privileges, etc.).
2. **Test** connectivity: from a jump host or one-off job, connect with the new URL; run `SELECT 1` and a read query on critical tables.
3. Build a **new** `DATABASE_URL` (and `ALEMBIC_DATABASE_URL` if used) with the new password — use URL-encoding for special characters in the password.
4. Update the secret in your orchestrator **without** restarting yet (if your platform supports “next revision only”).
5. **Rolling restart** application instances:
   - Each new process opens pools with the **new** URL.
   - Old processes drain their existing connections; on Postgres you can `SELECT pg_terminate_backend` for old app user sessions **after** all app nodes use the new role (optional, aggressive).
6. Monitor errors: `Database temporarily unavailable` (503), pool timeouts, migration failures.
7. **Revoke** old password or drop old role after stable period (e.g. 24–72h).

**Near–zero downtime:** Rolling restart + pre-created DB user avoids DB restart. Avoid changing **host** and **password** in unrelated steps in the same minute unless DNS/connection strings are validated.

### Supabase / managed Postgres

Use the provider’s **password rotate** flow; update `DATABASE_URL` in the secret store; rolling restart app. If migrations use **direct** (non-pooler) URL, update `ALEMBIC_DATABASE_URL` in the same change.

### SQLite

Not typical for production. To “rotate,” snapshot backup, restrict file permissions, or move to Postgres; `DATABASE_URL` path changes imply coordinated file move + restart.

### Rollback

Point `DATABASE_URL` back to the previous user/password; rolling restart. Keep old DB user enabled until rollback window ends.

---

## 5. Combined checklist (go / no-go)

| Step | Owner | Done |
|------|--------|------|
| Staging rehearsal with same orchestrator pattern | Eng | [ ] |
| Secrets updated in vault (not only in shell history) | Eng | [ ] |
| `FRONTEND_URL` / OAuth redirect URIs unchanged unless intentional | Eng | [ ] |
| Rolling restart / blue-green plan written | Eng | [ ] |
| Dashboard / automation clients updated for new `ADMIN_API_KEY` | Eng | [ ] |
| Post-deploy: `/health/`, authenticated GET, optional OAuth smoke test | Ops | [ ] |
| Old secrets revoked at source (Google, DB, gateway) | Eng | [ ] |

---

## 6. Downtime summary

| Secret | True zero-downtime? | Notes |
|--------|---------------------|--------|
| `ADMIN_API_KEY` | Only with **dual-key** at gateway or very fast coordinated deploy | App supports one key per process |
| `SESSION_SECRET_KEY` | **Session invalidation** expected; OAuth retries fix most issues | Avoid mid-flight OAuth during cut |
| `GOOGLE_CLIENT_SECRET` (same client ID) | **Yes** with rolling restart if wave is tight | Rare failed callback during wave |
| `GOOGLE_CLIENT_ID` change | **No** without user re-OAuth | Plan communication |
| DB password / URL | **Yes** with rolling restart + pre-created DB user | Pool on each worker reconnects independently |

---

## 7. Where each value lives (reminder)

| Secret | Typical location |
|--------|------------------|
| `ADMIN_API_KEY` | `backend/.env`, container env, CI; frontend `VITE_ADMIN_API_KEY` |
| `SESSION_SECRET_KEY` | `backend/.env`, container env only |
| `GOOGLE_CLIENT_*` | `backend/.env`, container env |
| DB password | Inside `DATABASE_URL` / `ALEMBIC_DATABASE_URL`; managed provider may offer rotation UI |

Production startup **requires** `DATABASE_URL`, `SESSION_SECRET_KEY`, and `ADMIN_API_KEY` when `APP_ENV` is not `dev` / `development` / `local` — do not clear one to “rotate” without staging the replacement first.
