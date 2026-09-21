import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))
os.environ["LLM_BRIDGE_HOME"] = tempfile.mkdtemp()
from llm_bridge import ir, store


class TestIR(unittest.TestCase):
    def test_text_of(self):
        self.assertEqual(ir.text_of("hi"), "hi")
        self.assertEqual(ir.text_of(None), "")
        self.assertEqual(ir.text_of([{"type": "text", "text": "a"}, {"type": "image_url", "image_url": {}}, {"type": "text", "text": "b"}]), "ab")

    def test_collect(self):
        r = ir.collect([("thinking", "t"), ("text", "he"), ("text", "llo"),
                        ("tool_call", {"id": "c1", "name": "f", "arguments": "{}"}),
                        ("usage", {"prompt_tokens": 1, "completion_tokens": 2}), ("finish", "stop")])
        self.assertEqual(r["text"], "hello")
        self.assertEqual(r["thinking"], "t")
        self.assertEqual(r["finish"], "tool_calls")  # tool calls force tool_calls
        self.assertEqual(r["usage"]["completion_tokens"], 2)
        e = ir.collect([("text", "x"), ("error", {"status": 502, "message": "boom"})])
        self.assertEqual(e["error"]["status"], 502)


class TestStore(unittest.TestCase):
    def test_keys_roundtrip(self):
        k = store.create_key("t1")
        self.assertTrue(k.startswith("sk-lb-") and len(k) == 46)
        self.assertTrue(store.verify_key(k))
        self.assertFalse(store.verify_key(k[:-1] + "x"))
        self.assertFalse(store.verify_key(""))
        self.assertEqual(store.mask(k), k[:10] + "…" + k[-2:])
        self.assertEqual(oct(os.stat(store.KEYS).st_mode & 0o777), "0o600")
        with self.assertRaises(ValueError):
            store.create_key("t1")
        store.revoke_key("t1")
        self.assertFalse(store.verify_key(k))

    def test_config(self):
        cfg = store.load_config()
        self.assertEqual(cfg["port"], 8000)
        store.save_config(default_provider="openai")
        self.assertEqual(store.load_config()["default_provider"], "openai")
        os.environ["LLM_BRIDGE_PORT"] = "9000"
        self.assertEqual(store.load_config()["port"], 9000)
        del os.environ["LLM_BRIDGE_PORT"]


if __name__ == "__main__":
    unittest.main()
