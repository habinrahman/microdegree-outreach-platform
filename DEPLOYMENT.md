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

