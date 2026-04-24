"""PostgreSQL logical backups via pg_dump (operator / cron — not invoked from hot request path by default)."""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def is_postgres_database_url(url: str | None) -> bool:
    if not url:
        return False
    d = url.split(":", 1)[0].lower()
    return d in ("postgresql", "postgres", "postgresql+psycopg2", "postgresql+asyncpg")


def _strip_sqlalchemy_driver(url: str) -> str:
    """pg_dump expects postgresql:// or postgres:// without +driver."""
    u = url.strip()
    for prefix in ("postgresql+psycopg2://", "postgresql+asyncpg://", "postgresql+psycopg://"):
        if u.startswith(prefix):
            return "postgresql://" + u[len(prefix) :]
    return u


def safe_db_url_host(url: str) -> str | None:
    try:
        p = urlparse(_strip_sqlalchemy_driver(url))
        return p.hostname
    except Exception:
        return None


def run_pg_dump_custom(
    database_url: str,
    output_path: Path,
    *,
    timeout_sec: int = 7200,
    pg_dump_bin: str | None = None,
) -> dict[str, Any]:
    """
    Create a compressed custom-format dump (-Fc) suitable for pg_restore.
    """
    if not is_postgres_database_url(database_url):
        return {"ok": False, "error": "not_a_postgres_url"}
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    bin_name = (pg_dump_bin or os.getenv("PG_DUMP_BIN") or "pg_dump").strip() or "pg_dump"
    conn = _strip_sqlalchemy_driver(database_url)
    cmd = [bin_name, "--no-owner", "--no-acl", "-Fc", "-f", str(out), conn]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            env=os.environ.copy(),
        )
    except FileNotFoundError:
        return {"ok": False, "error": "pg_dump_not_found", "bin": bin_name}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "pg_dump_timeout", "timeout_sec": timeout_sec}
    ok = proc.returncode == 0
    tail_out = (proc.stdout or "")[-4000:]
    tail_err = (proc.stderr or "")[-4000:]
    if not ok:
        logger.error("pg_dump failed rc=%s", proc.returncode)
    return {
        "ok": ok,
        "returncode": proc.returncode,
        "stdout_tail": tail_out,
        "stderr_tail": tail_err,
        "output_path": str(out.resolve()),
        "bytes": out.stat().st_size if out.is_file() else None,
    }


def verify_pg_dump_custom_format(
    dump_path: Path,
    *,
    timeout_sec: int = 600,
    pg_restore_bin: str | None = None,
) -> dict[str, Any]:
    """Validate dump file using pg_restore --list (no data restore)."""
    p = Path(dump_path)
    if not p.is_file():
        return {"ok": False, "error": "file_not_found"}
    bin_name = (pg_restore_bin or os.getenv("PG_RESTORE_BIN") or "pg_restore").strip() or "pg_restore"
    cmd = [bin_name, "--list", str(p)]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            env=os.environ.copy(),
        )
    except FileNotFoundError:
        return {"ok": False, "error": "pg_restore_not_found", "bin": bin_name}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "pg_restore_timeout"}
    ok = proc.returncode == 0
    listing_lines = len([ln for ln in (proc.stdout or "").splitlines() if ln.strip()])
    return {
        "ok": ok,
        "returncode": proc.returncode,
        "listing_lines": listing_lines,
        "stderr_tail": (proc.stderr or "")[-2000:],
    }


def redact_database_url(url: str) -> str:
    """Mask password for manifests / logs."""
    try:
        u = _strip_sqlalchemy_driver(url)
        p = urlparse(u)
        if p.password:
            netloc = p.netloc
            netloc = re.sub(r":([^:@]+)@", r":***@", netloc, count=1)
            return p._replace(netloc=netloc).geturl()
        return u
    except Exception:
        return "<unparseable>"
