const $ = (id) => document.getElementById(id);
let items = [];     // {url,label,match,referer,checked}
let referer = "";

async function activeTabId() {
  const forced = new URLSearchParams(location.search).get("tab");
  if (forced) return Number(forced);
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab.id;
}

async function scan() {
  try {
    const tabId = await activeTabId();
    const results = await chrome.scripting.executeScript({ target: { tabId, allFrames: true }, func: collectLinks });
    const byUrl = new Map();
    for (const r of results) {
      if (!r.result) continue;
      referer = referer || r.result.referer;
      for (const it of r.result.items) {
        const have = byUrl.get(it.url);
        if (!have) byUrl.set(it.url, { ...it, referer: r.result.referer, checked: it.match });
        else if (!have.label && it.label) have.label = it.label;
      }
    }
    items = [...byUrl.values()];
  } catch (e) {
    say("Can't read this page: " + e.message, true);
  }
  render();
}

function visible() {
  const q = $("filter").value.trim().toLowerCase();
  const all = $("all").checked;
  return items.filter((i) => (all || i.match) && (!q || (i.label + " " + i.url).toLowerCase().includes(q)));
}

function render() {
  const list = $("list");
  list.textContent = "";
  const shown = visible();
  if (!shown.length) {
    const d = document.createElement("div");
    d.id = "empty";
    d.textContent = items.length ? "No download links match. Tick “all links” to see every link." : "No links found on this page.";
    list.append(d);
  }
  for (const it of shown) {
    const row = document.createElement("label");
    row.className = "row";
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = it.checked;
    box.addEventListener("change", () => { it.checked = box.checked; count(); });
    const t = document.createElement("div");
    t.className = "t";
    const l = document.createElement("div");
    l.className = "l";
    l.textContent = it.label || decodeURIComponent(it.url.split("/").pop().split("?")[0]) || it.url;
    const u = document.createElement("div");
    u.className = "u";
    u.textContent = it.url;
    t.title = it.url;
    t.append(l, u);
    row.append(box, t);
    list.append(row);
  }
  count();
}

function count() {
  const n = visible().filter((i) => i.checked).length;
  $("go").disabled = n === 0;
  $("go").textContent = n ? `Download ${n}` : "Download";
  if (!$("status").classList.contains("err")) say(`${visible().length} link${visible().length === 1 ? "" : "s"}`);
}

function say(text, err = false) {
  $("status").textContent = text;
  $("status").classList.toggle("err", err);
}

$("filter").addEventListener("input", render);
$("all").addEventListener("change", render);
$("selAll").addEventListener("click", () => { visible().forEach((i) => (i.checked = true)); render(); });
$("selNone").addEventListener("click", () => { visible().forEach((i) => (i.checked = false)); render(); });

$("go").addEventListener("click", async () => {
  const chosen = visible().filter((i) => i.checked).map((i) => ({ url: i.url, referer: i.referer }));
  $("go").disabled = true;
  say("Sending…");
  const dir = $("dir").value.trim();
  chrome.storage.local.set({ dir });
  const reply = await chrome.runtime.sendMessage({ op: "send", items: chosen, dir });
  if (reply && reply.ok) {
    say(`Sent ${chosen.length} to Grab`);
    $("status").classList.remove("err");
  } else {
    say((reply && reply.error) || "Grab did not answer", true);
  }
  $("go").disabled = false;
});

$("all").addEventListener("change", () => chrome.storage.local.set({ allLinks: $("all").checked }));
$("filter").addEventListener("keydown", (e) => { if (e.key === "Enter" && !$("go").disabled) $("go").click(); });
$("dir").addEventListener("keydown", (e) => { if (e.key === "Enter" && !$("go").disabled) $("go").click(); });

async function engineLine() {
  const r = await chrome.runtime.sendMessage({ op: "status" });
  if (!r || !r.ok) { $("engine").textContent = (r && r.error) || ""; return; }
  $("engine").textContent = r.running
    ? `Grab is running · ${r.active} active · ${r.waiting} waiting · saving to ${r.dir}`
    : "Grab is closed — it opens when you send links";
}

$("auto").addEventListener("change", () => chrome.storage.local.set({ auto: $("auto").checked }));
chrome.storage.local.get({ auto: false, dir: "", allLinks: false }).then((v) => {
  $("auto").checked = v.auto;
  $("dir").value = v.dir;
  $("all").checked = v.allLinks;
  scan();
});
engineLine();
