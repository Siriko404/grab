const HOST = "io.github.siriko404.grab";
const GREEN = "#1f8f5a";
const RED = "#c0392b";
const SKIP = /^(blob|data|file|filesystem|chrome|about|javascript):/i;
const URL_IN_TEXT = /(?:https?:\/\/|ftp:\/\/|magnet:\?)[^\s"'<>]+/gi;

function explain(error) {
  if (/not found/i.test(error)) return "Grab isn't installed here. Run `grab setup` in a terminal, then reload this extension.";
  if (/forbidden/i.test(error)) return "Grab's browser link doesn't allow this extension. Run `grab setup` again.";
  if (/exited|communicating/i.test(error)) return "Grab's browser link stopped unexpectedly. Try again.";
  return error;
}

function send(msg) {
  return new Promise((resolve) => {
    chrome.runtime.sendNativeMessage(HOST, msg, (reply) => {
      const err = chrome.runtime.lastError;
      if (err) return resolve({ ok: false, code: "host", error: explain(err.message) });
      resolve(reply || { ok: false, code: "host", error: "Grab did not answer." });
    });
  });
}

async function cookieHeader(url) {
  try {
    const cookies = await chrome.cookies.getAll({ url });
    return cookies.map((c) => `${c.name}=${c.value}`).join("; ");
  } catch {
    return "";
  }
}

async function sendItems(items, dir) {
  const full = await Promise.all(items.map(async (i) => ({
    url: i.url,
    referer: i.referer || "",
    out: i.out || "",
    cookie: await cookieHeader(i.url),
    ua: navigator.userAgent,
  })));
  const reply = await send({ op: "add", items: full, dir: dir || "" });
  if (reply.ok) return reply;
  if (reply.code === "not_running") reply.error = "Grab couldn't open. Start it from the launcher, then try again.";
  return reply;
}

async function autoOn() {
  return (await chrome.storage.local.get({ auto: false })).auto;
}

async function paintIcon() {
  const on = await autoOn();
  const suffix = on ? "" : "-off";
  await chrome.action.setIcon({ path: { 16: `icon16${suffix}.png`, 48: `icon48${suffix}.png`, 128: `icon128${suffix}.png` } });
  await chrome.action.setTitle({ title: on ? "Grab — catching your downloads" : "Grab" });
}

async function flash(text, color) {
  await chrome.action.setBadgeBackgroundColor({ color });
  await chrome.action.setBadgeText({ text });
  setTimeout(() => chrome.action.setBadgeText({ text: "" }), 3000);
}

chrome.downloads.onCreated.addListener(async (item) => {
  if (!(await autoOn())) return;
  const url = item.finalUrl || item.url;
  if (!url || SKIP.test(url)) return;
  try { await chrome.downloads.pause(item.id); } catch {}
  const name = (item.filename || "").split(/[\\/]/).pop();
  const reply = await sendItems([{ url, referer: item.referrer, out: name }]);
  if (reply.ok) {
    await chrome.downloads.cancel(item.id);
    await chrome.downloads.erase({ id: item.id });
    flash("✓", GREEN);
  } else {
    try { await chrome.downloads.resume(item.id); } catch {}
    flash("!", RED);
    console.warn("Grab could not take the download:", reply.error);
  }
});

// Right-click: a link, or URLs inside selected text.
async function handleMenuClick(info, tab) {
  const items = [];
  if (info.menuItemId === "grab-link" && info.linkUrl) {
    items.push({ url: info.linkUrl, referer: info.pageUrl });
  } else if (info.menuItemId === "grab-selection" && info.selectionText) {
    const found = (info.selectionText.match(URL_IN_TEXT) || []).map((u) => u.replace(/[.,;:!?)\]}>'"]+$/, ""));
    for (const url of new Set(found)) items.push({ url, referer: info.pageUrl });
  }
  if (!items.length) return flash("?", RED);
  const reply = await sendItems(items);
  flash(reply.ok ? "✓" : "!", reply.ok ? GREEN : RED);
  return reply;
}

async function handleCommand(name) {
  if (name !== "toggle-auto") return;
  const on = !(await autoOn());
  await chrome.storage.local.set({ auto: on });
  flash(on ? "ON" : "OFF", on ? GREEN : "#7d828a");
}

function buildMenus() {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({ id: "grab-link", title: "Download with Grab", contexts: ["link"] });
    chrome.contextMenus.create({ id: "grab-selection", title: "Download links in selection with Grab", contexts: ["selection"] });
  });
}

chrome.contextMenus.onClicked.addListener(handleMenuClick);
chrome.commands.onCommand.addListener(handleCommand);

chrome.runtime.onMessage.addListener((msg, _sender, respond) => {
  if (msg && msg.op === "send") { sendItems(msg.items, msg.dir).then(respond); return true; }
  if (msg && msg.op === "status") { send({ op: "status" }).then(respond); return true; }
  return false;
});

chrome.storage.onChanged.addListener((changes) => { if (changes.auto) paintIcon(); });
chrome.runtime.onStartup.addListener(paintIcon);
chrome.runtime.onInstalled.addListener(() => { buildMenus(); paintIcon(); });
paintIcon();
