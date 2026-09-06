"""Unified Command Line Interface for Antigravity Bridge."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from typing import Optional

from .auth import check_token_status, get_auth_token, resolve_agy_bin, resolve_token_path, verify_upstream_access
from .config_hermes import configure_hermes, get_hermes_status, is_hermes_installed
from .config_openclaw import configure_openclaw, get_openclaw_status, is_openclaw_installed
from .models import AVAILABLE_MODELS
from .proxy import run_proxy

SYSTEMD_SERVICE_FILE = "/etc/systemd/system/antigravity-proxy.service"


def cmd_auth(args):
    """Inspect, refresh, and verify Antigravity authentication."""
    print("=== Antigravity OAuth Authentication Status ===")
    status = check_token_status(args.token_file)
    if not status.get("found"):
        print(f"[!] Token file NOT found at: {status.get('path')}")
        print("Please run 'agy' or 'agy login' to authenticate with your Google account first.")
        agy_bin = resolve_agy_bin(args.agy_bin)
        if agy_bin and shutil.which(agy_bin):
            print(f"Found agy binary at: {agy_bin}")
            choice = input("Would you like to run 'agy' now to log in? [y/N]: ").strip().lower()
            if choice == "y":
                subprocess.run([agy_bin])
        return 1

    print(f"[✓] Token file found: {status['path']}")
    print(f"    Auth Method: {status.get('auth_method')}")
    print(f"    Expiry: {status.get('expiry')}")

    if status.get("expired"):
        print("[!] Token is expired or expiring within 60s. Triggering refresh...")
        token = get_auth_token(args.token_file, args.agy_bin, force_refresh=True)
        if token:
            print("[✓] Token refreshed successfully.")
        else:
            print("[x] Automatic token refresh failed.")
            return 1
    else:
        rem_mins = round(status.get("seconds_remaining", 0) / 60, 1)
        print(f"[✓] Token is active (~{rem_mins} minutes remaining).")
        token = get_auth_token(args.token_file, args.agy_bin)

    print("Verifying connection to Google Antigravity Cloud Code backend...")
    ok, msg = verify_upstream_access(token)
    if ok:
        print(f"[✓] Backend status: {msg}")
        return 0
    else:
        print(f"[x] Verification failed: {msg}")
        return 1


def cmd_status(args):
    """Print complete diagnostics of proxy, auth, and connected agents."""
    print("=========================================================")
    print("               Antigravity Bridge Status                 ")
    print("=========================================================")

    # 1. Token status
    tok_status = check_token_status(args.token_file)
    if tok_status.get("found"):
        exp_txt = "EXPIRED" if tok_status.get("expired") else "VALID"
        rem_m = round(tok_status.get("seconds_remaining", 0) / 60, 1)
        print(f"Antigravity Token:   [✓] Present ({exp_txt}, ~{rem_m}m remaining)")
        print(f"  Token Path:        {tok_status.get('path')}")
    else:
        print("Antigravity Token:   [x] NOT FOUND (run 'antigravity-bridge auth')")

    # 2. Proxy service status
    is_systemd = os.path.exists("/bin/systemctl") or os.path.exists("/usr/bin/systemctl")
    proxy_running = False
    if is_systemd and os.path.exists(SYSTEMD_SERVICE_FILE):
        res = subprocess.run(["systemctl", "is-active", "antigravity-proxy.service"], capture_output=True, text=True)
        active_state = res.stdout.strip()
        proxy_running = active_state == "active"
        stat_icon = "[✓]" if proxy_running else "[!]"
        print(f"Proxy Service:       {stat_icon} systemd ({active_state})")
    else:
        # Check port
        try:
            with urllib.request.urlopen(f"http://{args.host}:{args.port}/health", timeout=2) as r:
                proxy_running = r.status == 200
        except Exception:
            proxy_running = False
        stat_icon = "[✓]" if proxy_running else "[x]"
        print(f"Proxy Service:       {stat_icon} Port {args.port} ({'responding' if proxy_running else 'inactive'})")

    # 3. Hermes status
    h_stat = get_hermes_status()
    if h_stat.get("installed"):
        h_icon = "[✓]" if h_stat.get("is_antigravity") else "[!]"
        print(f"Hermes Agent:        {h_icon} Installed")
        if h_stat.get("configured"):
            print(f"  Provider:          {h_stat.get('provider')}")
            print(f"  Base URL:          {h_stat.get('base_url')}")
            print(f"  Default Model:     {h_stat.get('model')}")
    else:
        print("Hermes Agent:        [ ] Not detected")

    # 4. OpenClaw status
    oc_stat = get_openclaw_status()
    if oc_stat.get("installed"):
        oc_icon = "[✓]" if oc_stat.get("is_antigravity") else "[!]"
        print(f"OpenClaw Agent:      {oc_icon} Installed")
        if oc_stat.get("configured"):
            print(f"  Primary Model:     {oc_stat.get('primary_model')}")
            print(f"  Base URL:          {oc_stat.get('base_url')}")
    else:
        print("OpenClaw Agent:      [ ] Not detected")

    print("=========================================================")
    return 0


def cmd_models(args):
    """List available models or switch the active default model."""
    if args.set:
        target_model = args.set
        agent = (args.agent or "both").lower()
        print(f"Switching default model to: {target_model}")
        if agent in ("hermes", "both"):
            ok, msg = configure_hermes(port=args.port, model=target_model, host=args.host)
            print(f"[Hermes] {msg}")
        if agent in ("openclaw", "both"):
            ok, msg = configure_openclaw(port=args.port, model=target_model, host=args.host)
            print(f"[OpenClaw] {msg}")
        return 0

    print("=== Available Antigravity Models ===")
    print(f"{'Model ID':<30} {'Display Name':<30}")
    print("-" * 60)
    for m in AVAILABLE_MODELS:
        print(f"{m['id']:<30} {m['name']:<30}")
    print("-" * 60)
    print("Switch active model using: antigravity-bridge models --set <model-id>")
    return 0


def install_systemd_service(port: int = 8000, host: str = "127.0.0.1") -> bool:
    """Create and enable the systemd service unit."""
    if not (os.path.exists("/bin/systemctl") or os.path.exists("/usr/bin/systemctl")):
        return False

    py_bin = sys.executable
    service_content = f"""[Unit]
Description=Antigravity OpenAI-Compatible Proxy Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root
ExecStart={py_bin} -m antigravity_bridge.cli serve --port {port} --host {host}
Restart=always
RestartSec=3
Environment=PORT={port}
Environment=HOST={host}
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
"""
    try:
        with open(SYSTEMD_SERVICE_FILE, "w", encoding="utf-8") as f:
            f.write(service_content)
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "enable", "--now", "antigravity-proxy.service"], check=True)
        return True
    except Exception as e:
        print(f"[!] Warning: Could not install systemd service: {e}")
        return False


def cmd_setup(args):
    """Setup and connect OpenClaw, Hermes, or both."""
    print("=========================================================")
    print("           Antigravity Bridge Setup Wizard               ")
    print("=========================================================")

    # 1. Auth check
    tok = get_auth_token(args.token_file, args.agy_bin)
    if not tok:
        print("[!] Antigravity token not found.")
        print("Please authenticate using 'antigravity-bridge auth' or run 'agy' before continuing.")
        return 1

    # 2. Agent selection
    target_agent = args.agent
    if not target_agent:
        print("\nWhich agent(s) do you want to connect to Antigravity?")
        print("  1) OpenClaw only")
        print("  2) Hermes only")
        print("  3) Both OpenClaw and Hermes")
        choice = input("Enter choice [1-3] (default: 3): ").strip()
        if choice == "1":
            target_agent = "openclaw"
        elif choice == "2":
            target_agent = "hermes"
        else:
            target_agent = "both"

    # 3. Model selection
    target_model = args.model
    if not target_model:
        print("\nSelect default model:")
        print("  1) gemini-3.8-flash (Recommended: fast, high quality)")
        print("  2) claude-sonnet-4-6 (Deep agentic reasoning)")
        print("  3) gemini-2.5-pro (High capability Gemini)")
        print("  4) gemini-2.5-flash (Ultra fast)")
        m_choice = input("Enter choice [1-4] (default: 1): ").strip()
        if m_choice == "2":
            target_model = "claude-sonnet-4-6"
        elif m_choice == "3":
            target_model = "gemini-2.5-pro"
        elif m_choice == "4":
            target_model = "gemini-2.5-flash"
        else:
            target_model = "gemini-3.8-flash"

    # 4. Service installation
    print(f"\nInstalling & starting background proxy service on {args.host}:{args.port}...")
    installed_service = install_systemd_service(port=args.port, host=args.host)
    if installed_service:
        print("[✓] Background service active: antigravity-proxy.service")
    else:
        print("[i] Non-systemd environment. You can start the proxy with: antigravity-bridge serve")

    # 5. Configure agents
    if target_agent in ("hermes", "both"):
        ok, msg = configure_hermes(port=args.port, model=target_model, host=args.host)
        print(f"[✓] {msg}")

    if target_agent in ("openclaw", "both"):
        ok, msg = configure_openclaw(port=args.port, model=target_model, host=args.host)
        print(f"[✓] {msg}")

    # 6. Verification test
    if not args.no_test:
        print("\nRunning verification test...")
        cmd_test(argparse.Namespace(agent=target_agent, prompt="Reply with 'Connection OK!' in 3 words.", port=args.port, host=args.host))

    print("\n[✓] Setup complete! Your agents are now powered by Antigravity.")
    return 0


def cmd_test(args):
    """Run a live verification prompt through the proxy and agent(s)."""
    agent = (args.agent or "both").lower()
    prompt = args.prompt or "Say: Antigravity connection verified!"

    # 1. Direct proxy check
    print(f"Testing direct proxy endpoint (http://{args.host}:{args.port}/v1/chat/completions)...")
    req_body = json.dumps({
        "model": "gemini-3.8-flash",
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")

    try:
        r = urllib.request.Request(
            f"http://{args.host}:{args.port}/v1/chat/completions",
            headers={"Content-Type": "application/json", "Authorization": "Bearer antigravity"},
            data=req_body,
        )
        with urllib.request.urlopen(r, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            ans = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            print(f"[✓] Direct proxy replied: {ans[:80]}")
    except Exception as e:
        print(f"[x] Direct proxy test failed: {e}")

    # 2. Hermes CLI test
    if agent in ("hermes", "both") and shutil.which("hermes"):
        print("\nTesting Hermes CLI execution...")
        try:
            res = subprocess.run(["hermes", "chat", "-q", prompt], capture_output=True, text=True, timeout=30)
            if res.returncode == 0:
                print(f"[✓] Hermes response succeeded (code 0).")
            else:
                print(f"[!] Hermes returned code {res.returncode}: {res.stderr[:200]}")
        except Exception as e:
            print(f"[!] Hermes execution error: {e}")

    # 3. OpenClaw CLI test
    if agent in ("openclaw", "both") and shutil.which("openclaw"):
        print("\nTesting OpenClaw CLI execution...")
        try:
            res = subprocess.run(["openclaw", "agent", "--message", prompt], capture_output=True, text=True, timeout=30)
            if res.returncode == 0:
                print(f"[✓] OpenClaw response: {res.stdout.strip()[:80]}")
            else:
                print(f"[!] OpenClaw returned code {res.returncode}: {res.stderr[:200]}")
        except Exception as e:
            print(f"[!] OpenClaw execution error: {e}")

    return 0


def cmd_service(args):
    """Manage the systemd service."""
    action = args.action
    if action == "install":
        ok = install_systemd_service(port=args.port, host=args.host)
        print("[✓] Service installed and started" if ok else "[x] Failed to install service")
    elif action in ("start", "stop", "restart", "status"):
        subprocess.run(["systemctl", action, "antigravity-proxy.service"])
    elif action == "uninstall":
        subprocess.run(["systemctl", "stop", "antigravity-proxy.service"])
        subprocess.run(["systemctl", "disable", "antigravity-proxy.service"])
        if os.path.exists(SYSTEMD_SERVICE_FILE):
            os.remove(SYSTEMD_SERVICE_FILE)
            subprocess.run(["systemctl", "daemon-reload"])
        print("[✓] Service uninstalled.")
    return 0


def cmd_serve(args):
    """Run proxy server foreground loop."""
    run_proxy(
        host=args.host,
        port=args.port,
        token_file=args.token_file,
        agy_bin=args.agy_bin,
    )
    return 0


def main():
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")), help="Proxy server port (default: 8000)")
    common_parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"), help="Proxy server host (default: 127.0.0.1)")
    common_parser.add_argument("--token-file", default=None, help="Path to Antigravity OAuth token file")
    common_parser.add_argument("--agy-bin", default=None, help="Path to agy binary executable")

    parser = argparse.ArgumentParser(
        prog="antigravity-bridge",
        description="Connect OpenClaw and Hermes to Google Antigravity OAuth session via local OpenAI proxy.",
        parents=[common_parser],
    )

    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # setup
    p_setup = subparsers.add_parser("setup", parents=[common_parser], help="Interactive or automated setup for OpenClaw and Hermes")
    p_setup.add_argument("--agent", choices=["openclaw", "hermes", "both"], help="Agent to configure")
    p_setup.add_argument("--model", default=None, help="Default model name (e.g. gemini-3.8-flash)")
    p_setup.add_argument("--no-test", action="store_true", help="Skip post-setup verification test")
    p_setup.set_defaults(func=cmd_setup)

    # auth
    p_auth = subparsers.add_parser("auth", parents=[common_parser], help="Verify or refresh Antigravity OAuth credentials")
    p_auth.set_defaults(func=cmd_auth)

    # status
    p_status = subparsers.add_parser("status", parents=[common_parser], help="Show health status of auth, proxy, and agents")
    p_status.set_defaults(func=cmd_status)

    # models
    p_models = subparsers.add_parser("models", parents=[common_parser], help="List available models or switch active model")
    p_models.add_argument("--set", dest="set", help="Set active model ID")
    p_models.add_argument("--agent", choices=["openclaw", "hermes", "both"], default="both", help="Target agent to update")
    p_models.set_defaults(func=cmd_models)

    # serve
    p_serve = subparsers.add_parser("serve", parents=[common_parser], help="Run the proxy server in the foreground")
    p_serve.set_defaults(func=cmd_serve)

    # service
    p_service = subparsers.add_parser("service", parents=[common_parser], help="Manage background systemd service")
    p_service.add_argument("action", choices=["start", "stop", "restart", "status", "install", "uninstall"])
    p_service.set_defaults(func=cmd_service)

    # test
    p_test = subparsers.add_parser("test", parents=[common_parser], help="Run a verification test turn against proxy and agents")
    p_test.add_argument("--agent", choices=["openclaw", "hermes", "both"], default="both", help="Target agent to test")
    p_test.add_argument("--prompt", default=None, help="Prompt text to send")
    p_test.set_defaults(func=cmd_test)

    args = parser.parse_args()
    if not args.subcommand:
        # Default to status if no subcommand passed
        cmd_status(args)
        return

    sys.exit(args.func(args) or 0)


if __name__ == "__main__":
    main()
