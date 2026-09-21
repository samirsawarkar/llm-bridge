#!/usr/bin/env python3
"""Example: Function calling / Tool use through LLM Bridge.

Demonstrates how tool calls are transformed and returned cleanly.
"""

import json
import os
import urllib.request

PROXY_URL = "http://127.0.0.1:8000/v1/chat/completions"

tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the current weather for a location",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "City and state, e.g. San Francisco, CA"
                    },
                    "unit": {
                        "type": "string",
                        "enum": ["celsius", "fahrenheit"]
                    }
                },
                "required": ["location"]
            }
        }
    }
]

payload = {
    "model": "anthropic/claude-sonnet-5",
    "messages": [
        {"role": "user", "content": "What is the weather in Tokyo right now?"}
    ],
    "tools": tools,
}

def main():
    print("Sending tool-calling request to proxy...")
    req = urllib.request.Request(
        PROXY_URL,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + os.environ["LLM_BRIDGE_KEY"]},
        data=json.dumps(payload).encode("utf-8"),
    )
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        print("\nProxy Response:")
        print(json.dumps(res, indent=2))

if __name__ == "__main__":
    main()
