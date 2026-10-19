# Security policy

## Reporting a vulnerability

Please report it privately through GitHub: **Security → Report a vulnerability** on this repository.
Do not open a public issue. You can expect an acknowledgement within a week.

## Supported versions

Only the latest release receives fixes.

## Security model

Grab runs entirely on your machine.

- **Engine RPC.** aria2 listens on `127.0.0.1` only and requires a random secret. The secret is stored in
  `~/.config/grab/config.json` and in `aria2.conf` inside the data directory, both mode `0600`, and is never put
  on a command line.
- **Browser extension → host.** The extension talks to the engine through Chromium's native-messaging channel.
  The host manifest allows exactly one extension id (pinned by the public key in the extension manifest).
  The host accepts only `http`, `https`, `ftp`, `ftps` and `magnet` links, at most 500 per message, and only
  download folders inside your home directory. File names from the browser are stripped of path separators.
- **Cookies.** To download pages that need a login the extension sends the cookies for the link's own site to
  your local engine. They are held in memory by aria2 and not written to Grab's files.
- **Permissions.** The extension asks for `downloads`, `cookies`, `nativeMessaging`, `storage`, `scripting`,
  `contextMenus` and access to all sites, because it must read links on any page and the cookies for any
  download. It contacts no server of its own.

Out of scope: anything that requires an attacker who can already run code as your user.
