"""Shared view helpers: how a download looks, and how a request becomes aria2 options."""

import os
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse

KEYS = [
    "gid",
    "status",
    "totalLength",
    "completedLength",
    "downloadSpeed",
    "files",
    "bittorrent",
    "errorCode",
    "errorMessage",
    "dir",
    "connections",
]


def snapshot(rpc):
    active = rpc.call("tellActive", KEYS)
    waiting = rpc.call("tellWaiting", 0, 1000, KEYS)
    stopped = rpc.call("tellStopped", 0, 500, KEYS)
    return active + waiting + stopped, rpc.call("getGlobalStat")


def name_of(d: dict) -> str:
    bt = (d.get("bittorrent") or {}).get("info", {}).get("name")
    if bt:
        return bt
    files = d.get("files") or []
    if files:
        path = files[0].get("path") or ""
        if path:
            return PurePosixPath(path).name
        uris = files[0].get("uris") or []
        if uris:
            uri = uris[0]["uri"]
            return unquote(PurePosixPath(urlparse(uri).path).name) or uri
    return d["gid"]


def on_disk(d: dict) -> int:
    """Bytes already on disk for a download the engine has not started yet."""
    files = d.get("files") or []
    try:
        return os.path.getsize(files[0]["path"]) if files and files[0].get("path") else 0
    except OSError:
        return 0


def size_label(d: dict) -> str:
    if int(d["totalLength"]):
        return fmt_size(d["totalLength"])
    partial = on_disk(d)
    return f"≥{fmt_size(partial)}" if partial else "?"


def fmt_size(n) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def fmt_speed(n) -> str:
    return "-" if int(n) == 0 else fmt_size(n) + "/s"


def fraction(d: dict) -> float:
    total = int(d["totalLength"])
    return int(d["completedLength"]) / total if total else 0.0


def eta(d: dict) -> str:
    speed = int(d["downloadSpeed"])
    left = int(d["totalLength"]) - int(d["completedLength"])
    if d["status"] != "active" or speed == 0 or left <= 0:
        return "-"
    s = left // speed
    if s >= 3600:
        return f"{s // 3600}h{(s % 3600) // 60:02d}m"
    return f"{s // 60}m{s % 60:02d}s" if s >= 60 else f"{s}s"


STATUS = {
    "active": ("●", "downloading", "green"),
    "waiting": ("◌", "queued", "dim"),
    "paused": ("⏸", "paused", "yellow"),
    "complete": ("✓", "done", "cyan"),
    "error": ("✗", "error", "red"),
    "removed": ("-", "removed", "dim"),
}


def status_of(d: dict):
    return STATUS.get(d["status"], ("?", d["status"], "white"))


def safe_name(name: str) -> str:
    return name.replace("/", "_").replace("\\", "_").strip().lstrip(".")


def uri_options(item: dict, cfg: dict) -> dict:
    """Turn an extension/CLI item into aria2 addUri options."""
    opts = {"dir": item.get("dir") or cfg["dir"]}
    if item.get("out"):
        opts["out"] = safe_name(item["out"])
    if item.get("connections"):
        opts["split"] = str(item["connections"])
        opts["max-connection-per-server"] = str(min(int(item["connections"]), 16))
    if item.get("paused"):
        opts["pause"] = "true"
    if item["url"].startswith("magnet:"):
        return opts
    headers = list(item.get("headers") or [])
    if item.get("cookie"):
        headers.append("Cookie: " + item["cookie"])
    if headers:
        opts["header"] = headers
    if item.get("referer"):
        opts["referer"] = item["referer"]
    if item.get("ua"):
        opts["user-agent"] = item["ua"]
    return opts


def url_of(d: dict) -> str:
    files = d.get("files") or []
    uris = files[0].get("uris") if files else None
    return uris[0]["uri"] if uris else ""


def path_of(d: dict) -> str:
    files = d.get("files") or []
    return files[0].get("path", "") if files else ""


def partial_paths(d: dict) -> list[str]:
    path = path_of(d)
    return [path, path + ".aria2"] if path else []


def as_dict(d: dict) -> dict:
    """Plain, stable shape for --json output."""
    return {
        "gid": d["gid"],
        "status": d["status"],
        "name": name_of(d),
        "url": url_of(d),
        "dir": d.get("dir", ""),
        "path": path_of(d),
        "total": int(d["totalLength"]),
        "done": int(d["completedLength"]),
        "speed": int(d["downloadSpeed"]),
        "error": d.get("errorMessage", "") if d["status"] == "error" else "",
    }
