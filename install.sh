#!/usr/bin/env bash
# Thin wrapper: pipx if available, else pip --user. `pip install .` is the canonical path.
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
command -v python3 >/dev/null || { echo "python3 is required"; exit 1; }
if command -v pipx >/dev/null; then
  pipx install --force "$DIR"
else
  python3 -m pip install --user "$DIR" 2>/dev/null || python3 -m pip install --user --break-system-packages "$DIR"
fi
echo
echo "Installed. Next:  llm-bridge up"
