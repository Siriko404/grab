import json
from pathlib import Path

from conftest import run_cli, wait_for
from grab import config
from grab.engine import Engine
from grab.rpc import Rpc


def started(env):
    eng = Engine(config.load())
    eng.start()
    return eng


def all_items(rpc):
    return rpc.call("tellActive") + rpc.call("tellWaiting", 0, 100) + rpc.call("tellStopped", 0, 100)


def test_secret_is_not_on_the_command_line_and_conf_is_private(env):
    eng = started(env)
    try:
        cmdline = Path(f"/proc/{eng.proc.pid}/cmdline").read_text()
        assert "testsecret" not in cmdline
        conf = env.data / "aria2.conf"
        assert oct(conf.stat().st_mode & 0o777) == "0o600"
        assert "rpc-secret=testsecret" in conf.read_text()
        assert eng.rpc.alive(), "engine must still authenticate with the conf-file secret"
        assert Rpc(env.port, "wrong").alive() is False
    finally:
        eng.stop()


def test_ls_json_status_and_exit_codes(env, server):
    r = run_cli(env, "status")
    assert r.returncode == 3 and "stopped" in r.stdout
    eng = started(env)
    try:
        assert run_cli(env, "status").returncode == 0
        eng.rpc.call("addUri", [server.url()], {"dir": str(env.dl), "out": "j.bin"})
        wait_for(lambda: any(int(d["completedLength"]) > 0 for d in all_items(eng.rpc)), what="progress")
        rows = json.loads(run_cli(env, "ls", "--json").stdout)
        assert rows[0]["name"] == "j.bin" and rows[0]["status"] == "active"
        assert set(rows[0]) == {"gid", "status", "name", "url", "dir", "path", "total", "done", "speed", "error"}
        assert run_cli(env, "ls", "-s", "error", "--json").stdout.strip() == "[]"
    finally:
        eng.stop()


def test_config_validation_and_live_apply(env):
    eng = started(env)
    try:
        assert run_cli(env, "config", "set", "concurrent", "99").returncode != 0
        assert run_cli(env, "config", "set", "dir", "relative/path").returncode != 0
        assert run_cli(env, "config", "set", "limit", "fast").returncode != 0
        assert run_cli(env, "config", "set", "limit", "3m").returncode == 0
        assert run_cli(env, "config", "get", "limit").stdout.strip() == "3M"
        assert eng.rpc.call("getGlobalOption")["max-overall-download-limit"] == str(3 * 1024 * 1024)
        assert run_cli(env, "config", "set", "nonsense", "1").returncode != 0
    finally:
        eng.stop()


def test_retry_failed_download_and_open(env, server):
    eng = started(env)
    try:
        eng.rpc.call("addUri", [server.url("/missing")], {"dir": str(env.dl), "out": "gone.bin"})
        wait_for(lambda: any(d["status"] == "error" for d in all_items(eng.rpc)), what="failure")
        old = next(d["gid"] for d in all_items(eng.rpc) if d["status"] == "error")
        r = run_cli(env, "retry", old[:6])
        assert r.returncode == 0, r.stderr
        new = r.stdout.strip()
        assert new and new != old
        assert old not in [d["gid"] for d in all_items(eng.rpc)], "old failed entry must be replaced"
        wait_for(lambda: any(d["gid"] == new and d["status"] == "error" for d in all_items(eng.rpc)), what="retry ran")
        assert run_cli(env, "retry", "nonexistent").returncode != 0

        eng.rpc.call("addUri", [server.url("/small.bin")], {"dir": str(env.dl), "out": "ok.bin"})
        wait_for(lambda: any(d["status"] == "complete" for d in all_items(eng.rpc)), timeout=15, what="small done")
        gid = next(d["gid"] for d in all_items(eng.rpc) if d["status"] == "complete")
        assert run_cli(env, "open", gid[:6]).returncode == 0
        assert run_cli(env, "open", gid[:6], "--folder").returncode == 0
        wait_for(
            lambda: (env.logs / "opener.log").exists() and len((env.logs / "opener.log").read_text().split()) == 2,
            what="opener calls",
        )
        opened = (env.logs / "opener.log").read_text().split()
        assert opened == [str(env.dl / "ok.bin"), str(env.dl)]
    finally:
        eng.stop()


def test_rm_delete_removes_partial_and_control_file_but_keeps_finished(env, server):
    eng = started(env)
    try:
        eng.rpc.call("addUri", [server.url()], {"dir": str(env.dl), "out": "part.bin"})
        wait_for(lambda: any(int(d["completedLength"]) > 1_000_000 for d in all_items(eng.rpc)), what="progress")
        gid = all_items(eng.rpc)[0]["gid"]
        assert run_cli(env, "pause", gid[:6]).returncode == 0
        wait_for(lambda: (env.dl / "part.bin.aria2").exists(), what="control file")
        r = run_cli(env, "rm", gid[:6], "--delete")
        assert r.returncode == 0, r.stderr
        assert not (env.dl / "part.bin").exists() and not (env.dl / "part.bin.aria2").exists()
        assert all_items(eng.rpc) == []

        eng.rpc.call("addUri", [server.url("/small.bin")], {"dir": str(env.dl), "out": "keep.bin"})
        wait_for(lambda: any(d["status"] == "complete" for d in all_items(eng.rpc)), timeout=15, what="done")
        gid = all_items(eng.rpc)[0]["gid"]
        r = run_cli(env, "rm", gid[:6], "--delete")
        assert (env.dl / "keep.bin").exists(), "a finished file must never be deleted"
        assert "kept" in r.stdout
    finally:
        eng.stop()


def test_engine_log_stays_quiet_at_warn_level(env, server):
    """aria2 logs every RPC call at its default debug level; one tab polling grew the log to tens of MB."""
    eng = started(env)
    try:
        for _ in range(60):
            eng.rpc.call("getGlobalStat")
            eng.rpc.call("tellActive")
        eng.rpc.call("addUri", [server.url("/missing")], {"dir": str(env.dl)})
        wait_for(lambda: any(d["status"] == "error" for d in all_items(eng.rpc)), what="error")
        log = (env.data / "aria2.log").read_text()
        assert "Executing RPC method" not in log and "HTTP Server received request" not in log
        assert len(log) < 20_000, f"log is {len(log)} bytes"
    finally:
        eng.stop()
