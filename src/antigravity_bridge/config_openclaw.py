"""OpenClaw agent configuration and SQLite credential store manager."""

import glob
import json
import os
import shutil
import sqlite3
import time
from typing import Dict, List, Optional, Tuple

from .models import AVAILABLE_MODELS

DEFAULT_OPENCLAW_CONFIG_PATHS = [
    os.path.expanduser("~/.openclaw/openclaw.json"),
    "/root/.openclaw/openclaw.json",
]


def resolve_openclaw_config_path() -> str:
    """Find the OpenClaw openclaw.json path."""
    for p in DEFAULT_OPENCLAW_CONFIG_PATHS:
        if os.path.exists(p):
            return p
    return DEFAULT_OPENCLAW_CONFIG_PATHS[0]


def is_openclaw_installed() -> bool:
    """Check if OpenClaw CLI or its config exists."""
    return bool(shutil.which("openclaw") or os.path.exists(resolve_openclaw_config_path()))


def get_openclaw_status() -> Dict:
    """Check current OpenClaw model provider configuration."""
    path = resolve_openclaw_config_path()
    if not os.path.exists(path):
        return {"installed": bool(shutil.which("openclaw")), "configured": False, "path": path}

    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)

        primary = cfg.get("agents", {}).get("defaults", {}).get("model", {}).get("primary", "")
        providers = cfg.get("models", {}).get("providers", {})
        ag_prov = providers.get("antigravity", {})
        base_url = ag_prov.get("baseUrl", "")

        is_ag = "antigravity" in primary or "127.0.0.1" in base_url or "localhost" in base_url

        return {
            "installed": True,
            "configured": True,
            "path": path,
            "primary_model": primary,
            "base_url": base_url,
            "is_antigravity": is_ag,
        }
    except Exception as e:
        return {"installed": True, "configured": False, "path": path, "error": str(e)}


def find_sqlite_auth_databases() -> List[str]:
    """Locate all OpenClaw agent SQLite databases."""
    patterns = [
        os.path.expanduser("~/.openclaw/agents/*/agent/openclaw-agent.sqlite"),
        "/root/.openclaw/agents/*/agent/openclaw-agent.sqlite",
    ]
    matches = []
    for pat in patterns:
        matches.extend(glob.glob(pat))
    return list(set(matches))


def update_openclaw_sqlite_auth(api_key: str = "antigravity") -> int:
    """Inject antigravity:manual profile into OpenClaw's SQLite credential store."""
    dbs = find_sqlite_auth_databases()
    updated_count = 0

    for db_path in dbs:
        try:
            con = sqlite3.connect(db_path)
            cur = con.cursor()

            # Check for auth_profile_store
            cur.execute("SELECT store_json FROM auth_profile_store WHERE store_key='primary';")
            row = cur.fetchone()
            if row:
                store = json.loads(row[0])
                if "profiles" not in store:
                    store["profiles"] = {}
                store["profiles"]["antigravity:manual"] = {
                    "type": "api_key",
                    "provider": "antigravity",
                    "key": api_key,
                }
                cur.execute(
                    "UPDATE auth_profile_store SET store_json=?, updated_at=? WHERE store_key='primary';",
                    (json.dumps(store), int(time.time() * 1000)),
                )

            # Check for auth_profile_state
            cur.execute("SELECT state_json FROM auth_profile_state WHERE state_key='primary';")
            row_state = cur.fetchone()
            if row_state:
                state = json.loads(row_state[0])
                if "lastGood" not in state:
                    state["lastGood"] = {}
                state["lastGood"]["antigravity"] = "antigravity:manual"
                cur.execute(
                    "UPDATE auth_profile_state SET state_json=?, updated_at=? WHERE state_key='primary';",
                    (json.dumps(state), int(time.time() * 1000)),
                )

            con.commit()
            con.close()
            updated_count += 1
        except Exception:
            pass

    return updated_count


def configure_openclaw(
    port: int = 8000,
    model: str = "claude-sonnet-4-6",
    api_key: str = "antigravity",
    host: str = "127.0.0.1",
) -> Tuple[bool, str]:
    """Point OpenClaw to the local Antigravity proxy and inject credentials."""
    path = resolve_openclaw_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)

    base_url = f"http://{host}:{port}/v1"

    if os.path.exists(path):
        backup_path = f"{path}.bak.{int(time.time())}"
        shutil.copy2(path, backup_path)
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    else:
        cfg = {}

    if "agents" not in cfg:
        cfg["agents"] = {}
    if "defaults" not in cfg["agents"]:
        cfg["agents"]["defaults"] = {}
    if "model" not in cfg["agents"]["defaults"]:
        cfg["agents"]["defaults"]["model"] = {}

    clean_model_id = model.split("/")[-1]
    cfg["agents"]["defaults"]["model"]["primary"] = f"antigravity/{clean_model_id}"

    if "models" not in cfg:
        cfg["models"] = {}
    if "providers" not in cfg["models"]:
        cfg["models"]["providers"] = {}

    cfg["models"]["providers"]["antigravity"] = {
        "baseUrl": base_url,
        "api": "openai-completions",
        "auth": "api-key",
        "models": AVAILABLE_MODELS,
    }

    if "auth" not in cfg:
        cfg["auth"] = {}
    if "profiles" not in cfg["auth"]:
        cfg["auth"]["profiles"] = {}

    cfg["auth"]["profiles"]["antigravity:manual"] = {
        "provider": "antigravity",
        "mode": "api_key",
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

    db_updated = update_openclaw_sqlite_auth(api_key)

    return True, (
        f"OpenClaw configured to use Antigravity proxy ({base_url}) with primary model 'antigravity/{clean_model_id}'. "
        f"Updated {db_updated} auth database(s)."
    )
