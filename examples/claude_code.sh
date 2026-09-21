#!/usr/bin/env bash
# Run Claude Code against any bridge model. Usage: LLM_BRIDGE_KEY=sk-lb-… examples/claude_code.sh [provider/model]
ANTHROPIC_BASE_URL=http://127.0.0.1:8000 ANTHROPIC_API_KEY="$LLM_BRIDGE_KEY" exec claude --model "${1:-openai/gpt-5.5}"
