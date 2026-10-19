"""aria2 session file: keep restored downloads paused, and queue downloads while the app is closed."""

from pathlib import Path


def normalize_paused(path: Path) -> None:
    """Mark every saved download paused, so nothing resumes until the user asks."""
    if not path.exists():
        return
    out, block = [], []

    def flush():
        if block:
            if not any(line.strip().startswith("pause=") for line in block[1:]):
                block.append(" pause=true")
            out.extend(block)
            block.clear()

    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        if line[0] not in " \t":
            flush()
        block.append(line)
    flush()
    path.write_text("\n".join(out) + ("\n" if out else ""))


def append_paused(path: Path, uris: list[str], directory: str) -> None:
    """Queue downloads in a closed engine's session file (only valid while the engine is not running)."""
    with path.open("a") as f:
        for uri in uris:
            f.write(f"{uri}\n dir={directory}\n pause=true\n")
