"""Tests for HR snapshot restore helpers (no DB for row parsing)."""

import json
from pathlib import Path
from uuid import UUID, uuid4

from app.scripts.restore_hr_contacts_from_snapshot import _validate_row, load_hr_snapshot_rows


def test_load_hr_snapshot_rows_jsonl(tmp_path: Path) -> None:
    d = tmp_path / "snap"
    d.mkdir()
    row = {"id": str(uuid4()), "email": "R@EXAMPLE.COM", "name": "Rec", "company": "Co"}
    (d / "hr_contacts_to_remove.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    rows = load_hr_snapshot_rows(d)
    assert len(rows) == 1
    assert rows[0]["email"] == "R@EXAMPLE.COM"


def test_load_hr_snapshot_rows_csv(tmp_path: Path) -> None:
    d = tmp_path / "snap2"
    d.mkdir()
    u = str(uuid4())
    (d / "hr_contacts_to_remove.csv").write_text(f"id,email,name,company\n{u},a@b.com,N,C\n", encoding="utf-8")
    rows = load_hr_snapshot_rows(d)
    assert rows[0]["email"] == "a@b.com"


def test_validate_row():
    u = str(uuid4())
    assert _validate_row({"id": u, "email": "x@y.com", "name": "N", "company": ""}) == {
        "id": UUID(u),
        "email": "x@y.com",
        "name": "N",
        "company": "Unknown",
    }
    assert _validate_row({"id": "", "email": "x@y.com", "name": "N", "company": "C"}) is None
