# Architecture

    browser ── extension ── native messaging ──► grab-host ──┐
                                                             ├──► aria2c (JSON-RPC, 127.0.0.1)
    terminal ── grab (Textual app / CLI) ────────────────────┘        ▲
         └── owns and starts ────────────────────────────────────────┘

## One owner

The terminal app (or `grab serve`) **owns** the engine. It takes a lock (`engine.lock` in the data directory),
starts `aria2c`, and on exit runs `forcePauseAll` → `saveSession` → `shutdown`. aria2 is also started with
`--stop-with-process=<app pid>`, so a hard kill of the app still stops the engine. On the next start every saved
download is rewritten as `pause=true` before aria2 reads the session, so nothing resumes by itself.

Consequences: there is no background service, the CLI works only while the app (or `grab serve`) runs, and
downloads never continue after you close the window.

## Starting on demand

`grab add`, `grab launch` and the browser host call `ensure_engine()`: if the engine answers, use it; if the
lock is free, open the app through `grab launch` (Omarchy's `omarchy-launch-or-focus-tui` when present, else
`xdg-terminal-exec`) and wait up to 20 s; if the lock is held but the engine is not up yet, just wait.

## Browser messages

`sendNativeMessage` starts a fresh `grab-host` per message. Requests are JSON with an `op`:

| op | request | reply |
|---|---|---|
| `ping` | | `{ok:true}` |
| `status` | | `{ok:true, running, active?, waiting?, speed?, dir?}`; never starts the app |
| `add` | `items:[{url, referer?, out?, cookie?, ua?}], dir?` | `{ok:true, gids}` or `{ok:false, code, error}` |

Error `code` is one of `bad_request`, `not_running`, `engine`, `internal`; the extension adds `host` when the
browser itself cannot reach the host.

## Catching downloads

With "Catch my downloads" on, `chrome.downloads.onCreated` pauses the browser's own download, sends the link with
its cookies and referrer to Grab, and cancels the browser's copy only after Grab accepted it. If Grab can't take
it, the browser's download is resumed and the toolbar badge shows `!`.

## Files

| | |
|---|---|
| `~/.config/grab/config.json` | port, secret, default folder, limits (mode 600) |
| `~/.local/share/grab/` | `session.txt` (queue), `aria2.conf` (secret, mode 600), `aria2.log`, `engine.lock` |
| `~/.local/share/grab/extension/` | the unpacked extension copied by `grab setup` |

Environment overrides used by the tests: `GRAB_CONFIG_DIR`, `GRAB_DATA_DIR`, `GRAB_NO_LAUNCH`, `GRAB_LAUNCH_CMD`,
`GRAB_OPENER`, `GRAB_CLIP`, `GRAB_PASTE`, `GRAB_NOTIFY`.
