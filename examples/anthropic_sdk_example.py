#!/usr/bin/env python3
"""Anthropic SDK against LLM Bridge (/v1/messages). pip install anthropic; LLM_BRIDGE_KEY=sk-lb-… python examples/anthropic_sdk_example.py"""
import os
from anthropic import Anthropic

client = Anthropic(base_url="http://127.0.0.1:8000", api_key=os.environ["LLM_BRIDGE_KEY"])
msg = client.messages.create(model="openai/gpt-5.5", max_tokens=64,  # any provider; native passthrough for anthropic/*
                             messages=[{"role": "user", "content": "Reply with: bridge OK"}])
print(msg.content[0].text)
