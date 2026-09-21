"""Codex OAuth provider: reuse the `codex` CLI session against chatgpt.com/backend-api/codex/responses."""
import base64
import json
import os
import time
import urllib.request
from datetime import datetime, timezone

from ..ir import text_of
from .base import Provider, UpstreamError, http, open_upstream, sse

# Verify against the installed CLI if anything 401s: these are Codex CLI's public OAuth client + endpoints.
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
TOKEN_URL = "https://auth.openai.com/oauth/token"
API_URL = "https://chatgpt.com/backend-api/codex/responses"
MODELS_URL = "https://chatgpt.com/backend-api/codex/models?client_version=1.0.0"
AUTH_FILE = os.path.expanduser(os.environ.get("CODEX_HOME", "~/.codex") + "/auth.json")


def jwt_claims(tok):
    try:
        part = tok.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except Exception:
        return {}


class OpenAI(Provider):
    name = "openai"
    native_fmt = "responses"
    prefixes = ("gpt-", "o1", "o3", "o4", "codex")
    login_hint = "run: codex login"
    SEED = [{"id": "gpt-5.5", "name": "GPT-5.5"}]  # only used until the backend answers
    _catalog, _catalog_at = None, 0.0

    @property
    def catalog(self):
        """The set of models a ChatGPT account may use changes; ask the backend (cached 10 min)."""
        if time.time() - self._catalog_at > 600:
            self._catalog_at = time.time()
            tok = self.token()
            if tok:
                try:
                    h = self._headers(tok)
                    h.pop("Accept", None)
                    with urllib.request.urlopen(urllib.request.Request(MODELS_URL, headers=h), timeout=15) as r:
                        ms = json.load(r).get("models") or []
                    ids = [m.get("slug") or m.get("id") for m in ms if isinstance(m, dict)]
                    self._catalog = [{"id": i, "name": i} for i in ids if i] or self._catalog
                except Exception:
                    pass
        return self._catalog or self.SEED

    def _raw(self):
        try:
            with open(AUTH_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def _load(self):
        data = self._raw() or {}
        t = data.get("tokens") or {}
        access = t.get("access_token")
        if not access:
            return None  # API-key mode auth.json (OPENAI_API_KEY) is not an OAuth session; out of scope
        account = t.get("account_id") or jwt_claims(t.get("id_token", "")).get("https://api.openai.com/auth", {}).get("chatgpt_account_id")
        return {"access": access, "refresh": t.get("refresh_token"), "expires_at": jwt_claims(access).get("exp", 0), "account_id": account, "_data": data}

    def _refresh(self, cred):
        if not cred.get("refresh"):
            return None
        try:
            with http(TOKEN_URL, {"client_id": CLIENT_ID, "grant_type": "refresh_token", "refresh_token": cred["refresh"]}, {}, timeout=20) as r:
                res = json.load(r)
        except Exception:
            return None
        t = cred["_data"].setdefault("tokens", {})
        t["access_token"] = res["access_token"]
        t["refresh_token"] = res.get("refresh_token") or cred["refresh"]
        if res.get("id_token"):
            t["id_token"] = res["id_token"]
        cred["_data"]["last_refresh"] = datetime.now(timezone.utc).isoformat()
        tmp = AUTH_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cred["_data"], f, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, AUTH_FILE)
        return self._load()

    def _headers(self, tok):
        acct = (self._cred_cached() or {}).get("account_id") or ""
        return {"Authorization": "Bearer " + tok, "chatgpt-account-id": acct, "OpenAI-Beta": "responses=experimental",
                "originator": "codex_cli_rs", "Accept": "text/event-stream", "User-Agent": "codex_cli_rs/0.40.0"}

    def stream(self, request, model):
        body = to_responses(request, model)
        try:
            resp = open_upstream(self, lambda tok: http(API_URL, body, self._headers(tok)))
        except UpstreamError as e:
            yield ("error", {"status": e.status, "message": e.message})
            return
        for ev in events_from_responses(resp):
            yield ev

    def passthrough(self, body, headers, model):
        if not body.get("stream"):
            return None  # codex backend only streams; non-stream goes through the translate+collect path
        body = dict(body, model=model, store=False)
        return open_upstream(self, lambda tok: http(API_URL, body, self._headers(tok)))


def to_responses(request, model):
    """IR Request -> Responses API body for the codex backend (always streaming)."""
    instructions, items = [], []
    for m in request["messages"]:
        role = m.get("role")
        if role == "system":
            instructions.append(text_of(m.get("content")))
        elif role == "user":
            items.append({"type": "message", "role": "user", "content": [{"type": "input_text", "text": text_of(m.get("content"))}]})
        elif role == "assistant":
            if text_of(m.get("content")):
                items.append({"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text_of(m["content"])}]})
            for tc in m.get("tool_calls") or []:
                items.append({"type": "function_call", "call_id": tc.get("id", ""), "name": tc.get("name", ""), "arguments": tc.get("arguments") or "{}"})
        elif role == "tool":
            items.append({"type": "function_call_output", "call_id": m.get("tool_call_id", ""), "output": text_of(m.get("content"))})
    body = {"model": model, "instructions": "\n\n".join(i for i in instructions if i) or "You are a helpful assistant.",
            "input": items, "stream": True, "store": False}
    if request.get("tools"):  # ponytail: max_tokens/temperature dropped; the codex backend rejects sampling params for reasoning models
        body["tools"] = [{"type": "function", "name": t["name"], "description": t.get("description", ""), "parameters": t.get("parameters") or {"type": "object", "properties": {}}} for t in request["tools"]]
        body["tool_choice"] = "auto"
        body["parallel_tool_calls"] = False
    return body


def events_from_responses(lines):
    """Responses API SSE -> Events."""
    for _, d in sse(lines):
        t = d.get("type")
        if t == "response.output_text.delta":
            yield ("text", d.get("delta", ""))
        elif t == "response.reasoning_summary_text.delta":
            yield ("thinking", d.get("delta", ""))
        elif t == "response.output_item.done":
            item = d.get("item") or {}
            if item.get("type") == "function_call":
                yield ("tool_call", {"id": item.get("call_id") or item.get("id", ""), "name": item.get("name", ""), "arguments": item.get("arguments") or "{}"})
        elif t in ("response.completed", "response.done", "response.incomplete"):
            r = d.get("response") or {}
            u = r.get("usage") or {}
            yield ("usage", {"prompt_tokens": u.get("input_tokens", 0), "completion_tokens": u.get("output_tokens", 0)})
            has_tools = any(i.get("type") == "function_call" for i in r.get("output") or [])
            yield ("finish", "tool_calls" if has_tools else ("length" if r.get("status") == "incomplete" else "stop"))
            return
        elif t in ("response.failed", "error"):
            err = (d.get("response") or {}).get("error") or d.get("error") or {}
            yield ("error", {"status": 502, "message": err.get("message", "upstream error")})
            return
    yield ("finish", "stop")
