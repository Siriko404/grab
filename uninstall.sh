#!/bin/bash
# Undo install.sh. Downloads, config and the queue are kept (~/.config/grab, ~/.local/share/grab).
set -euo pipefail
"${GRAB_VENV:-$HOME/.local/share/grab/venv}/bin/grab" setup --remove || true
rm -f "$HOME/.local/bin/grab"
echo "Removed the launcher, browser host and command. Remove the extension in your browser yourself."
