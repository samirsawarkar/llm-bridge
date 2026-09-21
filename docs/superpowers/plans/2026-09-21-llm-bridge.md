# LLM Bridge 2.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `antigravity-bridge` into `llm-bridge`: one local server that fronts Antigravity, Claude Code and Codex OAuth sessions behind OpenAI Chat / Anthropic Messages / OpenAI Responses endpoints, gated by generated API keys.

**Architecture:** Every inbound format is decoded into one internal `Request` dict (`ir.py`); a provider adapter streams it upstream and yields `Event` tuples; the inbound codec encodes events back. If the inbound format is the provider's native one, the raw body is passed through. Plain dicts and tuples, no classes beyond the three providers.

**Tech Stack:** Python 3.8+ stdlib only (`http.server`, `urllib`, `json`, `hmac`, `secrets`, `sqlite3`, `subprocess`). `unittest`.

**Spec:** `docs/superpowers/specs/2026-09-21-llm-bridge-design.md`

## Global Constraints

- `requires-python = ">=3.8"`, `dependencies = []` — no runtime deps, no f-string `=` specifiers, no `match`, no `str.removeprefix`.
- Package `src/llm_bridge/`, CLI entry points `llm-bridge` and `lbr`, version `2.0.0`.
- State dir `~/.llm-bridge/` (override `LLM_BRIDGE_HOME`), files mode `0600`.
- Keys are `sk-lb-` + 40 hex. Full secret printed only on creation.
- Model routing precedence: explicit `provider/model` → bare-name prefix → `default_provider` → 400. Provider prefix sets are disjoint.
- Provider refresh: one `threading.Lock` per provider around re-read → check → refresh → write-back. 401/403 → refresh once, retry once.
- `up` never installs a service. `service install` does.
- Tests: `python3 tests/run_tests.py`, no network.
- Commits: `git add` only the files the task names. Never commit `CLAUDE*.md`.
- Ponytail: shortest working code; `# ponytail:` comment on any deliberate ceiling.

## File structure

```
src/llm_bridge/__init__.py        __version__
src/llm_bridge/ir.py              Request/Event doc, text_of(), collect()
src/llm_bridge/store.py           keys.json + config.json
src/llm_bridge/providers/base.py  Provider base (cred cache, lock, token()), http(), sse(), UpstreamError, open_upstream()
src/llm_bridge/providers/antigravity.py
src/llm_bridge/providers/anthropic.py
src/llm_bridge/providers/openai.py
src/llm_bridge/providers/__init__.py   PROVIDERS, resolve(), RouteError, list_models()
src/llm_bridge/codecs/{__init__,openai_chat,anthropic,responses}.py
src/llm_bridge/server.py
src/llm_bridge/service.py
src/llm_bridge/connect/{__init__,hermes,openclaw}.py
src/llm_bridge/cli.py
tests/test_{ir_store,antigravity,anthropic,openai,router,codecs,server}.py
```

---

### Task 1: Package skeleton, `ir.py`, `store.py`

**Files:**
- Create: `src/llm_bridge/__init__.py`, `src/llm_bridge/ir.py`, `src/llm_bridge/store.py`
- Modify: `pyproject.toml`, `setup.py`
- Test: `tests/test_ir_store.py`

**Interfaces:**
- Produces: `ir.text_of(content) -> str`, `ir.collect(events) -> dict{thinking,text,tool_calls,usage,finish,error}`; `store.create_key(name)->str`, `store.load_keys()->dict`, `store.revoke_key(name)`, `store.verify_key(presented)->bool`, `store.mask(key)->str`, `store.load_config()->dict{host,port,default_provider}`, `store.save_config(**kv)`, `store.DIR`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ir_store.py
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))
os.environ["LLM_BRIDGE_HOME"] = tempfile.mkdtemp()
from llm_bridge import ir, store


class TestIR(unittest.TestCase):
    def test_text_of(self):
        self.assertEqual(ir.text_of("hi"), "hi")
        self.assertEqual(ir.text_of(None), "")
        self.assertEqual(ir.text_of([{"type": "text", "text": "a"}, {"type": "image_url", "image_url": {}}, {"type": "text", "text": "b"}]), "ab")

    def test_collect(self):
        r = ir.collect([("thinking", "t"), ("text", "he"), ("text", "llo"),
                        ("tool_call", {"id": "c1", "name": "f", "arguments": "{}"}),
                        ("usage", {"prompt_tokens": 1, "completion_tokens": 2}), ("finish", "stop")])
        self.assertEqual(r["text"], "hello")
        self.assertEqual(r["thinking"], "t")
        self.assertEqual(r["finish"], "tool_calls")  # tool calls force tool_calls
        self.assertEqual(r["usage"]["completion_tokens"], 2)
        e = ir.collect([("text", "x"), ("error", {"status": 502, "message": "boom"})])
        self.assertEqual(e["error"]["status"], 502)


class TestStore(unittest.TestCase):
    def test_keys_roundtrip(self):
        k = store.create_key("t1")
        self.assertTrue(k.startswith("sk-lb-") and len(k) == 46)
        self.assertTrue(store.verify_key(k))
        self.assertFalse(store.verify_key(k[:-1] + "x"))
        self.assertFalse(store.verify_key(""))
        self.assertEqual(store.mask(k), k[:10] + "…" + k[-2:])
        self.assertEqual(oct(os.stat(store.KEYS).st_mode & 0o777), "0o600")
        with self.assertRaises(ValueError):
            store.create_key("t1")
        store.revoke_key("t1")
        self.assertFalse(store.verify_key(k))

    def test_config(self):
        cfg = store.load_config()
        self.assertEqual(cfg["port"], 8000)
        store.save_config(default_provider="openai")
        self.assertEqual(store.load_config()["default_provider"], "openai")
        os.environ["LLM_BRIDGE_PORT"] = "9000"
        self.assertEqual(store.load_config()["port"], 9000)
        del os.environ["LLM_BRIDGE_PORT"]


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it** — `python3 -m unittest tests.test_ir_store -v` → FAIL `No module named llm_bridge`.

- [ ] **Step 3: Create the package**

`src/llm_bridge/__init__.py`:
```python
"""LLM Bridge: local OpenRouter-style gateway over CLI OAuth sessions."""
__version__ = "2.0.0"
```

`src/llm_bridge/ir.py`:
```python
"""Internal normalized request and stream events. The only place the shape is defined.

Request (dict):
  model        str            as sent by the client, e.g. "anthropic/claude-sonnet-5"
  messages     list[dict]     role: system|user|assistant|tool
                              content: str | None | list[parts]
                              tool_calls: [{id, name, arguments: str}]   (assistant)
                              tool_call_id, name                         (tool)
  tools        list[dict]     {name, description, parameters}   (flattened, no {"type":"function"} wrapper)
  stream       bool
  max_tokens   int | None
  temperature  float | None

Event (tuple), yielded in order by Provider.stream():
  ("thinking", str)                                   reasoning delta; codecs may drop
  ("text", str)                                       content delta
  ("tool_call", {id, name, arguments: str})           one complete call
  ("usage", {prompt_tokens, completion_tokens})       once, anywhere
  ("finish", "stop" | "tool_calls" | "length")        last event
  ("error", {status, message})                        terminal, replaces finish
"""


def text_of(content):
    """Flatten str | None | [parts] into plain text. Non-text parts are dropped."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    out = []
    for p in content:
        if isinstance(p, dict):
            if p.get("type") in (None, "text", "input_text", "output_text") and "text" in p:
                out.append(str(p["text"]))
        else:
            out.append(str(p))
    return "".join(out)


def collect(events):
    """Drain an event stream into one dict for non-streaming responses."""
    r = {"thinking": [], "text": [], "tool_calls": [], "usage": None, "finish": "stop", "error": None}
    for kind, payload in events:
        if kind in ("text", "thinking"):
            r[kind].append(payload)
        elif kind == "tool_call":
            r["tool_calls"].append(payload)
        elif kind == "usage":
            r["usage"] = payload
        elif kind == "finish":
            r["finish"] = payload
        elif kind == "error":
            r["error"] = payload
            break
    r["text"] = "".join(r["text"])
    r["thinking"] = "".join(r["thinking"])
    if r["tool_calls"] and r["finish"] == "stop":
        r["finish"] = "tool_calls"
    return r
```

`src/llm_bridge/store.py`:
```python
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
```

`pyproject.toml` — replace `[project]` name/version/description/keywords, scripts, and packages:
```toml
[project]
name = "llm-bridge"
version = "2.0.0"
description = "Local OpenRouter-style API over your Antigravity, Claude Code and Codex OAuth sessions"
readme = "README.md"
requires-python = ">=3.8"
license = { text = "MIT" }
authors = [{ name = "Samir Sawarkar", email = "samirsawarkars@gmail.com" }]
keywords = ["llm", "proxy", "openai-compatible", "anthropic", "codex", "antigravity", "gemini", "claude", "oauth", "gateway"]
classifiers = [ ...unchanged... ]
dependencies = []

[project.urls]  ...replace antigravity-bridge with llm-bridge in all four URLs...

[project.scripts]
llm-bridge = "llm_bridge.cli:main"
lbr = "llm_bridge.cli:main"
```
`setup.py`: same rename (`name="llm-bridge"`, `version="2.0.0"`, description, urls, `console_scripts` → `llm-bridge=llm_bridge.cli:main`, `lbr=llm_bridge.cli:main`).

- [ ] **Step 4: Run** — `python3 -m unittest tests.test_ir_store -v` → 4 tests PASS.
- [ ] **Step 5: Commit** — `git add src/llm_bridge/__init__.py src/llm_bridge/ir.py src/llm_bridge/store.py tests/test_ir_store.py pyproject.toml setup.py && git commit -m "feat(llm-bridge): package skeleton, internal request/event shape, key+config store"`

---

### Task 2: `providers/base.py` + `providers/antigravity.py` (port)

**Files:**
- Create: `src/llm_bridge/providers/base.py`, `src/llm_bridge/providers/antigravity.py`
- Test: `tests/test_antigravity.py` (replaces `tests/test_transform.py`, `tests/test_schema.py`, `tests/test_models.py`)
- Source to port from: `src/antigravity_bridge/auth.py`, `models.py`, `proxy.py` (uncommitted working-tree versions).

**Interfaces:**
- Produces (`base`): `class Provider` with attrs `name, native_fmt, prefixes, catalog, aliases, login_hint`; methods `upstream_model(m)`, `auth_status()->{ok,state,detail,fix}`, `token(force_refresh=False)->str|None`, `stream(request, model)->Iterator[Event]`, `passthrough(body, headers, model)->HTTPResponse|None`; subclass hooks `_load()->cred|None` (`{access, refresh, expires_at, ...}`), `_refresh(cred)->cred|None`. Helpers `http(url, body, headers, timeout=300)`, `sse(resp)->Iterator[(event, dict)]`, `class UpstreamError(Exception)` with `.status/.message`, `open_upstream(provider, send)->resp` (refresh-once-retry-once), `err_message(HTTPError)->str`.
- Produces (`antigravity`): `class Antigravity(Provider)`, `transform_messages(messages)->(sys_inst, contents)`, `transform_tools(tools)->list|None`, `clean_json_schema(s)`, `DEFAULT_THOUGHT_SIGNATURE`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_antigravity.py
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))
from llm_bridge.providers import antigravity as ag
from llm_bridge.providers.base import sse


class TestTransform(unittest.TestCase):
    def test_system_instruction(self):
        sys_inst, contents = ag.transform_messages([{"role": "system", "content": "S"}, {"role": "user", "content": "Hi"}])
        self.assertEqual(sys_inst["parts"][0]["text"], "S")
        self.assertEqual(contents, [{"role": "user", "parts": [{"text": "Hi"}]}])

    def test_tool_roundtrip(self):
        msgs = [{"role": "user", "content": "w?"},
                {"role": "assistant", "content": None, "tool_calls": [{"id": "call_9", "name": "get_weather", "arguments": '{"city": "Paris"}'}]},
                {"role": "tool", "tool_call_id": "call_9", "content": "Sunny"}]
        _, c = ag.transform_messages(msgs)
        p = c[1]["parts"][0]
        self.assertEqual(p["functionCall"]["name"], "get_weather")
        self.assertEqual(p["functionCall"]["args"], {"city": "Paris"})
        self.assertEqual(p["thoughtSignature"], ag.DEFAULT_THOUGHT_SIGNATURE)
        fr = c[2]["parts"][0]["functionResponse"]
        self.assertEqual((fr["name"], fr["id"], fr["response"]), ("get_weather", "call_9", {"output": "Sunny"}))

    def test_last_turn_user_guard(self):
        _, c = ag.transform_messages([{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}])
        self.assertEqual(c[-1]["role"], "user")

    def test_tools_and_schema(self):
        decl = ag.transform_tools([{"name": "lookup", "description": "d", "parameters": {
            "$schema": "x", "title": "T", "type": "object", "additionalProperties": False,
            "properties": {"id": {"anyOf": [{"type": "null"}, {"type": "string"}]}, "tags": {"type": "array", "items": [{"type": "string"}]},
                           "n": {"type": ["integer", "null"]}}, "required": ["id"]}}])[0]["functionDeclarations"][0]
        p = decl["parameters"]
        self.assertEqual(decl["name"], "lookup")
        for bad in ("$schema", "title", "additionalProperties"):
            self.assertNotIn(bad, p)
        self.assertEqual(p["properties"]["id"]["type"], "string")
        self.assertEqual(p["properties"]["tags"]["items"], {"type": "string"})
        self.assertEqual(p["properties"]["n"]["type"], "integer")
        self.assertIsNone(ag.transform_tools([]))


class TestProvider(unittest.TestCase):
    def test_aliases_explicit_only(self):
        p = ag.Antigravity()
        self.assertEqual(p.upstream_model("gemini-3.8-flash"), "gemini-3.8-flash-tiered")
        self.assertEqual(p.upstream_model("claude-sonnet"), "claude-sonnet-4-6")
        self.assertEqual(p.upstream_model("some-random-flash"), "some-random-flash")  # no fuzzy guessing
        self.assertEqual(p.prefixes, ("gemini-",))

    def test_events_from_sse(self):
        lines = [b'data: {"response":{"candidates":[{"content":{"parts":[{"text":"Hel"}]}}]}}\n',
                 b'\n',
                 b'data: {"response":{"candidates":[{"content":{"parts":[{"functionCall":{"id":"c1","name":"f","args":{"a":1}},"thoughtSignature":"sig"}]},"finishReason":"TOOL_CALL"}],"usageMetadata":{"promptTokenCount":3,"candidatesTokenCount":4}}}\n']
        ev = list(ag.events_from_stream(iter(lines)))
        self.assertEqual(ev[0], ("text", "Hel"))
        self.assertEqual(ev[1][0], "tool_call")
        self.assertEqual(ev[1][1]["arguments"], '{"a": 1}')
        self.assertEqual(ag.TOOL_CALL_CACHE["c1"]["thoughtSignature"], "sig")
        self.assertIn(("usage", {"prompt_tokens": 3, "completion_tokens": 4}), ev)
        self.assertEqual(ev[-1], ("finish", "tool_calls"))

    def test_sse_helper(self):
        got = list(sse(iter([b"event: ping\n", b"data: {\"a\":1}\n", b"\n", b"data: [DONE]\n", b"data: {\"b\":2}\n"])))
        self.assertEqual(got, [("ping", {"a": 1})])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it** — `python3 -m unittest tests.test_antigravity -v` → FAIL (import).

- [ ] **Step 3: Write `providers/base.py`**

```python
"""Provider contract and shared upstream helpers."""
import json
import threading
import time
import urllib.error
import urllib.request

CRED_TTL = 30  # ponytail: credential re-read every 30s; avoids a keychain subprocess per request


class UpstreamError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


class Provider:
    name = ""
    native_fmt = None          # "anthropic" | "responses" | None
    prefixes = ()              # bare-name routing; sets are disjoint across providers
    catalog = []               # [{"id": ..., "name": ...}]
    aliases = {}               # explicit id -> upstream id
    login_hint = ""

    def __init__(self):
        self._lock = threading.Lock()
        self._cred, self._cred_at = None, 0.0

    # --- subclass hooks -------------------------------------------------
    def _load(self):
        """Return {"access", "refresh", "expires_at": epoch_s, ...} or None."""
        raise NotImplementedError

    def _refresh(self, cred):
        """Refresh + write back. Return new cred dict or None on failure."""
        raise NotImplementedError

    def stream(self, request, model):
        raise NotImplementedError

    def passthrough(self, body, headers, model):
        return None

    # --- shared ---------------------------------------------------------
    def upstream_model(self, model):
        return self.aliases.get(model, model)

    def _cred_cached(self):
        if time.time() - self._cred_at > CRED_TTL:
            self._cred, self._cred_at = self._load(), time.time()
        return self._cred

    def auth_status(self):
        cred = self._cred_cached()
        if not cred:
            return {"ok": False, "state": "missing", "detail": "not logged in", "fix": self.login_hint}
        if cred["expires_at"] - time.time() < 60 and not cred.get("refresh"):
            return {"ok": False, "state": "expired", "detail": "token expired, no refresh token", "fix": self.login_hint}
        return {"ok": True, "state": "authenticated", "detail": "", "fix": ""}

    def token(self, force_refresh=False):
        with self._lock:
            cred = self._load()  # always re-read under the lock: another thread may have rotated the refresh token
            if not cred:
                return None
            if force_refresh or cred["expires_at"] - time.time() < 60:
                cred = self._refresh(cred) or cred
            self._cred, self._cred_at = cred, time.time()
            return cred.get("access")


def http(url, body, headers, timeout=300):
    data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    h = {"Content-Type": "application/json"}
    h.update(headers)
    return urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h, method="POST"), timeout=timeout)


def sse(lines):
    """Yield (event_name, json_dict) from SSE lines. Stops at [DONE]."""
    event = None
    for raw in lines:
        line = raw.decode("utf-8", "replace").rstrip("\r\n") if isinstance(raw, bytes) else raw.rstrip("\r\n")
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data = line[5:].strip()
            if data == "[DONE]":
                return
            try:
                yield event, json.loads(data)
            except ValueError:
                pass
            event = None
        elif not line:
            event = None


def err_message(e):
    try:
        body = e.read().decode("utf-8", "replace")[:1000]
    except Exception:
        body = ""
    try:
        m = json.loads(body).get("error")
        if isinstance(m, dict) and m.get("message"):
            return m["message"]
        if isinstance(m, str):
            return m
    except Exception:
        pass
    return " ".join(body.split())[:200] or "HTTP %s" % e.code


def open_upstream(provider, send):
    """send(token) -> response. On 401/403 refresh once and retry once. Raises UpstreamError."""
    tok = provider.token()
    if not tok:
        raise UpstreamError(401, "%s: %s" % (provider.name, provider.auth_status().get("fix") or "not authenticated"))
    try:
        return send(tok)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            tok = provider.token(force_refresh=True)
            if tok:
                try:
                    return send(tok)
                except urllib.error.HTTPError as e2:
                    e = e2
        raise UpstreamError(e.code, err_message(e))
    except UpstreamError:
        raise
    except Exception as e:
        raise UpstreamError(502, "upstream connection error: %s" % e)
```

- [ ] **Step 4: Write `providers/antigravity.py`** (port; `transform_messages` takes IR tool_calls `{id,name,arguments}`; `map_model` fuzzy heuristics dropped)

```python
"""Google Antigravity (agy) provider: OAuth token file + Cloud Code streamGenerateContent."""
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from ..ir import text_of
from .base import Provider, UpstreamError, http, open_upstream

TOKEN_PATHS = [
    os.path.expanduser("~/.openclaw/agents/main/agent/auth-profiles.json"),
    os.path.expanduser("~/.gemini/antigravity-cli/antigravity-oauth-token"),
    os.path.expanduser("~/.gemini/jetski-standalone-oauth-token"),
    os.path.expanduser("~/.gemini/oauth_token.json"),
    "/root/.gemini/antigravity-cli/antigravity-oauth-token",
]
CLIENT_ID = os.environ.get("ANTIGRAVITY_CLIENT_ID", "<ANTIGRAVITY_CLIENT_ID env>")
CLIENT_SECRET = os.environ.get("ANTIGRAVITY_CLIENT_SECRET", "<ANTIGRAVITY_CLIENT_SECRET env>")
PROJECT_ID = os.environ.get("ANTIGRAVITY_PROJECT_ID", "rising-fact-p41fc")
ENDPOINTS = [
    "https://cloudcode-pa.googleapis.com/v1internal:streamGenerateContent?alt=sse",
    "https://daily-cloudcode-pa.sandbox.googleapis.com/v1internal:streamGenerateContent?alt=sse",
    "https://daily-cloudcode-pa.googleapis.com/v1internal:streamGenerateContent?alt=sse",
]
FALLBACK_MODEL = "gemini-3.8-flash-tiered"
DEFAULT_THOUGHT_SIGNATURE = (
    "EnEKbwERTTIPtROYK8FSJmzasRTa7Z4nHGF3qBV0QaAHjAewGx2Rtqh5cFUMlYUu4USlmI+xm584wpNJ80dclO/vUl6efxAeNNv28wzaYcfZPUJLmEA/4rQNg5f4W4XGKq0/P1QZes539vt9Vqmid3qy+g=="
)
TOOL_CALL_CACHE = {}  # call_id -> {"name", "thoughtSignature"}   ponytail: unbounded, per-process; fine for a personal gateway


def token_path():
    p = os.environ.get("ANTIGRAVITY_TOKEN_FILE")
    if p and os.path.exists(p):
        return p
    for p in TOKEN_PATHS:
        if os.path.exists(p):
            return p
    return None


def agy_bin():
    return os.environ.get("AGY_BIN") or shutil.which("agy") or next((p for p in (os.path.expanduser("~/.local/bin/agy"), "/root/.local/bin/agy", "/usr/local/bin/agy") if os.path.exists(p)), None)


def _profile(data):
    """OpenClaw auth-profiles.json: return the antigravity credential dict, else None."""
    for k, v in (data.get("profiles") or {}).items():
        if "antigravity" in k.lower() and isinstance(v, dict):
            return v.get("credential", v)
    return None


def _parse(data):
    cred = _profile(data)
    if cred is not None:
        exp = float(cred.get("expires") or 0)
        return {"access": cred.get("access") or cred.get("access_token"), "refresh": cred.get("refresh") or cred.get("refresh_token"),
                "expires_at": exp / 1000.0 if exp > 1e11 else exp}
    tok = data.get("token") if isinstance(data.get("token"), dict) else data
    exp_s = tok.get("expiry") or data.get("expiry")
    expires_at = 0.0
    if exp_s:
        try:
            expires_at = datetime.fromisoformat(str(exp_s).split(".")[0].replace("Z", "")).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            pass
    return {"access": tok.get("access_token"), "refresh": tok.get("refresh_token"), "expires_at": expires_at}


class Antigravity(Provider):
    name = "antigravity"
    prefixes = ("gemini-",)
    login_hint = "run: agy   (log in with Google)"
    catalog = [
        {"id": "gemini-3.8-flash", "name": "Gemini 3.8 Flash"},
        {"id": "gemini-3.8-flash-high", "name": "Gemini 3.8 Flash (High)"},
        {"id": "gemini-3.7-flash", "name": "Gemini 3.7 Flash"},
        {"id": "gemini-3.6-flash-high", "name": "Gemini 3.6 Flash (High)"},
        {"id": "gemini-3.1-pro-high", "name": "Gemini 3.1 Pro (High)"},
        {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro"},
        {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash"},
        {"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6 (via Antigravity)"},
        {"id": "claude-opus-4-6-thinking", "name": "Claude Opus 4.6 Thinking (via Antigravity)"},
        {"id": "gpt-oss-120b-medium", "name": "GPT-OSS 120B"},
    ]
    aliases = {
        "gemini-3.8-flash": "gemini-3.8-flash-tiered", "gemini-3.8-flash-high": "gemini-3.8-flash-tiered",
        "gemini-3.8-flash-medium": "gemini-3.8-flash-tiered", "gemini-3.8-flash-low": "gemini-3.8-flash-tiered",
        "gemini-3.7-flash": "gemini-3.7-flash-tiered", "gemini-3.7-flash-high": "gemini-3.7-flash-tiered",
        "gemini-3.6-flash": "gemini-3.6-flash-high", "gemini-3.1-pro": "gemini-3.1-pro-high",
        "gemini-3-flash-thinking": "gemini-3-flash", "gemini-pro": "gemini-2.5-pro", "gemini-flash": "gemini-2.5-flash",
        "claude-sonnet": "claude-sonnet-4-6", "claude-opus": "claude-opus-4-6-thinking",
    }

    def _load(self):
        path = token_path()
        if not path:
            return None
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return None
        cred = _parse(data)
        if not cred.get("access"):
            return None
        cred["_data"], cred["_path"] = data, path
        return cred

    def _refresh(self, cred):
        if cred.get("refresh"):
            try:
                body = urllib.parse.urlencode({"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
                                               "refresh_token": cred["refresh"], "grant_type": "refresh_token"}).encode()
                with urllib.request.urlopen(urllib.request.Request("https://oauth2.googleapis.com/token", data=body), timeout=15) as r:
                    res = json.load(r)
                exp = datetime.fromtimestamp(time.time() + res.get("expires_in", 3600), timezone.utc)
                data = cred["_data"]
                prof = _profile(data)
                if prof is not None:
                    prof["access"], prof["expires"] = res["access_token"], int(exp.timestamp() * 1000)
                    if res.get("refresh_token"):
                        prof["refresh"] = res["refresh_token"]
                else:
                    tok = data["token"] if isinstance(data.get("token"), dict) else data
                    tok["access_token"], tok["expiry"] = res["access_token"], exp.isoformat()
                    if res.get("refresh_token"):
                        tok["refresh_token"] = res["refresh_token"]
                with open(cred["_path"], "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                return self._load()
            except Exception:
                pass
        b = agy_bin()  # fallback: let agy refresh its own file
        if b:
            try:
                subprocess.run([b, "models"], capture_output=True, timeout=30)
            except Exception:
                pass
        return self._load()

    def stream(self, request, model):
        sys_inst, contents = transform_messages(request["messages"])
        req = {"contents": contents}
        if sys_inst:
            req["systemInstruction"] = sys_inst
        decls = transform_tools(request.get("tools"))
        if decls:
            req["tools"] = decls
        body = {"project": PROJECT_ID, "model": model, "request": req, "requestType": "agent",
                "userAgent": "antigravity", "requestId": "agent-%d" % int(time.time() * 1000)}

        def send(tok):
            headers = {"Authorization": "Bearer " + tok, "User-Agent": "antigravity/1.15.8", "X-Goog-Api-Client": "google-cloud-sdk vscode"}
            last = None
            for ep in ENDPOINTS:
                try:
                    return http(ep, body, headers)
                except urllib.error.HTTPError as e:
                    last = e
                    if e.code not in (429, 503):
                        raise
                except Exception as e:
                    last = e
            raise last

        try:
            resp = open_upstream(self, send)
        except UpstreamError as e:
            if e.status in (429, 503) and model != FALLBACK_MODEL:  # existing behaviour: transparent quota fallback
                body["model"] = FALLBACK_MODEL
                try:
                    resp = open_upstream(self, send)
                except UpstreamError as e2:
                    yield ("error", {"status": e2.status, "message": e2.message})
                    return
            else:
                yield ("error", {"status": e.status, "message": e.message})
                return
        for ev in events_from_stream(resp):
            yield ev


def events_from_stream(lines):
    """Cloud Code SSE lines -> Events."""
    usage = None
    finish = None
    for raw in lines:
        line = raw.decode("utf-8", "replace").strip() if isinstance(raw, bytes) else raw.strip()
        if not line.startswith("data: "):
            continue
        try:
            d = json.loads(line[6:])
        except ValueError:
            continue
        resp = d.get("response", {})
        um = resp.get("usageMetadata")
        if um:
            usage = {"prompt_tokens": um.get("promptTokenCount", 0), "completion_tokens": um.get("candidatesTokenCount", 0)}
        cands = resp.get("candidates") or []
        if not cands:
            continue
        cand = cands[0]
        for part in cand.get("content", {}).get("parts", []):
            if part.get("thought") and "text" in part:
                yield ("thinking", part["text"])
            elif "text" in part:
                yield ("text", part["text"])
            if "functionCall" in part:
                fc = part["functionCall"]
                cid = fc.get("id") or "call_%d" % int(time.time() * 1000)
                TOOL_CALL_CACHE[cid] = {"name": fc.get("name", ""), "thoughtSignature": part.get("thoughtSignature")}
                yield ("tool_call", {"id": cid, "name": fc.get("name", ""), "arguments": json.dumps(fc.get("args", {}))})
        fr = cand.get("finishReason")
        if fr:
            finish = "tool_calls" if fr == "TOOL_CALL" else ("length" if fr == "MAX_TOKENS" else "stop")
    if usage:
        yield ("usage", usage)
    yield ("finish", finish or "stop")


def transform_messages(messages):
    """IR messages -> (systemInstruction | None, contents)."""
    call_names = {tc["id"]: tc["name"] for m in messages if m.get("role") == "assistant" for tc in m.get("tool_calls") or [] if tc.get("id")}
    system_parts, contents = [], []
    for msg in messages:
        role, content = msg.get("role", "user"), msg.get("content")
        if role == "system":
            if text_of(content):
                system_parts.append({"text": text_of(content)})
        elif role == "user":
            contents.append({"role": "user", "parts": [{"text": text_of(content)}]})
        elif role == "assistant":
            parts = []
            if text_of(content):
                parts.append({"text": text_of(content)})
            for tc in msg.get("tool_calls") or []:
                try:
                    args = json.loads(tc.get("arguments") or "{}")
                except ValueError:
                    args = {}
                sig = TOOL_CALL_CACHE.get(tc.get("id", ""), {}).get("thoughtSignature")
                parts.append({"functionCall": {"name": tc.get("name", ""), "args": args, "id": tc.get("id", "")},
                              "thoughtSignature": sig or DEFAULT_THOUGHT_SIGNATURE})
            contents.append({"role": "model", "parts": parts or [{"text": ""}]})
        elif role == "tool":
            cid = msg.get("tool_call_id", "")
            name = call_names.get(cid) or TOOL_CALL_CACHE.get(cid, {}).get("name") or msg.get("name") or "tool"
            raw = text_of(content)
            try:
                res = json.loads(raw)
            except ValueError:
                res = {"output": raw}
            if not isinstance(res, dict):
                res = {"output": res}
            contents.append({"role": "user", "parts": [{"functionResponse": {"name": name, "response": res, "id": cid}}]})
    if contents and contents[-1]["role"] == "model":  # Gemini requires the last turn to be user
        contents.append({"role": "user", "parts": [{"text": ""}]})
    return ({"parts": system_parts} if system_parts else None), contents


def transform_tools(tools):
    """IR tools -> [{"functionDeclarations": [...]}] | None."""
    decls = [{"name": t.get("name", ""), "description": t.get("description", ""), "parameters": clean_json_schema(t.get("parameters") or {})} for t in tools or []]
    return [{"functionDeclarations": decls}] if decls else None


def clean_json_schema(s):
    """Strip keys Cloud Code's protobuf schema rejects; collapse anyOf/oneOf/allOf and type lists."""
    if not isinstance(s, dict):
        return {"type": "string"}
    for key in ("anyOf", "oneOf"):
        if isinstance(s.get(key), list) and s[key]:
            return clean_json_schema(next((c for c in s[key] if isinstance(c, dict) and c.get("type") != "null"), s[key][0]))
    if isinstance(s.get("allOf"), list) and s["allOf"]:
        return clean_json_schema(s["allOf"][0])
    t = s.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), "string")
    elif not t:
        t = "object" if "properties" in s else "array" if "items" in s else "string"
    out = {"type": str(t).lower()}
    if isinstance(s.get("description"), str):
        out["description"] = s["description"]
    if out["type"] == "object":
        if isinstance(s.get("properties"), dict) and s["properties"]:
            out["properties"] = {k: clean_json_schema(v) for k, v in s["properties"].items()}
        if isinstance(s.get("required"), list):
            out["required"] = [r for r in s["required"] if isinstance(r, str)]
    elif out["type"] == "array":
        items = s.get("items")
        out["items"] = clean_json_schema(items[0] if isinstance(items, list) and items else items)
    if isinstance(s.get("enum"), list):
        out["enum"] = [str(e) for e in s["enum"]]
    return out
```

- [ ] **Step 5: Run** — `python3 -m unittest tests.test_antigravity -v` → 7 PASS. Delete `tests/test_transform.py tests/test_schema.py tests/test_models.py` (superseded).
- [ ] **Step 6: Commit** — `git add src/llm_bridge/providers/base.py src/llm_bridge/providers/antigravity.py tests/test_antigravity.py && git rm -q tests/test_transform.py tests/test_schema.py tests/test_models.py && git commit -m "feat(providers): provider contract + antigravity adapter ported to event stream"`

---

### Task 3: `providers/anthropic.py` (Claude Code)

**Files:**
- Create: `src/llm_bridge/providers/anthropic.py`
- Test: `tests/test_anthropic.py`

**Interfaces:**
- Consumes: `base.Provider`, `base.http`, `base.sse`, `base.open_upstream`, `ir.text_of`.
- Produces: `class Anthropic(Provider)` (`name="anthropic"`, `native_fmt="anthropic"`, `prefixes=("claude-",)`), `to_messages(request, model)->dict`, `events_from_messages(lines)->Iterator[Event]`, `ensure_identity(body)->body`, `IDENTITY`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_anthropic.py
import json, os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))
from llm_bridge.providers import anthropic as an


class TestAnthropic(unittest.TestCase):
    def test_to_messages(self):
        req = {"messages": [{"role": "system", "content": "Be terse."},
                            {"role": "user", "content": "hi"},
                            {"role": "assistant", "content": "", "tool_calls": [{"id": "t1", "name": "f", "arguments": '{"x":1}'}]},
                            {"role": "tool", "tool_call_id": "t1", "content": "42"},
                            {"role": "user", "content": [{"type": "text", "text": "and?"}]}],
               "tools": [{"name": "f", "description": "d", "parameters": {"type": "object", "properties": {}}}],
               "max_tokens": None, "temperature": 0.2, "stream": True}
        b = an.to_messages(req, "claude-sonnet-5")
        self.assertEqual(b["system"][0]["text"], an.IDENTITY)
        self.assertEqual(b["system"][1]["text"], "Be terse.")
        self.assertEqual([m["role"] for m in b["messages"]], ["user", "assistant", "user"])
        self.assertEqual(b["messages"][1]["content"][0], {"type": "tool_use", "id": "t1", "name": "f", "input": {"x": 1}})
        self.assertEqual(b["messages"][2]["content"][0]["type"], "tool_result")
        self.assertEqual(b["messages"][2]["content"][1], {"type": "text", "text": "and?"})  # merged into one user turn
        self.assertEqual(b["tools"][0]["input_schema"], {"type": "object", "properties": {}})
        self.assertEqual((b["max_tokens"], b["temperature"], b["stream"]), (8192, 0.2, True))

    def test_identity_not_duplicated(self):
        b = an.ensure_identity({"system": an.IDENTITY + "\nmore"})
        self.assertEqual(b["system"], [{"type": "text", "text": an.IDENTITY + "\nmore"}])
        b = an.ensure_identity({"system": [{"type": "text", "text": "x"}]})
        self.assertEqual(b["system"][0]["text"], an.IDENTITY)

    def test_events(self):
        lines = [
            'event: message_start', 'data: {"type":"message_start","message":{"usage":{"input_tokens":5,"output_tokens":0}}}', '',
            'event: content_block_start', 'data: {"type":"content_block_start","index":0,"content_block":{"type":"thinking"}}', '',
            'event: content_block_delta', 'data: {"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"hm"}}', '',
            'event: content_block_delta', 'data: {"type":"content_block_delta","index":1,"delta":{"type":"text_delta","text":"Hi"}}', '',
            'event: content_block_start', 'data: {"type":"content_block_start","index":2,"content_block":{"type":"tool_use","id":"tu1","name":"f"}}', '',
            'event: content_block_delta', 'data: {"type":"content_block_delta","index":2,"delta":{"type":"input_json_delta","partial_json":"{\\"a\\""}}', '',
            'event: content_block_delta', 'data: {"type":"content_block_delta","index":2,"delta":{"type":"input_json_delta","partial_json":":1}"}}', '',
            'event: content_block_stop', 'data: {"type":"content_block_stop","index":2}', '',
            'event: message_delta', 'data: {"type":"message_delta","delta":{"stop_reason":"tool_use"},"usage":{"output_tokens":7}}', '',
        ]
        ev = list(an.events_from_messages(iter(l + "\n" for l in lines)))
        self.assertEqual(ev[0], ("thinking", "hm"))
        self.assertEqual(ev[1], ("text", "Hi"))
        self.assertEqual(ev[2], ("tool_call", {"id": "tu1", "name": "f", "arguments": '{"a":1}'}))
        self.assertEqual(ev[3], ("usage", {"prompt_tokens": 5, "completion_tokens": 7}))
        self.assertEqual(ev[4], ("finish", "tool_calls"))

    def test_load_parses_credentials(self):
        p = an.Anthropic()
        p._raw = lambda: ({"claudeAiOauth": {"accessToken": "A", "refreshToken": "R", "expiresAt": 1900000000000}}, "file")
        c = p._load()
        self.assertEqual((c["access"], c["refresh"], c["expires_at"]), ("A", "R", 1900000000.0))
        p._raw = lambda: (None, None)
        self.assertIsNone(p._load())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it** → FAIL (import).

- [ ] **Step 3: Write `providers/anthropic.py`**

```python
"""Claude Code OAuth provider: reuse the `claude` CLI session against api.anthropic.com/v1/messages."""
import getpass
import json
import os
import subprocess
import sys
import time

from ..ir import text_of
from .base import Provider, UpstreamError, http, open_upstream, sse

# Verify against the installed CLI if anything 401s: these are Claude Code's public OAuth client + endpoints.
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
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
        """-> (json_dict, source) where source is "keychain" or a file path."""
        if sys.platform == "darwin":
            try:
                r = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"], capture_output=True, text=True, timeout=5)
                if r.returncode == 0 and r.stdout.strip():
                    return json.loads(r.stdout.strip()), "keychain"
            except Exception:
                pass
        try:
            with open(CRED_FILE, encoding="utf-8") as f:
                return json.load(f), CRED_FILE
        except (OSError, ValueError):
            return None, None

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
            with http(TOKEN_URL, {"grant_type": "refresh_token", "refresh_token": cred["refresh"], "client_id": CLIENT_ID}, {}, timeout=20) as r:
                res = json.load(r)
        except Exception:
            return None
        o = cred["_data"]["claudeAiOauth"]
        o["accessToken"] = res["access_token"]
        o["refreshToken"] = res.get("refresh_token") or cred["refresh"]
        o["expiresAt"] = int((time.time() + res.get("expires_in", 3600)) * 1000)
        self._save(cred["_data"], cred["_src"])
        return self._load()

    def _save(self, data, src):
        blob = json.dumps(data)
        if src == "keychain":  # same mechanism Claude Code itself uses; token is briefly visible in `ps`
            subprocess.run(["security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE, "-a", getpass.getuser(), "-w", blob], capture_output=True, timeout=5)
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
```

- [ ] **Step 4: Run** — `python3 -m unittest tests.test_anthropic -v` → 4 PASS.
- [ ] **Step 5: Commit** — `git add src/llm_bridge/providers/anthropic.py tests/test_anthropic.py && git commit -m "feat(providers): anthropic adapter over Claude Code OAuth"`

---

### Task 4: `providers/openai.py` (Codex)

**Files:**
- Create: `src/llm_bridge/providers/openai.py`
- Test: `tests/test_openai.py`

**Interfaces:**
- Produces: `class OpenAI(Provider)` (`name="openai"`, `native_fmt="responses"`, `prefixes=("gpt-", "o1", "o3", "o4", "codex")`), `to_responses(request, model)->dict`, `events_from_responses(lines)->Iterator[Event]`, `jwt_claims(tok)->dict`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_openai.py
import base64, json, os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))
from llm_bridge.providers import openai as oa


def _jwt(claims):
    b = lambda s: base64.urlsafe_b64encode(json.dumps(s).encode()).rstrip(b"=").decode()
    return b({"alg": "none"}) + "." + b(claims) + ".sig"


class TestOpenAI(unittest.TestCase):
    def test_to_responses(self):
        req = {"messages": [{"role": "system", "content": "S"}, {"role": "user", "content": "q"},
                            {"role": "assistant", "content": "thinking...", "tool_calls": [{"id": "c1", "name": "f", "arguments": "{}"}]},
                            {"role": "tool", "tool_call_id": "c1", "content": "out"}],
               "tools": [{"name": "f", "description": "d", "parameters": None}], "stream": False, "max_tokens": 10, "temperature": 0}
        b = oa.to_responses(req, "gpt-5-codex")
        self.assertEqual(b["instructions"], "S")
        self.assertEqual([i["type"] for i in b["input"]], ["message", "message", "function_call", "function_call_output"])
        self.assertEqual(b["input"][2]["call_id"], "c1")
        self.assertEqual(b["input"][3]["output"], "out")
        self.assertEqual(b["tools"][0], {"type": "function", "name": "f", "description": "d", "parameters": {"type": "object", "properties": {}}})
        self.assertTrue(b["stream"] and b["store"] is False)
        self.assertNotIn("temperature", b)  # codex backend rejects sampling params

    def test_events(self):
        lines = ['data: {"type":"response.output_text.delta","delta":"He"}',
                 'data: {"type":"response.output_item.done","item":{"type":"function_call","call_id":"c9","name":"f","arguments":"{\\"a\\":1}"}}',
                 'data: {"type":"response.completed","response":{"status":"completed","output":[{"type":"function_call"}],"usage":{"input_tokens":2,"output_tokens":3}}}']
        ev = list(oa.events_from_responses(iter(l + "\n" for l in lines)))
        self.assertEqual(ev, [("text", "He"), ("tool_call", {"id": "c9", "name": "f", "arguments": '{"a":1}'}),
                              ("usage", {"prompt_tokens": 2, "completion_tokens": 3}), ("finish", "tool_calls")])
        err = list(oa.events_from_responses(iter(['data: {"type":"response.failed","response":{"error":{"message":"nope"}}}\n'])))
        self.assertEqual(err, [("error", {"status": 502, "message": "nope"})])

    def test_load_from_auth_json(self):
        p = oa.OpenAI()
        acc = _jwt({"exp": 1900000000})
        idt = _jwt({"https://api.openai.com/auth": {"chatgpt_account_id": "acct_1"}})
        p._raw = lambda: {"tokens": {"access_token": acc, "refresh_token": "R", "id_token": idt}}
        c = p._load()
        self.assertEqual((c["access"], c["refresh"], c["expires_at"], c["account_id"]), (acc, "R", 1900000000, "acct_1"))
        p._raw = lambda: {"OPENAI_API_KEY": "sk-x"}
        self.assertIsNone(p._load())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it** → FAIL (import).

- [ ] **Step 3: Write `providers/openai.py`**

```python
"""Codex OAuth provider: reuse the `codex` CLI session against chatgpt.com/backend-api/codex/responses."""
import base64
import json
import os
import time
from datetime import datetime, timezone

from ..ir import text_of
from .base import Provider, UpstreamError, http, open_upstream, sse

# Verify against the installed CLI if anything 401s: these are Codex CLI's public OAuth client + endpoints.
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
TOKEN_URL = "https://auth.openai.com/oauth/token"
API_URL = "https://chatgpt.com/backend-api/codex/responses"
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
    catalog = [
        {"id": "gpt-5-codex", "name": "GPT-5 Codex"},
        {"id": "gpt-5", "name": "GPT-5"},
        {"id": "gpt-5-mini", "name": "GPT-5 Mini"},
        {"id": "codex-mini-latest", "name": "Codex Mini"},
    ]
    aliases = {"codex": "gpt-5-codex"}

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
```

- [ ] **Step 4: Run** — `python3 -m unittest tests.test_openai -v` → 3 PASS.
- [ ] **Step 5: Commit** — `git add src/llm_bridge/providers/openai.py tests/test_openai.py && git commit -m "feat(providers): openai adapter over Codex OAuth"`

---

### Task 5: Registry + routing (`providers/__init__.py`)

**Files:**
- Create: `src/llm_bridge/providers/__init__.py`
- Test: `tests/test_router.py`

**Interfaces:**
- Produces: `PROVIDERS: dict[name, Provider]`, `class RouteError(ValueError)`, `resolve(model, default_provider=None)->(provider, upstream_model)`, `list_models()->list[dict]` (OpenAI model objects, only for `auth_status().ok` providers).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_router.py
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))
from llm_bridge import providers as P


class TestRouter(unittest.TestCase):
    def test_precedence(self):
        p, m = P.resolve("antigravity/gemini-3.8-flash")
        self.assertEqual((p.name, m), ("antigravity", "gemini-3.8-flash-tiered"))
        p, m = P.resolve("claude-sonnet")
        self.assertEqual((p.name, m), ("anthropic", "claude-sonnet-5"))
        p, m = P.resolve("gpt-5-codex")
        self.assertEqual(p.name, "openai")
        p, m = P.resolve("mystery-model", default_provider="openai")
        self.assertEqual((p.name, m), ("openai", "mystery-model"))
        for bad in (None, "", "mystery-model", "nope/x"):
            with self.assertRaises(P.RouteError):
                P.resolve(bad)

    def test_prefixes_disjoint(self):
        names = ["gpt-5", "gpt-oss-120b-medium", "gemini-2.5-pro", "claude-x", "o3-mini", "codex-mini"]
        for n in names:
            hits = [p.name for p in P.PROVIDERS.values() if n.startswith(p.prefixes)]
            self.assertLessEqual(len(hits), 1, n)

    def test_list_models_shape(self):
        for p in P.PROVIDERS.values():
            p.auth_status = lambda: {"ok": True}
        ids = [m["id"] for m in P.list_models()]
        self.assertIn("anthropic/claude-sonnet-5", ids)
        self.assertIn("antigravity/gemini-3.8-flash", ids)
        self.assertTrue(all("/" in i for i in ids))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it** → FAIL.

- [ ] **Step 3: Write `providers/__init__.py`**

```python
"""Provider registry and model routing."""
import time

from .anthropic import Anthropic
from .antigravity import Antigravity
from .openai import OpenAI

PROVIDERS = {p.name: p for p in (Antigravity(), Anthropic(), OpenAI())}


class RouteError(ValueError):
    pass


def resolve(model, default_provider=None):
    """model string -> (provider, upstream_model). explicit provider/model > bare prefix > default_provider > error."""
    hint = "use provider/model, e.g. anthropic/claude-sonnet-5 (providers: %s)" % ", ".join(PROVIDERS)
    if not model:
        raise RouteError("model is required; " + hint)
    if "/" in model:
        pname, _, bare = model.partition("/")
        if pname not in PROVIDERS:
            raise RouteError("unknown provider '%s'; %s" % (pname, hint))
        return PROVIDERS[pname], PROVIDERS[pname].upstream_model(bare)
    for p in PROVIDERS.values():
        if model.startswith(p.prefixes):
            return p, p.upstream_model(model)
    if default_provider in PROVIDERS:
        return PROVIDERS[default_provider], PROVIDERS[default_provider].upstream_model(model)
    raise RouteError("cannot route model '%s'; %s" % (model, hint))


def list_models():
    now = int(time.time())
    return [{"id": "%s/%s" % (p.name, m["id"]), "object": "model", "created": now, "owned_by": p.name}
            for p in PROVIDERS.values() if p.auth_status()["ok"] for m in p.catalog]
```

- [ ] **Step 4: Run** → 3 PASS.
- [ ] **Step 5: Commit** — `git add src/llm_bridge/providers/__init__.py tests/test_router.py && git commit -m "feat(providers): registry and explicit model routing"`

---

### Task 6: Codecs (`codecs/openai_chat.py`, `codecs/anthropic.py`, `codecs/responses.py`)

**Files:**
- Create: `src/llm_bridge/codecs/__init__.py`, `src/llm_bridge/codecs/openai_chat.py`, `src/llm_bridge/codecs/anthropic.py`, `src/llm_bridge/codecs/responses.py`
- Test: `tests/test_codecs.py`

**Interfaces:**
- Consumes: `ir.text_of`, `ir.collect`.
- Produces per codec module: `fmt: str`, `decode(body)->Request`, `encode_stream(events, request, model)->Iterator[bytes]`, `encode_final(events, request, model)->(status:int, bytes)`, `encode_error(status, message, kind=None)->bytes`. `codecs.by_path(path)->module|None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_codecs.py
import json, os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))
from llm_bridge import codecs
from llm_bridge.codecs import openai_chat, anthropic, responses

EVENTS = [("thinking", "hm"), ("text", "Hel"), ("text", "lo"),
          ("tool_call", {"id": "c1", "name": "f", "arguments": '{"a":1}'}),
          ("usage", {"prompt_tokens": 1, "completion_tokens": 2}), ("finish", "tool_calls")]
ERR = [("text", "x"), ("error", {"status": 429, "message": "slow down"})]


def frames(gen):
    """Parse SSE bytes -> list of (event, dict)."""
    out, ev = [], None
    for line in b"".join(gen).decode().split("\n"):
        if line.startswith("event: "):
            ev = line[7:]
        elif line.startswith("data: ") and line != "data: [DONE]":
            out.append((ev, json.loads(line[6:])))
            ev = None
    return out


class TestOpenAIChat(unittest.TestCase):
    def test_decode(self):
        r = openai_chat.decode({"model": "m", "stream": True, "max_completion_tokens": 5, "messages": [
            {"role": "system", "content": "s"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "c", "type": "function", "function": {"name": "f", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c", "content": "r"}],
            "tools": [{"type": "function", "function": {"name": "f", "parameters": {"type": "object"}}}]})
        self.assertEqual(r["messages"][1]["tool_calls"], [{"id": "c", "name": "f", "arguments": "{}"}])
        self.assertEqual(r["tools"], [{"name": "f", "description": "", "parameters": {"type": "object"}}])
        self.assertEqual((r["stream"], r["max_tokens"]), (True, 5))

    def test_stream_and_final(self):
        fr = frames(openai_chat.encode_stream(iter(EVENTS), {}, "m"))
        deltas = [f[1]["choices"][0]["delta"] for f in fr]
        self.assertEqual(deltas[0], {"role": "assistant", "content": ""})
        self.assertIn({"reasoning_content": "hm"}, deltas)
        self.assertIn({"content": "Hel"}, deltas)
        self.assertEqual(deltas[-2]["tool_calls"][0]["function"], {"name": "f", "arguments": '{"a":1}'})
        self.assertEqual(fr[-1][1]["choices"][0]["finish_reason"], "tool_calls")
        self.assertEqual(fr[-1][1]["usage"]["total_tokens"], 3)
        status, body = openai_chat.encode_final(iter(EVENTS), {}, "m")
        msg = json.loads(body)["choices"][0]["message"]
        self.assertEqual((status, msg["content"], msg["tool_calls"][0]["id"]), (200, "Hello", "c1"))
        status, body = openai_chat.encode_final(iter(ERR), {}, "m")
        self.assertEqual((status, json.loads(body)["error"]["code"]), (429, 429))
        fr = frames(openai_chat.encode_stream(iter(ERR), {}, "m"))
        self.assertEqual(fr[-1][1]["error"]["message"], "slow down")


class TestAnthropic(unittest.TestCase):
    def test_decode(self):
        r = anthropic.decode({"model": "m", "max_tokens": 9, "system": [{"type": "text", "text": "s"}], "messages": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": [{"type": "text", "text": "t"}, {"type": "tool_use", "id": "u", "name": "f", "input": {"a": 1}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "u", "content": "r"}, {"type": "text", "text": "next"}]}],
            "tools": [{"name": "f", "input_schema": {"type": "object"}}]})
        self.assertEqual(r["messages"][0], {"role": "system", "content": "s"})
        self.assertEqual(r["messages"][2]["tool_calls"], [{"id": "u", "name": "f", "arguments": '{"a": 1}'}])
        self.assertEqual([m["role"] for m in r["messages"]], ["system", "user", "assistant", "tool", "user"])
        self.assertEqual(r["tools"][0]["parameters"], {"type": "object"})
        self.assertEqual(r["max_tokens"], 9)

    def test_stream_and_final(self):
        fr = frames(anthropic.encode_stream(iter(EVENTS), {}, "m"))
        names = [f[0] for f in fr]
        self.assertEqual(names[0], "message_start")
        self.assertEqual(names[-2:], ["message_delta", "message_stop"])
        starts = [f[1]["content_block"]["type"] for f in fr if f[0] == "content_block_start"]
        self.assertEqual(starts, ["thinking", "text", "tool_use"])
        self.assertEqual(names.count("content_block_start"), names.count("content_block_stop"))
        self.assertEqual(fr[-2][1]["delta"]["stop_reason"], "tool_use")
        status, body = anthropic.encode_final(iter(EVENTS), {}, "m")
        b = json.loads(body)
        self.assertEqual([c["type"] for c in b["content"]], ["thinking", "text", "tool_use"])
        self.assertEqual(b["content"][2]["input"], {"a": 1})
        self.assertEqual(b["usage"], {"input_tokens": 1, "output_tokens": 2})
        status, body = anthropic.encode_final(iter(ERR), {}, "m")
        self.assertEqual((status, json.loads(body)["error"]["type"]), (429, "rate_limit_error"))
        self.assertEqual(frames(anthropic.encode_stream(iter(ERR), {}, "m"))[-1][0], "error")


class TestResponses(unittest.TestCase):
    def test_decode(self):
        r = responses.decode({"model": "m", "instructions": "s", "max_output_tokens": 4, "input": [
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "q"}]},
            {"type": "function_call", "call_id": "c", "name": "f", "arguments": "{}"},
            {"type": "function_call_output", "call_id": "c", "output": "o"}],
            "tools": [{"type": "function", "name": "f", "parameters": {}}]})
        self.assertEqual([m["role"] for m in r["messages"]], ["system", "user", "assistant", "tool"])
        self.assertEqual(r["messages"][2]["tool_calls"][0]["id"], "c")
        self.assertEqual(r["max_tokens"], 4)
        self.assertEqual(responses.decode({"input": "plain"})["messages"], [{"role": "user", "content": "plain"}])

    def test_stream_and_final(self):
        fr = frames(responses.encode_stream(iter(EVENTS), {}, "m"))
        names = [f[0] for f in fr]
        self.assertEqual(names[0], "response.created")
        self.assertEqual(names[-1], "response.completed")
        self.assertIn("response.output_text.delta", names)
        done = [f[1]["item"] for f in fr if f[0] == "response.output_item.done"]
        self.assertEqual([d["type"] for d in done], ["message", "function_call"])
        self.assertEqual(done[0]["content"][0]["text"], "Hello")
        final = fr[-1][1]["response"]
        self.assertEqual(final["usage"]["total_tokens"], 3)
        self.assertEqual([i["type"] for i in final["output"]], ["message", "function_call"])
        status, body = responses.encode_final(iter(EVENTS), {}, "m")
        self.assertEqual(json.loads(body)["output"][1]["call_id"], "c1")
        self.assertEqual(frames(responses.encode_stream(iter(ERR), {}, "m"))[-1][0], "response.failed")

    def test_by_path(self):
        self.assertIs(codecs.by_path("/v1/chat/completions"), openai_chat)
        self.assertIs(codecs.by_path("/chat/completions"), openai_chat)
        self.assertIs(codecs.by_path("/v1/messages"), anthropic)
        self.assertIs(codecs.by_path("/v1/responses"), responses)
        self.assertIsNone(codecs.by_path("/nope"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it** → FAIL.

- [ ] **Step 3: Write `codecs/__init__.py`**

```python
"""Inbound API formats. Each module: fmt, decode, encode_stream, encode_final, encode_error."""
from . import anthropic, openai_chat, responses

_BY_PATH = {"/v1/chat/completions": openai_chat, "/chat/completions": openai_chat,
            "/v1/messages": anthropic, "/messages": anthropic,
            "/v1/responses": responses, "/responses": responses}


def by_path(path):
    return _BY_PATH.get(path)
```

- [ ] **Step 4: Write `codecs/openai_chat.py`**

```python
"""OpenAI Chat Completions <-> internal Request/Events (near-identity)."""
import json
import time
import uuid

from ..ir import collect

fmt = "openai_chat"


def decode(body):
    msgs = []
    for m in body.get("messages") or []:
        n = {"role": m.get("role", "user"), "content": m.get("content")}
        if m.get("tool_calls"):
            n["tool_calls"] = [{"id": tc.get("id", ""), "name": (tc.get("function") or {}).get("name", ""),
                                "arguments": (tc.get("function") or {}).get("arguments") or "{}"} for tc in m["tool_calls"]]
        for k in ("tool_call_id", "name"):
            if m.get(k):
                n[k] = m[k]
        msgs.append(n)
    tools = [{"name": t["function"].get("name", ""), "description": t["function"].get("description", ""), "parameters": t["function"].get("parameters")}
             for t in body.get("tools") or [] if t.get("type") == "function" and isinstance(t.get("function"), dict)]
    return {"model": body.get("model"), "messages": msgs, "tools": tools, "stream": bool(body.get("stream")),
            "max_tokens": body.get("max_tokens") or body.get("max_completion_tokens"), "temperature": body.get("temperature")}


def _usage(u):
    u = u or {"prompt_tokens": 0, "completion_tokens": 0}
    return {"prompt_tokens": u["prompt_tokens"], "completion_tokens": u["completion_tokens"], "total_tokens": u["prompt_tokens"] + u["completion_tokens"]}


def _chunk(rid, created, model, delta, finish=None, usage=None):
    c = {"id": rid, "object": "chat.completion.chunk", "created": created, "model": model,
         "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
    if usage:
        c["usage"] = usage
    return ("data: %s\n\n" % json.dumps(c)).encode("utf-8")


def encode_stream(events, request, model):
    rid, created, i, usage, done = "chatcmpl-" + uuid.uuid4().hex[:24], int(time.time()), 0, None, False
    yield _chunk(rid, created, model, {"role": "assistant", "content": ""})
    for kind, p in events:
        if kind == "text":
            yield _chunk(rid, created, model, {"content": p})
        elif kind == "thinking":
            yield _chunk(rid, created, model, {"reasoning_content": p})
        elif kind == "tool_call":
            yield _chunk(rid, created, model, {"tool_calls": [{"index": i, "id": p["id"], "type": "function", "function": {"name": p["name"], "arguments": p["arguments"]}}]})
            i += 1
        elif kind == "usage":
            usage = _usage(p)
        elif kind == "finish":
            yield _chunk(rid, created, model, {}, p, usage)
            done = True
        elif kind == "error":
            yield ("data: %s\n\n" % encode_error(p["status"], p["message"], "upstream_error").decode()).encode()
            done = True
    if not done:
        yield _chunk(rid, created, model, {}, "stop", usage)
    yield b"data: [DONE]\n\n"


def encode_final(events, request, model):
    r = collect(events)
    if r["error"]:
        return r["error"]["status"], encode_error(r["error"]["status"], r["error"]["message"], "upstream_error")
    msg = {"role": "assistant", "content": r["text"] or None}
    if r["thinking"]:
        msg["reasoning_content"] = r["thinking"]
    if r["tool_calls"]:
        msg["tool_calls"] = [{"id": t["id"], "type": "function", "function": {"name": t["name"], "arguments": t["arguments"]}} for t in r["tool_calls"]]
    out = {"id": "chatcmpl-" + uuid.uuid4().hex[:24], "object": "chat.completion", "created": int(time.time()), "model": model,
           "choices": [{"index": 0, "message": msg, "finish_reason": r["finish"]}], "usage": _usage(r["usage"])}
    return 200, json.dumps(out).encode("utf-8")


def encode_error(status, message, kind=None):
    return json.dumps({"error": {"message": message, "type": kind or "api_error", "code": status}}).encode("utf-8")
```

- [ ] **Step 5: Write `codecs/anthropic.py`**

```python
"""Anthropic Messages API <-> internal Request/Events."""
import json
import uuid

from ..ir import collect, text_of

fmt = "anthropic"
STOP = {"stop": "end_turn", "tool_calls": "tool_use", "length": "max_tokens"}
ERR_TYPES = {400: "invalid_request_error", 401: "authentication_error", 403: "permission_error", 404: "not_found_error", 429: "rate_limit_error", 529: "overloaded_error"}


def decode(body):
    msgs = []
    if body.get("system"):
        msgs.append({"role": "system", "content": text_of(body["system"])})
    for m in body.get("messages") or []:
        role, c = m.get("role", "user"), m.get("content")
        if isinstance(c, str):
            msgs.append({"role": role, "content": c})
            continue
        texts, calls, results = [], [], []
        for b in c or []:
            t = b.get("type")
            if t == "text":
                texts.append(b.get("text", ""))
            elif t == "tool_use":
                calls.append({"id": b.get("id", ""), "name": b.get("name", ""), "arguments": json.dumps(b.get("input") or {})})
            elif t == "tool_result":
                results.append({"role": "tool", "tool_call_id": b.get("tool_use_id", ""), "content": text_of(b.get("content"))})
        if role == "user":
            msgs.extend(results)
            if texts:
                msgs.append({"role": "user", "content": "".join(texts)})
        else:
            n = {"role": "assistant", "content": "".join(texts) or None}
            if calls:
                n["tool_calls"] = calls
            msgs.append(n)
    tools = [{"name": t.get("name", ""), "description": t.get("description", ""), "parameters": t.get("input_schema")} for t in body.get("tools") or [] if t.get("name")]
    return {"model": body.get("model"), "messages": msgs, "tools": tools, "stream": bool(body.get("stream")),
            "max_tokens": body.get("max_tokens"), "temperature": body.get("temperature")}


def _ev(name, data):
    return ("event: %s\ndata: %s\n\n" % (name, json.dumps(data))).encode("utf-8")


def encode_stream(events, request, model):
    mid = "msg_" + uuid.uuid4().hex[:24]
    st = {"idx": -1, "open": None}
    usage = {"input_tokens": 0, "output_tokens": 0}
    yield _ev("message_start", {"type": "message_start", "message": {"id": mid, "type": "message", "role": "assistant", "model": model, "content": [], "stop_reason": None, "stop_sequence": None, "usage": usage}})

    def close():
        if not st["open"]:
            return b""
        st["open"] = None
        return _ev("content_block_stop", {"type": "content_block_stop", "index": st["idx"]})

    def open_block(kind, block):
        st["idx"] += 1
        st["open"] = kind
        return _ev("content_block_start", {"type": "content_block_start", "index": st["idx"], "content_block": block})

    stop = "stop"
    for kind, p in events:
        if kind == "text":
            if st["open"] != "text":
                yield close()
                yield open_block("text", {"type": "text", "text": ""})
            yield _ev("content_block_delta", {"type": "content_block_delta", "index": st["idx"], "delta": {"type": "text_delta", "text": p}})
        elif kind == "thinking":
            if st["open"] != "thinking":
                yield close()
                yield open_block("thinking", {"type": "thinking", "thinking": ""})
            yield _ev("content_block_delta", {"type": "content_block_delta", "index": st["idx"], "delta": {"type": "thinking_delta", "thinking": p}})
        elif kind == "tool_call":
            yield close()
            yield open_block("tool", {"type": "tool_use", "id": p["id"], "name": p["name"], "input": {}})
            yield _ev("content_block_delta", {"type": "content_block_delta", "index": st["idx"], "delta": {"type": "input_json_delta", "partial_json": p["arguments"]}})
            yield close()
        elif kind == "usage":
            usage = {"input_tokens": p["prompt_tokens"], "output_tokens": p["completion_tokens"]}
        elif kind == "finish":
            stop = p
        elif kind == "error":
            yield close()
            yield _ev("error", {"type": "error", "error": {"type": ERR_TYPES.get(p["status"], "api_error"), "message": p["message"]}})
            return
    yield close()
    yield _ev("message_delta", {"type": "message_delta", "delta": {"stop_reason": STOP.get(stop, "end_turn"), "stop_sequence": None}, "usage": usage})
    yield _ev("message_stop", {"type": "message_stop"})


def encode_final(events, request, model):
    r = collect(events)
    if r["error"]:
        return r["error"]["status"], encode_error(r["error"]["status"], r["error"]["message"])
    content = []
    if r["thinking"]:
        content.append({"type": "thinking", "thinking": r["thinking"], "signature": ""})
    if r["text"]:
        content.append({"type": "text", "text": r["text"]})
    for t in r["tool_calls"]:
        try:
            inp = json.loads(t["arguments"] or "{}")
        except ValueError:
            inp = {}
        content.append({"type": "tool_use", "id": t["id"], "name": t["name"], "input": inp})
    u = r["usage"] or {"prompt_tokens": 0, "completion_tokens": 0}
    out = {"id": "msg_" + uuid.uuid4().hex[:24], "type": "message", "role": "assistant", "model": model, "content": content,
           "stop_reason": STOP.get(r["finish"], "end_turn"), "stop_sequence": None,
           "usage": {"input_tokens": u["prompt_tokens"], "output_tokens": u["completion_tokens"]}}
    return 200, json.dumps(out).encode("utf-8")


def encode_error(status, message, kind=None):
    return json.dumps({"type": "error", "error": {"type": kind if kind in ERR_TYPES.values() else ERR_TYPES.get(status, "api_error"), "message": message}}).encode("utf-8")
```

- [ ] **Step 6: Write `codecs/responses.py`**

```python
"""OpenAI Responses API <-> internal Request/Events."""
import json
import time
import uuid

from ..ir import collect, text_of

fmt = "responses"


def decode(body):
    msgs = []
    if body.get("instructions"):
        msgs.append({"role": "system", "content": body["instructions"]})
    inp = body.get("input")
    if isinstance(inp, str):
        msgs.append({"role": "user", "content": inp})
    else:
        for it in inp or []:
            t = it.get("type", "message")
            if t == "message":
                role = it.get("role", "user")
                msgs.append({"role": "system" if role in ("system", "developer") else role, "content": text_of(it.get("content"))})
            elif t == "function_call":
                msgs.append({"role": "assistant", "content": None, "tool_calls": [{"id": it.get("call_id") or it.get("id", ""), "name": it.get("name", ""), "arguments": it.get("arguments") or "{}"}]})
            elif t == "function_call_output":
                o = it.get("output")
                msgs.append({"role": "tool", "tool_call_id": it.get("call_id", ""), "content": o if isinstance(o, str) else json.dumps(o)})
    tools = [{"name": t.get("name", ""), "description": t.get("description", ""), "parameters": t.get("parameters")} for t in body.get("tools") or [] if t.get("type") == "function"]
    return {"model": body.get("model"), "messages": msgs, "tools": tools, "stream": bool(body.get("stream")),
            "max_tokens": body.get("max_output_tokens"), "temperature": body.get("temperature")}


def _ev(name, data, seq):
    data["type"] = name
    data["sequence_number"] = seq[0]
    seq[0] += 1
    return ("event: %s\ndata: %s\n\n" % (name, json.dumps(data))).encode("utf-8")


def _usage(u):
    u = u or {"prompt_tokens": 0, "completion_tokens": 0}
    return {"input_tokens": u["prompt_tokens"], "output_tokens": u["completion_tokens"], "total_tokens": u["prompt_tokens"] + u["completion_tokens"]}


def _msg_item(mid, text):
    return {"id": mid, "type": "message", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": text, "annotations": []}]}


def _fc_item(t):
    return {"id": "fc_" + uuid.uuid4().hex[:24], "type": "function_call", "status": "completed", "call_id": t["id"], "name": t["name"], "arguments": t["arguments"]}


def encode_stream(events, request, model):
    rid, seq = "resp_" + uuid.uuid4().hex[:24], [0]
    base = {"id": rid, "object": "response", "created_at": int(time.time()), "model": model, "status": "in_progress", "output": []}
    yield _ev("response.created", {"response": dict(base)}, seq)
    yield _ev("response.in_progress", {"response": dict(base)}, seq)
    st = {"idx": -1, "mid": None, "text": []}
    output, usage, stop = [], None, "stop"

    def close_msg():
        if not st["mid"]:
            return
        full = "".join(st["text"])
        item = _msg_item(st["mid"], full)
        output.append(item)
        yield _ev("response.output_text.done", {"item_id": st["mid"], "output_index": st["idx"], "content_index": 0, "text": full}, seq)
        yield _ev("response.content_part.done", {"item_id": st["mid"], "output_index": st["idx"], "content_index": 0, "part": item["content"][0]}, seq)
        yield _ev("response.output_item.done", {"output_index": st["idx"], "item": item}, seq)
        st["mid"], st["text"] = None, []

    for kind, p in events:
        if kind == "text":
            if not st["mid"]:
                st["idx"] += 1
                st["mid"] = "msg_" + uuid.uuid4().hex[:24]
                yield _ev("response.output_item.added", {"output_index": st["idx"], "item": {"id": st["mid"], "type": "message", "role": "assistant", "status": "in_progress", "content": []}}, seq)
                yield _ev("response.content_part.added", {"item_id": st["mid"], "output_index": st["idx"], "content_index": 0, "part": {"type": "output_text", "text": "", "annotations": []}}, seq)
            st["text"].append(p)
            yield _ev("response.output_text.delta", {"item_id": st["mid"], "output_index": st["idx"], "content_index": 0, "delta": p}, seq)
        elif kind == "tool_call":
            for f in close_msg():
                yield f
            st["idx"] += 1
            item = _fc_item(p)
            yield _ev("response.output_item.added", {"output_index": st["idx"], "item": dict(item, status="in_progress", arguments="")}, seq)
            yield _ev("response.function_call_arguments.delta", {"item_id": item["id"], "output_index": st["idx"], "delta": p["arguments"]}, seq)
            yield _ev("response.function_call_arguments.done", {"item_id": item["id"], "output_index": st["idx"], "arguments": p["arguments"]}, seq)
            yield _ev("response.output_item.done", {"output_index": st["idx"], "item": item}, seq)
            output.append(item)
        elif kind == "usage":
            usage = p
        elif kind == "finish":
            stop = p
        elif kind == "error":
            for f in close_msg():
                yield f
            yield _ev("response.failed", {"response": dict(base, status="failed", error={"code": "upstream_error", "message": p["message"]})}, seq)
            return
        # ponytail: "thinking" dropped in Responses encoding; add response.reasoning_summary_text.delta when a client needs it
    for f in close_msg():
        yield f
    yield _ev("response.completed", {"response": dict(base, status="incomplete" if stop == "length" else "completed", output=output, usage=_usage(usage))}, seq)


def encode_final(events, request, model):
    r = collect(events)
    if r["error"]:
        return r["error"]["status"], encode_error(r["error"]["status"], r["error"]["message"], "upstream_error")
    output = []
    if r["text"]:
        output.append(_msg_item("msg_" + uuid.uuid4().hex[:24], r["text"]))
    output += [_fc_item(t) for t in r["tool_calls"]]
    out = {"id": "resp_" + uuid.uuid4().hex[:24], "object": "response", "created_at": int(time.time()), "model": model,
           "status": "incomplete" if r["finish"] == "length" else "completed", "output": output, "usage": _usage(r["usage"])}
    return 200, json.dumps(out).encode("utf-8")


def encode_error(status, message, kind=None):
    return json.dumps({"error": {"message": message, "type": kind or "api_error", "code": status}}).encode("utf-8")
```

- [ ] **Step 7: Run** — `python3 -m unittest tests.test_codecs -v` → 7 PASS.
- [ ] **Step 8: Commit** — `git add src/llm_bridge/codecs tests/test_codecs.py && git commit -m "feat(codecs): openai chat, anthropic messages, openai responses codecs"`

---

### Task 7: `server.py`

**Files:**
- Create: `src/llm_bridge/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `codecs.by_path`, `providers.resolve/RouteError/list_models/PROVIDERS`, `providers.base.UpstreamError`, `store.verify_key`.
- Produces: `serve(host, port, cfg)`, `class Handler(BaseHTTPRequestHandler)` with class attr `cfg`.

- [ ] **Step 1: Write the failing test** (in-process server, fake provider injected into the registry)

```python
# tests/test_server.py
import json, os, sys, tempfile, threading, unittest, urllib.error, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))
os.environ["LLM_BRIDGE_HOME"] = tempfile.mkdtemp()
from http.server import ThreadingHTTPServer
from llm_bridge import providers, server, store
from llm_bridge.providers.base import Provider


class Fake(Provider):
    name, native_fmt, prefixes, catalog, aliases = "fake", None, ("fake-",), [{"id": "fake-1", "name": "Fake"}], {}
    def _load(self):
        return {"access": "t", "refresh": None, "expires_at": 9e9}
    def stream(self, request, model):
        self.last = request
        yield ("text", "ok:" + model)
        yield ("usage", {"prompt_tokens": 1, "completion_tokens": 1})
        yield ("finish", "stop")


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        providers.PROVIDERS["fake"] = cls.fake = Fake()
        cls.key = store.create_key("t")
        server.Handler.cfg = {"default_provider": None}
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def call(self, path, body=None, key=None, headers=None):
        h = {"Content-Type": "application/json"}
        if key is not False:
            h["Authorization"] = "Bearer " + (key or self.key)
        h.update(headers or {})
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_health_and_auth(self):
        self.assertEqual(self.call("/health", key=False)[0], 200)
        s, b = self.call("/v1/models", key="sk-lb-bad")
        self.assertEqual((s, json.loads(b)["error"]["type"]), (401, "authentication_error"))
        s, b = self.call("/v1/messages", {"model": "fake-1", "messages": []}, key=False)
        self.assertEqual((s, json.loads(b)["type"]), (401, "error"))  # anthropic-shaped error
        s, b = self.call("/v1/messages", {"model": "fake-1", "messages": [{"role": "user", "content": "x"}], "max_tokens": 5}, key=False, headers={"x-api-key": self.key})
        self.assertEqual(s, 200)

    def test_models(self):
        s, b = self.call("/v1/models")
        self.assertIn("fake/fake-1", [m["id"] for m in json.loads(b)["data"]])

    def test_chat_nonstream_and_stream(self):
        s, b = self.call("/v1/chat/completions", {"model": "fake/fake-1", "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual((s, json.loads(b)["choices"][0]["message"]["content"]), (200, "ok:fake-1"))
        s, b = self.call("/v1/chat/completions", {"model": "fake-1", "stream": True, "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(s, 200)
        self.assertTrue(b.endswith(b"data: [DONE]\n\n"))
        self.assertIn(b'"content": "ok:fake-1"', b)

    def test_routing_errors(self):
        s, b = self.call("/v1/chat/completions", {"model": "unknown-thing", "messages": []})
        self.assertEqual(s, 400)
        self.assertIn("provider/model", json.loads(b)["error"]["message"])
        s, b = self.call("/v1/chat/completions", {"model": "fake/x", "messages": []}, headers={"Content-Type": "text/plain"})
        self.assertEqual(s, 200)  # content-type is not enforced, body was valid JSON
        req = urllib.request.Request(self.base + "/v1/chat/completions", data=b"{bad", headers={"Authorization": "Bearer " + self.key})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(cm.exception.code, 400)

    def test_other_formats(self):
        s, b = self.call("/v1/messages", {"model": "fake-1", "max_tokens": 5, "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual((s, json.loads(b)["content"][0]["text"]), (200, "ok:fake-1"))
        s, b = self.call("/v1/responses", {"model": "fake-1", "input": "hi"})
        self.assertEqual((s, json.loads(b)["output"][0]["content"][0]["text"]), (200, "ok:fake-1"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it** → FAIL.

- [ ] **Step 3: Write `server.py`**

```python
"""HTTP server: key auth, format dispatch, provider pipeline, native passthrough."""
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import codecs, providers
from .codecs import openai_chat
from .providers.base import UpstreamError
from .store import verify_key

CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Authorization, Content-Type, x-api-key, anthropic-version, anthropic-beta"}


class Handler(BaseHTTPRequestHandler):
    cfg = {}
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # replaced by _log
        pass

    def _log(self, status, t0, what=""):
        print("[%s] %s %s %s %dms %s" % (time.strftime("%H:%M:%S"), self.command, self.path, status, (time.time() - t0) * 1000, what), flush=True)

    def _head(self, status, ctype="application/json", length=None, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        if length is not None:
            self.send_header("Content-Length", str(length))
        for k, v in dict(CORS, **(extra or {})).items():
            self.send_header(k, v)
        self.end_headers()

    def _send(self, status, body, ctype="application/json"):
        self._head(status, ctype, len(body))
        self.wfile.write(body)

    def _authed(self):
        h = self.headers
        key = h.get("x-api-key") or (h.get("Authorization") or "").replace("Bearer", "", 1).strip()
        return verify_key(key)

    def do_OPTIONS(self):
        self._head(204, length=0)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/health"):
            return self._send(200, b'{"status":"ok","service":"llm-bridge"}')
        if not self._authed():
            return self._send(401, openai_chat.encode_error(401, "invalid API key (llm-bridge keys list)", "authentication_error"))
        if path in ("/v1/models", "/models"):
            return self._send(200, json.dumps({"object": "list", "data": providers.list_models()}).encode())
        if path.startswith("/v1/models/"):
            return self._send(200, json.dumps({"id": path[len("/v1/models/"):], "object": "model", "created": int(time.time()), "owned_by": "llm-bridge"}).encode())
        self._send(404, openai_chat.encode_error(404, "not found", "invalid_request_error"))

    def do_POST(self):
        t0, path = time.time(), self.path.split("?")[0]
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))  # always drain: keep-alive safety
        codec = codecs.by_path(path)
        if not codec:
            return self._send(404, openai_chat.encode_error(404, "not found", "invalid_request_error"))
        if not self._authed():
            return self._send(401, codec.encode_error(401, "invalid API key (llm-bridge keys list)", "authentication_error"))
        try:
            body = json.loads(raw)
            if not isinstance(body, dict):
                raise ValueError("body must be a JSON object")
        except ValueError as e:
            return self._send(400, codec.encode_error(400, "invalid JSON: %s" % e, "invalid_request_error"))
        try:
            provider, model = providers.resolve(body.get("model"), self.cfg.get("default_provider"))
        except providers.RouteError as e:
            return self._send(400, codec.encode_error(400, str(e), "invalid_request_error"))
        st = provider.auth_status()
        if not st["ok"]:
            return self._send(401, codec.encode_error(401, "%s: %s. %s" % (provider.name, st["detail"], st["fix"]), "authentication_error"))
        what = "%s/%s" % (provider.name, model)
        try:
            if codec.fmt == provider.native_fmt:
                up = provider.passthrough(body, {k.lower(): v for k, v in self.headers.items()}, model)
                if up is not None:
                    return self._pipe(up, t0, what + " passthrough")
            request = codec.decode(body)
            events = provider.stream(request, model)
            if request["stream"]:
                self._head(200, "text/event-stream", extra={"Cache-Control": "no-cache", "Connection": "close"})
                for frame in codec.encode_stream(events, request, model):
                    if frame:
                        self.wfile.write(frame)
                        self.wfile.flush()
                self.close_connection = True
                return self._log(200, t0, what + " stream")
            status, out = codec.encode_final(events, request, model)
            self._send(status, out)
            self._log(status, t0, what)
        except UpstreamError as e:
            self._send(e.status, codec.encode_error(e.status, e.message, "upstream_error"))
            self._log(e.status, t0, what + " " + e.message)
        except (BrokenPipeError, ConnectionResetError):
            self._log("closed", t0, what)

    def _pipe(self, up, t0, what):
        """Stream an upstream response back verbatim."""
        self._head(up.status, up.headers.get("Content-Type", "application/json"), extra={"Cache-Control": "no-cache", "Connection": "close"})
        for chunk in iter(lambda: up.read(4096), b""):
            self.wfile.write(chunk)
            self.wfile.flush()
        self.close_connection = True
        self._log(up.status, t0, what)


def serve(host, port, cfg):
    Handler.cfg = cfg
    srv = ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True
    print("[llm-bridge] listening on http://%s:%d/v1" % (host, port), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
```

- [ ] **Step 4: Run** — `python3 -m unittest tests.test_server -v` → 5 PASS.
- [ ] **Step 5: Commit** — `git add src/llm_bridge/server.py tests/test_server.py && git commit -m "feat(server): unified gateway with key auth, three inbound formats, native passthrough"`

---

### Task 8: `service.py`, `connect/`, `cli.py`

**Files:**
- Create: `src/llm_bridge/service.py`, `src/llm_bridge/connect/__init__.py`, `src/llm_bridge/connect/hermes.py`, `src/llm_bridge/connect/openclaw.py`, `src/llm_bridge/cli.py`
- Source: `connect/hermes.py` = `src/antigravity_bridge/config_hermes.py` verbatim except defaults; `connect/openclaw.py` = `config_openclaw.py` with the provider block below.
- Test: manual (`llm-bridge --help`, `llm-bridge keys create x`, `llm-bridge models`); CI runs `llm-bridge --help && lbr --help`.

**Interfaces:**
- Produces: `service.install(host, port)`, `service.uninstall()`, `service.ctl(action)` (`start|stop|restart|status`), `service.installed()->bool`; `connect.hermes.configure_hermes(port, model, api_key, host)`, `connect.openclaw.configure_openclaw(port, model, api_key, host)`; `cli.main()`.

- [ ] **Step 1: `service.py`**

```python
"""Background service: launchd user agent (macOS) or systemd unit (Linux)."""
import os
import shutil
import subprocess
import sys

LABEL = "com.llm-bridge"
PLIST = os.path.expanduser("~/Library/LaunchAgents/%s.plist" % LABEL)
UNIT_USER = os.path.expanduser("~/.config/systemd/user/llm-bridge.service")
UNIT_SYSTEM = "/etc/systemd/system/llm-bridge.service"
MAC = sys.platform == "darwin"
ROOT = os.geteuid() == 0


def _exe():
    return [shutil.which("llm-bridge")] if shutil.which("llm-bridge") else [sys.executable, "-m", "llm_bridge.cli"]


def _unit_path():
    return UNIT_SYSTEM if ROOT else UNIT_USER


def _systemctl(*args):
    return subprocess.run(["systemctl"] + ([] if ROOT else ["--user"]) + list(args), capture_output=True, text=True)


def installed():
    return os.path.exists(PLIST if MAC else _unit_path())


def install(host, port):
    args = _exe() + ["up", "--host", str(host), "--port", str(port)]
    if MAC:
        os.makedirs(os.path.dirname(PLIST), exist_ok=True)
        log = os.path.expanduser("~/.llm-bridge/service.log")
        os.makedirs(os.path.dirname(log), exist_ok=True)
        items = "".join("<string>%s</string>" % a for a in args)
        with open(PLIST, "w") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                    '<plist version="1.0"><dict><key>Label</key><string>%s</string><key>ProgramArguments</key><array>%s</array>'
                    '<key>RunAtLoad</key><true/><key>KeepAlive</key><true/><key>StandardOutPath</key><string>%s</string><key>StandardErrorPath</key><string>%s</string>'
                    '</dict></plist>\n' % (LABEL, items, log, log))
        subprocess.run(["launchctl", "unload", PLIST], capture_output=True)
        r = subprocess.run(["launchctl", "load", "-w", PLIST], capture_output=True, text=True)
        return r.returncode == 0, r.stderr.strip() or PLIST
    if not shutil.which("systemctl"):
        return False, "no systemd or launchd on this system; run `llm-bridge up` in a terminal multiplexer instead"
    path = _unit_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("[Unit]\nDescription=LLM Bridge\nAfter=network.target\n\n[Service]\nExecStart=%s\nRestart=always\nRestartSec=3\nEnvironment=PYTHONUNBUFFERED=1\n\n[Install]\nWantedBy=%s\n"
                % (" ".join(args), "multi-user.target" if ROOT else "default.target"))
    _systemctl("daemon-reload")
    r = _systemctl("enable", "--now", "llm-bridge.service")
    return r.returncode == 0, r.stderr.strip() or path


def uninstall():
    if MAC:
        subprocess.run(["launchctl", "unload", "-w", PLIST], capture_output=True)
        if os.path.exists(PLIST):
            os.remove(PLIST)
        return True
    _systemctl("disable", "--now", "llm-bridge.service")
    if os.path.exists(_unit_path()):
        os.remove(_unit_path())
    _systemctl("daemon-reload")
    return True


def ctl(action):
    """start | stop | restart | status -> (ok, text)."""
    if MAC:
        if action == "status":
            r = subprocess.run(["launchctl", "list", LABEL], capture_output=True, text=True)
            return r.returncode == 0, "running" if r.returncode == 0 else "not loaded"
        for a in (["stop", "start"] if action == "restart" else [action]):
            r = subprocess.run(["launchctl", a, LABEL], capture_output=True, text=True)
        return r.returncode == 0, r.stderr.strip() or action
    r = _systemctl("is-active" if action == "status" else action, "llm-bridge.service")
    return r.returncode == 0, (r.stdout or r.stderr).strip()
```

- [ ] **Step 2: `connect/__init__.py`** — empty docstring `"""Optional client auto-configuration (Hermes, OpenClaw)."""`.

- [ ] **Step 3: `connect/hermes.py`** — copy `src/antigravity_bridge/config_hermes.py`; change `configure_hermes` defaults to `model="antigravity/gemini-3.8-flash", api_key=""`, message text `"Hermes configured for LLM Bridge (%s) with model '%s'"`; rename `is_antigravity` key to `is_bridge`.

- [ ] **Step 4: `connect/openclaw.py`** — copy `src/antigravity_bridge/config_openclaw.py`; replace `from .models import AVAILABLE_MODELS` with `from ..providers import list_models`; in `configure_openclaw` replace the provider block with:

```python
    clean_model_id = model if "/" in model else "antigravity/" + model
    cfg["agents"]["defaults"]["model"]["primary"] = "llm-bridge/" + clean_model_id
    cfg["models"]["providers"]["llm-bridge"] = {
        "baseUrl": base_url, "api": "openai-completions", "auth": "api-key",
        "models": [{"id": m["id"], "name": m["id"]} for m in list_models()],
    }
    cfg["auth"]["profiles"]["llm-bridge:manual"] = {"provider": "llm-bridge", "mode": "api_key"}
```
and in `update_openclaw_sqlite_auth` use profile key `"llm-bridge:manual"`, `"provider": "llm-bridge"`, `state["lastGood"]["llm-bridge"] = "llm-bridge:manual"`. Defaults `model="antigravity/gemini-3.8-flash", api_key=""`. Rename `is_antigravity` → `is_bridge` (`"llm-bridge" in primary or "127.0.0.1" in base_url`).

- [ ] **Step 5: `cli.py`**

```python
"""llm-bridge command line."""
import argparse
import json
import os
import shutil
import subprocess
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
```

- [ ] **Step 6: Verify** — `pip install -e . -q && llm-bridge --help && lbr --version && llm-bridge keys create smoke && llm-bridge keys list && llm-bridge keys revoke smoke && llm-bridge models && python3 tests/run_tests.py`.
- [ ] **Step 7: Commit** — `git add src/llm_bridge/service.py src/llm_bridge/connect src/llm_bridge/cli.py && git commit -m "feat(cli): up/keys/models/status/test/service/connect"`

---

### Task 9: Remove old package, docs, packaging, CI

**Files:**
- Delete: `src/antigravity_bridge/` (all), `bin/antigravity-bridge`, `bin/agy-bridge`, `systemd/antigravity-proxy.service`, `docs/systemd.md`
- Modify: `README.md`, `install.sh`, `.github/workflows/ci.yml`, `CHANGELOG.md`, `docs/quickstart.md`, `docs/models.md`, `docs/hermes.md`, `docs/openclaw.md`, `examples/*`, `SECURITY.md` (name only), `CONTRIBUTING.md` (name + test cmd)
- Create: `bin/llm-bridge`, `docs/providers.md`

- [ ] **Step 1: Delete** — `git rm -rq src/antigravity_bridge bin systemd docs/systemd.md`.

- [ ] **Step 2: `bin/llm-bridge`** (chmod +x)

```bash
#!/usr/bin/env bash
exec python3 -m llm_bridge.cli "$@"
```

- [ ] **Step 3: `install.sh`**

```bash
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
```

- [ ] **Step 4: `.github/workflows/ci.yml`** — replace the last step's commands with `llm-bridge --help` and `lbr --version`.

- [ ] **Step 5: `README.md`** — rewrite. Sections, in order: title + badges (CI, Python 3.8+, MIT, Zero Dependencies); one-paragraph pitch (“Your `agy`, `claude` and `codex` logins → one local OpenAI-compatible API with your own keys. Nothing leaves your machine.”); the ToS note (one sentence: using subscription OAuth tokens from third-party clients may violate Anthropic/OpenAI terms — your account, your call); **Quickstart** (`pip install .` → `llm-bridge up` → the banner as shown in the spec §2 → curl example); **Use it from** table: curl, OpenAI SDK (`base_url="http://127.0.0.1:8000/v1"`), Anthropic SDK (`base_url="http://127.0.0.1:8000"`, `api_key=<key>`), Claude Code (`ANTHROPIC_BASE_URL=http://127.0.0.1:8000 ANTHROPIC_API_KEY=<key> claude --model openai/gpt-5-codex`), Cursor/Cline/Continue (base URL + key), Hermes/OpenClaw (`llm-bridge connect …`); **Providers** table (how to log in, what models); **Model names** (`provider/model`, bare-prefix routing, precedence, `default_provider`); **Endpoints** table; **Commands** table (spec §2); **Background service**; **Architecture** (the two ASCII diagrams from the spec §3, shortened); **Testing**; **Docs** links; **Contributing**; **License**.

- [ ] **Step 6: `docs/`** — `quickstart.md`: same 3 commands + banner + one curl. `providers.md` (new): per provider the credential file, refresh endpoint, upstream URL, catalog, quirks (Claude Code identity line; codex streaming-only; antigravity quota fallback). `models.md`: routing precedence + alias table per provider. `hermes.md` / `openclaw.md`: replace `antigravity-bridge setup --agent X` with `llm-bridge connect X --model …`, keep the rest.

- [ ] **Step 7: `examples/`** — `curl_completions.sh`: `MODEL=${1:-antigravity/gemini-3.8-flash}`, `KEY=$(python3 -c "import json,os;print(next(iter(json.load(open(os.path.expanduser('~/.llm-bridge/keys.json'))).values()))['key'])")`. `openai_sdk_example.py` / `tool_calling_example.py`: `base_url="http://127.0.0.1:8000/v1"`, `api_key=os.environ["LLM_BRIDGE_KEY"]`, model `anthropic/claude-sonnet-5`. Add `examples/anthropic_sdk_example.py` (8 lines) and `examples/claude_code.sh` (2 lines env + `claude`).

- [ ] **Step 8: `CHANGELOG.md`** — prepend `## [2.0.0] - 2026-09-21` with: Renamed to llm-bridge; Added anthropic (Claude Code) and openai (Codex) providers; Added `/v1/messages` and `/v1/responses` with native passthrough; Added API keys (`keys create/list/revoke`); Added launchd service; Changed `setup` → `up` + `connect`; Removed fuzzy model matching; Breaking: package, CLI names, Bearer key now required.

- [ ] **Step 9: Verify** — `python3 tests/run_tests.py` (all green), `pip install -e . -q && llm-bridge --help`, `rg -n "antigravity[-_]bridge|agy-bridge" --glob '!docs/superpowers/**' --glob '!CHANGELOG.md'` returns nothing.
- [ ] **Step 10: Commit** — `git add -A -- . ':!CLAUDE*.md' && git commit -m "feat!: rename to llm-bridge 2.0 — multi-provider gateway, docs, packaging"`

---

## Live verification (after Task 9, needs the real CLIs)

```bash
llm-bridge up &          # note the key
llm-bridge models        # states per provider
llm-bridge test antigravity/gemini-3.8-flash
llm-bridge test anthropic/claude-sonnet-5
llm-bridge test openai/gpt-5-codex
# cross-format:
ANTHROPIC_BASE_URL=http://127.0.0.1:8000 ANTHROPIC_API_KEY=<key> claude --model openai/gpt-5-codex -p "say hi"
```
If a provider 401s after refresh, compare `CLIENT_ID`/`TOKEN_URL`/headers in that adapter against the installed CLI's actual credential file and traffic — those constants are the drift risk called out in the spec §4.
