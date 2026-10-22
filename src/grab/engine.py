"""The aria2 engine. It lives and dies with the app that owns it."""

import fcntl
import os
import shutil
import subprocess
import time

from . import config, session
from .rpc import Rpc, RpcDown, RpcError


class EngineError(Exception):
    pass


class Engine:
    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or config.load()
        self.rpc = Rpc(self.cfg["port"], self.cfg["secret"])
        self.proc: subprocess.Popen | None = None
        self._lock = None

    def start(self) -> None:
        data = config.private_dir(config.data_dir())
        lock = open(data / "engine.lock", "a+")  # noqa: SIM115 - held open for the life of the engine
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            raise EngineError("Grab is already running.") from None
        self._lock = lock
        try:
            if self.rpc.alive():
                raise EngineError(f"Port {self.cfg['port']} is already served by another aria2.")
            aria2c = shutil.which("aria2c")
            if not aria2c:
                raise EngineError("aria2c is not installed (pacman -S aria2).")
            sess = data / "session.txt"
            sess.touch()
            session.normalize_paused(sess)
            conf = data / "aria2.conf"  # holds the RPC secret; keeps it out of `ps`
            fd = os.open(conf, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(f"rpc-secret={self.cfg['secret']}\n")
            log_path = data / "aria2.log"
            if log_path.exists() and log_path.stat().st_size > 5_000_000:
                log_path.replace(data / "aria2.log.1")
            conns = int(self.cfg["connections"])
            args = [
                aria2c,
                f"--conf-path={conf}",
                "--enable-rpc",
                f"--rpc-listen-port={self.cfg['port']}",
                f"--input-file={sess}",
                f"--save-session={sess}",
                "--save-session-interval=15",
                f"--stop-with-process={os.getpid()}",
                f"--dir={self.cfg['dir']}",
                "--continue=true",
                f"--max-concurrent-downloads={self.cfg['concurrent']}",
                f"--split={conns}",
                f"--max-connection-per-server={min(conns, 16)}",
                "--min-split-size=1M",
                "--file-allocation=none",
                "--allow-overwrite=false",
                "--auto-file-renaming=true",
                "--max-tries=5",
                "--retry-wait=5",
                "--connect-timeout=15",
                "--timeout=30",
                "--seed-time=0",
                f"--max-overall-download-limit={self.cfg['limit']}",
                "--console-log-level=warn",
                "--log-level=warn",
                f"--log={log_path}",
                "--summary-interval=0",
            ]
            with open(data / "aria2.out", "ab") as log:
                self.proc = subprocess.Popen(
                    args, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True
                )
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if self.proc.poll() is not None:
                    raise EngineError(f"aria2c exited at startup; see {data / 'aria2.log'}")
                if self.rpc.alive():
                    return
                time.sleep(0.1)
            raise EngineError("aria2c did not answer in time.")
        except BaseException:
            self.stop()
            raise

    def stop(self) -> None:
        """Pause everything, save the session, then shut the engine down."""
        if self.proc is not None:
            try:
                self.rpc.call("forcePauseAll", timeout=3)
                self.rpc.call("saveSession", timeout=5)
                self.rpc.call("shutdown", timeout=3)
            except (RpcDown, RpcError):
                pass
            try:
                self.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait()
            self.proc = None
        if self._lock is not None:
            self._lock.close()
            self._lock = None


def lock_held() -> bool:
    """True while some process owns the engine (it may still be starting up)."""
    path = config.data_dir() / "engine.lock"
    if not path.exists():
        return False
    with open(path, "a+") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(f, fcntl.LOCK_UN)
    return False
