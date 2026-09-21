"""Claude Code OAuth provider: reuse the `claude` CLI session against api.anthropic.com/v1/messages."""
import getpass
import json
import os
import re
import subprocess
import sys
import time

from ..ir import text_of
from .base import Provider, UpstreamError, http, open_upstream, sse

# Verify against the installed CLI if anything 401s: these are Claude Code's public OAuth client + endpoints.
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
TOKEN_URL = "https://api.anthropic.com/v1/oauth/token"
API_URL = "https://api.anthropic.com/v1/messages"
CRED_FILE = os.path.expanduser("~/.claude/.credentials.json")
KEYCHAIN_SERVICE = "Claude Code-credentials"
IDENTITY = "You are Claude Code, Anthropic's official CLI for Claude."
BETA = "oauth-2025-04-20,interleaved-thinking-2025-05-14"
STOP = {"end_turn": "stop", "stop_sequence": "stop", "tool_use": "tool_calls", "max_tokens": "length"}


class Anthropic(Provider):
    name = "anthropic"
    native_fmt = "anthropic"
    prefixes = ("claude-",)
    login_hint = "run: claude   (then /login)"
    catalog = [
        {"id": "claude-fable-5-1", "name": "Claude Fable 5.1"},
        {"id": "claude-opus-5", "name": "Claude Opus 5"},
        {"id": "claude-sonnet-5", "name": "Claude Sonnet 5"},
        {"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5"},
        {"id": "claude-opus-4-6", "name": "Claude Opus 4.6"},
        {"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6"},
    ]
    aliases = {"claude-opus": "claude-opus-5", "claude-sonnet": "claude-sonnet-5", "claude-haiku": "claude-haiku-4-5-20251001"}

    def _raw(self):
        """-> (json_dict, source). Prefer whichever store actually holds a token; keychain and file
        can both exist and either may be the empty/placeholder one (varies by Claude Code version)."""
        sources = []
        if sys.platform == "darwin":
            try:
                r = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"], capture_output=True, text=True, timeout=5)
                if r.returncode == 0 and r.stdout.strip():
                    sources.append((json.loads(r.stdout.strip()), "keychain"))
            except Exception:
                pass
        try:
            with open(CRED_FILE, encoding="utf-8") as f:
                sources.append((json.load(f), CRED_FILE))
        except (OSError, ValueError):
            pass
        return _pick(sources)

    def _load(self):
        data, src = self._raw()
        o = (data or {}).get("claudeAiOauth") or {}
        if not o.get("accessToken"):
            return None
        return {"access": o["accessToken"], "refresh": o.get("refreshToken"), "expires_at": (o.get("expiresAt") or 0) / 1000.0, "_data": data, "_src": src}

    def _refresh(self, cred):
        if not cred.get("refresh"):
            return None
        try:
            with http(TOKEN_URL, {"grant_type": "refresh_token", "refresh_token": cred["refresh"], "client_id": CLIENT_ID}, {"User-Agent": "claude-cli/2.0.0 (external, cli)"}, timeout=20) as r:
                res = json.load(r)
        except Exception:
            return None
        o = cred["_data"]["claudeAiOauth"]
        o["accessToken"] = res["access_token"]
        o["refreshToken"] = res.get("refresh_token") or cred["refresh"]
        o["expiresAt"] = int((time.time() + res.get("expires_in", 3600)) * 1000)
        self._save(cred["_data"], cred["_src"])
        new = self._load()
        if not new or new["access"] != res["access_token"]:  # refresh tokens rotate: a lost write-back logs the CLI out
            print("[anthropic] WARNING: refreshed token did not persist to %s; run `claude` and /login if the CLI stops working" % cred["_src"], flush=True)
        return new

    def _keychain_account(self):
        """Account name of the existing keychain item, so the write-back updates it instead of creating a twin."""
        try:
            r = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE], capture_output=True, text=True, timeout=5)
            m = re.search(r'"acct"<blob>="([^"]*)"', r.stdout)
            if m:
                return m.group(1)
        except Exception:
            pass
        return getpass.getuser()

    def _save(self, data, src):
        blob = json.dumps(data)
        if src == "keychain":  # same mechanism Claude Code itself uses; token is briefly visible in `ps`
            subprocess.run(["security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE, "-a", self._keychain_account(), "-w", blob], capture_output=True, timeout=5)
        else:
            tmp = src + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(blob)
            os.chmod(tmp, 0o600)
            os.replace(tmp, src)

    def _headers(self, tok, client_headers=None):
        beta = (client_headers or {}).get("anthropic-beta", "")
        if "oauth-2025-04-20" not in beta:
            beta = BETA if not beta else beta + ",oauth-2025-04-20"
        return {"Authorization": "Bearer " + tok, "anthropic-version": (client_headers or {}).get("anthropic-version", "2023-06-01"),
                "anthropic-beta": beta, "Accept": "text/event-stream", "User-Agent": "claude-cli/2.0.0 (external, cli)"}

    def stream(self, request, model):
        body = to_messages(request, model)
        try:
            resp = open_upstream(self, lambda tok: http(API_URL, body, self._headers(tok)))
        except UpstreamError as e:
            yield ("error", {"status": e.status, "message": e.message})
            return
        for ev in events_from_messages(resp):
            yield ev

    def passthrough(self, body, headers, model):
        body = ensure_identity(dict(body, model=model))
        return open_upstream(self, lambda tok: http(API_URL, body, self._headers(tok, headers)))



def _pick(sources):
    """From [(data, src), ...] choose the first with a non-empty accessToken, else the first that parsed."""
    fallback = (None, None)
    for data, src in sources:
        if isinstance(data, dict):
            if (data.get("claudeAiOauth") or {}).get("accessToken"):
                return data, src
            fallback = (data, src)
    return fallback


def ensure_identity(body):
    """OAuth tokens are only honoured when the first system block is the Claude Code identity line."""
    s = body.get("system")
    blocks = [{"type": "text", "text": s}] if isinstance(s, str) else list(s or [])
    blocks = [b for b in blocks if b.get("type") != "text" or str(b.get("text", "")).strip()]  # Anthropic rejects empty text blocks
    if not blocks or not str(blocks[0].get("text", "")).startswith(IDENTITY):
        blocks.insert(0, {"type": "text", "text": IDENTITY})
    body["system"] = blocks
    return body


def to_messages(request, model):
    """IR Request -> Anthropic Messages body (streaming)."""
    system, msgs = [], []
    for m in request["messages"]:
        role = m.get("role")
        if role == "system":
            system.append(text_of(m.get("content")))
        elif role == "user":
            msgs.append({"role": "user", "content": [{"type": "text", "text": text_of(m.get("content")) or "(empty)"}]})  # ponytail: images dropped; add base64 image blocks when a client needs them
        elif role == "assistant":
            blocks = []
            if text_of(m.get("content")):
                blocks.append({"type": "text", "text": text_of(m["content"])})
            for tc in m.get("tool_calls") or []:
                try:
                    inp = json.loads(tc.get("arguments") or "{}")
                except ValueError:
                    inp = {}
                blocks.append({"type": "tool_use", "id": tc.get("id", ""), "name": tc.get("name", ""), "input": inp})
            if blocks:
                msgs.append({"role": "assistant", "content": blocks})
        elif role == "tool":
            msgs.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": m.get("tool_call_id", ""), "content": text_of(m.get("content"))}]})
    merged = []  # Anthropic requires strict user/assistant alternation
    for m in msgs:
        if merged and merged[-1]["role"] == m["role"]:
            merged[-1]["content"] += m["content"]
        else:
            merged.append(m)
    body = {"model": model, "messages": merged or [{"role": "user", "content": [{"type": "text", "text": "(empty)"}]}],
            "system": "\n\n".join(s for s in system if s), "max_tokens": request.get("max_tokens") or 8192, "stream": True}
    ensure_identity(body)
    if request.get("temperature") is not None:
        body["temperature"] = request["temperature"]
    if request.get("tools"):
        body["tools"] = [{"name": t["name"], "description": t.get("description", ""), "input_schema": t.get("parameters") or {"type": "object", "properties": {}}} for t in request["tools"]]
    return body


def events_from_messages(lines):
    """Anthropic Messages SSE -> Events."""
    tools = {}  # index -> {"id","name","json":[...]}
    usage = {"prompt_tokens": 0, "completion_tokens": 0}
    for _, d in sse(lines):
        t = d.get("type")
        if t == "content_block_start":
            cb = d.get("content_block") or {}
            if cb.get("type") == "tool_use":
                tools[d.get("index")] = {"id": cb.get("id", ""), "name": cb.get("name", ""), "json": []}
        elif t == "content_block_delta":
            delta = d.get("delta") or {}
            dt = delta.get("type")
            if dt == "text_delta":
                yield ("text", delta.get("text", ""))
            elif dt == "thinking_delta":
                yield ("thinking", delta.get("thinking", ""))
            elif dt == "input_json_delta" and d.get("index") in tools:
                tools[d["index"]]["json"].append(delta.get("partial_json", ""))
        elif t == "content_block_stop" and d.get("index") in tools:
            tc = tools.pop(d["index"])
            yield ("tool_call", {"id": tc["id"], "name": tc["name"], "arguments": "".join(tc["json"]) or "{}"})
        elif t == "message_start":
            usage["prompt_tokens"] = (d.get("message") or {}).get("usage", {}).get("input_tokens", 0)
        elif t == "message_delta":
            usage["completion_tokens"] = (d.get("usage") or {}).get("output_tokens", usage["completion_tokens"])
            yield ("usage", dict(usage))
            yield ("finish", STOP.get((d.get("delta") or {}).get("stop_reason"), "stop"))
            return
        elif t == "error":
            yield ("error", {"status": 502, "message": (d.get("error") or {}).get("message", "upstream error")})
            return
    yield ("usage", dict(usage))
    yield ("finish", "stop")
