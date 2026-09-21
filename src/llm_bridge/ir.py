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
