#!/usr/bin/env bash
set -e

echo "========================================================="
echo "        Installing Antigravity Bridge for Agents         "
echo "========================================================="

# 1. Check Python 3
if ! command -v python3 &>/dev/null; then
    echo "[x] Error: Python 3 is required but not installed."
    exit 1
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "[✓] Found Python ${PY_VER}"

# 2. Get repository root
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

# 3. Install via pip or python setup.py
echo "[*] Installing antigravity-bridge package..."
if command -v pip3 &>/dev/null; then
    pip3 install -e "${DIR}" --break-system-packages 2>/dev/null || pip3 install -e "${DIR}"
elif command -v pip &>/dev/null; then
    pip install -e "${DIR}" --break-system-packages 2>/dev/null || pip install -e "${DIR}"
else
    python3 "${DIR}/setup.py" develop || python3 "${DIR}/setup.py" install
fi

# 4. Create symlink in /usr/local/bin if not automatically in PATH
for BIN_NAME in antigravity-bridge agy-bridge; do
    if ! command -v "${BIN_NAME}" &>/dev/null; then
        echo "[*] Creating symlink for ${BIN_NAME} in /usr/local/bin..."
        ln -sf "${DIR}/bin/${BIN_NAME}" "/usr/local/bin/${BIN_NAME}" 2>/dev/null || true
    fi
done

echo ""
echo "[✓] Installation complete!"
echo ""
echo "Next steps:"
echo "  1. Verify your Google Antigravity OAuth:  antigravity-bridge auth"
echo "  2. Connect OpenClaw or Hermes:            antigravity-bridge setup"
echo "  3. Check overall health:                  antigravity-bridge status"
echo ""
