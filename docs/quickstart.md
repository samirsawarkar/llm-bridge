# Quickstart

```bash
git clone https://github.com/samirsawarkar/llm-bridge.git && cd llm-bridge
pip install .            # or ./install.sh
llm-bridge up
```

`up` prints the base URL, your key (once), which providers are logged in, and a few model ids. Copy the key.

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"antigravity/gemini-3.8-flash","messages":[{"role":"user","content":"Say hi"}]}'
```

A provider shows `✗ missing`? Log in with its CLI (`agy`, `claude` then `/login`, `codex login`) — no restart needed.

Run it in the background: `llm-bridge service install` (launchd on macOS, systemd on Linux).

More keys: `llm-bridge keys create cursor`. Check everything: `llm-bridge status`, `llm-bridge models`, `llm-bridge test`.
