# Security checklist (release / periodic)

Use with `docs/SECURITY_AUDIT.md` and `docs/GO_LIVE_CHECKLIST.md`.

## Identity & access

- [ ] `ADMIN_API_KEY` set in production; not committed to git.
- [ ] `SESSION_SECRET_KEY` unique per environment; rotation runbook followed if rotated.
- [ ] OAuth redirect URIs match deployed backend URLs only.
- [ ] `APP_ENV=production` (or staging) so dev fallbacks are disabled.

## Network & browser

- [ ] CORS locked to real dashboard origins (`CORS_ALLOW_ORIGINS` or regex).
- [ ] Reverse proxy: TLS, HSTS, rate limits on `/oauth/*`, `/auth/*`, `/admin/*`, `/outreach/*` (see `REVERSE_PROXY_SECURITY.md`).

## Data

- [ ] Postgres: least-privilege DB role for app; separate role for migrations.
- [ ] Backups encrypted at rest; restore drill documented.
- [ ] PII export (`export_operator_snapshot`) stored only in secured buckets.

## Application

- [ ] `DEBUG=0` in production (no `/debug/*`).
- [ ] WebSocket `/ws/logs` requires API key in production.
- [ ] Rate limiting at edge for anonymous abuse paths.
- [ ] Dependency scan: `pip install pip-audit && pip-audit -r requirements.txt` (or platform equivalent).

## Email

- [ ] Header injection mitigations in place for thread headers (`email_sender` sanitization).
- [ ] SMTP credentials never returned in REST JSON (student serializers reviewed).

## Audit

- [ ] Audit log append-only at DB permission level where possible.
- [ ] Operator actions include `correlation_id` in `meta` where implemented (extend over time).
