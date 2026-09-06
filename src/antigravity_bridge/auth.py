"""Antigravity OAuth token management, validation, and auto-refresh."""

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

DEFAULT_TOKEN_PATHS = [
    os.path.expanduser("~/.gemini/antigravity-cli/antigravity-oauth-token"),
    os.path.expanduser("~/.gemini/oauth_token.json"),
    "/root/.gemini/antigravity-cli/antigravity-oauth-token",
]

DEFAULT_AGY_PATHS = [
    shutil.which("agy"),
    os.path.expanduser("~/.local/bin/agy"),
    "/root/.local/bin/agy",
    "/usr/local/bin/agy",
]


def resolve_token_path(custom_path: Optional[str] = None) -> Optional[str]:
    """Find the Antigravity OAuth token file path."""
    if custom_path and os.path.exists(custom_path):
        return custom_path
    env_path = os.environ.get("ANTIGRAVITY_TOKEN_FILE")
    if env_path and os.path.exists(env_path):
        return env_path
    for p in DEFAULT_TOKEN_PATHS:
        if p and os.path.exists(p):
            return p
    return DEFAULT_TOKEN_PATHS[0]


def resolve_agy_bin(custom_path: Optional[str] = None) -> Optional[str]:
    """Find the agy CLI binary executable."""
    if custom_path and os.path.exists(custom_path):
        return custom_path
    env_path = os.environ.get("AGY_BIN")
    if env_path and os.path.exists(env_path):
        return env_path
    for p in DEFAULT_AGY_PATHS:
        if p and os.path.exists(p):
            return p
    return shutil.which("agy") or "/root/.local/bin/agy"


def check_token_status(token_path: Optional[str] = None) -> Dict:
    """Return diagnostic information about the local Antigravity OAuth token."""
    path = resolve_token_path(token_path)
    if not path or not os.path.exists(path):
        return {
            "found": False,
            "path": path,
            "error": "Token file does not exist. Please run 'agy' to log in.",
        }

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return {"found": True, "path": path, "error": f"Failed to parse token file: {e}"}

    tok = data.get("token", {})
    access_token = tok.get("access_token")
    expiry_str = tok.get("expiry")
    auth_method = data.get("auth_method", "unknown")

    if not access_token:
        return {"found": True, "path": path, "error": "access_token missing in token file."}

    expired = True
    secs_rem = 0.0
    if expiry_str:
        try:
            clean_exp = expiry_str.split(".")[0].replace("Z", "")
            exp_dt = datetime.fromisoformat(clean_exp).replace(tzinfo=timezone.utc)
            now_dt = datetime.now(timezone.utc)
            secs_rem = (exp_dt - now_dt).total_seconds()
            expired = secs_rem <= 60
        except Exception:
            pass

    return {
        "found": True,
        "path": path,
        "auth_method": auth_method,
        "expired": expired,
        "seconds_remaining": secs_rem,
        "expiry": expiry_str,
    }


def refresh_token(agy_bin: Optional[str] = None) -> bool:
    """Trigger native agy token refresh by invoking `agy models`."""
    bin_path = resolve_agy_bin(agy_bin)
    if not bin_path or not os.path.exists(bin_path):
        return False
    try:
        res = subprocess.run([bin_path, "models"], capture_output=True, timeout=30)
        return res.returncode == 0
    except Exception:
        return False


def get_auth_token(
    token_path: Optional[str] = None,
    agy_bin: Optional[str] = None,
    force_refresh: bool = False,
) -> Optional[str]:
    """Retrieve a valid, non-expired access token, refreshing via agy if required."""
    status = check_token_status(token_path)
    if not status.get("found"):
        return None

    if force_refresh or status.get("expired"):
        refresh_token(agy_bin)

    # Re-read token file
    path = status["path"]
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("token", {}).get("access_token")
    except Exception:
        return None


def verify_upstream_access(
    token: str,
    project_id: str = "aicode-consumers",
) -> Tuple[bool, str]:
    """Verify that the token has active permissions on the Antigravity backend."""
    url = "https://daily-cloudcode-pa.googleapis.com/v1internal:loadCodeAssist"
    body = json.dumps({
        "cloudaicompanionProject": "default-cli-project",
        "metadata": {"ideType": "JETSKI", "ideVersion": "1.1.27"},
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Antigravity-CLI/1.1.27",
        },
        data=body,
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            tier = data.get("currentTier", {}).get("name", "Antigravity")
            paid = data.get("paidTier", {}).get("name", "Standard")
            return True, f"Authenticated (Tier: {tier}, Plan: {paid})"
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8", errors="replace")[:300]
        return False, f"HTTP {e.code}: {err_msg}"
    except Exception as e:
        return False, f"Connection error: {e}"
