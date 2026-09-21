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
