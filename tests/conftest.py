import hashlib
import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

SIZE = 12 * 1024 * 1024
RATE = 2 * 1024 * 1024  # bytes/s per connection
SMALL = 400 * 1024  # /small.bin, served slowly enough to be seen in flight
BLOCK = os.urandom(1 << 20)
CONTENT = (BLOCK * (SIZE // len(BLOCK) + 1))[:SIZE]
BIN = Path(sys.executable).parent


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(fn, timeout=20.0, what="condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(0.15)
    raise AssertionError(f"timed out waiting for {what}")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_HEAD(self):
        self.serve(head=True)

    def do_GET(self):
        self.server.requests.append(dict(self.headers) | {"_path": self.path})
        self.serve(head=False)

    PAGE = b"""<!doctype html><title>Test page</title>
<a href="/files/alpha.zip">Alpha archive</a>
<a href="/files/beta.pdf">Beta report</a>
<a href="/files/alpha.zip">Alpha again</a>
<a href="/get.php?file=gamma%2Eiso">Gamma image</a>
<a href="/files/delta.bin" download>Delta</a>
<a href="magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567&dn=epsilon">Epsilon magnet</a>
<a href="/about">About us</a>
<a href="mailto:x@y.z">Mail</a>
<video src="/media/zeta.mp4"></video>
<a id="dl" href="/dl/attach.bin">Attachment</a>
"""

    def serve(self, head):
        if self.path.startswith("/page"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(self.PAGE)))
            self.end_headers()
            if not head:
                self.wfile.write(self.PAGE)
            return
        if self.path.startswith("/missing"):
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        small = self.path.startswith("/small")
        size = SMALL if small else SIZE
        rate = RATE / 8 if small else RATE
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            a, _, b = rng[6:].partition("-")
            start = int(a)
            end = int(b) if b else size - 1
        status = 206 if rng else 200
        self.send_response(status)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition", 'attachment; filename="big.bin"')
        if rng:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if head:
            return
        pos = start
        try:
            while pos <= end:
                chunk = CONTENT[pos : min(pos + 65536, end + 1)]
                self.wfile.write(chunk)
                pos += len(chunk)
                time.sleep(len(chunk) / rate)
        except OSError:
            pass


@pytest.fixture
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.requests = []
    srv.url = lambda path="/big.bin": f"http://127.0.0.1:{srv.server_address[1]}{path}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


@pytest.fixture
def env(tmp_path, monkeypatch):
    cfg_dir, data_dir, dl = tmp_path / "cfg", tmp_path / "data", tmp_path / "dl"
    for d in (cfg_dir, data_dir, dl):
        d.mkdir()
    port = free_port()
    (cfg_dir / "config.json").write_text(
        json.dumps(
            {"port": port, "secret": "testsecret", "dir": str(dl), "connections": 1, "concurrent": 5, "limit": "0"}
        )
    )
    monkeypatch.setenv("GRAB_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setenv("GRAB_DATA_DIR", str(data_dir))
    monkeypatch.setenv("GRAB_NO_LAUNCH", "1")
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "paste.txt").write_text("")
    monkeypatch.setenv("GRAB_OPENER", f"sh -c 'echo \"$@\" >> {logs}/opener.log' _")
    monkeypatch.setenv("GRAB_NOTIFY", f"sh -c 'echo \"$@\" >> {logs}/notify.log' _")
    monkeypatch.setenv("GRAB_CLIP", f"sh -c 'cat > {logs}/clip.txt'")
    monkeypatch.setenv("GRAB_PASTE", f"cat {logs}/paste.txt")
    e = SimpleNamespace(
        logs=logs,
        cfg_dir=cfg_dir,
        data=data_dir,
        dl=dl,
        port=port,
        root=tmp_path,
        environ=dict(os.environ),
        session=data_dir / "session.txt",
    )
    yield e
    subprocess.run(["pkill", "-9", "-f", str(tmp_path)], check=False)


def aria_pids(env) -> list[int]:
    out = subprocess.run(["pgrep", "-f", "--", f"--input-file={env.session}"], capture_output=True, text=True).stdout
    return [int(p) for p in out.split()]


def run_cli(env, *args, **kw):
    return subprocess.run([str(BIN / "grab"), *args], env=env.environ, capture_output=True, text=True, timeout=30, **kw)


def owner_pid(env) -> int:
    """PID of the process that owns the engine (aria2c watches it via --stop-with-process)."""
    out = subprocess.run(["pgrep", "-af", "--", f"--input-file={env.session}"], capture_output=True, text=True).stdout
    return int(out.split("--stop-with-process=")[1].split()[0])
