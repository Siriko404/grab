import json
import subprocess
import sys

from conftest import BIN
from grab import integrate


def test_user_install_writes_hosts_only_for_browsers_that_exist(tmp_path):
    home = tmp_path
    (home / ".config/chromium").mkdir(parents=True)
    (home / ".config/vivaldi").mkdir(parents=True)

    done = integrate.install_user(home, host_path="/opt/venv/bin/grab-host")

    assert sorted(p.parent.parent.name for p in done["hosts"]) == ["chromium", "vivaldi"]
    manifest = json.loads(done["hosts"][0].read_text())
    assert manifest == {
        "name": integrate.HOST_NAME,
        "description": "Grab download manager host",
        "path": "/opt/venv/bin/grab-host",
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{integrate.extension_id()}/"],
    }
    assert (done["extension"] / "manifest.json").exists() and (done["extension"] / "popup.html").exists()
    assert (
        done["desktop"].read_text().count("\nExec=") == 1 and done["desktop"].read_text().rstrip().count("launch") == 1
    )
    assert done["icon"].stat().st_size > 0

    again = integrate.install_user(home, host_path="/opt/venv/bin/grab-host")  # idempotent
    assert again["hosts"] == done["hosts"]

    gone = integrate.remove_user(home)
    assert done["extension"] in gone and not done["extension"].exists()
    assert not any(p.exists() for p in done["hosts"] + [done["desktop"], done["icon"]])


def test_system_layout_for_packagers(tmp_path):
    written = integrate.install_system(tmp_path)
    rel = sorted(str(p.relative_to(tmp_path)) for p in written)
    assert rel == [
        "etc/chromium/native-messaging-hosts/io.github.siriko404.grab.json",
        "etc/opt/chrome/native-messaging-hosts/io.github.siriko404.grab.json",
        "usr/share/applications/grab.desktop",
        "usr/share/grab/extension",
        "usr/share/icons/hicolor/256x256/apps/grab.png",
    ]
    host = json.loads((tmp_path / rel[0]).read_text())
    assert host["path"] == "/usr/bin/grab-host"
    assert "Exec=grab launch" in (tmp_path / "usr/share/applications/grab.desktop").read_text()
    assert (tmp_path / "usr/share/grab/extension/manifest.json").exists()


def test_grab_setup_round_trip_through_the_cli(tmp_path):
    (tmp_path / ".config/chromium").mkdir(parents=True)
    env = {"HOME": str(tmp_path), "PATH": str(BIN) + ":/usr/bin"}
    ok = subprocess.run([str(BIN / "grab"), "setup"], env=env, capture_output=True, text=True)
    assert ok.returncode == 0, ok.stderr
    assert "chrome://extensions" in ok.stdout and str(tmp_path / ".local/share/grab/extension") in ok.stdout
    assert (tmp_path / f".config/chromium/NativeMessagingHosts/{integrate.HOST_NAME}.json").exists()
    out = subprocess.run([sys.executable, "-m", "grab", "setup", "--remove"], env=env, capture_output=True, text=True)
    assert out.returncode == 0 and "removed" in out.stdout
    assert not (tmp_path / f".config/chromium/NativeMessagingHosts/{integrate.HOST_NAME}.json").exists()
