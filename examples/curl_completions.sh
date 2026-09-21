#!/usr/bin/env bash
# curl against LLM Bridge. Usage: examples/curl_completions.sh [provider/model]
MODEL="${1:-antigravity/gemini-3.8-flash}"
BASE="http://${HOST:-127.0.0.1}:${PORT:-8000}"
KEY="${LLM_BRIDGE_KEY:-$(python3 -c "import json,os;print(next(iter(json.load(open(os.path.expanduser('~/.llm-bridge/keys.json'))).values()))['key'])")}"

echo "== health";  curl -s "$BASE/health"; echo
echo "== models";  curl -s "$BASE/v1/models" -H "Authorization: Bearer $KEY" | head -c 400; echo
echo "== chat ($MODEL)"
curl -s "$BASE/v1/chat/completions" -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with: bridge OK\"}]}"; echo
echo "== stream"
curl -sN "$BASE/v1/chat/completions" -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d "{\"model\":\"$MODEL\",\"stream\":true,\"messages\":[{\"role\":\"user\",\"content\":\"Count to 5\"}]}"
