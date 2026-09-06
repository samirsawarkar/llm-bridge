#!/usr/bin/env python3
"""Example: Using the official openai Python library with Antigravity Bridge.

Requirements:
    pip install openai

Run:
    python examples/openai_sdk_example.py
"""

import os
import sys

try:
    from openai import OpenAI
except ImportError:
    print("[!] Please install the OpenAI SDK: pip install openai")
    sys.exit(1)

client = OpenAI(
    base_url="http://127.0.0.1:8000/v1",
    api_key="antigravity",  # Any non-empty string is accepted
)

def main():
    print("=== 1. Non-streaming Chat Completion ===")
    response = client.chat.completions.create(
        model="gemini-3.8-flash",
        messages=[
            {"role": "system", "content": "You are an expert AI assistant."},
            {"role": "user", "content": "Explain Antigravity Bridge in two sentences."}
        ],
    )
    print(f"Response:
{response.choices[0].message.content}
")

    print("=== 2. Streaming Chat Completion ===")
    stream = client.chat.completions.create(
        model="claude-sonnet-4-6",
        messages=[
            {"role": "user", "content": "Count from 1 to 5 with short words."}
        ],
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content or ""
        print(delta, end="", flush=True)
    print("
")

if __name__ == "__main__":
    main()
