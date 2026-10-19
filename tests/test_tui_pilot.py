import asyncio
import time

from textual.widgets import DataTable, TextArea

from grab import config
from grab.engine import Engine
from grab.tui import GrabApp


def run(coro):
    asyncio.run(coro)


async def until(pilot, fn, timeout=20.0, what="condition"):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if fn():
            return
        await pilot.pause(0.2)
    raise AssertionError(f"timed out waiting for {what}")


def names(app):
    table = app.query_one(DataTable)
    return [str(table.get_row(k)[0]) for k in app.order]


def headers(app):
    return [c.label.plain for c in app.query_one(DataTable).columns.values()]


def add(eng, url, **opts):
    return eng.rpc.call("addUri", [url], opts)


def test_columns_follow_the_tile_width(env, server):
    eng = Engine(config.load())
    eng.start()

    async def scenario():
        app = GrabApp(eng)
        async with app.run_test(size=(130, 25)) as pilot:
            add(eng, server.url(), dir=str(env.dl), out="a.bin")
            await until(pilot, lambda: names(app) == ["a.bin"], what="row")
            assert headers(app) == ["Name", "Size", "Progress", "Speed", "ETA", "Status"]
            await pilot.resize_terminal(80, 25)
            await until(pilot, lambda: headers(app) == ["Name", "Progress", "Speed", "Status"], what="mid layout")
            await pilot.resize_terminal(60, 20)
            await until(pilot, lambda: headers(app) == ["Name", "Done", ""], what="narrow layout")
            assert names(app) == ["a.bin"], "rows survive a re-layout"

    try:
        run(scenario())
    finally:
        eng.stop()


def test_tabs_search_and_details(env, server):
    eng = Engine(config.load())
    eng.start()

    async def scenario():
        app = GrabApp(eng)
        async with app.run_test(size=(120, 30)) as pilot:
            add(eng, server.url(), dir=str(env.dl), out="run.bin")
            add(eng, server.url("/big.bin?x"), dir=str(env.dl), out="held.bin", pause="true")
            add(eng, server.url("/missing"), dir=str(env.dl), out="bad.bin")
            await until(
                pilot,
                lambda: (
                    sorted(names(app)) == ["bad.bin", "held.bin", "run.bin"]
                    and app.items[app.order[0]]["status"] != "waiting"
                ),
                what="three rows",
            )
            await until(pilot, lambda: any(d["status"] == "error" for d in app.items.values()), what="error row")
            await pilot.press("3")
            await until(pilot, lambda: names(app) == ["held.bin"], what="Paused tab")
            await pilot.press("5")
            await until(pilot, lambda: names(app) == ["bad.bin"], what="Error tab")
            await pilot.press("i")
            await until(pilot, lambda: "Resource not found" in app.detail_plain, what="error text in details")
            assert "/missing" in app.detail_plain and "bad.bin" in app.detail_plain
            await pilot.press("i")
            assert app.query_one("#detail").display is False
            await pilot.press("1")
            await pilot.press("slash")
            for ch in "held":
                await pilot.press(ch)
            await pilot.press("enter")
            await until(pilot, lambda: names(app) == ["held.bin"], what="search")
            await pilot.press("escape")
            await until(pilot, lambda: len(names(app)) == 3, what="search cleared")

    try:
        run(scenario())
    finally:
        eng.stop()


def test_pause_resume_and_queue_order(env, server):
    eng = Engine(config.load())
    eng.start()

    async def scenario():
        app = GrabApp(eng)
        async with app.run_test(size=(120, 30)) as pilot:
            add(eng, server.url("/big.bin?a"), dir=str(env.dl), out="a.bin", pause="true")
            add(eng, server.url("/big.bin?b"), dir=str(env.dl), out="b.bin", pause="true")
            await until(pilot, lambda: names(app) == ["a.bin", "b.bin"], what="two paused")
            await pilot.press("J")  # move a.bin down the queue
            await until(pilot, lambda: names(app) == ["b.bin", "a.bin"], what="reorder")
            await pilot.press("space")  # cursor is on b.bin: resume it
            await until(pilot, lambda: app.items[app.order[0]]["status"] == "active", what="resumed")
            await pilot.press("space")
            await until(pilot, lambda: app.items[app.order[0]]["status"] == "paused", what="paused again")

    try:
        run(scenario())
    finally:
        eng.stop()


def test_remove_asks_and_can_delete_partial_data(env, server):
    eng = Engine(config.load())
    eng.start()

    async def scenario():
        app = GrabApp(eng)
        async with app.run_test(size=(120, 30)) as pilot:
            add(eng, server.url(), dir=str(env.dl), out="big.bin")
            await until(
                pilot,
                lambda: names(app) == ["big.bin"] and int(app.items[app.order[0]]["completedLength"]) > 1_000_000,
                what="progress",
            )
            await pilot.press("space")
            await until(
                pilot,
                lambda: (env.dl / "big.bin.aria2").exists() and app.items[app.order[0]]["status"] == "paused",
                what="paused with control file",
            )
            await pilot.press("x")
            await until(pilot, lambda: type(app.screen).__name__ == "ConfirmRemove", what="confirm dialog")
            await pilot.press("n")
            await pilot.pause(0.5)
            assert names(app) == ["big.bin"] and (env.dl / "big.bin").exists(), "cancel must change nothing"
            await pilot.press("x")
            await until(pilot, lambda: type(app.screen).__name__ == "ConfirmRemove", what="confirm dialog again")
            await pilot.press("d")
            await until(pilot, lambda: names(app) == [], what="row gone")
            assert not (env.dl / "big.bin").exists() and not (env.dl / "big.bin.aria2").exists()

    try:
        run(scenario())
    finally:
        eng.stop()


def test_retry_notifications_open_and_copy(env, server):
    eng = Engine(config.load())
    eng.start()

    async def scenario():
        app = GrabApp(eng)
        async with app.run_test(size=(120, 30)) as pilot:
            add(eng, server.url("/small.bin"), dir=str(env.dl), out="ok.bin")
            add(eng, server.url("/missing"), dir=str(env.dl), out="bad.bin")
            await until(
                pilot,
                lambda: {d["status"] for d in app.items.values()} == {"complete", "error"} and len(app.items) == 2,
                timeout=25,
                what="finished + failed",
            )
            await until(
                pilot,
                lambda: (
                    (env.logs / "notify.log").exists() and "Download finished" in (env.logs / "notify.log").read_text()
                ),
                what="finished notification",
            )
            note = (env.logs / "notify.log").read_text()
            assert "ok.bin" in note
            # retry the failed one: a new gid replaces it
            await pilot.press("5")
            await until(pilot, lambda: names(app) == ["bad.bin"], what="error tab")
            old = app.order[0]
            await pilot.press("R")
            await until(pilot, lambda: app.order and app.order[0] != old, what="retried with a new gid")
            # open / copy on the finished one
            await pilot.press("4")
            await until(pilot, lambda: names(app) == ["ok.bin"], what="done tab")
            await pilot.press("o")
            await pilot.press("O")
            await pilot.press("y")
            await until(
                pilot,
                lambda: (
                    (env.logs / "clip.txt").exists() and (env.logs / "clip.txt").read_text() == server.url("/small.bin")
                ),
                what="clipboard",
            )
            await until(
                pilot,
                lambda: (env.logs / "opener.log").exists() and len((env.logs / "opener.log").read_text().split()) == 2,
                what="opener",
            )
            assert (env.logs / "opener.log").read_text().split() == [str(env.dl / "ok.bin"), str(env.dl)]

    try:
        run(scenario())
    finally:
        eng.stop()


def test_add_dialog_prefills_from_clipboard_and_adds(env, server):
    (env.logs / "paste.txt").write_text(server.url("/small.bin"))
    eng = Engine(config.load())
    eng.start()

    async def scenario():
        app = GrabApp(eng)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("a")
            await until(pilot, lambda: type(app.screen).__name__ == "AddScreen", what="add dialog")
            await until(
                pilot,
                lambda: app.screen.query_one("#links", TextArea).text == server.url("/small.bin"),
                what="clipboard prefill",
            )
            await pilot.press("ctrl+s")
            await until(pilot, lambda: len(names(app)) == 1, what="download added")
            await pilot.press("a")  # empty dialog: ctrl+s with nothing does not add
            await until(pilot, lambda: type(app.screen).__name__ == "AddScreen", what="dialog again")

    try:
        run(scenario())
    finally:
        eng.stop()
