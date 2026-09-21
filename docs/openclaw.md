# OpenClaw Agent

[OpenClaw](https://openclaw.ai) uses a JSON config plus a SQLite credential store; `connect` writes both.

```bash
llm-bridge connect openclaw --model antigravity/gemini-3.8-flash
openclaw agent --message "Say hello!"
```

What it changes (existing `openclaw.json` is backed up first):

- `models.providers["llm-bridge"]` → `baseUrl: http://127.0.0.1:8000/v1`, `api: openai-completions`, `auth: api-key`, and the current model list from the bridge.
- `agents.defaults.model.primary` → `llm-bridge/<provider>/<model>`.
- `auth.profiles["llm-bridge:manual"]` and, in every `~/.openclaw/agents/*/agent/openclaw-agent.sqlite`, an `llm-bridge:manual` API-key profile holding your bridge key.

Switch models by re-running `connect --model …`. Restart the OpenClaw gateway afterwards if it was running.
