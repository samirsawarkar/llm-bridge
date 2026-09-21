# Models & routing

Model ids are `provider/model`. `GET /v1/models` and `llm-bridge models` list them; a model is listed only when its provider is authenticated. Catalogs are static seeds — `llm-bridge test <model>` is the real probe.

## Routing precedence

1. `provider/model` — explicit; unknown provider → 400.
2. Bare name matching a provider prefix: `claude-*` → anthropic; `gpt-*`, `o1*`, `o3*`, `o4*`, `codex*` → openai; `gemini-*` → antigravity. Prefix sets are disjoint (tested).
3. `default_provider` from `~/.llm-bridge/config.json` or `LLM_BRIDGE_DEFAULT_PROVIDER`.
4. 400 `model_not_found`.

No substring guessing. `gpt-oss-120b-medium` lives on antigravity and must be written `antigravity/gpt-oss-120b-medium`.

## Aliases (resolved inside the provider)

| Provider | Alias | Upstream |
|---|---|---|
| antigravity | `gemini-3.8-flash`, `-high`, `-medium`, `-low` | `gemini-3.8-flash-tiered` |
| antigravity | `gemini-3.7-flash`, `-high` | `gemini-3.7-flash-tiered` |
| antigravity | `gemini-3.6-flash` | `gemini-3.6-flash-high` |
| antigravity | `gemini-3.1-pro` | `gemini-3.1-pro-high` |
| antigravity | `gemini-pro` / `gemini-flash` | `gemini-2.5-pro` / `gemini-2.5-flash` |
| antigravity | `claude-sonnet` / `claude-opus` | `claude-sonnet-4-6` / `claude-opus-4-6-thinking` |
| anthropic | `claude-opus` / `claude-sonnet` / `claude-haiku` | `claude-opus-5` / `claude-sonnet-5` / `claude-haiku-4-5-20251001` |
| openai | `codex` | `gpt-5-codex` |
