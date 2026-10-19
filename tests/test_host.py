import json
import os
import signal
import struct
import subprocess
import sys

from conftest import BIN, aria_pids, owner_pid, run_cli, wait_for
from grab import config
from grab.engine import Engine
from grab.rpc import Rpc


def host_call(env, msg, environ=None):
    data = json.dumps(msg).encode()
    p = subprocess.run(
        [str(BIN / "grab-host")],
        input=struct.pack("=I", len(data)) + data,
        env=environ or env.environ,
        capture_output=True,
        timeout=40,
    )
    assert p.returncode == 0, p.stderr
    (n,) = struct.unpack("=I", p.stdout[:4])
    assert len(p.stdout) == 4 + n, "host must write nothing but the framed reply"
    return json.loads(p.stdout[4:])


def test_host_forwards_cookie_referer_agent_and_name(env, server):
    eng = Engine(config.load())
    eng.start()
    try:
        reply = host_call(
            env,
            {
                "op": "add",
                "items": [
                    {
                        "url": server.url("/file?id=7"),
                        "referer": "https://site.example/page",
                        "cookie": "sid=abc123; theme=dark",
                        "ua": "TestAgent/1.0",
                        "out": "renamed.bin",
                    }
                ],
            },
        )
        assert reply["ok"] and len(reply["gids"]) == 1
        wait_for(lambda: any(r.get("_path") == "/file?id=7" for r in server.requests), what="request")
        req = next(r for r in server.requests if r.get("_path") == "/file?id=7")
        assert req["Cookie"] == "sid=abc123; theme=dark"
        assert req["Referer"] == "https://site.example/page"
        assert req["User-Agent"] == "TestAgent/1.0"
        wait_for(lambda: (env.dl / "renamed.bin").exists(), what="named file")
    finally:
        eng.stop()


def test_host_rejects_unknown_op_and_pings(env):
    assert host_call(env, {"op": "ping"}) == {"ok": True}
    assert host_call(env, {"op": "nope"})["ok"] is False


def test_host_reports_error_when_app_cannot_start(env, server):
    reply = host_call(env, {"op": "add", "items": [{"url": server.url()}]})
    assert reply["ok"] is False and "not running" in reply["error"].lower()


def test_host_starts_the_app_when_it_is_closed(env, server):
    environ = dict(env.environ)
    environ.pop("GRAB_NO_LAUNCH")
    environ["GRAB_LAUNCH_CMD"] = f"{sys.executable} -m grab.cli serve"
    reply = host_call(env, {"op": "add", "items": [{"url": server.url()}]}, environ)
    assert reply["ok"], reply
    cfg = config.load()
    rpc = Rpc(cfg["port"], cfg["secret"])
    wait_for(lambda: any(int(d["completedLength"]) > 500_000 for d in rpc.call("tellActive")), what="download")
    # closing the app it started must pause the download
    os.kill(owner_pid(env), signal.SIGTERM)
    wait_for(lambda: not aria_pids(env), timeout=15, what="engine gone")
    assert "pause=true" in env.session.read_text()


def test_cli_add_ls_pause_resume_rm(env, server):
    eng = Engine(config.load())
    eng.start()
    try:
        r = run_cli(env, "add", server.url(), "-o", "one.bin")
        assert r.returncode == 0, r.stderr
        gid = r.stdout.split()[0]
        wait_for(lambda: "one.bin" in run_cli(env, "ls").stdout, what="ls row")
        assert run_cli(env, "pause", gid[:6]).returncode == 0
        assert "paused" in run_cli(env, "ls").stdout
        assert run_cli(env, "resume", "all").returncode == 0
        wait_for(lambda: "downloading" in run_cli(env, "ls").stdout, what="resumed")
        assert run_cli(env, "rm", gid[:6]).returncode == 0
        wait_for(lambda: "one.bin" not in run_cli(env, "ls").stdout, what="removed")
        assert run_cli(env, "limit", "1M").returncode == 0
        assert json.loads((env.cfg_dir / "config.json").read_text())["limit"] == "1M"
    finally:
        eng.stop()


def test_cli_says_how_to_start_when_closed(env):
    r = run_cli(env, "ls")
    assert r.returncode != 0 and "Open it with: grab" in (r.stderr + r.stdout)


def test_host_rejects_dangerous_links_and_folders_but_accepts_home_folders(env, server, tmp_path):
    eng = Engine(config.load())
    eng.start()
    try:
        for bad in ("file:///etc/passwd", "javascript:alert(1)", "chrome://settings", "data:text/plain,hi"):
            reply = host_call(env, {"op": "add", "items": [{"url": bad}]})
            assert reply["ok"] is False and reply["code"] == "bad_request", bad
        environ = dict(env.environ, HOME=str(tmp_path))
        outside = host_call(env, {"op": "add", "items": [{"url": server.url()}], "dir": "/etc"}, environ)
        assert outside["ok"] is False and "home" in outside["error"]
        relative = host_call(env, {"op": "add", "items": [{"url": server.url()}], "dir": "../x"}, environ)
        assert relative["ok"] is False
        assert host_call(env, {"op": "add", "items": []}, environ)["ok"] is False
        inside = host_call(
            env,
            {"op": "add", "items": [{"url": server.url(), "out": "../../evil.bin"}], "dir": str(tmp_path / "chosen")},
            environ,
        )
        assert inside["ok"], inside
        wait_for(
            lambda: (
                (tmp_path / "chosen" / ".._.._evil.bin").exists()
                or any(f.name.endswith("evil.bin") for f in (tmp_path / "chosen").glob("*"))
            ),
            what="file in chosen folder",
        )
        assert not (tmp_path / "evil.bin").exists(), "file name must not escape the folder"
    finally:
        eng.stop()


def test_host_status_reports_running_and_closed(env):
    assert host_call(env, {"op": "status"}) == {"ok": True, "running": False}
    eng = Engine(config.load())
    eng.start()
    try:
        reply = host_call(env, {"op": "status"})
        assert reply["running"] is True and reply["active"] == 0 and reply["dir"] == str(env.dl)
    finally:
        eng.stop()
