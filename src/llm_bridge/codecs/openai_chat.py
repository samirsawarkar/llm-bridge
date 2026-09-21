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
