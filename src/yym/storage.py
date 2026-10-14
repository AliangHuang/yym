from __future__ import annotations

from datetime import datetime
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import tempfile

from yym.models import Snapshot


def data_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
    path = base / "yym"
    path.mkdir(parents=True, exist_ok=True)
    return path


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="yym-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def load_settings() -> dict:
    try:
        result = json.loads((data_dir() / "settings.json").read_text(encoding="utf-8"))
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(value: dict) -> None:
    atomic_json(data_dir() / "settings.json", value)


def save_snapshot(snapshot: Snapshot) -> None:
    if snapshot.account.uid or snapshot.account.short_id:
        atomic_json(data_dir() / "accounts" / snapshot.account.key / "latest.json", snapshot.to_dict())


def setup_logging(filename: str = 'yym.log') -> None:
    handler = RotatingFileHandler(data_dir() / filename, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)
