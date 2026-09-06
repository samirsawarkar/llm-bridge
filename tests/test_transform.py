import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))
from antigravity_bridge.proxy import transform_messages, transform_tools
from antigravity_bridge.models import DEFAULT_THOUGHT_SIGNATURE

class TestTransformations(unittest.TestCase):
    def test_system_instruction_extraction(self):
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello!"}
        ]
        sys_inst, contents = transform_messages(messages)
        self.assertIsNotNone(sys_inst)
        self.assertEqual(sys_inst["parts"][0]["text"], "You are a helpful assistant.")
        self.assertEqual(len(contents), 1)
        self.assertEqual(contents[0]["role"], "user")

    def test_tool_call_and_thought_signature_attachment(self):
        messages = [
            {"role": "user", "content": "What is the weather?"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_999",
                        "type": "function",
                        "function": {"name": "get_weather", "arguments": '{"city": "Paris"}'}
                    }
                ]
            },
            {
                "role": "tool",
                "tool_call_id": "call_999",
                "content": "Sunny 20C"
            }
        ]
        sys_inst, contents = transform_messages(messages)
        self.assertIsNone(sys_inst)
        self.assertEqual(len(contents), 3)

        # Assistant turn should contain thoughtSignature and functionCall
        model_turn = contents[1]
        self.assertEqual(model_turn["role"], "model")
        p = model_turn["parts"][0]
        self.assertIn("functionCall", p)
        self.assertIn("thoughtSignature", p)
        self.assertEqual(p["thoughtSignature"], DEFAULT_THOUGHT_SIGNATURE)
        self.assertEqual(p["functionCall"]["name"], "get_weather")

        # Tool turn should match exact tool name from previous turn
        tool_turn = contents[2]
        self.assertEqual(tool_turn["role"], "user")
        fr = tool_turn["parts"][0]["functionResponse"]
        self.assertEqual(fr["name"], "get_weather")
        self.assertEqual(fr["id"], "call_999")

    def test_last_turn_user_guard(self):
        # If input messages end with assistant message, transform_messages should append dummy user turn
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"}
        ]
        _, contents = transform_messages(messages)
        self.assertEqual(contents[-1]["role"], "user")

    def test_tools_transformation(self):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "description": "Look up records",
                    "parameters": {
                        "type": "object",
                        "properties": {"id": {"type": "string"}},
                        "required": ["id"],
                        "additionalProperties": False
                    }
                }
            }
        ]
        decls = transform_tools(tools)
        self.assertIsNotNone(decls)
        fn_decl = decls[0]["functionDeclarations"][0]
        self.assertEqual(fn_decl["name"], "lookup")
        self.assertNotIn("additionalProperties", fn_decl["parameters"])

if __name__ == "__main__":
    unittest.main()
