# Application security audit — MicroDegree Outreach

**Scope:** FastAPI backend, React dashboard, Gmail OAuth, SMTP/IMAP, Postgres/SQLite, audit logs.  
**Method:** OWASP-aligned review of code paths and configuration (not a full pen-test).

## Executive summary

| Priority | Theme | Status |
|----------|-------|--------|
| P0 | Production secrets & API key on sensitive routes | Enforced in `main.py` / `auth.py` when `APP_ENV` not dev |
| P0 | Session signing for OAuth | `SessionMiddleware` + `SESSION_SECRET_KEY` |
| P1 | CORS / CSRF | CORS explicit; OAuth state in session; see gaps below |
| P1 | Email header injection | Mitigated for In-Reply-To / References (`_sanitize_rfc_header_value`) |
| P2 | Rate limiting | Recommended at reverse proxy (documented) |
| P2 | Audit tamper resistance | Append-only by policy; cryptographic chaining not implemented |

## OWASP-style findings

### A01 Broken access control

- **Finding:** Sensitive routers use `require_api_key` / `require_admin` when `ADMIN_API_KEY` set; open when unset (dev).
- **Risk:** Misconfigured prod env leaves APIs open.
- **Remediation:** Production startup hard-fail already requires key; add deployment check in CI.

### A02 Cryptographic failures

- **Finding:** Session secret has dev fallback string in code path when unset (dev only).
- **Risk:** Accidental prod misconfig could use weak secret if guard bypassed.
- **Remediation:** Keep `_enforce_production_secrets`; periodic secret rotation (`SECRET_ROTATION_RUNBOOK.md`).

### A03 Injection (SQL)

- **Finding:** SQLAlchemy ORM used; raw SQL rare. Prefer parameterized `text()` where used.
- **Remediation:** Code review any new `execute(text(...))` for concatenation.

### A03 Injection (email headers)

- **Finding:** Threading headers could carry CRLF; **fixed** with sanitization in `email_sender.build_email_message`.

### A04 Insecure design

- **Finding:** In-process metrics reset on restart — acceptable for single-node; multi-node needs Redis/Prometheus.
- **Remediation:** Document horizontal scaling limits.

### A05 Security misconfiguration

- **Finding:** CORS defaults to local dev origins.
- **Remediation:** Set `CORS_ALLOW_ORIGINS` or regex in prod (warned in `main.py`).

### A07 Identification & auth failures

- **Finding:** Gmail OAuth per student; API key for operator routes.
- **Remediation:** Short-lived tokens where possible; monitor failed OAuth.

### A09 Logging & integrity failures

- **Finding:** Audit logs mutable by DB admin; no Merkle chain.
- **Remediation:** Ship logs to WORM storage; DB role without UPDATE on `audit_logs` if product allows.

### A10 SSRF / abuse

- **Finding:** IMAP/SMTP outbound to configured hosts; sheet sync external APIs.
- **Remediation:** Network egress allowlists in prod; timeouts on external calls.

## Template / prompt injection

- Email bodies are operator/student-controlled HTML/text; recipients are HR emails. **Risk:** phishing-style content — product/process, not code sandbox escape.
- **Remediation:** UI warnings, optional content policy for generated templates; never execute templates as code.

## Risk register (abridged)

| ID | Risk | Likelihood | Impact | Mitigation |
|----|------|------------|--------|------------|
| R1 | Leaked `ADMIN_API_KEY` | M | H | Rotate key; IP restrict `/admin/*`; short TTL tokens future |
| R2 | OAuth token exfil via XSS on dashboard | L | H | CSP on frontend, sanitize React inputs |
| R3 | Backup dump without encryption | M | H | Encrypt at rest; `BACKUPS_DIR` permissions |
| R4 | SMTP credential in logs | L | H | Never log passwords; grep CI for `logger.*password` |

## Regression security tests (in repo)

- `tests/test_email_header_sanitization.py` — CRLF stripped from header fragments.
- Extend over time: SSRF mocks for sheet sync, auth matrix snapshot test.

## Supply chain

- Run **`pip-audit`** / **`npm audit`** on release cadence; track critical CVEs.
- Pin major versions in `requirements.txt` / `package.json` where practical.

## Remediation priority (next 30 days)

1. Enforce edge rate limits + WAF rules for auth and admin paths.  
2. Enable Prometheus + alert rules for bounce spike and scheduler stall.  
3. Restrict DB application role from UPDATE/DELETE on `audit_logs`.  
4. Frontend CSP report-only → enforce.
