import json, os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))
from llm_bridge.providers import anthropic as an


class TestAnthropic(unittest.TestCase):
    def test_to_messages(self):
        req = {"messages": [{"role": "system", "content": "Be terse."},
                            {"role": "user", "content": "hi"},
                            {"role": "assistant", "content": "", "tool_calls": [{"id": "t1", "name": "f", "arguments": '{"x":1}'}]},
                            {"role": "tool", "tool_call_id": "t1", "content": "42"},
                            {"role": "user", "content": [{"type": "text", "text": "and?"}]}],
               "tools": [{"name": "f", "description": "d", "parameters": {"type": "object", "properties": {}}}],
               "max_tokens": None, "temperature": 0.2, "stream": True}
        b = an.to_messages(req, "claude-sonnet-5")
        self.assertEqual(b["system"][0]["text"], an.IDENTITY)
        self.assertEqual(b["system"][1]["text"], "Be terse.")
        self.assertEqual([m["role"] for m in b["messages"]], ["user", "assistant", "user"])
        self.assertEqual(b["messages"][1]["content"][0], {"type": "tool_use", "id": "t1", "name": "f", "input": {"x": 1}})
        self.assertEqual(b["messages"][2]["content"][0]["type"], "tool_result")
        self.assertEqual(b["messages"][2]["content"][1], {"type": "text", "text": "and?"})  # merged into one user turn
        self.assertEqual(b["tools"][0]["input_schema"], {"type": "object", "properties": {}})
        self.assertEqual((b["max_tokens"], b["temperature"], b["stream"]), (8192, 0.2, True))

    def test_identity_not_duplicated(self):
        b = an.ensure_identity({"system": an.IDENTITY + "\nmore"})
        self.assertEqual(b["system"], [{"type": "text", "text": an.IDENTITY + "\nmore"}])
        b = an.ensure_identity({"system": [{"type": "text", "text": "x"}]})
        self.assertEqual(b["system"][0]["text"], an.IDENTITY)
        self.assertEqual(an.ensure_identity({"system": ""})["system"], [{"type": "text", "text": an.IDENTITY}])

    def test_events(self):
        lines = [
            'event: message_start', 'data: {"type":"message_start","message":{"usage":{"input_tokens":5,"output_tokens":0}}}', '',
            'event: content_block_start', 'data: {"type":"content_block_start","index":0,"content_block":{"type":"thinking"}}', '',
            'event: content_block_delta', 'data: {"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"hm"}}', '',
            'event: content_block_delta', 'data: {"type":"content_block_delta","index":1,"delta":{"type":"text_delta","text":"Hi"}}', '',
            'event: content_block_start', 'data: {"type":"content_block_start","index":2,"content_block":{"type":"tool_use","id":"tu1","name":"f"}}', '',
            'event: content_block_delta', 'data: {"type":"content_block_delta","index":2,"delta":{"type":"input_json_delta","partial_json":"{\\"a\\""}}', '',
            'event: content_block_delta', 'data: {"type":"content_block_delta","index":2,"delta":{"type":"input_json_delta","partial_json":":1}"}}', '',
            'event: content_block_stop', 'data: {"type":"content_block_stop","index":2}', '',
            'event: message_delta', 'data: {"type":"message_delta","delta":{"stop_reason":"tool_use"},"usage":{"output_tokens":7}}', '',
        ]
        ev = list(an.events_from_messages(iter(l + "\n" for l in lines)))
        self.assertEqual(ev[0], ("thinking", "hm"))
        self.assertEqual(ev[1], ("text", "Hi"))
        self.assertEqual(ev[2], ("tool_call", {"id": "tu1", "name": "f", "arguments": '{"a":1}'}))
        self.assertEqual(ev[3], ("usage", {"prompt_tokens": 5, "completion_tokens": 7}))
        self.assertEqual(ev[4], ("finish", "tool_calls"))

    def test_load_parses_credentials(self):
        p = an.Anthropic()
        p._raw = lambda: ({"claudeAiOauth": {"accessToken": "A", "refreshToken": "R", "expiresAt": 1900000000000}}, "file")
        c = p._load()
        self.assertEqual((c["access"], c["refresh"], c["expires_at"]), ("A", "R", 1900000000.0))
        p._raw = lambda: (None, None)
        self.assertIsNone(p._load())

    def test_pick_prefers_source_with_token(self):
        empty = {"claudeAiOauth": {"accessToken": "", "refreshToken": ""}}
        real = {"claudeAiOauth": {"accessToken": "A", "refreshToken": "R"}}
        self.assertEqual(an._pick([(empty, "keychain"), (real, "file")]), (real, "file"))  # skip empty keychain
        self.assertEqual(an._pick([(real, "keychain"), (empty, "file")])[1], "keychain")   # first with token wins
        self.assertEqual(an._pick([(empty, "keychain")]), (empty, "keychain"))             # fallback to only source
        self.assertEqual(an._pick([]), (None, None))


if __name__ == "__main__":
    unittest.main()
