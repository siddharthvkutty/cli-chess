"""Tiny JSON config in the OS-appropriate config dir (~/.config/chess-cli, %APPDATA%\\chess-cli)."""
import json
import os
import shutil
from pathlib import Path

from platformdirs import user_config_dir

PATH = Path(user_config_dir("chess-cli", appauthor=False)) / "config.json"
DEFAULT_SERVER = "ws://localhost:8765"


def load() -> dict:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(**updates) -> None:
    data = {**load(), **updates}
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def stockfish_path() -> str | None:
    """STOCKFISH_PATH env var, then config file, then PATH."""
    for candidate in (os.environ.get("STOCKFISH_PATH"), load().get("stockfish_path")):
        if candidate and Path(candidate).is_file():
            return candidate
    return shutil.which("stockfish")
