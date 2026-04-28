"""Startup DDL helpers (no engine / session imports — safe for fixture bootstrap + config)."""

import os


def bootstrap_ddl_statement_timeout_ms() -> int:
    """
    Milliseconds for ``SET LOCAL statement_timeout`` during startup DDL (column drift, fixture columns,
    uniqueness/index steps). Env ``DB_BOOTSTRAP_DDL_STATEMENT_TIMEOUT_MS`` (default 300000 = 5 minutes).
    Clamped 1 s–10 min; poolers may still enforce a lower ceiling.
    """
    try:
        v = int((os.getenv("DB_BOOTSTRAP_DDL_STATEMENT_TIMEOUT_MS") or "300000").strip())
    except ValueError:
        v = 300_000
    return max(1000, min(v, 600_000))
