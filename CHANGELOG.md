# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [0.3.0] - 2026-10-19

First public release.

### Added
- aria2 download engine owned by a terminal app: closing the app (quit, hang-up, terminate, or a hard kill)
  pauses every download and saves the queue; the next start restores it paused.
- Terminal app built with Textual: follows the terminal's colour palette (and so the Omarchy theme), reflows from
  a full screen to a half-screen tile, filter tabs, search, details pane, retry, queue ordering, open/copy,
  desktop notifications.
- `grab` CLI: `add`, `ls` (`--json`), `status`, `pause`, `resume`, `rm` (`--delete`), `retry`, `open`, `clear`,
  `config`, `serve`, `launch`, `setup`.
- Chromium extension (Manifest V3): page link picker, "Catch my downloads" switch, right-click menu, keyboard
  shortcuts, save-to folder, clear errors when the browser host is missing.
- Native-messaging host that validates links and folders before handing them to the engine.
- `grab setup` registers the browser host (Chromium, Chrome, Brave, Edge, Vivaldi), the launcher entry and the
  unpacked extension; `grab setup --remove` undoes it.
- Arch Linux `PKGBUILD`.

### Security
- The engine's RPC secret lives in a mode-600 file and never appears on a command line.
- The engine listens on 127.0.0.1 only and requires the secret.
