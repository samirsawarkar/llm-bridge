"""Hermes agent configuration manager."""

import os
import re
import shutil
import time
from typing import Dict, Optional, Tuple

DEFAULT_HERMES_CONFIG_PATHS = [
    os.path.expanduser("~/.hermes/config.yaml"),
    "/root/.hermes/config.yaml",
]


def resolve_hermes_config_path() -> str:
    """Find the Hermes config.yaml path."""
    for p in DEFAULT_HERMES_CONFIG_PATHS:
        if os.path.exists(p):
            return p
    return DEFAULT_HERMES_CONFIG_PATHS[0]


def is_hermes_installed() -> bool:
    """Check if Hermes CLI or its config exists."""
    return bool(shutil.which("hermes") or os.path.exists(resolve_hermes_config_path()))


def get_hermes_status() -> Dict:
    """Check current Hermes model provider configuration."""
    path = resolve_hermes_config_path()
    if not os.path.exists(path):
        return {"installed": bool(shutil.which("hermes")), "configured": False, "path": path}

    try:
        try:
            import yaml
            with open(path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            m = cfg.get("model", {})
            return {
                "installed": True,
                "configured": True,
                "path": path,
                "provider": m.get("provider"),
                "base_url": m.get("base_url"),
                "model": m.get("default"),
                "is_antigravity": "127.0.0.1" in str(m.get("base_url", "")) or "localhost" in str(m.get("base_url", "")),
            }
        except ImportError:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read()
            m_prov = re.search(r"provider:\s*([^\n]+)", raw)
            m_url = re.search(r"base_url:\s*([^\n]+)", raw)
            m_def = re.search(r"default:\s*([^\n]+)", raw)
            base_url = m_url.group(1).strip() if m_url else ""
            return {
                "installed": True,
                "configured": True,
                "path": path,
                "provider": m_prov.group(1).strip() if m_prov else "",
                "base_url": base_url,
                "model": m_def.group(1).strip() if m_def else "",
                "is_antigravity": "127.0.0.1" in base_url or "localhost" in base_url,
            }
    except Exception as e:
        return {"installed": True, "configured": False, "path": path, "error": str(e)}


def configure_hermes(
    port: int = 8000,
    model: str = "claude-sonnet-4-6",
    api_key: str = "antigravity",
    host: str = "127.0.0.1",
) -> Tuple[bool, str]:
    """Point Hermes to the local Antigravity proxy."""
    path = resolve_hermes_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)

    base_url = f"http://{host}:{port}/v1"

    # Backup existing config if present
    if os.path.exists(path):
        backup_path = f"{path}.bak.{int(time.time())}"
        shutil.copy2(path, backup_path)

    try:
        import yaml
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        else:
            cfg = {}

        if "model" not in cfg or not isinstance(cfg["model"], dict):
            cfg["model"] = {}

        cfg["model"]["provider"] = "custom"
        cfg["model"]["base_url"] = base_url
        cfg["model"]["api_key"] = api_key
        cfg["model"]["default"] = model

        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, default_flow_style=False)

        return True, f"Hermes configured to use Antigravity proxy ({base_url}) with model '{model}'"
    except ImportError:
        # Fallback pure-regex updater
        content = ""
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

        new_model_block = (
            f"model:\n"
            f"  provider: custom\n"
            f"  base_url: {base_url}\n"
            f"  api_key: {api_key}\n"
            f"  default: {model}\n"
        )

        if re.search(r"^model:\s*(\n\s+.*)*", content, flags=re.MULTILINE):
            content = re.sub(r"^model:\s*(\n\s+.*)*", new_model_block, content, flags=re.MULTILINE)
        else:
            content = new_model_block + "\n" + content

        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        return True, f"Hermes configured via standard text replacement ({base_url})"
    except Exception as e:
        return False, f"Failed to configure Hermes: {e}"
