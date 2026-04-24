"""App configuration for Part 2 campaign engine."""
import logging
import os
from pathlib import Path
from dotenv import load_dotenv, dotenv_values

logger = logging.getLogger(__name__)

# Load env files deterministically regardless of process cwd.
# Order: repo root .env (base), then backend/.env (backend-specific overrides).
APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
REPO_ROOT = BACKEND_DIR.parent

_pytest_running = os.getenv("PYTEST_RUNNING", "").strip() == "1"
# During pytest, conftest pins DATABASE_URL (often in-memory SQLite). Root .env uses
# override=True by default which would stomp that and re-point tests at the dev DB.
load_dotenv(REPO_ROOT / ".env", override=not _pytest_running)

# Apply backend overrides but never override existing values with empty strings.
backend_vals = dotenv_values(BACKEND_DIR / ".env")
for k, v in backend_vals.items():
    if v is None:
        continue
    # Skip empty strings so root .env values remain intact.
    if isinstance(v, str) and v.strip() == "":
        continue
    if _pytest_running and k == "DATABASE_URL":
        continue
    os.environ[k] = v

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    logger.info("DATABASE_URL is set (value not logged)")
else:
    logger.warning("DATABASE_URL is not set")

_gid = os.getenv("GOOGLE_CLIENT_ID", "")
_gsec = os.getenv("GOOGLE_CLIENT_SECRET", "")
logger.info(
    "Google OAuth env: GOOGLE_CLIENT_ID=%s GOOGLE_CLIENT_SECRET=%s",
    "set" if _gid else "unset",
    "set" if _gsec else "unset",
)

# Daily limit previously existed; sending limits are not enforced.
DAILY_INITIAL_EMAIL_LIMIT = int(os.getenv("DAILY_INITIAL_EMAIL_LIMIT", "0") or "0")

# IST sending window (hours and minutes). Used only when ENFORCE_IST_SEND_WINDOW is true.
SEND_START_HOUR, SEND_START_MINUTE = 9, 30   # 9:30 AM IST
SEND_END_HOUR, SEND_END_MINUTE = 17, 30     # 5:30 PM IST
ENFORCE_IST_SEND_WINDOW = os.getenv("ENFORCE_IST_SEND_WINDOW", "").strip().lower() in (
    "1",
    "true",
    "yes",
)

# Random delay between emails (seconds)
SEND_DELAY_MIN = 2 * 60   # 2 minutes
SEND_DELAY_MAX = 5 * 60   # 5 minutes

# Gmail OAuth (for Gmail API)
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")

# Follow-ups foundation (Step 1): feature flags (default OFF).
FOLLOWUPS_ENABLED = os.getenv("FOLLOWUPS_ENABLED", "").strip().lower() in ("1", "true", "yes")
FOLLOWUPS_DRY_RUN = os.getenv("FOLLOWUPS_DRY_RUN", "true").strip().lower() in ("1", "true", "yes")

# Optional: scheduler only sends to HRs at or above this tier (A = strictest). Empty = no tier filter.
# Example: SCHEDULER_MIN_HR_TIER=B allows A and B only.
SCHEDULER_MIN_HR_TIER = (os.getenv("SCHEDULER_MIN_HR_TIER") or "").strip().upper()

# Phase 2+: if true, scheduler may prefer priority-queue ordering (NOT wired in Phase 1; default off).
SCHEDULER_USE_PRIORITY_QUEUE = os.getenv("SCHEDULER_USE_PRIORITY_QUEUE", "").strip().lower() in (
    "1",
    "true",
    "yes",
)