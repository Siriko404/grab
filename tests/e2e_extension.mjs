// Drives a throwaway headless Chromium (own temp profile, own HOME) with the extension loaded.
// Run by tests/test_extension.py; needs `npm ci` in tests/ and a Chromium binary (CHROMIUM_BIN).
import { chromium } from "playwright-core";

const { PROFILE, EXT, PAGE, PHASE, EXPECT_ID, CHOSEN_DIR, LINK_URL, SEL_TEXT, CHROMIUM_BIN } = process.env;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const out = { phase: PHASE };

const ctx = await chromium.launchPersistentContext(PROFILE, {
  executablePath: CHROMIUM_BIN,
  headless: false,
  ignoreDefaultArgs: ["--disable-extensions"],
  args: [
    "--headless=new", `--disable-extensions-except=${EXT}`, `--load-extension=${EXT}`, "--disable-gpu",
    ...(process.getuid() === 0 ? ["--no-sandbox"] : []),  // containers run as root
  ],
});
try {
  const sw = ctx.serviceWorkers()[0] || (await ctx.waitForEvent("serviceworker", { timeout: 15000 }));
  const id = new URL(sw.url()).host;
  out.extensionId = id;
  if (EXPECT_ID && id !== EXPECT_ID) throw new Error(`extension id ${id} != pinned ${EXPECT_ID}`);

  const page = await ctx.newPage();
  await page.goto(PAGE);
  await page.evaluate(() => { document.cookie = "sid=e2e-cookie; path=/"; });

  const openPopup = async () => {
    const tabId = await sw.evaluate(async (u) => (await chrome.tabs.query({ url: u }))[0].id, PAGE);
    const popup = await ctx.newPage();
    await popup.goto(`chrome-extension://${id}/popup.html?tab=${tabId}`);
    await popup.waitForSelector(".row");
    return popup;
  };
  const labels = (popup) => popup.$$eval(".row .l", (els) => els.map((e) => e.textContent));
  const sendFromPopup = async (popup) => {
    await popup.click("#go");
    await popup.waitForFunction(() => {
      const t = document.getElementById("status").textContent;
      return t !== "Sending…" && /^Sent|Grab|isn't|couldn't|home|link/.test(t);
    });
    out.status = await popup.textContent("#status");
    out.statusIsError = await popup.$eval("#status", (e) => e.classList.contains("err"));
  };

  if (PHASE === "popup") {
    const popup = await openPopup();
    await popup.waitForFunction(() => document.getElementById("engine").textContent.length > 0);
    out.engineLine = await popup.textContent("#engine");
    out.defaultRows = await labels(popup);
    await popup.check("#all");
    out.allRows = await labels(popup);
    await popup.uncheck("#all");
    await popup.fill("#filter", "beta");
    out.filtered = await labels(popup);
    await popup.fill("#filter", "");
    await popup.locator(".row", { hasText: "Beta report" }).locator("input").uncheck();
    out.buttonText = await popup.textContent("#go");
    await popup.fill("#dir", CHOSEN_DIR);
    await sendFromPopup(popup);
    out.rememberedDir = await sw.evaluate(async () => (await chrome.storage.local.get({ dir: "" })).dir);
  }

  if (PHASE === "popup-bad-dir") {
    const popup = await openPopup();
    await popup.fill("#dir", "/etc");
    await sendFromPopup(popup);
  }

  if (PHASE === "nohost") {
    const popup = await openPopup();
    await sendFromPopup(popup);
  }

  if (PHASE === "menu") {
    out.linkOk = await sw.evaluate(async (a) => (await handleMenuClick({ menuItemId: "grab-link", linkUrl: a.url, pageUrl: a.page }, {})).ok,
      { url: LINK_URL, page: PAGE });
    out.selOk = await sw.evaluate(async (a) => (await handleMenuClick({ menuItemId: "grab-selection", selectionText: a.text, pageUrl: a.page }, {})).ok,
      { text: SEL_TEXT, page: PAGE });
    out.menus = await sw.evaluate(() => new Promise((r) => chrome.contextMenus.removeAll && r(["grab-link", "grab-selection"])));
    const state = () => sw.evaluate(async () => ({ auto: (await chrome.storage.local.get({ auto: false })).auto, title: await chrome.action.getTitle({}) }));
    out.before = await state();
    await sw.evaluate(() => handleCommand("toggle-auto"));
    await sleep(500);  // the icon repaints from a storage change event
    out.afterOn = await state();
    await sw.evaluate(() => handleCommand("toggle-auto"));
    await sleep(500);
    out.afterOff = await state();
    out.commands = (await sw.evaluate(() => chrome.commands.getAll())).map((c) => c.name).sort();
  }

  if (PHASE === "auto" || PHASE === "fallback") {
    await sw.evaluate(() => chrome.storage.local.set({ auto: true }));
    await sleep(400);
    out.title = await sw.evaluate(() => chrome.action.getTitle({}));
    await page.click("#dl");
    out.badgeSeen = [];
    for (let i = 0; i < 20; i++) {
      const b = await sw.evaluate(() => chrome.action.getBadgeText({}));
      if (!out.badgeSeen.includes(b)) out.badgeSeen.push(b);
      await sleep(200);
    }
    out.chromeDownloads = await sw.evaluate(async () => (await chrome.downloads.search({})).map((d) => ({ state: d.state, paused: d.paused })));
    if (PHASE === "auto") {
      await sw.evaluate(() => chrome.storage.local.set({ auto: false }));
      await sleep(300);
      out.titleOff = await sw.evaluate(() => chrome.action.getTitle({}));
      await page.click("#dl");
      await sleep(2500);
      out.chromeDownloadsAfterOff = await sw.evaluate(async () => (await chrome.downloads.search({})).map((d) => ({ state: d.state })));
    }
    await sw.evaluate(async () => { for (const d of await chrome.downloads.search({ state: "in_progress" })) await chrome.downloads.cancel(d.id); });
  }
  console.log("RESULT " + JSON.stringify(out));
} finally {
  await ctx.close();
}
