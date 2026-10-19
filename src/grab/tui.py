import asyncio
import os
import signal

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Input, Label, Static, TextArea

from . import config, desktop, ops
from .model import (
    eta,
    fmt_size,
    fmt_speed,
    fraction,
    name_of,
    partial_paths,
    path_of,
    size_label,
    snapshot,
    status_of,
    url_of,
)
from .rpc import RpcDown, RpcError

TABS = [
    ("1", "All", None),
    ("2", "Active", ("active", "waiting")),
    ("3", "Paused", ("paused",)),
    ("4", "Done", ("complete",)),
    ("5", "Error", ("error",)),
]

# (column key, fixed width or None for the flexible name column), picked by how wide the tile is
LAYOUTS = {
    "wide": [("name", None), ("size", 9), ("progress", 17), ("speed", 10), ("eta", 7), ("status", 13)],
    "mid": [("name", None), ("progress", 14), ("speed", 10), ("status", 12)],
    "narrow": [("name", None), ("progress", 5), ("status", 2)],
}
HEADERS = {"name": "Name", "size": "Size", "progress": "Progress", "speed": "Speed", "eta": "ETA", "status": "Status"}
NARROW_HEADERS = {"progress": "Done", "status": ""}


def tier(width: int) -> str:
    return "wide" if width >= 100 else "mid" if width >= 68 else "narrow"


def bar(frac: float, width: int) -> Text:
    full = round(frac * width)
    t = Text()
    t.append("█" * full, style="green")
    t.append("░" * (width - full), style="bright_black")
    t.append(f" {frac * 100:3.0f}%")
    return t


def cell(d: dict, key: str, width: int) -> Text | str:
    if key == "name":
        return name_of(d)
    if key == "size":
        return size_label(d)
    if key == "progress":
        return bar(fraction(d), width - 5) if width >= 12 else Text(f"{fraction(d) * 100:3.0f}%")
    if key == "speed":
        return fmt_speed(d["downloadSpeed"])
    if key == "eta":
        return eta(d)
    glyph, label, style = status_of(d)
    return Text(glyph if width <= 2 else f"{glyph} {label}", style=style)


class TextPrompt(ModalScreen):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, heading: str, value: str = ""):
        super().__init__()
        self.heading, self.value = heading, value

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.heading)
            yield Input(value=self.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())

    def action_cancel(self) -> None:
        self.dismiss(None)


class AddScreen(ModalScreen):
    BINDINGS = [Binding("escape", "cancel", "Cancel"), Binding("ctrl+s", "submit", "Add", priority=True)]

    def __init__(self, links: str, default_dir: str):
        super().__init__()
        self.links, self.default_dir = links, default_dir

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Links, one per line")
            yield TextArea(self.links, id="links", tab_behavior="focus")
            yield Label("Save to (empty = default)")
            yield Input(placeholder=self.default_dir, id="where")
            yield Label("Ctrl+S or Enter in the folder box adds · Esc cancels", classes="hint")

    def on_mount(self) -> None:
        self.query_one("#links", TextArea).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.action_submit()

    def action_submit(self) -> None:
        links = [ln.strip() for ln in self.query_one("#links", TextArea).text.splitlines() if ln.strip()]
        self.dismiss((links, self.query_one("#where", Input).value.strip()) if links else None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmRemove(ModalScreen):
    BINDINGS = [
        Binding("y", "answer('list')", "Remove"),
        Binding("d", "answer('delete')", "Remove + delete"),
        Binding("n,escape", "answer('no')", "Cancel"),
    ]

    def __init__(self, name: str):
        super().__init__()
        self.name_text = name

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(f"Remove “{self.name_text}”?")
            yield Label("y  remove from list     d  also delete the partial file     n  cancel", classes="hint")

    def action_answer(self, what: str) -> None:
        self.dismiss(what)


class Help(ModalScreen):
    BINDINGS = [Binding("escape,question_mark,q", "close", "Close")]

    def compose(self) -> ComposeResult:
        rows = [
            "a  add links              space  pause / resume       enter / i  details",
            "p  pause all              r  resume all               R  retry failed",
            "x  remove                 c  clear finished           l  speed limit",
            "o  open file              O  open folder              y  copy link",
            "J / K  move in queue      1-5  filter tabs            /  search (esc clears)",
            "?  this help              q  quit (pauses everything)",
        ]
        with Vertical(classes="dialog"):
            yield Label("Grab")
            for r in rows:
                yield Label(r)

    def action_close(self) -> None:
        self.dismiss(None)


class GrabApp(App):
    TITLE = "Grab"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen { background: ansi_default; color: ansi_default; }
    #head { height: 1; padding: 0 1; text-style: bold; }
    #tabs { height: 1; padding: 0 1; color: ansi_bright_black; }
    #empty { padding: 1 2; color: ansi_bright_black; }
    DataTable { height: 1fr; background: ansi_default; color: ansi_default; }
    DataTable > .datatable--header { background: ansi_default; color: ansi_bright_black; text-style: bold; }
    DataTable > .datatable--cursor { background: ansi_blue; color: ansi_white; }
    DataTable > .datatable--even-row { background: ansi_default; }
    DataTable > .datatable--odd-row { background: ansi_default; }
    #detail { display: none; height: auto; max-height: 10; padding: 0 1; border-top: solid ansi_bright_black; }
    Footer { background: ansi_default; color: ansi_bright_black; }
    ModalScreen { align: center middle; background: ansi_default 60%; }
    .dialog { width: 90%; max-width: 84; height: auto; padding: 1 2; border: round ansi_cyan; background: ansi_default; }
    .dialog TextArea { height: 6; }
    .hint { color: ansi_bright_black; }
    """
    BINDINGS = [
        Binding("a", "add", "Add"),
        Binding("space", "toggle", "Pause"),
        Binding("i", "details", "Details"),
        Binding("x", "remove", "Remove"),
        Binding("slash", "search", "Search"),
        Binding("question_mark", "help", "Help"),
        Binding("q", "quit", "Quit"),
        Binding("p", "pause_all", "Pause all", show=False),
        Binding("r", "resume_all", "Resume all", show=False),
        Binding("R", "retry", "Retry", show=False),
        Binding("c", "clear", "Clear done", show=False),
        Binding("l", "limit", "Limit", show=False),
        Binding("o", "open_file", "Open", show=False),
        Binding("O", "open_folder", "Folder", show=False),
        Binding("y", "copy_url", "Copy link", show=False),
        Binding("J", "queue_down", "Queue down", show=False),
        Binding("K", "queue_up", "Queue up", show=False),
        Binding("escape", "clear_search", "Clear search", show=False),
        *[Binding(k, f"tab('{k}')", name, show=False) for k, name, _ in TABS],
    ]

    def __init__(self, engine):
        super().__init__(ansi_color=True)
        self.engine = engine
        self.rpc = engine.rpc
        self.items: dict[str, dict] = {}  # latest snapshot by gid
        self.order: list[str] = []  # gids currently shown
        self.stat: dict = {}
        self.tab = "1"
        self.query = ""
        self.detail_open = False
        self._busy = False
        self._layout_key: tuple | None = None
        self._prev: dict[str, str] = {}
        self.detail_plain = ""

    # ----- layout
    def compose(self) -> ComposeResult:
        yield Static("", id="head")
        yield Static("", id="tabs")
        yield Static("", id="empty")
        yield DataTable(cursor_type="row")
        yield Static("", id="detail")
        yield Footer()

    def on_mount(self) -> None:
        if "textual-ansi" in self.available_themes:
            self.theme = "textual-ansi"
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGHUP):
            loop.add_signal_handler(sig, self.exit)
        self.set_interval(1.0, self.refresh_data)
        self.run_worker(self.refresh_data())

    def on_resize(self, event) -> None:
        self.render_table(force=True)

    # ----- data
    async def refresh_data(self) -> None:
        if self._busy:
            return
        self._busy = True
        try:
            items, stat = await asyncio.to_thread(snapshot, self.rpc)
        except (RpcDown, RpcError) as e:
            self.query_one("#head", Static).update(f"Engine unreachable: {e}")
            return
        finally:
            self._busy = False
        self.stat = stat
        self.items = {d["gid"]: d for d in items if d["status"] != "removed"}
        self.announce_changes()
        self.render_table()

    def announce_changes(self) -> None:
        for gid, d in self.items.items():
            before, now = self._prev.get(gid), d["status"]
            if before in ("active", "waiting") and now == "complete":
                desktop.notify("Download finished", name_of(d))
            elif before in ("active", "waiting") and now == "error":
                desktop.notify("Download failed", f"{name_of(d)}: {d.get('errorMessage', '')}")
            self._prev[gid] = now

    def matches(self, d: dict) -> bool:
        wanted = next(s for k, _, s in TABS if k == self.tab)
        if wanted and d["status"] not in wanted:
            return False
        return not self.query or self.query in (name_of(d) + " " + url_of(d)).lower()

    # ----- drawing
    def columns(self) -> list[tuple[str, int]]:
        width = self.size.width
        spec = LAYOUTS[tier(width)]
        fixed = sum(w for _, w in spec if w)
        flex = max(12, width - fixed - 2 * len(spec) - 3)
        return [(k, w or flex) for k, w in spec]

    def render_table(self, force: bool = False) -> None:
        table = self.query_one(DataTable)
        cols = self.columns()
        shown = [gid for gid, d in self.items.items() if self.matches(d)]
        key = (tuple(cols), self.tab, self.query)
        keep = self.selected()
        if force or key != self._layout_key or shown != self.order:
            table.clear(columns=True)
            narrow = tier(self.size.width) == "narrow"
            for k, w in cols:
                table.add_column(NARROW_HEADERS.get(k, HEADERS[k]) if narrow else HEADERS[k], width=w, key=k)
            for gid in shown:
                table.add_row(*(cell(self.items[gid], k, w) for k, w in cols), key=gid)
            self._layout_key, self.order = key, shown
            if keep in shown:
                table.move_cursor(row=shown.index(keep))
        else:
            for gid in shown:
                for k, w in cols:
                    table.update_cell(gid, k, cell(self.items[gid], k, w), update_width=False)
        self.query_one("#empty", Static).display = not shown
        self.query_one("#empty", Static).update(
            "Nothing matches."
            if self.items
            else "Nothing here yet.  Press a to add links, or send them from the browser."
        )
        table.display = bool(shown)
        self.draw_chrome()
        self.draw_detail()

    def draw_chrome(self) -> None:
        s = self.stat or {}
        narrow = self.size.width < 68
        head = f"Grab  ▼ {fmt_speed(s.get('downloadSpeed', 0))}"
        if not narrow:
            count = lambda *st: sum(1 for d in self.items.values() if d["status"] in st)  # noqa: E731
            head += (
                f"   {count('active')} active   {count('waiting', 'paused')} paused/queued   "
                f"{count('complete')} done   {count('error')} failed   → {self.engine.cfg['dir']}"
            )
        self.query_one("#head", Static).update(head)
        tabs = Text()
        for k, name, statuses in TABS:
            count = sum(1 for d in self.items.values() if not statuses or d["status"] in statuses)
            label = f"{k} {name} {count}" if not narrow else f"{k}:{count}"
            tabs.append(label + "  ", style="bold" if k == self.tab else "")
        if self.query:
            tabs.append(f"/{self.query}", style="yellow")
        self.query_one("#tabs", Static).update(tabs)

    def draw_detail(self) -> None:
        box = self.query_one("#detail", Static)
        box.display = self.detail_open
        d = self.items.get(self.selected() or "")
        if not self.detail_open or d is None:
            return
        glyph, label, _ = status_of(d)
        lines = [
            Text(name_of(d), style="bold"),
            Text(
                f"{glyph} {label}   {fmt_size(d['completedLength'])} of {size_label(d)}   "
                f"{fmt_speed(d['downloadSpeed'])}   ETA {eta(d)}"
            ),
            Text(f"link   {url_of(d) or '-'}"),
            Text(f"file   {path_of(d) or d.get('dir', '')}"),
        ]
        if d["status"] == "error":
            lines.append(Text(f"error  {d.get('errorMessage') or 'code ' + str(d.get('errorCode'))}", style="red"))
        resumable = any(p.endswith(".aria2") and os.path.exists(p) for p in partial_paths(d))
        lines.append(
            Text(
                f"resume {'saved progress on disk' if resumable else 'starts from the beginning'}"
                f"   ·   {d.get('connections', 0)} connections   ·   {d['gid'][:8]}",
                style="bright_black",
            )
        )
        text = Text("\n").join(lines)
        self.detail_plain = text.plain
        box.update(text)

    def on_data_table_row_highlighted(self, event) -> None:
        self.draw_detail()

    def on_data_table_row_selected(self, event) -> None:  # Enter on a row
        self.action_details()

    # ----- helpers
    def selected(self) -> str | None:
        table = self.query_one(DataTable)
        if not table.row_count:
            return None
        return table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value

    def current(self) -> dict | None:
        return self.items.get(self.selected() or "")

    async def rpc_do(self, *calls) -> None:
        try:
            for method, *params in calls:
                await asyncio.to_thread(self.rpc.call, method, *params)
        except (RpcDown, RpcError) as e:
            self.notify(str(e), severity="error")
        await self.refresh_data()

    def run_ops(self, fn, *args) -> None:
        async def go():
            try:
                await asyncio.to_thread(fn, self.rpc, *args)
            except (RpcDown, RpcError) as e:
                self.notify(str(e), severity="error")
            await self.refresh_data()

        self.run_worker(go())

    # ----- actions
    def action_tab(self, key: str) -> None:
        self.tab = key
        self.render_table()

    def action_search(self) -> None:
        def done(value):
            if value is not None:
                self.query = value.lower()
                self.render_table()

        self.push_screen(TextPrompt("Search by name or link:", self.query), done)

    def action_clear_search(self) -> None:
        if self.query:
            self.query = ""
            self.render_table()

    def action_details(self) -> None:
        self.detail_open = not self.detail_open
        self.draw_detail()

    def action_help(self) -> None:
        self.push_screen(Help())

    def action_add(self) -> None:
        async def open_dialog():
            clip = await asyncio.to_thread(desktop.paste_text)
            links = (
                clip.strip() if clip.strip().lower().startswith(("http://", "https://", "magnet:", "ftp://")) else ""
            )

            def done(result):
                if result:
                    links_, where = result
                    opts = {"dir": where} if where else {}
                    self.run_worker(self.rpc_do(*[("addUri", [u], dict(opts)) for u in links_]))

            self.push_screen(AddScreen(links, self.engine.cfg["dir"]), done)

        self.run_worker(open_dialog())

    def action_toggle(self) -> None:
        d = self.current()
        if d is None:
            return
        if d["status"] in ("active", "waiting"):
            self.run_worker(self.rpc_do(("forcePause", d["gid"])))
        elif d["status"] == "paused":
            self.run_worker(self.rpc_do(("unpause", d["gid"])))

    def action_pause_all(self) -> None:
        self.run_worker(self.rpc_do(("forcePauseAll",)))

    def action_resume_all(self) -> None:
        self.run_worker(self.rpc_do(("unpauseAll",)))

    def action_remove(self) -> None:
        d = self.current()
        if d is None:
            return
        if d["status"] in ("complete", "error"):
            self.run_ops(ops.remove, d, False)
            return

        def done(answer):
            if answer in ("list", "delete"):
                self.run_ops(ops.remove, d, answer == "delete")

        self.push_screen(ConfirmRemove(name_of(d)), done)

    def action_retry(self) -> None:
        d = self.current()
        if d is not None and d["status"] == "error":
            self.run_ops(ops.retry, d)

    def action_clear(self) -> None:
        self.run_worker(self.rpc_do(("purgeDownloadResult",)))

    def action_limit(self) -> None:
        def done(value):
            if value:
                try:
                    ops.apply_setting(self.rpc, "limit", value)
                    self.engine.cfg["limit"] = config.coerce("limit", value)
                except (ValueError, RpcError, RpcDown) as e:
                    self.notify(str(e), severity="error")

        self.push_screen(TextPrompt("Overall speed limit (2M, 500K, 0 = none):", str(self.engine.cfg["limit"])), done)

    def action_open_file(self) -> None:
        d = self.current()
        if d and path_of(d):
            desktop.open_path(path_of(d))

    def action_open_folder(self) -> None:
        d = self.current()
        if d:
            desktop.open_path(d.get("dir", ""))

    def action_copy_url(self) -> None:
        d = self.current()
        if d and url_of(d):
            desktop.copy_text(url_of(d))
            self.notify("Link copied")

    def _move(self, offset: int) -> None:
        d = self.current()
        if d is not None and d["status"] in ("waiting", "paused"):
            self.run_worker(self.rpc_do(("changePosition", d["gid"], offset, "POS_CUR")))

    def action_queue_up(self) -> None:
        self._move(-1)

    def action_queue_down(self) -> None:
        self._move(1)
