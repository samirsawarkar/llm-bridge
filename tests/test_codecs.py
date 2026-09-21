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
