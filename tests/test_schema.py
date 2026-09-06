import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))
from antigravity_bridge.models import clean_json_schema

class TestSchemaSanitizer(unittest.TestCase):
    def test_strip_unsupported_keys(self):
        input_schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "title": "WeatherParams",
            "additionalProperties": False,
            "properties": {
                "city": {"type": "string", "description": "City name"}
            },
            "required": ["city"]
        }
        cleaned = clean_json_schema(input_schema)
        self.assertNotIn("$schema", cleaned)
        self.assertNotIn("title", cleaned)
        self.assertNotIn("additionalProperties", cleaned)
        self.assertEqual(cleaned["type"], "object")
        self.assertIn("city", cleaned["properties"])
        self.assertEqual(cleaned["required"], ["city"])

    def test_anyof_resolution(self):
        schema = {
            "anyOf": [
                {"type": "null"},
                {"type": "string", "description": "A string value"}
            ]
        }
        cleaned = clean_json_schema(schema)
        self.assertEqual(cleaned["type"], "string")
        self.assertEqual(cleaned.get("description"), "A string value")

    def test_nested_array_items_normalization(self):
        schema = {
            "type": "array",
            "items": [{"type": "string"}]  # list of schemas instead of single object
        }
        cleaned = clean_json_schema(schema)
        self.assertEqual(cleaned["type"], "array")
        self.assertIsInstance(cleaned["items"], dict)
        self.assertEqual(cleaned["items"]["type"], "string")

    def test_multi_type_list(self):
        schema = {
            "type": ["string", "null"],
            "description": "Nullable string"
        }
        cleaned = clean_json_schema(schema)
        self.assertEqual(cleaned["type"], "string")

if __name__ == "__main__":
    unittest.main()
