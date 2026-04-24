"""
CI guard: every ``Student(...)`` / ``HRContact(...)`` in ``tests/`` must pass
``is_fixture_test_data=`` explicitly (``True`` for synthetic rows, ``False`` for intentional
\"production-like\" control rows). Prevents silent fixture leakage into operator surfaces.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_SKIP_FILES = frozenset(
    {
        "test_ci_fixture_tag_enforcement.py",
    }
)


def _iter_test_py_files() -> list[Path]:
    root = Path(__file__).resolve().parents[1] / "tests"
    return sorted(p for p in root.rglob("*.py") if p.name not in _SKIP_FILES)


def _call_name(func: ast.AST) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        # e.g. models.Student — still treat as Student-like if attr matches
        return func.attr
    return None


def _has_fixture_kw(keywords: list[ast.keyword]) -> bool:
    for kw in keywords:
        if kw.arg == "is_fixture_test_data":
            if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, bool):
                return True
            return False
    return False


@pytest.mark.parametrize("path", _iter_test_py_files(), ids=lambda p: str(p.relative_to(p.parents[1])))
def test_student_and_hrcontact_calls_include_explicit_fixture_flag(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node.func)
        if name not in ("Student", "HRContact"):
            continue
        if not _has_fixture_kw(node.keywords):
            pytest.fail(f"{path}:{node.lineno}: {name}(...) missing is_fixture_test_data=<bool>")
