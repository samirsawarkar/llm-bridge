#!/usr/bin/env bash
# Example: Querying Antigravity Bridge via standard curl

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
BASE_URL="http://${HOST}:${PORT}"

echo "=== 1. Health Check ==="
curl -s "${BASE_URL}/health" | jq . || curl -s "${BASE_URL}/health"
echo ""

echo "=== 2. List Models ==="
curl -s "${BASE_URL}/v1/models" | jq . || curl -s "${BASE_URL}/v1/models"
echo ""

echo "=== 3. Chat Completion (gemini-3.8-flash) ==="
curl -s -X POST "${BASE_URL}/v1/chat/completions"   -H "Content-Type: application/json"   -H "Authorization: Bearer antigravity"   -d '{
    "model": "gemini-3.8-flash",
    "messages": [
      {"role": "user", "content": "Reply with: Antigravity Bridge is running!"}
    ]
  }' | jq . || curl -s -X POST "${BASE_URL}/v1/chat/completions"   -H "Content-Type: application/json"   -H "Authorization: Bearer antigravity"   -d '{"model": "gemini-3.8-flash", "messages": [{"role": "user", "content": "Hello!"}]}'
echo ""
