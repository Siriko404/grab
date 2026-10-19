import fcntl
import os
import pty
import select
import signal
import struct
import subprocess
import termios
import threading

from conftest import BIN, aria_pids, wait_for
from grab import config
from grab.rpc import Rpc


class Terminal:
    """Run grab under a pseudo-terminal, no window involved."""

    def __init__(self, env):
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 140, 0, 0))
        e = dict(env.environ, TERM="xterm-256color")
        self.proc = subprocess.Popen(
            [str(BIN / "grab")], stdin=slave, stdout=slave, stderr=slave, env=e, start_new_session=True
        )
        os.close(slave)
        self.buf = b""
        self._stop = False
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        while not self._stop:
            r, _, _ = select.select([self.master], [], [], 0.2)
            if r:
                try:
                    self.buf += os.read(self.master, 65536)
                except OSError:
                    return

    def has(self, text: str) -> bool:
        return text.encode() in self.buf

    def send(self, keys: str):
        os.write(self.master, keys.encode())

    def close(self):
        self._stop = True
        if self.proc.poll() is None:
            self.proc.kill()


def test_tui_shows_download_and_q_pauses_everything(env, server):
    term = Terminal(env)
    try:
        cfg = config.load()
        rpc = Rpc(cfg["port"], cfg["secret"])
        wait_for(rpc.alive, timeout=20, what="engine")
        wait_for(lambda: term.has("Nothing here yet"), what="empty state")
        rpc.call("addUri", [server.url()], {"dir": str(env.dl)})
        wait_for(lambda: term.has("big.bin"), what="row in TUI")
        wait_for(lambda: term.has("downloading"), what="status in TUI")
        wait_for(lambda: any(int(d["completedLength"]) > 1_000_000 for d in rpc.call("tellActive")), what="progress")
        term.send("q")
        assert term.proc.wait(timeout=15) == 0
        assert not aria_pids(env), "engine must stop when the app quits"
        assert "pause=true" in env.session.read_text()
        assert (env.dl / "big.bin.aria2").exists()
    finally:
        term.close()


def test_tui_space_toggles_pause(env, server):
    term = Terminal(env)
    try:
        cfg = config.load()
        rpc = Rpc(cfg["port"], cfg["secret"])
        wait_for(rpc.alive, timeout=20, what="engine")
        rpc.call("addUri", [server.url()], {"dir": str(env.dl)})
        wait_for(lambda: term.has("downloading"), what="row")
        term.send(" ")
        wait_for(
            lambda: rpc.call("tellWaiting", 0, 10) and rpc.call("tellWaiting", 0, 10)[0]["status"] == "paused",
            what="paused via space",
        )
        term.send(" ")
        wait_for(lambda: rpc.call("tellActive"), what="resumed via space")
        term.send("q")
        assert term.proc.wait(timeout=15) == 0
    finally:
        term.close()


def test_tui_sighup_like_a_closed_terminal_window(env, server):
    term = Terminal(env)
    try:
        cfg = config.load()
        rpc = Rpc(cfg["port"], cfg["secret"])
        wait_for(rpc.alive, timeout=20, what="engine")
        rpc.call("addUri", [server.url()], {"dir": str(env.dl)})
        wait_for(lambda: any(int(d["completedLength"]) > 1_000_000 for d in rpc.call("tellActive")), what="progress")
        term.proc.send_signal(signal.SIGHUP)
        term.proc.wait(timeout=15)
        assert not aria_pids(env)
        assert "pause=true" in env.session.read_text()
    finally:
        term.close()


def test_second_instance_is_refused_without_touching_the_first(env, server):
    term = Terminal(env)
    try:
        cfg = config.load()
        rpc = Rpc(cfg["port"], cfg["secret"])
        wait_for(rpc.alive, timeout=20, what="engine")
        second = subprocess.run([str(BIN / "grab")], env=env.environ, capture_output=True, text=True, timeout=15)
        assert second.returncode == 1 and "already running" in second.stdout
        assert rpc.alive()
        term.send("q")
        assert term.proc.wait(timeout=15) == 0
    finally:
        term.close()
