"""
PostgreSQL logical backup via pg_dump (-Fc).

  python -m app.scripts.pg_dump_backup [--output-dir DIR] [--verify]

Writes backup + backup_manifest_*.json under BACKUPS_DIR or ./backups.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    argv = argv if argv is not None else sys.argv[1:]
    p = argparse.ArgumentParser(description="Run pg_dump custom backup for DATABASE_URL (Postgres only).")
    p.add_argument("--output-dir", type=str, default="", help="Override BACKUPS_DIR / default ./backups")
    p.add_argument("--verify", action="store_true", help="Run pg_restore --list after dump")
    args = p.parse_args(argv)

    try:
        from app.database.config import DATABASE_URL
        from app.services.backup_health import default_backups_dir, write_backup_manifest
        from app.services.backup_pg import is_postgres_database_url, run_pg_dump_custom, verify_pg_dump_custom_format
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    if not is_postgres_database_url(DATABASE_URL or ""):
        print("DATABASE_URL is not PostgreSQL; use SQLite admin backup or provider snapshots.", file=sys.stderr)
        return 2

    out_root = Path(args.output_dir).resolve() if args.output_dir.strip() else default_backups_dir()
    out_root.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    fname = f"microdegree_outreach_{ts}.dump"
    out_path = out_root / fname

    res = run_pg_dump_custom(DATABASE_URL or "", out_path)
    print(json.dumps({"pg_dump": res}, indent=2))

    manifest_extra = {
        "relative_file": fname,
        "pg_dump_ok": bool(res.get("ok")),
        "pg_dump_returncode": res.get("returncode"),
        "bytes": res.get("bytes"),
    }
    mf = write_backup_manifest(backups_dir=out_root, kind="postgres_custom", relative_file=fname, extra=manifest_extra)

    if not res.get("ok"):
        print(f"Manifest written: {mf}", file=sys.stderr)
        return 1

    verify_out: dict = {"skipped": True}
    if args.verify:
        verify_out = verify_pg_dump_custom_format(out_path)
        print(json.dumps({"pg_restore_list": verify_out}, indent=2))
        mf2 = write_backup_manifest(
            backups_dir=out_root,
            kind="postgres_custom_verify",
            relative_file=fname,
            extra={**manifest_extra, "pg_restore_list_ok": verify_out.get("ok"), "listing_lines": verify_out.get("listing_lines")},
        )
        logger.info("verify manifest: %s", mf2)
        if not verify_out.get("ok"):
            return 1

    logger.info("manifest: %s", mf)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
