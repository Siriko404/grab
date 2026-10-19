import os
import shutil
import stat
import subprocess
import sys

import pytest

from grab import integrate
from grab.launcher import focus_window, launch_argv


def stub(directory, name):
    path = directory / name
    path.write_text("#!/bin/sh\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


def test_launch_prefers_omarchy_then_xdg_terminal_exec_then_nothing(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    monkeypatch.setenv("PATH", str(bindir))
    omarchy = stub(bindir, "omarchy-launch-or-focus-tui")
    xdg = stub(bindir, "xdg-terminal-exec")

    argv = launch_argv()
    assert argv[0] == omarchy and len(argv) == 2 and os.path.basename(argv[1]) == "grab"

    os.remove(omarchy)
    argv = launch_argv()
    assert argv[:3] == [xdg, "--app-id=grab", "-e"] and os.path.basename(argv[3]) == "grab"

    os.remove(xdg)
    assert launch_argv() is None


def test_grab_launch_explains_when_no_terminal_launcher_exists(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    r = subprocess.run(
        [sys.executable, "-m", "grab", "launch"],
        env={"PATH": str(empty), "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0 and "No terminal launcher found" in r.stderr


def test_focus_window_is_false_outside_hyprland(monkeypatch):
    monkeypatch.delenv("HYPRLAND_INSTANCE_SIGNATURE", raising=False)
    assert focus_window() is False


def test_desktop_entry_is_static_and_valid():
    desktop = integrate.package_dir("data") / "grab.desktop"
    text = desktop.read_text()
    assert "Exec=grab launch" in text and "Icon=grab" in text and "TUI.float" not in text
    if shutil.which("desktop-file-validate"):
        assert subprocess.run(["desktop-file-validate", str(desktop)], capture_output=True).returncode == 0
    else:
        pytest.skip("desktop-file-validate not installed (the entry itself was checked above)")
