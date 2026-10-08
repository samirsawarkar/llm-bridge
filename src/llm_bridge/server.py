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
            try:
                models = providers.list_models()
            except ValueError:
                return self._send(503, openai_chat.encode_error(503, "account configuration is unreadable; repair accounts.json", "configuration_error"))
            return self._send(200, json.dumps({"object": "list", "data": models}).encode())
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
