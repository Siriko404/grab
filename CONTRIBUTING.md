# Contributing

Thanks for helping. Small, focused pull requests with a test are easiest to review.

## Setup

You need `aria2c`, Python 3.12+, and for the extension tests `node`/`npm` and a Chromium binary.
On Arch: `sudo pacman -S aria2 python nodejs npm chromium desktop-file-utils procps-ng`.

    git clone https://github.com/Siriko404/grab && cd grab
    ./install.sh --dev                     # private venv with an editable install and test tools
    npm ci --prefix tests                  # only for the extension tests
    ~/.local/share/grab/venv/bin/python -m pytest

Without a venv: `python -m venv .venv && .venv/bin/pip install -e '.[dev]'`.

## What the tests do

No test opens a window or touches your real downloads. Each test runs against its own config, data directory,
port and a throwaway local web server, and checks the behaviour that can fail:

- `test_engine.py`: pause-on-close for every way the app can end, resume mid-file, byte-identical result.
- `test_cli.py`, `test_host.py`, `test_integrate.py`, `test_launch.py`: the commands, the browser host's input
  checks, setup/remove, and the launcher fallbacks.
- `test_tui_pty.py` runs the app under a pseudo-terminal; `test_tui_pilot.py` drives it with Textual's pilot.
- `test_extension.py` (marked `e2e`) loads the extension into a headless Chromium with a temporary profile.
  It is skipped when `node_modules` or Chromium is missing. Set `CHROMIUM_BIN` to pick the browser.
- `test_consistency.py`: version, host name and extension id must agree across files.

Run `pytest -m "not e2e"` to skip the browser tests.

## Style

`ruff check` and `ruff format` (line length 120). Keep comments for the *why*. The engine stays a single aria2
process owned by one app; features that need a long-lived background service are out of scope.

## Changing the extension

If you edit `src/grab/extension/`, bump its `version` together with `grab.__version__` (a test enforces this),
and reload it at `chrome://extensions`. Do not commit a private signing key; the `key` in the manifest is the
*public* key that pins the extension id.

## Releasing (maintainers)

1. Update `grab.__version__`, the extension `manifest.json` version, and `CHANGELOG.md`.
2. Tag `vX.Y.Z` and push the tag. The release workflow builds the sdist, wheel and extension zip.
3. In `packaging/arch/`, run `updpkgsums` and `makepkg --printsrcinfo > .SRCINFO`, then update the AUR package.

## Reporting bugs and security issues

Use the issue templates for bugs. For security problems follow [SECURITY.md](SECURITY.md); please don't open a
public issue.
