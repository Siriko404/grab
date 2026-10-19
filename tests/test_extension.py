import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import BIN, wait_for
from grab import integrate
from grab.config import load as load_config
from grab.engine import Engine
from grab.rpc import Rpc

ROOT = Path(__file__).resolve().parent
EXT = integrate.package_dir("extension")
CHROMIUM = (
    os.environ.get("CHROMIUM_BIN")
    or shutil.which("chromium")
    or shutil.which("chromium-browser")
    or shutil.which("google-chrome-stable")
)
HAVE_PLAYWRIGHT = (ROOT / "node_modules" / "playwright-core").exists() and shutil.which("node")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not (CHROMIUM and HAVE_PLAYWRIGHT),
        reason="needs node, `npm ci` in tests/, and a Chromium binary (CHROMIUM_BIN)",
    ),
]


def ext_id() -> str:
    return integrate.extension_id()


@pytest.fixture
def browser(env):
    profile = env.root / "profile"
    (profile / "NativeMessagingHosts").mkdir(parents=True)
    (profile / "Default").mkdir()
    chrome_dl = env.root / "chrome-dl"
    chrome_dl.mkdir()
    (profile / "Default" / "Preferences").write_text(
        json.dumps({"download": {"default_directory": str(chrome_dl), "prompt_for_download": False}})
    )
    (profile / "NativeMessagingHosts" / f"{integrate.HOST_NAME}.json").write_text(
        integrate.host_manifest(str(BIN / "grab-host"))
    )

    def run(phase, page_url, **extra):
        e = dict(
            env.environ,
            PROFILE=str(profile),
            EXT=str(EXT),
            CHROMIUM_BIN=CHROMIUM,
            PAGE=page_url,
            PHASE=phase,
            EXPECT_ID=ext_id(),
            HOME=str(env.root),
            CHOSEN_DIR=str(env.root / "picked"),
            **extra,
        )
        p = subprocess.run(
            ["node", str(ROOT / "e2e_extension.mjs")], env=e, capture_output=True, text=True, timeout=120, cwd=ROOT
        )
        assert p.returncode == 0, p.stdout[-2000:] + p.stderr[-2000:]
        line = next(ln for ln in p.stdout.splitlines() if ln.startswith("RESULT "))
        return json.loads(line[7:])

    run.chrome_dl = chrome_dl
    run.profile = profile
    yield run
    subprocess.run(["pkill", "-9", "-f", str(env.root)], check=False)


def urls_in_engine(rpc):
    items = rpc.call("tellActive") + rpc.call("tellWaiting", 0, 100) + rpc.call("tellStopped", 0, 100)
    return sorted(f["uris"][0]["uri"] for d in items for f in d["files"] if f.get("uris"))


def test_popup_lists_links_lets_you_unselect_and_sends_the_rest(env, server, browser):
    eng = Engine(load_config())
    eng.start()
    try:
        out = browser("popup", server.url("/page"))
        assert out["extensionId"] == ext_id()
        assert out["defaultRows"] == [
            "Alpha archive",
            "Beta report",
            "Gamma image",
            "Delta",
            "Epsilon magnet",
            "Attachment",
            "zeta.mp4",
        ]
        assert "About us" in out["allRows"] and "Mail" not in out["allRows"]
        assert out["filtered"] == ["Beta report"]
        assert out["buttonText"] == "Download 6"
        assert out["status"] == "Sent 6 to Grab", out
        assert out["engineLine"].startswith("Grab is running"), out["engineLine"]
        assert out["rememberedDir"] == str(env.root / "picked")
        rpc = Rpc(eng.cfg["port"], eng.cfg["secret"])
        sent = urls_in_engine(rpc)
        base = server.url("")
        assert f"{base}/files/alpha.zip" in sent and f"{base}/files/delta.bin" in sent
        assert f"{base}/get.php?file=gamma%2Eiso" in sent and f"{base}/media/zeta.mp4" in sent
        assert f"{base}/files/beta.pdf" not in sent, "unselected link must not be downloaded"
        assert f"{base}/about" not in sent
        assert len(sent) == 5, sent  # the magnet link is queued by its own gid, not as a uri row
        dirs = {d["dir"] for d in rpc.call("tellActive") + rpc.call("tellWaiting", 0, 100)}
        assert dirs == {str(env.root / "picked")}, dirs
    finally:
        eng.stop()


def test_auto_catch_hands_clicked_download_to_grab_with_cookies(env, server, browser):
    eng = Engine(load_config())
    eng.start()
    try:
        out = browser("auto", server.url("/page"))
        assert out["title"] == "Grab — catching your downloads" and out["titleOff"] == "Grab"
        assert out["chromeDownloads"] == [], "Chrome's own copy must be cancelled and erased"
        rpc = Rpc(eng.cfg["port"], eng.cfg["secret"])
        wait_for(lambda: server.url("/dl/attach.bin") in urls_in_engine(rpc), what="engine to hold the download")
        mine = [
            r for r in server.requests if r.get("_path") == "/dl/attach.bin" and "Want-Digest" in r
        ]  # aria2 marks its requests so
        assert mine, (
            f"aria2's own request not seen: {[r for r in server.requests if r.get('_path') == '/dl/attach.bin']}"
        )
        assert "sid=e2e-cookie" in mine[0]["Cookie"]
        assert mine[0]["Referer"] == server.url("/page")
        assert "Chrome" in mine[0]["User-Agent"]
        assert out["chromeDownloadsAfterOff"], "with the toggle off Chrome must keep its own download"
        assert len([u for u in urls_in_engine(rpc) if u.endswith("/dl/attach.bin")]) == 1, "toggle off must not forward"
    finally:
        eng.stop()


def test_auto_catch_falls_back_to_chrome_when_grab_cannot_take_it(env, server, browser):
    out = browser("fallback", server.url("/page"))  # engine is not running, and GRAB_NO_LAUNCH=1
    assert out["chromeDownloads"], "Chrome must keep the download when Grab is unavailable"
    assert "!" in out["badgeSeen"], out["badgeSeen"]


def test_popup_refuses_a_folder_outside_home_with_a_clear_message(env, server, browser):
    eng = Engine(load_config())
    eng.start()
    try:
        out = browser("popup-bad-dir", server.url("/page"))
        assert out["statusIsError"] and "home" in out["status"], out
        rpc = Rpc(eng.cfg["port"], eng.cfg["secret"])
        assert urls_in_engine(rpc) == []
    finally:
        eng.stop()


def test_missing_host_shows_how_to_install(env, server, browser):
    (browser.profile / "NativeMessagingHosts" / f"{integrate.HOST_NAME}.json").unlink()
    out = browser("nohost", server.url("/page"))
    assert out["statusIsError"] and "isn't installed" in out["status"] and "grab setup" in out["status"], out


def test_right_click_menu_shortcut_command_and_icon_state(env, server, browser):
    eng = Engine(load_config())
    eng.start()
    try:
        base = server.url("")
        text = f"grab {base}/sel/one.bin and {base}/sel/two.bin, also magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567 ok"
        out = browser("menu", server.url("/page"), LINK_URL=f"{base}/link/target.bin", SEL_TEXT=text)
        assert out["linkOk"] is True and out["selOk"] is True
        rpc = Rpc(eng.cfg["port"], eng.cfg["secret"])
        sent = urls_in_engine(rpc)
        assert f"{base}/link/target.bin" in sent and f"{base}/sel/one.bin" in sent and f"{base}/sel/two.bin" in sent
        assert out["before"]["auto"] is False and out["afterOn"]["auto"] is True and out["afterOff"]["auto"] is False
        assert out["afterOn"]["title"].startswith("Grab — catching") and out["afterOff"]["title"] == "Grab"
        assert out["commands"] == ["_execute_action", "toggle-auto"]
    finally:
        eng.stop()
