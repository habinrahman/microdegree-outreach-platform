## Security policy

This repository is designed to be publishable, but it includes **high‑risk capabilities** (email automation, OAuth, data export). Treat it like production software.

### Reporting a vulnerability

- **Do not** open a public issue for credential leaks or exploitable bugs.
- Preferred: contact the maintainer privately (add your preferred contact method before launch).
- Include: reproduction steps, affected versions/commit, impact analysis, and suggested fix if available.

### Secret handling (required)

This repo uses **defense in depth** to prevent secret commits:

- **Pre-commit**: Gitleaks runs locally (see `.pre-commit-config.yaml`).
- **CI**: GitHub Actions runs Gitleaks on push/PR (`.github/workflows/gitleaks.yml`).
- **Allowlist**: false positives are narrowly allowlisted in `.gitleaks.toml` (keep it tight).

#### Setup pre-commit

```bash
pip install pre-commit
pre-commit install
pre-commit run --all-files
```

### What must never be committed

- **`.env` / `.env.*`** (local dev + prod secrets)
- **Service account keys** (`credentials.json`, `*service-account*.json`, private keys)
- **OAuth tokens / refresh tokens**
- **Database URLs** that include passwords (e.g. `postgresql://user:pass@…`)
- **SMTP passwords / app passwords**
- **Supabase keys** (anon/service role), JWT signing keys, session secrets
- **Exports/backups**: CSV dumps, `cleanup_export/`, `backups/`, `*.dump`, `*.sql.gz`, SQLite DBs
- **Logs** containing email addresses or request payloads

If you need a template, add it to `backend/.env.example` and keep values blank.

### If a secret is accidentally committed

1. **Assume compromise. Rotate immediately.**
2. Remove the secret from the working tree (delete or replace with env config).
3. **Purge Git history** (example using `git-filter-repo`):

```bash
pip install git-filter-repo
git filter-repo --force --path backend/db_test.py --invert-paths
git push --force --prune origin --all
git push --force --prune origin --tags
```

4. Ask collaborators to re-clone (or hard reset) to the rewritten history.

### Dependency security

- Keep lockfiles consistent (prefer one package manager workflow).
- Run periodic scans:
  - Backend: `pip-audit` (optional)
  - Frontend: `npm audit` (or an equivalent SCA tool)

### Deployment security baseline

Before production:

- Set `APP_ENV=production` (or staging) and ensure required secrets are provided (startup should fail fast).
- Lock CORS (`CORS_ALLOW_ORIGINS` or regex).
- Put `/admin/*`, `/campaigns/run_once`, and OAuth routes behind TLS + rate limiting at the edge (see `docs/REVERSE_PROXY_SECURITY.md`).
- Store secrets in a secrets manager; never bake them into images.

