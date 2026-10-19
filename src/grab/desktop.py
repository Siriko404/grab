"""Thin wrappers over desktop tools. Each can be overridden by an env var (used by the tests)."""

import os
import shlex
import subprocess


def _cmd(env_name: str, default: list[str]) -> list[str]:
    return shlex.split(os.environ.get(env_name, "")) or default


def _spawn(cmd: list[str], stdin: bytes | None = None) -> None:
    try:
        p = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        if stdin is not None and p.stdin:
            p.stdin.write(stdin)
            p.stdin.close()
    except OSError:
        pass


def open_path(path: str) -> None:
    _spawn(_cmd("GRAB_OPENER", ["xdg-open"]) + [path])


def copy_text(text: str) -> None:
    _spawn(_cmd("GRAB_CLIP", ["wl-copy"]), text.encode())


def paste_text() -> str:
    try:
        out = subprocess.run(_cmd("GRAB_PASTE", ["wl-paste", "-n"]), capture_output=True, text=True, timeout=1)
        return out.stdout if out.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def notify(title: str, body: str) -> None:
    _spawn(_cmd("GRAB_NOTIFY", ["notify-send", "-a", "Grab"]) + [title, body])
