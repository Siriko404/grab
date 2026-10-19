"""Desktop integration: browser host manifests, the launcher entry, the icon and the unpacked extension.

One implementation used three ways: `grab setup` (per user), `python -m grab.integrate --system`
(packagers, with --destdir), and the repo's install.sh.
"""

import argparse
import base64
import hashlib
import json
import shutil
import sys
from importlib import resources
from pathlib import Path

HOST_NAME = "io.github.siriko404.grab"

# (label, config root that must exist, NativeMessagingHosts dir) relative to $HOME
USER_BROWSERS = [
    ("chromium", ".config/chromium", ".config/chromium/NativeMessagingHosts"),
    ("google-chrome", ".config/google-chrome", ".config/google-chrome/NativeMessagingHosts"),
    ("brave", ".config/BraveSoftware/Brave-Browser", ".config/BraveSoftware/Brave-Browser/NativeMessagingHosts"),
    ("microsoft-edge", ".config/microsoft-edge", ".config/microsoft-edge/NativeMessagingHosts"),
    ("vivaldi", ".config/vivaldi", ".config/vivaldi/NativeMessagingHosts"),
]
SYSTEM_HOST_DIRS = ["etc/chromium/native-messaging-hosts", "etc/opt/chrome/native-messaging-hosts"]


def package_dir(name: str) -> Path:
    return Path(str(resources.files("grab") / name))


def extension_id(manifest: Path | None = None) -> str:
    """Chrome derives an extension's id from its public key; the manifest pins one."""
    manifest = manifest or package_dir("extension") / "manifest.json"
    der = base64.b64decode(json.loads(manifest.read_text())["key"])
    return "".join(chr(ord("a") + int(c, 16)) for c in hashlib.sha256(der).hexdigest()[:32])


def host_manifest(host_path: str) -> str:
    text = (package_dir("data") / "native-messaging-host.json.in").read_text()
    return text.replace("@NAME@", HOST_NAME).replace("@PATH@", host_path).replace("@ID@", extension_id())


def find_host_executable() -> str:
    """The grab-host that belongs to this interpreter (venv, pipx or system), else the one on PATH."""
    sibling = Path(sys.executable).parent / "grab-host"
    return str(sibling) if sibling.exists() else (shutil.which("grab-host") or str(sibling))


def _copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def install_user(home: Path, host_path: str | None = None) -> dict:
    """Per-user install. Returns what was written, for the summary and the tests."""
    host_path = host_path or find_host_executable()
    done = {"hosts": [], "extension": None, "desktop": None, "icon": None}
    for _label, root, hosts in USER_BROWSERS:
        if (home / root).is_dir():
            target = home / hosts / f"{HOST_NAME}.json"
            _write(target, host_manifest(host_path))
            done["hosts"].append(target)
    done["extension"] = home / ".local/share/grab/extension"
    _copy_tree(package_dir("extension"), done["extension"])
    apps = home / ".local/share/applications"
    done["desktop"] = apps / "grab.desktop"
    grab = Path(sys.executable).parent / "grab"
    exec_path = str(grab) if grab.exists() else "grab"
    _write(
        done["desktop"], (package_dir("data") / "grab.desktop").read_text().replace("Exec=grab ", f"Exec={exec_path} ")
    )
    done["icon"] = home / ".local/share/icons/hicolor/256x256/apps/grab.png"
    done["icon"].parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(package_dir("data") / "grab.png", done["icon"])
    return done


def remove_user(home: Path) -> list[Path]:
    gone = []
    candidates = [home / hosts / f"{HOST_NAME}.json" for _l, _r, hosts in USER_BROWSERS]
    candidates += [
        home / ".local/share/applications/grab.desktop",
        home / ".local/share/icons/hicolor/256x256/apps/grab.png",
    ]
    for path in candidates:
        if path.exists():
            path.unlink()
            gone.append(path)
    ext = home / ".local/share/grab/extension"
    if ext.exists():
        shutil.rmtree(ext)
        gone.append(ext)
    return gone


def install_system(destdir: Path, prefix: str = "/usr") -> list[Path]:
    """Layout for a distribution package. Host manifests point at <prefix>/bin/grab-host."""
    root = destdir / prefix.lstrip("/")
    written = []
    _copy_tree(package_dir("extension"), root / "share/grab/extension")
    written.append(root / "share/grab/extension")
    desktop = root / "share/applications/grab.desktop"
    _write(desktop, (package_dir("data") / "grab.desktop").read_text())
    icon = root / "share/icons/hicolor/256x256/apps/grab.png"
    icon.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(package_dir("data") / "grab.png", icon)
    written += [desktop, icon]
    for rel in SYSTEM_HOST_DIRS:
        target = destdir / rel / f"{HOST_NAME}.json"
        _write(target, host_manifest(f"{prefix}/bin/grab-host"))
        written.append(target)
    return written


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="python -m grab.integrate", description=__doc__)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--user", action="store_true", help="install for the current user")
    mode.add_argument("--remove", action="store_true", help="remove the per-user install")
    mode.add_argument("--system", action="store_true", help="install a system-wide layout (for packagers)")
    p.add_argument("--destdir", type=Path, default=Path("/"), help="with --system: staging root")
    p.add_argument("--prefix", default="/usr", help="with --system: install prefix")
    args = p.parse_args(argv)
    if args.system:
        for path in install_system(args.destdir, args.prefix):
            print(path)
    elif args.remove:
        for path in remove_user(Path.home()):
            print("removed", path)
    else:
        done = install_user(Path.home())
        for host in done["hosts"]:
            print("browser host ", host)
        print("extension    ", done["extension"])
        print("launcher     ", done["desktop"])
        if not done["hosts"]:
            print("No supported browser profile found; open the browser once, then run this again.")
        print(
            f"\nLast step, in your browser: chrome://extensions → Developer mode → Load unpacked → {done['extension']}"
        )


if __name__ == "__main__":
    main()
