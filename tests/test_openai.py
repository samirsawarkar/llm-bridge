import base64, json, os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))
from llm_bridge.providers import openai as oa


def _jwt(claims):
    b = lambda s: base64.urlsafe_b64encode(json.dumps(s).encode()).rstrip(b"=").decode()
    return b({"alg": "none"}) + "." + b(claims) + ".sig"


class TestOpenAI(unittest.TestCase):
    def test_to_responses(self):
        req = {"messages": [{"role": "system", "content": "S"}, {"role": "user", "content": "q"},
                            {"role": "assistant", "content": "thinking...", "tool_calls": [{"id": "c1", "name": "f", "arguments": "{}"}]},
                            {"role": "tool", "tool_call_id": "c1", "content": "out"}],
               "tools": [{"name": "f", "description": "d", "parameters": None}], "stream": False, "max_tokens": 10, "temperature": 0}
        b = oa.to_responses(req, "gpt-5-codex")
        self.assertEqual(b["instructions"], "S")
        self.assertEqual([i["type"] for i in b["input"]], ["message", "message", "function_call", "function_call_output"])
        self.assertEqual(b["input"][2]["call_id"], "c1")
        self.assertEqual(b["input"][3]["output"], "out")
        self.assertEqual(b["tools"][0], {"type": "function", "name": "f", "description": "d", "parameters": {"type": "object", "properties": {}}})
        self.assertTrue(b["stream"] and b["store"] is False)
        self.assertNotIn("temperature", b)  # codex backend rejects sampling params

    def test_events(self):
        lines = ['data: {"type":"response.output_text.delta","delta":"He"}',
                 'data: {"type":"response.output_item.done","item":{"type":"function_call","call_id":"c9","name":"f","arguments":"{\\"a\\":1}"}}',
                 'data: {"type":"response.completed","response":{"status":"completed","output":[{"type":"function_call"}],"usage":{"input_tokens":2,"output_tokens":3}}}']
        ev = list(oa.events_from_responses(iter(l + "\n" for l in lines)))
        self.assertEqual(ev, [("text", "He"), ("tool_call", {"id": "c9", "name": "f", "arguments": '{"a":1}'}),
                              ("usage", {"prompt_tokens": 2, "completion_tokens": 3}), ("finish", "tool_calls")])
        err = list(oa.events_from_responses(iter(['data: {"type":"response.failed","response":{"error":{"message":"nope"}}}\n'])))
        self.assertEqual(err, [("error", {"status": 502, "message": "nope"})])

    def test_load_from_auth_json(self):
        p = oa.OpenAI()
        acc = _jwt({"exp": 1900000000})
        idt = _jwt({"https://api.openai.com/auth": {"chatgpt_account_id": "acct_1"}})
        p._raw = lambda: {"tokens": {"access_token": acc, "refresh_token": "R", "id_token": idt}}
        c = p._load()
        self.assertEqual((c["access"], c["refresh"], c["expires_at"], c["account_id"]), (acc, "R", 1900000000, "acct_1"))
        p._raw = lambda: {"OPENAI_API_KEY": "sk-x"}
        self.assertIsNone(p._load())


if __name__ == "__main__":
    unittest.main()
