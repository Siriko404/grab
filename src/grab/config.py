import contextlib
import json
import os
import re
import secrets
from pathlib import Path

DEFAULTS = {
    "port": 16802,
    "dir": str(Path.home() / "Downloads"),
    "concurrent": 5,
    "connections": 8,
    "limit": "0",
}


def config_dir() -> Path:
    return Path(os.environ.get("GRAB_CONFIG_DIR") or Path.home() / ".config" / "grab")


def data_dir() -> Path:
    return Path(os.environ.get("GRAB_DATA_DIR") or Path.home() / ".local" / "share" / "grab")


def private_dir(path: Path) -> Path:
    """Create `path` readable only by the user. aria2 rewrites its session file with the default mode, so the
    folder is what keeps other local users out of it."""
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def save(cfg: dict) -> None:
    private_dir(config_dir())
    path = config_dir() / "config.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(cfg, f, indent=2)


def load() -> dict:
    private_dir(config_dir())
    private_dir(data_dir())
    cfg = dict(DEFAULTS)
    with contextlib.suppress(OSError, ValueError):
        cfg.update(json.loads((config_dir() / "config.json").read_text()))
    if not cfg.get("secret"):
        cfg["secret"] = secrets.token_hex(16)
        save(cfg)
    return cfg


SETTINGS = ("dir", "concurrent", "connections", "limit")


def coerce(key: str, raw: str):
    """Validate a user-facing setting; raises ValueError with a readable reason."""
    if key not in SETTINGS:
        raise ValueError(f"unknown setting '{key}' (one of: {', '.join(SETTINGS)})")
    if key == "dir":
        path = Path(raw).expanduser()
        if not path.is_absolute():
            raise ValueError("dir must be an absolute path")
        return str(path)
    if key in ("concurrent", "connections"):
        top = 20 if key == "concurrent" else 16
        if not raw.isdigit() or not 1 <= int(raw) <= top:
            raise ValueError(f"{key} must be a number from 1 to {top}")
        return int(raw)
    if not re.fullmatch(r"\d+[KkMm]?", raw):
        raise ValueError("limit looks like 2M, 500K or 0 for none")
    return raw.upper()
