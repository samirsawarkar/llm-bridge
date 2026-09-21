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
