import os
import signal
import subprocess
import sys
import time

from conftest import BIN, CONTENT, SIZE, aria_pids, sha, wait_for
from grab import config
from grab.engine import Engine
from grab.rpc import Rpc


def tell_all(rpc):
    out = rpc.call("tellActive") + rpc.call("tellWaiting", 0, 100) + rpc.call("tellStopped", 0, 100)
    return out


def test_stop_pauses_and_restart_resumes_to_identical_file(env, server):
    eng = Engine(config.load())
    eng.start()
    eng.rpc.call("addUri", [server.url()], {"dir": str(env.dl)})
    wait_for(lambda: any(int(d["completedLength"]) > 2_000_000 for d in tell_all(eng.rpc)), what="progress")
    pid = eng.proc.pid
    eng.stop()

    assert not os.path.exists(f"/proc/{pid}"), "aria2c must be gone after stop"
    session = env.session.read_text()
    assert server.url() in session and "pause=true" in session
    assert (env.dl / "big.bin.aria2").exists(), "control file needed for resume"
    assert 0 < (env.dl / "big.bin").stat().st_size < SIZE

    eng2 = Engine(config.load())
    eng2.start()
    items = tell_all(eng2.rpc)
    assert [d["status"] for d in items] == ["paused"], items
    server.requests.clear()
    time.sleep(2)
    assert not server.requests, "a paused download must not touch the network"

    eng2.rpc.call("unpauseAll")
    wait_for(lambda: tell_all(eng2.rpc)[0]["status"] == "complete", timeout=30, what="completion")
    eng2.stop()
    resumed_from = [int(r["Range"][6:].split("-")[0]) for r in server.requests if r.get("Range")]
    assert resumed_from and max(resumed_from) >= 2_000_000, f"must resume mid-file, got {resumed_from}"
    assert sha((env.dl / "big.bin").read_bytes()) == sha(CONTENT)


def test_hard_kill_of_owner_stops_engine_and_restart_is_paused(env, server):
    owner = subprocess.Popen(
        [sys.executable, "-m", "grab.cli", "serve"], env=env.environ, stdout=subprocess.PIPE, text=True
    )
    cfg = config.load()
    rpc = Rpc(cfg["port"], cfg["secret"])
    wait_for(rpc.alive, what="engine up")
    rpc.call("addUri", [server.url()], {"dir": str(env.dl)})
    wait_for(lambda: any(int(d["completedLength"]) > 1_000_000 for d in tell_all(rpc)), what="progress")
    assert aria_pids(env)
    owner.send_signal(signal.SIGKILL)
    owner.wait()
    wait_for(lambda: not aria_pids(env), timeout=10, what="aria2c to exit after owner died")

    eng = Engine(config.load())
    eng.start()
    assert [d["status"] for d in tell_all(eng.rpc)] == ["paused"]
    eng.stop()


def test_sighup_on_serve_pauses_and_exits(env, server):
    owner = subprocess.Popen(
        [sys.executable, "-m", "grab.cli", "serve"], env=env.environ, stdout=subprocess.PIPE, text=True
    )
    rpc = Rpc(config.load()["port"], config.load()["secret"])
    wait_for(rpc.alive, what="engine up")
    r = subprocess.run([str(BIN / "grab"), "add", server.url()], env=env.environ, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    wait_for(lambda: any(int(d["completedLength"]) > 1_000_000 for d in tell_all(rpc)), what="progress")
    owner.send_signal(signal.SIGHUP)
    assert owner.wait(timeout=15) == 0
    assert not aria_pids(env)
    assert "pause=true" in env.session.read_text()
