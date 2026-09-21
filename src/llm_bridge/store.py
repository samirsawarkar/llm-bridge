"""~/.llm-bridge/keys.json and config.json."""
import hmac
import json
import os
import secrets
from datetime import datetime, timezone

DIR = os.path.expanduser(os.environ.get("LLM_BRIDGE_HOME", "~/.llm-bridge"))
KEYS = os.path.join(DIR, "keys.json")
CONFIG = os.path.join(DIR, "config.json")
DEFAULTS = {"host": "127.0.0.1", "port": 8000, "default_provider": None}


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _write(path, data):
    os.makedirs(DIR, mode=0o700, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def load_keys():
    return _read(KEYS)


def create_key(name):
    keys = load_keys()
    if name in keys:
        raise ValueError("key '%s' already exists" % name)
    keys[name] = {"key": "sk-lb-" + secrets.token_hex(20),
                  "created": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    _write(KEYS, keys)
    return keys[name]["key"]


def revoke_key(name):
    keys = load_keys()
    if name not in keys:
        raise KeyError(name)
    del keys[name]
    _write(KEYS, keys)


def verify_key(presented):
    if not presented:
        return False
    ok = False
    for k in load_keys().values():  # ponytail: file read per request; cache if >100 rps ever matters
        ok |= hmac.compare_digest(k["key"], presented)
    return ok


def mask(key):
    return key[:10] + "…" + key[-2:]


def load_config():
    cfg = dict(DEFAULTS)
    cfg.update(_read(CONFIG))
    for k in DEFAULTS:
        v = os.environ.get("LLM_BRIDGE_" + k.upper())
        if v:
            cfg[k] = int(v) if k == "port" else v
    return cfg


def save_config(**kv):
    cfg = _read(CONFIG)
    cfg.update(kv)
    _write(CONFIG, cfg)
