# Grab

[![CI](https://github.com/Siriko404/grab/actions/workflows/ci.yml/badge.svg)](https://github.com/Siriko404/grab/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A small download manager for Linux: an [aria2](https://aria2.github.io/) engine inside a terminal app, a CLI,
and a Chromium extension. Built to feel at home on [Omarchy](https://omarchy.org/), and it works on any Linux
desktop with aria2 and a terminal.

- **Closing the app pauses everything.** The engine belongs to the app. Quit, close the window, or kill it: every
  download is paused and saved, and comes back paused. Nothing keeps downloading behind your back.
- **A normal tiled window.** On Omarchy it is the single window `org.omarchy.grab`; the launcher, the browser and
  `grab` all focus it instead of opening a second copy.
- **Native look, any size.** It uses your terminal's own colours, so it follows theme changes, and it reflows from
  a full screen down to a half-screen tile.
- **A browser extension that earns its place.** Pick which links on a page to download, catch every download you
  click, or right-click a link. Cookies and referrer go along, so logged-in downloads work.

```
 Grab  ▼ 2.1 MB/s   1 active   1 paused/queued   1 done   1 failed   → ~/Downloads
 1 All 4  2 Active 1  3 Paused 1  4 Done 1  5 Error 1
 Name                           Size       Progress           Speed       ETA      Status
 ubuntu-desktop-amd64.iso       12.0 MB    ███████░░░░░  59%  2.0 MB/s    2s       ● downloading
 conference-talk-2160p.mkv      ?          ░░░░░░░░░░░░   0%  -           -        ⏸ paused
 broken-link.zip                ?          ░░░░░░░░░░░░   0%  -           -        ✗ error
 notes.pdf                      400.0 KB   ████████████ 100%  -           -        ✓ done

 a Add  space Pause  i Details  x Remove  / Search  ? Help  q Quit
```
<sub>Text rendering of the app at 100 columns, and below at a 58-column tile.</sub>

```
 Grab  ▼ 2.1 MB/s
 1:4  2:1  3:1  4:1  5:1
 Name                                        Done
 ubuntu-desktop-amd64.iso                     59%   ●
 conference-talk-2160p.mkv                     0%   ⏸
 broken-link.zip                               0%   ✗
 notes.pdf                                   100%   ✓
 a Add  space Pause  i Details  x Remove  / Search  ? Help
```

## Install

Requirements: Linux, Python 3.12+, `aria2`, and a terminal. The extension works in Chromium-based browsers
(Chromium, Chrome, Brave, Edge, Vivaldi). Desktop notifications use `notify-send`, "copy link" uses `wl-copy`,
"open" uses `xdg-open`; each is optional.

**From source** (any Linux):

    git clone https://github.com/Siriko404/grab && cd grab
    ./install.sh

This creates a private virtualenv, puts `grab` in `~/.local/bin`, registers the browser host, adds a launcher entry
and copies the extension to `~/.local/share/grab/extension`. `./uninstall.sh` removes all of it (your queue and
settings are kept).

**With pipx or uv:** `pipx install .` (or `uv tool install .`), then run `grab setup`.

**Arch Linux:** a `PKGBUILD` is in [`packaging/arch`](packaging/arch). It installs system-wide, including the
browser host for Chromium and Chrome and the extension in `/usr/share/grab/extension`.

Finally, load the extension: open `chrome://extensions`, turn on **Developer mode**, click **Load unpacked** and
choose `~/.local/share/grab/extension` (or `/usr/share/grab/extension` for the Arch package). The extension id is
pinned to `knbeaamojgknknpedofcphmoofhpgjfa`, so the browser host already trusts it. Reload the extension after upgrading Grab.

> The package is called **grab-dl** where package names must be unique (`grab` is taken on PyPI). The command,
> the import name and the app are all `grab`.

## The app

Run `grab`, or open **Grab** from your launcher. Optional Omarchy keybinding for `~/.config/hypr/bindings.lua`
(check `omarchy menu keybindings --print` for conflicts first):

    o.bind("SUPER + SHIFT + G", "Grab", { tui = "grab", focus = true })

| key | action | key | action |
|---|---|---|---|
| `a` | add links (pastes a link from your clipboard) | `space` | pause / resume |
| `i` / `enter` | details | `x` | remove (asks about the partial file) |
| `1`–`5` | All / Active / Paused / Done / Error | `/` | search (`esc` clears) |
| `R` | retry a failed download | `J` / `K` | move down / up the queue |
| `o` / `O` | open file / folder | `y` | copy link |
| `p` / `r` | pause all / resume all | `c` | clear finished |
| `l` | speed limit | `?` | help |

After a restart your downloads are back but paused: press `r` to resume them all.

## The CLI

    grab                      open the app
    grab add URL… [-d DIR] [-o NAME] [-c N] [--paused] [-i FILE]
    grab ls [-a] [-s STATUS] [--json]
    grab status               one line; exit code 3 when Grab is closed
    grab pause|resume GID|all
    grab rm GID… [--delete]   --delete also removes the unfinished file and its control file
    grab retry GID…           grab open GID [--folder]         grab clear
    grab config [get|set KEY VALUE]     dir, concurrent, connections, limit
    grab serve                engine only, no window (Ctrl-C pauses and exits)
    grab launch               open the app window, or focus it
    grab setup [--remove]     register / unregister the browser host, launcher entry and extension

Download IDs can be abbreviated to any unique prefix. Exit codes: 0 ok, 1 failed, 2 bad usage, 3 Grab not running.
`grab add` opens the app if it is closed, so scripts can use it.

## The extension

- **Toolbar button:** lists the page's download links with the likely ones ticked; filter, untick, pick a folder, send.
- **Catch my downloads** (switch in the popup, or `Alt+Shift+G`): downloads you click go to Grab with your cookies,
  referrer and user agent. If Grab can't take one, the browser keeps it and the badge shows `!`.
- **Right-click** a link → *Download with Grab*; select text containing URLs → *Download links in selection with Grab*.
- `Alt+Shift+D` opens the popup. The icon is grey when catching is off, green when on.

## Security

Everything runs on your machine. The engine listens on `127.0.0.1` with a random secret kept in a mode-600 file,
never on a command line; the browser host accepts only web/ftp/magnet links and folders inside your home. Details
and how to report a problem: [SECURITY.md](SECURITY.md). How it fits together: [docs/architecture.md](docs/architecture.md).

## Contributing

Issues and pull requests are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md). Licensed under the [MIT License](LICENSE).
