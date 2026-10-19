"""Chrome native-messaging host: the extension talks to the engine through this."""

import json
import struct
import sys
from pathlib import Path

from . import config
from .launcher import NotRunning, ensure_engine
from .model import uri_options
from .rpc import Rpc, RpcDown, RpcError

SCHEMES = ("http://", "https://", "ftp://", "ftps://", "magnet:")
MAX_ITEMS = 500


def read_message():
    raw = sys.stdin.buffer.read(4)
    if len(raw) < 4:
        return None
    (length,) = struct.unpack("=I", raw)
    return json.loads(sys.stdin.buffer.read(length))


def write_message(obj) -> None:
    data = json.dumps(obj).encode()
    sys.stdout.buffer.write(struct.pack("=I", len(data)) + data)
    sys.stdout.buffer.flush()


def fail(code: str, error: str) -> dict:
    return {"ok": False, "code": code, "error": error}


def safe_dir(raw: str, cfg: dict) -> str | None:
    """Only folders inside the user's home are accepted from a browser message."""
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError("folder must be an absolute path")
    path = path.resolve()
    if Path.home().resolve() not in (path, *path.parents):
        raise ValueError("folder must be inside your home directory")
    return str(path)


def handle(msg: dict) -> dict:
    cfg = config.load()
    op = msg.get("op")
    if op == "ping":
        return {"ok": True}
    if op == "status":
        rpc = Rpc(cfg["port"], cfg["secret"])
        try:
            stat = rpc.call("getGlobalStat", timeout=2)
        except (RpcDown, RpcError):
            return {"ok": True, "running": False}
        return {
            "ok": True,
            "running": True,
            "active": int(stat["numActive"]),
            "waiting": int(stat["numWaiting"]),
            "speed": int(stat["downloadSpeed"]),
            "dir": cfg["dir"],
        }
    if op == "add":
        items = msg.get("items")
        if not isinstance(items, list) or not items or len(items) > MAX_ITEMS:
            return fail("bad_request", f"send between 1 and {MAX_ITEMS} links")
        for item in items:
            url = str(item.get("url", ""))
            if not url.lower().startswith(SCHEMES):
                return fail("bad_request", f"unsupported link: {url[:60]}")
        try:
            folder = safe_dir(msg.get("dir", ""), cfg)
        except ValueError as e:
            return fail("bad_request", str(e))
        try:
            rpc = ensure_engine(cfg)
        except NotRunning as e:
            return fail("not_running", str(e))
        gids = []
        for item in items:
            if folder:
                item = dict(item, dir=folder)
            gids.append(rpc.call("addUri", [item["url"]], uri_options(item, cfg)))
        return {"ok": True, "gids": gids}
    return fail("bad_request", "unknown op")


def main() -> None:
    while (msg := read_message()) is not None:
        try:
            write_message(handle(msg))
        except (RpcDown, RpcError) as e:
            write_message(fail("engine", str(e)))
        except Exception as e:
            write_message(fail("internal", str(e)))


if __name__ == "__main__":
    main()
