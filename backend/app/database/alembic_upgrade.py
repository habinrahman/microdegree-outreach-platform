"""Optional startup: alembic upgrade head (set ALEMBIC_UPGRADE_ON_START=1)."""
from pathlib import Path

from alembic import command
from alembic.config import Config


def run_alembic_upgrade_head() -> None:
    backend_root = Path(__file__).resolve().parents[2]
    ini = backend_root / "alembic.ini"
    if not ini.is_file():
        raise FileNotFoundError(f"alembic.ini not found at {ini}")
    cfg = Config(str(ini))
    command.upgrade(cfg, "head")
