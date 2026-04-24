"""Regression-style tests for pg_dump / restore verify helpers (mocked subprocess)."""
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.backup_pg import run_pg_dump_custom, verify_pg_dump_custom_format


def test_run_pg_dump_rejects_non_postgres_url(tmp_path):
    res = run_pg_dump_custom("sqlite:///./x.db", tmp_path / "a.dump")
    assert res["ok"] is False
    assert res.get("error") == "not_a_postgres_url"


def test_run_pg_dump_success_mocked(tmp_path):
    out = tmp_path / "t.dump"
    fake = MagicMock()
    fake.returncode = 0
    fake.stdout = ""
    fake.stderr = ""
    with patch("app.services.backup_pg.subprocess.run", return_value=fake):
        res = run_pg_dump_custom("postgresql://u:p@h/db", out)
    assert res["ok"] is True


def test_verify_pg_dump_missing_file(tmp_path):
    res = verify_pg_dump_custom_format(tmp_path / "nope.dump")
    assert res["ok"] is False
    assert res.get("error") == "file_not_found"


def test_verify_pg_restore_success_mocked(tmp_path):
    p = tmp_path / "x.dump"
    p.write_bytes(b"PGDMP")
    fake = MagicMock()
    fake.returncode = 0
    fake.stdout = ";\n;\n"
    fake.stderr = ""
    with patch("app.services.backup_pg.subprocess.run", return_value=fake):
        res = verify_pg_dump_custom_format(p)
    assert res["ok"] is True
    assert res.get("listing_lines", 0) >= 1
