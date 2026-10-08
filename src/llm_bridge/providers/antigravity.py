"""Google Antigravity (agy) provider: OAuth token file + Cloud Code streamGenerateContent."""
import json
import math
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from ..ir import text_of
from ..accounts import atomic_json, file_lock
from .base import Provider, UpstreamError, http, open_upstream

TOKEN_PATHS = [
    os.path.expanduser("~/.openclaw/agents/main/agent/auth-profiles.json"),
    os.path.expanduser("~/.gemini/antigravity-cli/antigravity-oauth-token"),
    os.path.expanduser("~/.gemini/jetski-standalone-oauth-token"),
    os.path.expanduser("~/.gemini/oauth_token.json"),
    "/root/.gemini/antigravity-cli/antigravity-oauth-token",
]
CLIENT_ID = os.environ.get("ANTIGRAVITY_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("ANTIGRAVITY_CLIENT_SECRET", "")
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
            stamp = datetime.fromisoformat(str(exp_s).replace("Z", "+00:00"))
            expires_at = (stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)).timestamp()
        except ValueError:
            pass
    elif tok.get("expiry_date") is not None:
        expires_at = float(tok["expiry_date"]) / 1000.0
    return {"access": tok.get("access_token"), "refresh": tok.get("refresh_token"), "expires_at": expires_at}


class Antigravity(Provider):
    def __init__(self, token_file=None, project_id=None):
        super().__init__()
        self.token_file = token_file
        self.project_id = project_id or PROJECT_ID

    def token(self, force_refresh=False):
        if self.token_file:
            with file_lock(self.token_file + ".lock"):
                return super().token(force_refresh)
        return super().token(force_refresh)

    name = "antigravity"
    prefixes = ("gemini-",)
    login_hint = "run: agy   (log in with Google)"
    catalog = [
        {"id": "gemini-3.8-flash", "name": "Gemini 3.8 Flash"},
        {"id": "gemini-3.8-flash-high", "name": "Gemini 3.8 Flash (High)"},
        {"id": "gemini-3.7-flash", "name": "Gemini 3.7 Flash"},
        {"id": "gemini-3.6-flash-high", "name": "Gemini 3.6 Flash (High)"},
        {"id": "gemini-3.1-pro-high", "name": "Gemini 3.1 Pro (High)"},
        {"id": "gemini-3.1-pro-low", "name": "Gemini 3.1 Pro (Low)"},
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
        path = self.token_file or token_path()
        if not path:
            return None
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return None
        try:
            cred = _parse(data)
        except (ValueError, TypeError, AttributeError, OverflowError):
            return None
        if not cred.get("access"):
            return None
        if not isinstance(cred["access"], str) or not math.isfinite(cred["expires_at"]):
            return None
        cred["_data"], cred["_path"] = data, path
        return cred

    def _refresh(self, cred):
        if cred.get("refresh") and CLIENT_ID and CLIENT_SECRET:  # direct Google OAuth refresh; without creds we fall back to `agy`
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
                atomic_json(cred["_path"], data)
                return self._load()
            except Exception:
                pass
        if self.token_file:
            return None  # A named account must never refresh through an unrelated CLI login.
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
        # The generation endpoint accepts the Pro tier route, not the catalog's
        # high display id. Keep Pro High's advertised 10001-token thinking budget.
        upstream_model = model
        if model == "gemini-3.1-pro-high":
            upstream_model = "gemini-3.1-pro-low"
            req["generationConfig"] = {"thinkingConfig": {"thinkingBudget": 10001, "includeThoughts": True}}
        if sys_inst:
            req["systemInstruction"] = sys_inst
        decls = transform_tools(request.get("tools"))
        if decls:
            req["tools"] = decls
        body = {"project": self.project_id, "model": upstream_model, "request": req, "requestType": "agent",
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
