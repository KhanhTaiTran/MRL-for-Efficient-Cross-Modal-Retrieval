"""Stable locations for artifacts; independent of package nesting and CWD."""
from pathlib import Path

WORKER_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = WORKER_ROOT.parent


def worker_path(value: str | Path) -> Path:
    """Resolve local artifact paths relative to ai-worker; preserve absolute paths."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else WORKER_ROOT / path
