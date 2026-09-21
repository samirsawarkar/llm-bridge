import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))
from llm_bridge import providers as P


class TestRouter(unittest.TestCase):
    def test_precedence(self):
        p, m = P.resolve("antigravity/gemini-3.8-flash")
        self.assertEqual((p.name, m), ("antigravity", "gemini-3.8-flash-tiered"))
        p, m = P.resolve("claude-sonnet")
        self.assertEqual((p.name, m), ("anthropic", "claude-sonnet-5"))
        p, m = P.resolve("gpt-5.5")
        self.assertEqual((p.name, m), ("openai", "gpt-5.5"))
        p, m = P.resolve("mystery-model", default_provider="openai")
        self.assertEqual((p.name, m), ("openai", "mystery-model"))
        for bad in (None, "", "mystery-model", "nope/x"):
            with self.assertRaises(P.RouteError):
                P.resolve(bad)

    def test_prefixes_disjoint(self):
        names = ["gpt-5", "gpt-oss-120b-medium", "gemini-2.5-pro", "claude-x", "o3-mini", "codex-mini"]
        for n in names:
            hits = [p.name for p in P.PROVIDERS.values() if n.startswith(p.prefixes)]
            self.assertLessEqual(len(hits), 1, n)

    def test_list_models_shape(self):
        for p in P.PROVIDERS.values():
            p.auth_status = lambda: {"ok": True}
        ids = [m["id"] for m in P.list_models()]
        self.assertIn("anthropic/claude-sonnet-5", ids)
        self.assertIn("antigravity/gemini-3.8-flash", ids)
        self.assertTrue(all("/" in i for i in ids))


if __name__ == "__main__":
    unittest.main()
