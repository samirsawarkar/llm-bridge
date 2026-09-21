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
