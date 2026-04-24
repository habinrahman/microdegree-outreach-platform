"""Startup guard that blocks deprecated email log usage."""
from pathlib import Path


def assert_no_deprecated_legacy_log_usage() -> None:
    """
    Fail fast if deprecated legacy email log tokens reappear anywhere in backend Python code.
    """
    backend_root = Path(__file__).resolve().parents[2]
    forbidden = [
        "email" + "_logs",
        "Email" + "Log",
        "email" + "_log",
    ]
    skip_parts = {"venv", "venv_old", "__pycache__", ".pytest_cache"}

    offenders: list[str] = []
    for py_file in backend_root.rglob("*.py"):
        if any(part in skip_parts for part in py_file.parts):
            continue
        try:
            content = py_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if any(token in content for token in forbidden):
            offenders.append(str(py_file.relative_to(backend_root)))

    if offenders:
        joined = ", ".join(offenders[:25])
        extra = "" if len(offenders) <= 25 else f" (+{len(offenders) - 25} more)"
        raise RuntimeError(
            "Deprecated legacy email log usage detected. "
            "Use email_campaigns only. Offenders: "
            f"{joined}{extra}"
        )

