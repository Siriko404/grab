// Injected into the page; must be self-contained. Returns {referer, items:[{url,label,match}]}.
function collectLinks() {
  const exts = "zip|rar|7z|tar|gz|tgz|bz2|xz|zst|iso|img|dmg|exe|msi|deb|rpm|apk|appimage|pkg|torrent|" +
    "mkv|mp4|avi|mov|webm|m4v|ts|mp3|flac|wav|ogg|opus|m4a|aac|pdf|epub|mobi|djvu|" +
    "doc|docx|xls|xlsx|ppt|pptx|csv|bin|cab|jar|whl|vsix";
  const ext = new RegExp("\\.(" + exts + ")(?![a-z0-9])", "i");
  const seen = new Map();
  const add = (raw, label, forced) => {
    let url;
    try { url = new URL(raw, location.href); } catch { return; }
    if (!/^(https?|ftp):$|^magnet:$/.test(url.protocol)) return;
    const href = url.href;
    const probe = url.protocol === "magnet:" ? "" : decodeURIComponent(url.pathname + url.search).replace(/\/+$/, "");
    const match = forced || url.protocol === "magnet:" || ext.test(probe);
    const text = (label || "").replace(/\s+/g, " ").trim().slice(0, 140);
    const prev = seen.get(href);
    if (!prev) seen.set(href, { url: href, label: text, match });
    else if (!prev.label && text) prev.label = text;
  };
  for (const a of document.querySelectorAll("a[href]")) {
    add(a.getAttribute("href"), a.textContent || a.title || a.getAttribute("download"), a.hasAttribute("download"));
  }
  for (const el of document.querySelectorAll("video[src], audio[src], source[src]")) {
    add(el.getAttribute("src"), el.title || "", true);
  }
  return { referer: location.href, items: [...seen.values()] };
}
