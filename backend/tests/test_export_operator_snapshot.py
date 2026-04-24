"""Operator JSONL export script."""
import json
from pathlib import Path

from app.scripts.export_operator_snapshot import main as export_main


def test_export_operator_snapshot_runs(tmp_path: Path):
    out = tmp_path / "snap"
    assert export_main(["--out", str(out)]) == 0
    assert (out / "manifest.json").is_file()
    assert (out / "students.jsonl").is_file()
    man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert "counts" in man
