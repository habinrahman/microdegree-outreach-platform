## Deployment (Production)

### Backend (Docker)

1. Create env file:
   - Copy `backend/.env.example` → `backend/.env`
   - Set `APP_ENV=production` (or `staging`) only when ready: the API **refuses to start** without `DATABASE_URL`, `SESSION_SECRET_KEY`, and `ADMIN_API_KEY` (no dev fallbacks).
   - Set at minimum:
     - `ADMIN_API_KEY`
     - `DATABASE_URL` (Postgres recommended in prod)
     - `SESSION_SECRET_KEY` (sessions + OAuth state signing)
     - `GOOGLE_CLIENT_ID`
     - `GOOGLE_CLIENT_SECRET`
     - `FRONTEND_URL` (your dashboard domain)

2. Build and run:

```bash
docker compose up -d --build
```

Backend will be on `http://<server>:8010` (or your configured port) and docs at `/docs`.

**Edge security (HSTS, headers, rate limits, docs exposure):** see `docs/REVERSE_PROXY_SECURITY.md` — the API does not set these; enforce at your reverse proxy or gateway.

**Rotating secrets (API key, session key, Google OAuth, DB):** see `docs/SECRET_ROTATION_RUNBOOK.md`.

**Controlled go-live:** see `docs/GO_LIVE_CHECKLIST.md`.

### OAuth callback URL (Google Cloud Console)

Add this to **Authorized redirect URIs**:
- `https://<your-backend-domain>/oauth/gmail/callback`

For local dev:
- `http://127.0.0.1:8010/oauth/gmail/callback`

### Backups + audit logs

- **SQLite backup (local/dev):** `POST /admin/backup/sqlite` with `X-Admin-Key`
- **Audit log list:** `GET /audit/` with `X-Admin-Key`

For Postgres production backups, use your platform tools (Supabase backups) or `pg_dump`. Operator scripts, restore drills, and PITR guidance: `docs/DISASTER_RECOVERY_RUNBOOK.md`. Dashboard: `GET /admin/backup-health`. Observability / SRE: `docs/SRE_ARCHITECTURE.md`, `GET /admin/reliability`, dashboard route `/system-reliability`. Security: `docs/SECURITY_AUDIT.md`, `docs/SECURITY_CHECKLIST.md`. **Launch gate (principal-engineer review):** `docs/PRODUCTION_READINESS_REVIEW.md`.

### Alembic migrations on Supabase (lock / timeout pitfalls)

Supabase connection poolers (e.g. Supavisor / PgBouncer endpoints) plus long-lived app transactions can cause
even “metadata-only” DDL (like `ALTER TABLE ... SET DEFAULT`) to hang waiting on locks or hit aggressive
statement timeouts.

- **Best practice**
  - Use a **direct Postgres connection** for migrations when possible (port `5432`, not the transaction pooler).
  - Run migrations while the API / scheduler is stopped (or at least ensure no sessions are `idle in transaction`).

- **Safe investigation commands**
  - `alembic current -v`
  - `alembic heads`
  - Inspect DB directly:
    - `SELECT version_num FROM alembic_version;`
    - Check the intended schema state via `information_schema.columns`.

- **Bypassing a blocked “default-only” migration**
  - If a migration only changes a column default (no data backfill, no constraints), it can be safe to **bypass**
    by advancing the recorded revision **after verifying the schema is already acceptable for your app**.
  - Preferred: `alembic stamp <revision>`
  - **Last resort (ops escape hatch):** `UPDATE alembic_version SET version_num = '<revision>';`

- **Rollback strategy**
  - If you only stamped/updated `alembic_version` (no schema change), rollback is simply:
    - `alembic stamp <previous_revision>` (or update the row back), then re-run `alembic upgrade head`.
  - If schema changes were applied, rollback must use the corresponding Alembic `downgrade` or a new forward
    repair migration (append-only discipline).

