"""llm-bridge command line."""
import argparse
import json
import sys
import urllib.error
import urllib.request

from . import __version__, providers, service, store
from .connect.hermes import configure_hermes, get_hermes_status
from .connect.openclaw import configure_openclaw, get_openclaw_status
from .server import serve

OK, BAD, WARN = "✓", "✗", "!"


def _first_key():
    keys = store.load_keys()
    return next(iter(keys.values()))["key"] if keys else None


def _base(a):
    cfg = store.load_config()
    return a.host or cfg["host"], a.port or cfg["port"], cfg


def banner(host, port, new_key=None):
    print("LLM Bridge  http://%s:%d/v1" % (host, port))
    if new_key:
        print("API key     %s   (new; shown once — llm-bridge keys list to see masked)" % new_key)
    else:
        k = _first_key()
        print("API key     %s   (llm-bridge keys list)" % (store.mask(k) if k else "none — run: llm-bridge keys create default"))
    print()
    print("Providers")
    for p in providers.PROVIDERS.values():
        st = p.auth_status()
        mark = OK if st["ok"] else BAD
        print("  %-12s %s %-16s %s" % (p.name, mark, st["state"], "" if st["ok"] else "→ " + st["fix"]))
    ids = [m["id"] for m in providers.list_models()]
    print()
    print("Models      " + ("  ".join(ids[:4]) + ("  … (llm-bridge models)" if len(ids) > 4 else "") if ids else "none (log in to a provider above)"))
    if host not in ("127.0.0.1", "localhost", "::1"):
        print("\n[%s] bound to %s — reachable from other machines; API keys are the only protection" % (WARN, host))
    print()


def cmd_up(a):
    host, port, cfg = _base(a)
    new = store.create_key("default") if not store.load_keys() else None
    banner(host, port, new)
    serve(host, port, cfg)
    return 0


def cmd_keys(a):
    if a.action == "create":
        try:
            print(store.create_key(a.name))
        except ValueError as e:
            print("[%s] %s" % (BAD, e))
            return 1
    elif a.action == "list":
        keys = store.load_keys()
        if not keys:
            print("no keys — run: llm-bridge keys create default")
        for n, k in keys.items():
            print("%-16s %s   created %s" % (n, store.mask(k["key"]), k["created"]))
    elif a.action == "revoke":
        try:
            store.revoke_key(a.name)
            print("[%s] revoked %s" % (OK, a.name))
        except KeyError:
            print("[%s] no key named %s" % (BAD, a.name))
            return 1
    return 0


def cmd_models(a):
    print("%-40s %-34s %s" % ("Model", "Name", "Status"))
    print("-" * 90)
    for p in providers.PROVIDERS.values():
        st = p.auth_status()
        status = (OK + " available") if st["ok"] else ("%s %s → %s" % (BAD, st["state"], st["fix"]))
        for m in p.catalog:
            print("%-40s %-34s %s" % ("%s/%s" % (p.name, m["id"]), m["name"], status))
    return 0


def cmd_status(a):
    host, port, _ = _base(a)
    try:
        with urllib.request.urlopen("http://%s:%d/health" % (host, port), timeout=2) as r:
            up = r.status == 200
    except Exception:
        up = False
    print("Server       %s http://%s:%d/v1 %s" % (OK if up else BAD, host, port, "responding" if up else "not running (llm-bridge up)"))
    print("Keys         %d (llm-bridge keys list)" % len(store.load_keys()))
    print("Service      %s" % (service.ctl("status")[1] if service.installed() else "not installed (llm-bridge service install)"))
    for p in providers.PROVIDERS.values():
        st = p.auth_status()
        print("%-12s %s %s %s" % (p.name, OK if st["ok"] else BAD, st["state"], "" if st["ok"] else "→ " + st["fix"]))
    h, o = get_hermes_status(), get_openclaw_status()
    if h.get("installed"):
        print("Hermes       %s %s" % (OK if h.get("is_bridge") else WARN, h.get("model") or "installed"))
    if o.get("installed"):
        print("OpenClaw     %s %s" % (OK if o.get("is_bridge") else WARN, o.get("primary_model") or "installed"))
    return 0


def cmd_test(a):
    host, port, _ = _base(a)
    key = _first_key()
    if not key:
        print("[%s] no API key — run: llm-bridge keys create default" % BAD)
        return 1
    model = a.model or next((m["id"] for m in providers.list_models()), None)
    if not model:
        print("[%s] no authenticated provider" % BAD)
        return 1
    print("POST http://%s:%d/v1/chat/completions  model=%s" % (host, port, model))
    req = urllib.request.Request("http://%s:%d/v1/chat/completions" % (host, port),
                                 data=json.dumps({"model": model, "messages": [{"role": "user", "content": a.prompt}], "max_tokens": 64}).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.load(r)
        print("[%s] %s" % (OK, (d["choices"][0]["message"].get("content") or "").strip()[:200]))
        return 0
    except urllib.error.HTTPError as e:
        print("[%s] HTTP %d: %s" % (BAD, e.code, e.read().decode("utf-8", "replace")[:300]))
    except Exception as e:
        print("[%s] %s" % (BAD, e))
    return 1


def cmd_service(a):
    host, port, _ = _base(a)
    if a.action == "install":
        ok, msg = service.install(host, port)
    elif a.action == "uninstall":
        ok, msg = service.uninstall(), "removed"
    else:
        ok, msg = service.ctl(a.action)
    print("[%s] %s" % (OK if ok else BAD, msg))
    return 0 if ok else 1


def cmd_connect(a):
    host, port, _ = _base(a)
    key = _first_key() or store.create_key("default")
    fn = configure_hermes if a.client == "hermes" else configure_openclaw
    ok, msg = fn(port=port, model=a.model, api_key=key, host=host)
    print("[%s] %s" % (OK if ok else BAD, msg))
    return 0 if ok else 1


def main():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--host", default=None, help="bind host (default: config or 127.0.0.1)")
    common.add_argument("--port", type=int, default=None, help="bind port (default: config or 8000)")
    p = argparse.ArgumentParser(prog="llm-bridge", description="Local OpenRouter-style API over your CLI OAuth sessions.", parents=[common])
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("up", parents=[common], help="start the server in the foreground").set_defaults(func=cmd_up)
    k = sub.add_parser("keys", parents=[common], help="manage API keys")
    k.add_argument("action", choices=["create", "list", "revoke"])
    k.add_argument("name", nargs="?", default="default")
    k.set_defaults(func=cmd_keys)
    sub.add_parser("models", parents=[common], help="list provider/model ids and auth state").set_defaults(func=cmd_models)
    sub.add_parser("status", parents=[common], help="server, keys, providers, clients").set_defaults(func=cmd_status)
    t = sub.add_parser("test", parents=[common], help="live round-trip through the local server")
    t.add_argument("model", nargs="?")
    t.add_argument("--prompt", default="Reply with exactly: bridge OK")
    t.set_defaults(func=cmd_test)
    s = sub.add_parser("service", parents=[common], help="background service (launchd / systemd)")
    s.add_argument("action", choices=["install", "uninstall", "start", "stop", "restart", "status"])
    s.set_defaults(func=cmd_service)
    c = sub.add_parser("connect", parents=[common], help="point a client at the bridge")
    c.add_argument("client", choices=["hermes", "openclaw"])
    c.add_argument("--model", default="antigravity/gemini-3.8-flash")
    c.set_defaults(func=cmd_connect)
    a = p.parse_args()
    if not a.cmd:
        return cmd_status(a)
    return a.func(a) or 0


if __name__ == "__main__":
    sys.exit(main())
