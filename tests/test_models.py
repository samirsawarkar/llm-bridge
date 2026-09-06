import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))
from antigravity_bridge.models import map_model, AVAILABLE_MODELS

class TestModelMapping(unittest.TestCase):
    def test_flash_38_aliasing(self):
        self.assertEqual(map_model("gemini-3.8-flash"), "gemini-3.8-flash-tiered")
        self.assertEqual(map_model("gemini-3.8-flash-high"), "gemini-3.8-flash-tiered")
        self.assertEqual(map_model("flash-3.8"), "gemini-3.8-flash-tiered")
        self.assertEqual(map_model("flash 3.8"), "gemini-3.8-flash-tiered")
        self.assertEqual(map_model("antigravity/gemini-3.8-flash"), "gemini-3.8-flash-tiered")

    def test_flash_37_aliasing(self):
        self.assertEqual(map_model("gemini-3.7-flash"), "gemini-3.7-flash-tiered")
        self.assertEqual(map_model("gemini-3.7-flash-high"), "gemini-3.7-flash-tiered")
        self.assertEqual(map_model("antigravity/gemini-3.7-flash"), "gemini-3.7-flash-tiered")

    def test_claude_sonnet_aliasing(self):
        self.assertEqual(map_model("claude-sonnet-4-6"), "claude-sonnet-4-6")
        self.assertEqual(map_model("antigravity/claude-sonnet-4-6"), "claude-sonnet-4-6")
        self.assertEqual(map_model("claude-sonnet"), "claude-sonnet-4-6")

    def test_pro_and_flash_fallbacks(self):
        self.assertEqual(map_model("some-random-flash"), "gemini-3.8-flash-tiered")
        self.assertEqual(map_model("some-random-pro"), "gemini-2.5-pro")
        self.assertEqual(map_model(None), "claude-sonnet-4-6")
        self.assertEqual(map_model(""), "claude-sonnet-4-6")

    def test_available_models_structure(self):
        self.assertTrue(len(AVAILABLE_MODELS) >= 5)
        for m in AVAILABLE_MODELS:
            self.assertIn("id", m)
            self.assertIn("name", m)

if __name__ == "__main__":
    unittest.main()
