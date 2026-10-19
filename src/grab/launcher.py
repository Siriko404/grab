"""Make sure an engine is running, starting the app if it is not."""

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import config
from .engine import lock_held
from .rpc import Rpc


class NotRunning(Exception):
    pass


def grab_executable() -> str:
    return shutil.which("grab") or str(Path(sys.executable).parent / "grab")


def launch_argv() -> list[str] | None:
    """How to open the app in a terminal window on this system, or None if there is no way."""
    exe = grab_executable()
    if omarchy := shutil.which("omarchy-launch-or-focus-tui"):
        return [omarchy, exe]  # app-id org.omarchy.grab: a normal tiled Omarchy window, one instance
    if xdg := shutil.which("xdg-terminal-exec"):
        return [xdg, "--app-id=grab", "-e", exe]
    return None


def focus_window() -> bool:
    """Focus the app's existing Omarchy window. False if there is none (or not on Hyprland)."""
    if not (
        os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
        and shutil.which("hyprctl")
        and shutil.which("omarchy-launch-or-focus")
    ):
        return False
    try:
        clients = json.loads(
            subprocess.run(["hyprctl", "clients", "-j"], capture_output=True, text=True, timeout=5).stdout
        )
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False
    if not any(c.get("class") == "org.omarchy.grab" for c in clients):
        return False
    subprocess.run(["omarchy-launch-or-focus", "org.omarchy.grab", "true"], check=False)
    return True


def _launch_command() -> list[str]:
    override = os.environ.get("GRAB_LAUNCH_CMD")
    if override:
        return shlex.split(override)
    return [grab_executable(), "launch"]


def ensure_engine(cfg: dict | None = None, wait: float = 20.0) -> Rpc:
    cfg = cfg or config.load()
    rpc = Rpc(cfg["port"], cfg["secret"])
    if rpc.alive():
        return rpc
    if not lock_held():
        if os.environ.get("GRAB_NO_LAUNCH"):
            raise NotRunning("Grab is not running.")
        subprocess.Popen(
            _launch_command(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if rpc.alive():
            return rpc
        time.sleep(0.25)
    raise NotRunning("Grab did not start in time.")
