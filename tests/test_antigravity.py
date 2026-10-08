import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))
from llm_bridge.providers import antigravity as ag
from llm_bridge.providers.base import sse
from unittest.mock import patch


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
    def test_pro_high_uses_generation_route_with_high_thinking_budget(self):
        p = ag.Antigravity(project_id="test-project")
        with patch.object(p, "token", return_value="test-token"), patch.object(ag, "http", return_value=iter([b'data: {"response":{"candidates":[{"content":{"parts":[{"text":"ok"}]}}]}}\n'])) as send:
            events = list(p.stream({"messages": [{"role": "user", "content": "hi"}]}, "gemini-3.1-pro-high"))
        body = send.call_args[0][1]
        self.assertEqual(body["model"], "gemini-3.1-pro-low")
        self.assertEqual(body["request"]["generationConfig"]["thinkingConfig"],
                         {"thinkingBudget": 10001, "includeThoughts": True})
        self.assertEqual(body["project"], "test-project")
        self.assertIn(("text", "ok"), events)
        self.assertEqual(send.call_count, 1)  # Successful Pro request, no Flash fallback.

    def test_other_models_do_not_receive_pro_high_settings(self):
        p = ag.Antigravity()
        for model in ("gemini-3.1-pro-low", "gemini-3.8-flash-tiered"):
            with patch.object(p, "token", return_value="test-token"), patch.object(ag, "http", return_value=iter([])) as send:
                list(p.stream({"messages": [{"role": "user", "content": "hi"}]}, model))
            body = send.call_args[0][1]
            self.assertEqual(body["model"], model)
            self.assertNotIn("generationConfig", body["request"])

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
