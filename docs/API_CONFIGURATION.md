## API configuration (single source of truth)

### Frontend
- **Single API base**: `frontend/src/lib/constants.ts` exports `API_BASE_URL`
- **Single HTTP client**: `frontend/src/api/api.ts` (Axios instance with `baseURL: API_BASE_URL`)
- **Environment variables**
  - **Preferred**: `VITE_API_BASE_URL` (example: `http://127.0.0.1:8010`)
  - **Back-compat**: `VITE_API_URL` (supported, but prefer the new name)
- **Rules**
  - Do **not** hardcode ports or origins in feature code.
  - Only `constants.ts` may contain the local default fallback.
  - All requests should go through `src/api/api.ts` helpers.

### Backend
- **Listening port**
  - Docker: `PORT` env (defaults to `8010` in the Dockerfile)
  - Local dev: run `uvicorn app.main:app --port 8010`
- **CORS**
  - Prefer env-driven config in production:
    - `CORS_ALLOW_ORIGINS=https://dashboard.example.com,https://admin.example.com`
    - or `CORS_ALLOW_ORIGIN_REGEX=^https://dashboard\.example\.com$`
  - Dev defaults allow Vite origins only.
- **OAuth redirects**
  - `FRONTEND_URL` controls where the user is sent after OAuth success.
  - Callback URLs are generated from the incoming request host to avoid hardcoded backend origins.

### Local dev defaults (recommended)
- Backend: `http://127.0.0.1:8010`
- Frontend: `http://127.0.0.1:5173`

### Drift protection
- Run: `npm run check:config-drift` from `frontend/`
  - Fails if hardcoded `:8000` / `:8010` or duplicate Axios clients appear in `frontend/src`.

