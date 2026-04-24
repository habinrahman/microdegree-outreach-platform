# Reverse-proxy security posture — assumptions and checklist

This document describes **what the placement outreach stack does not implement in-process** and what operators should enforce **in front of the API** (reverse proxy, API gateway, load balancer, or cloud edge).

**Verified (codebase):** The FastAPI app does **not** add `Strict-Transport-Security`, `Content-Security-Policy`, `X-Frame-Options`, `X-Content-Type-Options`, or HTTP rate limiting middleware. CORS is configured in-app (`app/main.py`). Authentication for business routes is `ADMIN_API_KEY` (see `docs/ROUTE_AUTH_MATRIX.md`). **TLS termination, abuse controls, and browser-oriented security headers are assumed to live at the edge** unless you add middleware later.

Use this as a **go-live checklist** for production or staging hostnames that expose the backend to browsers or the open internet.

---

## 1. HSTS (`Strict-Transport-Security`)

| Item | Recommendation |
|------|----------------|
| **Assumption** | HTTPS is terminated at the proxy (or platform ingress). Clients must not rely on first-hit HTTP→HTTPS redirect alone. |
| **Header** | `Strict-Transport-Security: max-age=31536000; includeSubDomains` (adjust `max-age` during rollout; consider `preload` only with full org process). |
| **Checklist** | [ ] HTTPS only on public listener<br>[ ] HSTS enabled on **API** virtual host<br>[ ] HSTS enabled on **dashboard** host if separate<br>[ ] No mixed-content downgrade paths for operator UI |

**Note:** HSTS is a **hostname** property. Apply on every host that serves operator-facing HTTPS.

---

## 2. CSP (`Content-Security-Policy`)

| Item | Recommendation |
|------|----------------|
| **API (FastAPI)** | CSP is **optional** for JSON-only API responses; many teams omit CSP on API origins or use a minimal `default-src 'none'` if responses are never HTML. |
| **Dashboard (Vite SPA)** | CSP matters where **HTML** is served (static host, CDN, or dev server). Policy must allow your API origin for `connect-src`, script/style sources for the framework, and any OAuth redirects you use. |
| **Checklist** | [ ] CSP defined for **frontend** HTML shell (if you control it)<br>[ ] `connect-src` includes API base URL<br>[ ] OAuth / Google domains allowed if the SPA opens them<br>[ ] Avoid `unsafe-inline` where possible; use nonces/hashes if policy tightens |

**CSP does not replace** API authentication (`X-API-Key`); it reduces XSS impact in the browser.

---

## 3. `X-Frame-Options` / `frame-ancestors`

| Item | Recommendation |
|------|----------------|
| **Purpose** | Reduce **clickjacking** (embedding your dashboard or API docs in an attacker’s iframe). |
| **Legacy header** | `X-Frame-Options: DENY` or `SAMEORIGIN` (sufficient for many setups). |
| **Modern** | Prefer CSP `frame-ancestors 'none'` or `'self'` on hosts that serve HTML (dashboard). |
| **Checklist** | [ ] Dashboard cannot be framed by untrusted sites<br>[ ] Decide policy for `/docs` if operators use it in browser (often `DENY` or internal-only — see [Docs exposure](#7-docs-openapi--redoc-exposure-policy)) |

---

## 4. `X-Content-Type-Options`

| Item | Recommendation |
|------|----------------|
| **Header** | `X-Content-Type-Options: nosniff` |
| **Checklist** | [ ] Set on API and dashboard responses<br>[ ] Ensures browsers do not MIME-sniff non-script responses as executable content |

Low cost; enable everywhere.

---

## 5. Other useful response headers (proxy-level)

| Header | Typical use |
|--------|-------------|
| `Referrer-Policy` | e.g. `strict-origin-when-cross-origin` — limit referrer leakage to OAuth partners. |
| `Permissions-Policy` | Restrict geolocation, camera, etc., if not needed. |
| `Cross-Origin-Resource-Policy` | Usually **not** set on a CORS-enabled API without testing; can break browser calls if misaligned with `Access-Control-Allow-Origin`. Coordinate with `CORS_ALLOW_ORIGINS` / regex in `app/main.py`. |

---

## 6. Rate limits

| Item | Recommendation |
|------|----------------|
| **Assumption** | The application has **no** built-in per-IP HTTP rate limiting for `/outreach/send`, OAuth start, login-like paths, or `/health`. |
| **Abuse surface** | Brute force on `X-API-Key`, credential stuffing against any future login, scraping of `/analytics`, expensive queries, OAuth endpoints. |
| **Checklist** | [ ] Global connection / request rate limit at edge<br>[ ] Stricter limits on `POST` bodies (send, assignments, admin backup)<br>[ ] Stricter limits on `/oauth/*` and `/auth/*` **starts** (not Google callbacks)<br>[ ] Optional: geofence or bot management (WAF) for public ingress |

Tune limits with **429** responses and logging; align with scheduler and dashboard polling intervals so health checks are not throttled (`/health/` is often high-frequency).

---

## 7. IP allowlisting

| Item | Recommendation |
|------|----------------|
| **When** | Strongest control for an **internal** placement tool: allow only office/VPN egress IPs to reach the API listener. |
| **Checklist** | [ ] Decide: public API vs VPN-only<br>[ ] If VPN-only: allowlist on firewall / cloud security group / nginx `allow` + `deny`<br>[ ] Health checks from load balancer: use **private** health path or separate listener so probes are not blocked<br>[ ] Document bypass procedure for on-call from home |

Allowlisting **complements** `ADMIN_API_KEY`; it does not replace it if the API is reachable from many trusted IPs.

---

## 8. Docs, OpenAPI, and ReDoc exposure policy

**Current behavior:** FastAPI exposes **`/docs`**, **`/redoc`**, and **`/openapi.json`** by default (same process as the API). These reveal route names, parameters, and integration surface.

| Policy option | When to use |
|---------------|-------------|
| **A — Internal only** | Block `/docs`, `/redoc`, `/openapi.json` at the proxy for **public** listeners; allow from VPN or admin IP range only. |
| **B — Disable in app** | Set `docs_url=None`, `openapi_url=None`, `redoc_url=None` on `FastAPI()` (requires a small **application** change — not done today). |
| **C — Accept risk** | Only if API is already VPN-only and schema disclosure is acceptable. |

**Checklist**

- [ ] Written policy: A, B, or C  
- [ ] If A: proxy rules tested (exact paths)  
- [ ] Operators know how to reach docs (VPN URL or separate admin host)  
- [ ] OAuth callbacks (`/oauth/gmail/callback`, `/auth/callback`) remain **allowed** from Google — do not block by mistake  

---

## 9. TLS and upstream trust

| Item | Recommendation |
|------|----------------|
| **Certificates** | Use managed certs (Let’s Encrypt, cloud CA) on the proxy; **min TLS 1.2** (prefer 1.3-only where clients allow). |
| **Upstream** | Proxy → Uvicorn is often HTTP on a private network; ensure that hop is **not** exposed to the internet. |
| **Forwarded headers** | If the app ever needs client IP or HTTPS scheme, configure **trusted** `X-Forwarded-For` / `X-Forwarded-Proto` only from your proxy (Uvicorn `--proxy-headers` / platform equivalent). |

---

## 10. Quick verification commands (after deploy)

Replace `https://api.example.com` with your API URL.

```bash
# HSTS (repeat with -L if redirects)
curl -sI https://api.example.com/health/ | findstr /i strict-transport

# Security headers (Windows: use findstr; on Unix use grep -i)
curl -sI https://api.example.com/health/ | findstr /i "x-content-type-options x-frame-options content-security-policy"

# Confirm docs blocked (if policy A) — expect 403/404 from edge
curl -sI https://api.example.com/docs
```

---

## 11. Related internal docs

- `DEPLOYMENT.md` — Docker, env, OAuth URLs  
- `docs/ROUTE_AUTH_MATRIX.md` — which routes are public vs API-key protected  
- `docs/OPERATOR_RUNBOOK.md` — health endpoints and operations  

---

## Summary

| Control | In-app today | Expected at reverse proxy |
|--------|----------------|----------------------------|
| HSTS | No | Yes (HTTPS hosts) |
| CSP | No | Yes on dashboard HTML; optional/minimal on API |
| `X-Frame-Options` / `frame-ancestors` | No | Yes (esp. dashboard) |
| `X-Content-Type-Options` | No | Yes |
| Rate limiting | No | Yes (edge / WAF) |
| IP allowlisting | No | Optional but recommended for internal tools |
| `/docs` / OpenAPI | Open | Policy decision at proxy or app config |
