#!/bin/bash
# Install Grab for the current user from this checkout:
# a private venv, `grab` on PATH, the browser host, the launcher entry and the unpacked extension.
#   ./install.sh          regular install
#   ./install.sh --dev    editable install with test tools (for contributors)
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
venv=${GRAB_VENV:-$HOME/.local/share/grab/venv}

[[ -d $venv ]] || python3 -m venv "$venv"
if [[ ${1:-} == --dev ]]; then
  "$venv/bin/pip" install -q -e "$here[dev]"
else
  "$venv/bin/pip" install -q --upgrade "$here"
fi
mkdir -p "$HOME/.local/bin"
ln -sf "$venv/bin/grab" "$HOME/.local/bin/grab"
"$venv/bin/grab" setup
