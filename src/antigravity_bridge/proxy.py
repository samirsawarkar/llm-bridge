"""Antigravity OpenAI-Compatible Proxy Server Engine."""

import json
import os
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional, Tuple

from .auth import get_auth_token, resolve_agy_bin, resolve_token_path
from .models import (
    AVAILABLE_MODELS,
    DEFAULT_THOUGHT_SIGNATURE,
    clean_json_schema,
    map_model,
)

API_ENDPOINT = "https://daily-cloudcode-pa.googleapis.com/v1internal:streamGenerateContent?alt=sse"
DEFAULT_PROJECT_ID = "aicode-consumers"

# Global tool call cache: call_id -> {"name": str, "thoughtSignature": str}
TOOL_CALL_CACHE: Dict[str, Dict] = {}


def transform_messages(messages: List[Dict]) -> Tuple[Optional[Dict], List[Dict]]:
    """Translate OpenAI messages to Gemini systemInstruction and contents array."""
    # 1. Pre-scan assistant messages to map tool_call_id -> function name
    call_id_to_name = {}
    for msg in messages:
        if msg.get("role") == "assistant":
            for tc in msg.get("tool_calls") or []:
                cid = tc.get("id")
                fn = tc.get("function", {})
                fn_name = fn.get("name")
                if cid and fn_name:
                    call_id_to_name[cid] = fn_name

    system_parts = []
    contents = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content")

        if role == "system":
            if content:
                system_parts.append({"text": str(content)})
        elif role == "user":
            text = content if isinstance(content, str) else json.dumps(content) if content else ""
            contents.append({"role": "user", "parts": [{"text": text}]})
        elif role == "assistant":
            parts = []
            if content:
                parts.append({"text": str(content)})
            tool_calls = msg.get("tool_calls") or []
            for tc in tool_calls:
                cid = tc.get("id", "")
                fn = tc.get("function", {})
                name = fn.get("name", "")
                args_str = fn.get("arguments", "{}")
                try:
                    args = json.loads(args_str) if isinstance(args_str, str) else (args_str or {})
                except Exception:
                    args = {}
                part = {"functionCall": {"name": name, "args": args, "id": cid}}
                ts = None
                if cid in TOOL_CALL_CACHE and "thoughtSignature" in TOOL_CALL_CACHE[cid]:
                    ts = TOOL_CALL_CACHE[cid]["thoughtSignature"]
                part["thoughtSignature"] = ts or DEFAULT_THOUGHT_SIGNATURE
                parts.append(part)
            if not parts:
                parts.append({"text": ""})
            contents.append({"role": "model", "parts": parts})
        elif role == "tool":
            cid = msg.get("tool_call_id", "")
            name = call_id_to_name.get(cid) or TOOL_CALL_CACHE.get(cid, {}).get("name") or msg.get("name") or "tool"
            raw_res = content if content is not None else ""
            try:
                res_obj = json.loads(raw_res) if isinstance(raw_res, str) else raw_res
            except Exception:
                res_obj = {"output": str(raw_res)}
            if not isinstance(res_obj, dict):
                res_obj = {"output": res_obj}

            contents.append({
                "role": "user",
                "parts": [{
                    "functionResponse": {
                        "name": name,
                        "response": res_obj,
                        "id": cid,
                    }
                }],
            })

    # Gemini requires the last turn in contents to be role == 'user'
    if contents and contents[-1].get("role") == "model":
        contents.append({"role": "user", "parts": [{"text": ""}]})

    sys_instruction = {"parts": system_parts} if system_parts else None
    return sys_instruction, contents


def transform_tools(tools: Optional[List[Dict]]) -> Optional[List[Dict]]:
    """Translate OpenAI tools array into Google functionDeclarations."""
    if not tools:
        return None
    declarations = []
    for t in tools:
        if t.get("type") == "function":
            fn = t.get("function", {})
            params = clean_json_schema(fn.get("parameters", {}))
            declarations.append({
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "parameters": params,
            })
    return [{"functionDeclarations": declarations}] if declarations else None


class ProxyHandler(BaseHTTPRequestHandler):
    token_file: Optional[str] = None
    agy_bin: Optional[str] = None
    project_id: str = DEFAULT_PROJECT_ID

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path == "/v1/models" or self.path == "/models":
            self.handle_models()
        elif self.path.startswith("/v1/models/"):
            mid = self.path.split("/v1/models/")[-1]
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(
                json.dumps({
                    "id": mid,
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": "antigravity",
                }).encode()
            )
        elif self.path in ("/", "/health"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps({"status": "ok", "service": "antigravity-bridge-proxy"}).encode()
            )
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path in ("/v1/chat/completions", "/chat/completions"):
            self.handle_chat_completions()
        else:
            self.send_response(404)
            self.end_headers()

    def handle_models(self):
        models_data = [
            {
                "id": m["id"],
                "object": "model",
                "created": int(time.time()),
                "owned_by": "antigravity",
            }
            for m in AVAILABLE_MODELS
        ]
        resp = {"object": "list", "data": models_data}
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(resp).encode())

    def handle_chat_completions(self):
        content_len = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_len)
        try:
            req_json = json.loads(post_data.decode("utf-8"))
        except Exception as e:
            self.send_error(400, f"Invalid JSON: {e}")
            return

        requested_model = req_json.get("model")
        model_name = map_model(requested_model)
        messages = req_json.get("messages", [])
        tools = req_json.get("tools")
        stream = bool(req_json.get("stream", False))

        sys_inst, contents = transform_messages(messages)
        f_decls = transform_tools(tools)

        req_payload = {"contents": contents}
        if sys_inst:
            req_payload["systemInstruction"] = sys_inst
        if f_decls:
            req_payload["tools"] = f_decls

        body_dict = {
            "project": self.project_id,
            "model": model_name,
            "request": req_payload,
        }
        body_bytes = json.dumps(body_dict).encode("utf-8")

        token = get_auth_token(self.token_file, self.agy_bin)
        if not token:
            self.send_error(500, "Failed to obtain Antigravity OAuth token")
            return

        def send_upstream(tok: str):
            r = urllib.request.Request(
                API_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {tok}",
                    "Content-Type": "application/json",
                    "User-Agent": "Antigravity-CLI/1.1.27",
                },
                data=body_bytes,
            )
            return urllib.request.urlopen(r, timeout=180)

        try:
            upstream_resp = send_upstream(token)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                print(f"[PROXY] HTTP {e.code} received. Forcing token refresh...", flush=True)
                token = get_auth_token(self.token_file, self.agy_bin, force_refresh=True)
                if not token:
                    self.send_error(502, "Failed to refresh Antigravity token")
                    return
                try:
                    upstream_resp = send_upstream(token)
                except Exception as e2:
                    self.send_error(502, f"Upstream error after refresh: {e2}")
                    return
            else:
                err_body = e.read().decode("utf-8", errors="replace")[:1000]
                print(f"[PROXY] Upstream HTTP {e.code} for model {model_name} (req: {requested_model}): {err_body}", flush=True)
                self.send_error(e.code, f"Upstream error: {err_body}")
                return
        except Exception as e:
            self.send_error(502, f"Upstream connection error: {e}")
            return

        req_id = f"chatcmpl-{int(time.time())}"
        created_time = int(time.time())

        if stream:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            for raw_line in upstream_resp:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data: "):
                    continue
                try:
                    d = json.loads(line[6:])
                    cands = d.get("response", {}).get("candidates", [])
                    if not cands:
                        continue
                    cand = cands[0]
                    parts = cand.get("content", {}).get("parts", [])
                    finish_reason = cand.get("finishReason")

                    for part in parts:
                        thought_sig = part.get("thoughtSignature")
                        if "text" in part:
                            txt = part["text"]
                            chunk = {
                                "id": req_id,
                                "object": "chat.completion.chunk",
                                "created": created_time,
                                "model": model_name,
                                "choices": [{
                                    "index": 0,
                                    "delta": {"content": txt},
                                    "finish_reason": None,
                                }],
                            }
                            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
                            self.wfile.flush()

                        if "functionCall" in part:
                            fc = part["functionCall"]
                            cid = fc.get("id") or f"call_{int(time.time() * 1000)}"
                            fn_name = fc.get("name", "")
                            fn_args = json.dumps(fc.get("args", {}))
                            TOOL_CALL_CACHE[cid] = {
                                "name": fn_name,
                                "thoughtSignature": thought_sig,
                            }
                            chunk = {
                                "id": req_id,
                                "object": "chat.completion.chunk",
                                "created": created_time,
                                "model": model_name,
                                "choices": [{
                                    "index": 0,
                                    "delta": {
                                        "tool_calls": [{
                                            "index": 0,
                                            "id": cid,
                                            "type": "function",
                                            "function": {"name": fn_name, "arguments": fn_args},
                                        }]
                                    },
                                    "finish_reason": None,
                                }],
                            }
                            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
                            self.wfile.flush()

                    if finish_reason:
                        fr_mapped = "tool_calls" if finish_reason == "TOOL_CALL" else "stop"
                        end_chunk = {
                            "id": req_id,
                            "object": "chat.completion.chunk",
                            "created": created_time,
                            "model": model_name,
                            "choices": [{
                                "index": 0,
                                "delta": {},
                                "finish_reason": fr_mapped,
                            }],
                        }
                        self.wfile.write(f"data: {json.dumps(end_chunk)}\n\n".encode("utf-8"))
                        self.wfile.flush()

                except Exception as e:
                    print(f"[STREAM] Parse error: {e}", flush=True)

            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            self.close_connection = True

        else:
            collected_text = []
            collected_tool_calls = []
            prompt_tokens = 0
            candidates_tokens = 0
            finish_reason = "stop"

            for raw_line in upstream_resp:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data: "):
                    continue
                try:
                    d = json.loads(line[6:])
                    resp_obj = d.get("response", {})
                    usage = resp_obj.get("usageMetadata", {})
                    prompt_tokens = usage.get("promptTokenCount", prompt_tokens)
                    candidates_tokens = usage.get("candidatesTokenCount", candidates_tokens)

                    cands = resp_obj.get("candidates", [])
                    if not cands:
                        continue
                    cand = cands[0]
                    if cand.get("finishReason"):
                        finish_reason = "tool_calls" if cand["finishReason"] == "TOOL_CALL" else "stop"

                    for part in cand.get("content", {}).get("parts", []):
                        thought_sig = part.get("thoughtSignature")
                        if "text" in part:
                            collected_text.append(part["text"])
                        if "functionCall" in part:
                            fc = part["functionCall"]
                            cid = fc.get("id") or f"call_{int(time.time() * 1000)}"
                            fn_name = fc.get("name", "")
                            fn_args = json.dumps(fc.get("args", {}))
                            TOOL_CALL_CACHE[cid] = {
                                "name": fn_name,
                                "thoughtSignature": thought_sig,
                            }
                            collected_tool_calls.append({
                                "id": cid,
                                "type": "function",
                                "function": {"name": fn_name, "arguments": fn_args},
                            })
                except Exception as e:
                    print(f"[COLLECT] Parse error: {e}", flush=True)

            msg = {
                "role": "assistant",
                "content": "".join(collected_text) if collected_text else None,
            }
            if collected_tool_calls:
                msg["tool_calls"] = collected_tool_calls
                finish_reason = "tool_calls"

            final_resp = {
                "id": req_id,
                "object": "chat.completion",
                "created": created_time,
                "model": model_name,
                "choices": [{
                    "index": 0,
                    "message": msg,
                    "finish_reason": finish_reason,
                }],
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": candidates_tokens,
                    "total_tokens": prompt_tokens + candidates_tokens,
                },
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(final_resp).encode("utf-8"))


def run_proxy(
    host: str = "127.0.0.1",
    port: int = 8000,
    token_file: Optional[str] = None,
    agy_bin: Optional[str] = None,
    project_id: str = DEFAULT_PROJECT_ID,
):
    """Run the proxy server foreground loop."""
    handler = ProxyHandler
    handler.token_file = resolve_token_path(token_file)
    handler.agy_bin = resolve_agy_bin(agy_bin)
    handler.project_id = project_id

    server = ThreadingHTTPServer((host, port), handler)
    print(f"[SERVER] Antigravity OpenAI Proxy listening on http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[SERVER] Stopping proxy...", flush=True)
    finally:
        server.server_close()
