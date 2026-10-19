"""Actions shared by the TUI and the CLI."""

import contextlib
import os

from . import config
from .model import partial_paths, path_of
from .rpc import Rpc, RpcError

LIVE_OPTIONS = {
    "dir": lambda v: {"dir": v},
    "concurrent": lambda v: {"max-concurrent-downloads": str(v)},
    "connections": lambda v: {"split": str(v), "max-connection-per-server": str(v)},
    "limit": lambda v: {"max-overall-download-limit": v},
}


def remove(rpc: Rpc, d: dict, delete_partial: bool = False) -> list[str]:
    """Drop a download from the list; optionally delete its unfinished files. Returns deleted paths."""
    victims = partial_paths(d) if delete_partial and d["status"] != "complete" else []
    if d["status"] in ("active", "waiting", "paused"):
        with contextlib.suppress(RpcError):
            rpc.call("forceRemove", d["gid"])
    with contextlib.suppress(RpcError):
        rpc.call("removeDownloadResult", d["gid"])
    gone = []
    for path in victims:
        if os.path.isabs(path) and os.path.isfile(path):
            os.remove(path)
            gone.append(path)
    return gone


def retry(rpc: Rpc, d: dict) -> str:
    """Re-add a failed download with the same sources, folder and name."""
    uris = list(dict.fromkeys(u["uri"] for u in d["files"][0].get("uris", [])))
    if not uris:
        raise RpcError("nothing to retry: no source URL recorded")
    opts = {"dir": d["dir"]}
    if path_of(d):
        opts["out"] = os.path.basename(path_of(d))
    gid = rpc.call("addUri", uris, opts)
    rpc.call("removeDownloadResult", d["gid"])
    return gid


def apply_setting(rpc: Rpc | None, key: str, raw: str):
    """Validate, persist, and apply to a running engine."""
    value = config.coerce(key, raw)
    cfg = config.load()
    cfg[key] = value
    config.save(cfg)
    if rpc is not None:
        rpc.call("changeGlobalOption", LIVE_OPTIONS[key](value))
    return value
