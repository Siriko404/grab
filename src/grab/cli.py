import argparse
import json
import os
import signal
import sys
import threading
from pathlib import Path

from rich.console import Console
from rich.table import Table

from . import __version__, config, desktop, integrate, ops
from .engine import Engine, EngineError
from .launcher import NotRunning, ensure_engine, focus_window, launch_argv
from .model import as_dict, fmt_speed, fraction, name_of, path_of, size_label, snapshot, status_of, uri_options
from .rpc import Rpc, RpcDown, RpcError

# exit codes: 0 ok, 1 failed, 2 bad usage, 3 Grab is not running
EXIT_DOWN = 3
NOT_RUNNING = "Grab is not running, so nothing is downloading (downloads pause when it closes).\nOpen it with: grab"


def _rpc(required: bool = True) -> Rpc | None:
    cfg = config.load()
    rpc = Rpc(cfg["port"], cfg["secret"])
    if rpc.alive():
        return rpc
    if required:
        print(NOT_RUNNING, file=sys.stderr)
        sys.exit(EXIT_DOWN)
    return None


def _find(rpc: Rpc, prefix: str) -> dict:
    items, _ = snapshot(rpc)
    hits = [d for d in items if d["gid"].startswith(prefix)]
    if len(hits) != 1:
        sys.exit(f"{'No' if not hits else 'Ambiguous'} download matches '{prefix}'. See: grab ls")
    return hits[0]


def cmd_tui(_args) -> None:
    from .tui import GrabApp

    engine = Engine()
    try:
        engine.start()
    except EngineError as e:
        if "already running" in str(e) and not os.environ.get("GRAB_NO_LAUNCH") and focus_window():
            sys.exit(0)
        print(e)
        sys.exit(1)
    try:
        GrabApp(engine).run()
    finally:
        engine.stop()


def cmd_launch(_args) -> None:
    argv = launch_argv()
    if argv is None:
        sys.exit("No terminal launcher found (omarchy-launch-or-focus-tui or xdg-terminal-exec). Run: grab")
    os.execvp(argv[0], argv)


def cmd_setup(args) -> None:
    if args.remove:
        for path in integrate.remove_user(Path.home()):
            print("removed", path)
        return
    integrate.main(["--user"])


def cmd_serve(_args) -> None:
    engine = Engine()
    try:
        engine.start()
    except EngineError as e:
        sys.exit(str(e))
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: stop.set())
    print("grab engine running", flush=True)
    stop.wait()
    engine.stop()


def cmd_add(args) -> None:
    urls = list(args.urls)
    if args.input:
        text = sys.stdin.read() if args.input == "-" else Path(args.input).read_text()
        urls += [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    if not urls:
        sys.exit("Give at least one URL, or -i FILE.")
    cfg = config.load()
    try:
        rpc = ensure_engine(cfg)
    except NotRunning as e:
        print(e, file=sys.stderr)
        sys.exit(EXIT_DOWN)
    for url in urls:
        item = {
            "url": url,
            "dir": args.dir,
            "out": args.out if len(urls) == 1 else None,
            "connections": args.connections,
            "headers": args.header,
            "referer": args.referer,
            "paused": args.paused,
        }
        print(rpc.call("addUri", [url], uri_options(item, cfg)), url)


def _row_filter(args, items: list) -> list:
    keep = []
    for d in items:
        if d["status"] == "removed":
            continue
        if args.status:
            if d["status"] != args.status and not (args.status == "paused" and d["status"] == "waiting"):
                continue
        elif d["status"] == "complete" and not args.all:
            continue
        keep.append(d)
    return keep


def cmd_ls(args) -> None:
    items, stat = snapshot(_rpc())
    items = _row_filter(args, items)
    if args.json:
        print(json.dumps([as_dict(d) for d in items], indent=2))
        return
    table = Table(box=None, pad_edge=False, header_style="dim")
    for col, just in (
        ("ID", "left"),
        ("STATUS", "left"),
        ("DONE", "right"),
        ("SIZE", "right"),
        ("SPEED", "right"),
        ("NAME", "left"),
    ):
        table.add_column(col, justify=just, no_wrap=col != "NAME", overflow="ellipsis")
    for d in items:
        glyph, label, style = status_of(d)
        table.add_row(
            d["gid"][:6],
            f"[{style}]{glyph} {label}[/]",
            f"{fraction(d) * 100:.0f}%",
            size_label(d),
            fmt_speed(d["downloadSpeed"]),
            name_of(d),
        )
    console = Console()
    console.print(table if items else "[dim]nothing here[/]")
    console.print(
        f"[dim]{stat['numActive']} active · {stat['numWaiting']} waiting · "
        f"{stat['numStopped']} finished · ▼ {fmt_speed(stat['downloadSpeed'])}[/]"
    )


def cmd_status(_args) -> None:
    rpc = _rpc(required=False)
    if rpc is None:
        print("stopped")
        sys.exit(EXIT_DOWN)
    stat = rpc.call("getGlobalStat")
    print(f"running · {stat['numActive']} active · {stat['numWaiting']} waiting · ▼ {fmt_speed(stat['downloadSpeed'])}")


def _each(args, fn, bulk_name: str | None) -> None:
    rpc = _rpc()
    if args.gids == ["all"] and bulk_name:
        rpc.call(bulk_name)
        return
    for g in args.gids:
        d = _find(rpc, g)
        try:
            fn(rpc, d)
        except RpcError as e:
            print(f"{d['gid'][:6]}: {e}")


def cmd_pause(args) -> None:
    _each(args, lambda r, d: r.call("forcePause", d["gid"]), "forcePauseAll")


def cmd_resume(args) -> None:
    _each(args, lambda r, d: r.call("unpause", d["gid"]), "unpauseAll")


def cmd_rm(args) -> None:
    def one(rpc, d):
        gone = ops.remove(rpc, d, delete_partial=args.delete)
        for path in gone:
            print("deleted", path)
        if args.delete and d["status"] == "complete":
            print(f"{d['gid'][:6]}: finished file kept (--delete only removes unfinished data)")

    _each(args, one, None)


def cmd_retry(args) -> None:
    def one(rpc, d):
        if d["status"] != "error":
            sys.exit(f"{d['gid'][:6]} is {d['status']}, not failed.")
        print(ops.retry(rpc, d))

    _each(args, one, None)


def cmd_open(args) -> None:
    d = _find(_rpc(), args.gid)
    target = d["dir"] if args.folder else path_of(d)
    if not target:
        sys.exit("No file yet for that download.")
    desktop.open_path(target)


def cmd_clear(_args) -> None:
    _rpc().call("purgeDownloadResult")


def cmd_config(args) -> None:
    cfg = config.load()
    if args.action == "set":
        if not (args.key and args.value is not None):
            sys.exit("Usage: grab config set KEY VALUE")
        try:
            value = ops.apply_setting(_rpc(required=False), args.key, args.value)
        except ValueError as e:
            sys.exit(f"Invalid: {e}")
        print(f"{args.key} = {value}")
    elif args.key:
        if args.key not in config.SETTINGS:
            sys.exit(f"Unknown setting '{args.key}'.")
        print(cfg[args.key])
    else:
        for k in config.SETTINGS:
            print(f"{k} = {cfg[k]}")


def cmd_limit(args) -> None:
    cmd_config(argparse.Namespace(action="set", key="limit", value=args.speed))


def main(argv=None) -> None:
    p = argparse.ArgumentParser(
        prog="grab",
        description="Lean download manager. With no command it opens the app.",
        epilog="exit codes: 0 ok, 1 failed, 2 bad usage, 3 Grab is not running",
    )
    sub = p.add_subparsers(dest="cmd", metavar="command")
    p.add_argument("--version", action="version", version=f"grab {__version__}")
    sub.add_parser("launch", help="open the app in a terminal window (focuses it if already open)").set_defaults(
        fn=cmd_launch
    )
    st = sub.add_parser("setup", help="register the browser host, launcher entry and unpacked extension for this user")
    st.add_argument("--remove", action="store_true", help="undo setup")
    st.set_defaults(fn=cmd_setup)
    sub.add_parser("serve", help="run the engine without the TUI (Ctrl-C pauses and exits)").set_defaults(fn=cmd_serve)
    a = sub.add_parser("add", help="add downloads (opens the app if it is closed)")
    a.add_argument("urls", nargs="*")
    a.add_argument("-i", "--input", metavar="FILE", help="file with one URL per line ('-' for stdin)")
    a.add_argument("-d", "--dir")
    a.add_argument("-o", "--out", help="file name (single URL only)")
    a.add_argument("-c", "--connections", type=int)
    a.add_argument("--header", action="append", default=[], metavar="'Name: value'")
    a.add_argument("--referer")
    a.add_argument("--paused", action="store_true", help="queue without starting")
    a.set_defaults(fn=cmd_add)
    ls = sub.add_parser("ls", help="list downloads")
    ls.add_argument("-a", "--all", action="store_true", help="include finished")
    ls.add_argument("-s", "--status", choices=["active", "paused", "complete", "error"])
    ls.add_argument("--json", action="store_true", help="machine-readable output")
    ls.set_defaults(fn=cmd_ls)
    sub.add_parser("status", help="one-line engine summary (exit 3 if stopped)").set_defaults(fn=cmd_status)
    for name, fn, helptext in (("pause", cmd_pause, "pause downloads"), ("resume", cmd_resume, "resume downloads")):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("gids", nargs="+", metavar="GID|all")
        s.set_defaults(fn=fn)
    rm = sub.add_parser("rm", help="remove downloads from the list")
    rm.add_argument("gids", nargs="+", metavar="GID")
    rm.add_argument("--delete", action="store_true", help="also delete the unfinished file and its control file")
    rm.set_defaults(fn=cmd_rm)
    rt = sub.add_parser("retry", help="re-add failed downloads")
    rt.add_argument("gids", nargs="+", metavar="GID")
    rt.set_defaults(fn=cmd_retry)
    op = sub.add_parser("open", help="open a download's file (or folder) with the desktop default")
    op.add_argument("gid")
    op.add_argument("--folder", action="store_true")
    op.set_defaults(fn=cmd_open)
    sub.add_parser("clear", help="forget finished downloads").set_defaults(fn=cmd_clear)
    cf = sub.add_parser("config", help="show or change settings: dir, concurrent, connections, limit")
    cf.add_argument("action", nargs="?", choices=["get", "set"], default="get")
    cf.add_argument("key", nargs="?")
    cf.add_argument("value", nargs="?")
    cf.set_defaults(fn=cmd_config)
    lim = sub.add_parser("limit", help="shortcut for: config set limit SPEED (2M, 500K, 0 = none)")
    lim.add_argument("speed")
    lim.set_defaults(fn=cmd_limit)
    args = p.parse_args(argv)
    try:
        (args.fn if args.cmd else cmd_tui)(args)
    except RpcDown:
        print(NOT_RUNNING, file=sys.stderr)
        sys.exit(EXIT_DOWN)
    except RpcError as e:
        sys.exit(f"Engine error: {e}")


if __name__ == "__main__":
    main()
