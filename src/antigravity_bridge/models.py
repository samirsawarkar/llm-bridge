"""Model catalogs, alias resolution, and JSON schema sanitization."""

import json

DEFAULT_THOUGHT_SIGNATURE = (
    "EnEKbwERTTIPtROYK8FSJmzasRTa7Z4nHGF3qBV0QaAHjAewGx2Rtqh5cFUMlYUu4USlmI+xm584wpNJ80dclO/vUl6efxAeNNv28wzaYcfZPUJLmEA/4rQNg5f4W4XGKq0/P1QZes539vt9Vqmid3qy+g=="
)

AVAILABLE_MODELS = [
    {"id": "gemini-3.8-flash", "name": "Gemini 3.8 Flash"},
    {"id": "gemini-3.8-flash-tiered", "name": "Gemini 3.8 Flash (Tiered)"},
    {"id": "gemini-3.8-flash-high", "name": "Gemini 3.8 Flash (High)"},
    {"id": "gemini-3.7-flash", "name": "Gemini 3.7 Flash"},
    {"id": "gemini-3.7-flash-tiered", "name": "Gemini 3.7 Flash (Tiered)"},
    {"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6 (Thinking)"},
    {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro"},
    {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash"},
    {"id": "gemini-3.1-pro-high", "name": "Gemini 3.1 Pro (High)"},
    {"id": "gemini-3.6-flash-high", "name": "Gemini 3.6 Flash (High)"},
    {"id": "claude-opus-4-6-thinking", "name": "Claude Opus 4.6 (Thinking)"},
    {"id": "gpt-oss-120b-medium", "name": "GPT-OSS 120B"},
]

MODEL_MAP = {
    # Claude models (Vertex AI)
    "claude-sonnet-4-6": "claude-sonnet-4-6",
    "claude-opus-4-6-thinking": "claude-opus-4-6-thinking",
    "claude-sonnet": "claude-sonnet-4-6",
    "claude-opus": "claude-opus-4-6-thinking",
    # Gemini 3.8 Flash (Maps to Google Cloud Code internal identifier: gemini-3.8-flash-tiered)
    "gemini-3.8-flash": "gemini-3.8-flash-tiered",
    "gemini-3.8-flash-high": "gemini-3.8-flash-tiered",
    "gemini-3.8-flash-tiered": "gemini-3.8-flash-tiered",
    "gemini-3.8-flash-medium": "gemini-3.8-flash-tiered",
    "gemini-3.8-flash-low": "gemini-3.8-flash-tiered",
    "flash-3.8": "gemini-3.8-flash-tiered",
    "flash 3.8": "gemini-3.8-flash-tiered",
    "gemini-flash-3.8": "gemini-3.8-flash-tiered",
    # Gemini 3.7 Flash
    "gemini-3.7-flash": "gemini-3.7-flash-tiered",
    "gemini-3.7-flash-high": "gemini-3.7-flash-tiered",
    "gemini-3.7-flash-tiered": "gemini-3.7-flash-tiered",
    "flash-3.7": "gemini-3.7-flash-tiered",
    "flash 3.7": "gemini-3.7-flash-tiered",
    "gemini-flash-3.7": "gemini-3.7-flash-tiered",
    # Gemini 3.6 Flash
    "gemini-3.6-flash-high": "gemini-3.6-flash-high",
    "gemini-3.6-flash": "gemini-3.6-flash-high",
    # Gemini 3.1 Pro
    "gemini-3.1-pro-high": "gemini-3.1-pro-high",
    "gemini-3.1-pro": "gemini-3.1-pro-high",
    # Gemini 2.5 Pro & Flash
    "gemini-2.5-pro": "gemini-2.5-pro",
    "gemini-2.5-flash": "gemini-2.5-flash",
    "gemini-pro": "gemini-2.5-pro",
    "gemini-flash": "gemini-2.5-flash",
    # OSS
    "gpt-oss-120b-medium": "gpt-oss-120b-medium",
}


def map_model(requested_model: str) -> str:
    """Map incoming requested model name to upstream Google Cloud Code model identifier."""
    if not requested_model:
        return "claude-sonnet-4-6"
    req = str(requested_model).lower().strip()
    if "/" in req:
        req = req.split("/")[-1]
    if req in MODEL_MAP:
        return MODEL_MAP[req]
    for k, v in MODEL_MAP.items():
        if k in req or req in k:
            return v
    if "3.8" in req or "38" in req:
        return "gemini-3.8-flash-tiered"
    if "3.7" in req or "37" in req:
        return "gemini-3.7-flash-tiered"
    if "flash" in req:
        return "gemini-3.8-flash-tiered"
    if "pro" in req:
        return "gemini-2.5-pro"
    return "claude-sonnet-4-6"


def clean_json_schema(s):
    """Clean standard JSON schema to conform to Google Gemini / Cloud Code protobuf schema requirements.

    Removes unsupported keys ($schema, additionalProperties, title), normalizes multi-type definitions
    and resolves anyOf/oneOf/allOf into single typed schema objects.
    """
    if not isinstance(s, dict):
        return {"type": "string"}

    # Handle composition keywords
    if "anyOf" in s and isinstance(s["anyOf"], list) and s["anyOf"]:
        for candidate in s["anyOf"]:
            if isinstance(candidate, dict) and candidate.get("type") != "null":
                return clean_json_schema(candidate)
        return clean_json_schema(s["anyOf"][0])

    if "oneOf" in s and isinstance(s["oneOf"], list) and s["oneOf"]:
        for candidate in s["oneOf"]:
            if isinstance(candidate, dict) and candidate.get("type") != "null":
                return clean_json_schema(candidate)
        return clean_json_schema(s["oneOf"][0])

    if "allOf" in s and isinstance(s["allOf"], list) and s["allOf"]:
        return clean_json_schema(s["allOf"][0])

    cleaned = {}
    t = s.get("type")
    if isinstance(t, list):
        non_null = [x for x in t if x != "null"]
        t = non_null[0] if non_null else "string"
    elif not t:
        if "properties" in s:
            t = "object"
        elif "items" in s:
            t = "array"
        else:
            t = "string"
    cleaned["type"] = str(t).lower()

    if "description" in s and isinstance(s["description"], str):
        cleaned["description"] = s["description"]

    if cleaned["type"] == "object":
        props = s.get("properties")
        if isinstance(props, dict) and props:
            cleaned["properties"] = {pk: clean_json_schema(pv) for pk, pv in props.items()}
        req = s.get("required")
        if isinstance(req, list):
            cleaned["required"] = [str(r) for r in req if isinstance(r, str)]
    elif cleaned["type"] == "array":
        items = s.get("items")
        if isinstance(items, list) and items:
            cleaned["items"] = clean_json_schema(items[0])
        elif isinstance(items, dict):
            cleaned["items"] = clean_json_schema(items)
        else:
            cleaned["items"] = {"type": "string"}

    if "enum" in s and isinstance(s["enum"], list):
        cleaned["enum"] = [str(e) for e in s["enum"]]

    return cleaned
