# Supported Models & Upstream Aliasing

Antigravity Bridge exposes top-tier frontier models from Google Antigravity via a standard OpenAI-compatible API.

---

## Model Catalog

| Model ID | Display Name | Recommended Use Case |
| :--- | :--- | :--- |
| `gemini-3.8-flash` | Gemini 3.8 Flash | Ultra-fast agent loops, CRM tasks, automated mentions |
| `claude-sonnet-4-6` | Claude Sonnet 4.6 | High-level code architecture, complex reasoning, diffs |
| `gemini-2.5-pro` | Gemini 2.5 Pro | Deep multi-turn context, multi-tool workflows |
| `gemini-2.5-flash` | Gemini 2.5 Flash | High-throughput subagents, background jobs |
| `gemini-3.1-pro-high` | Gemini 3.1 Pro (High) | Heavy reasoning benchmarks |
| `gemini-3.6-flash-high`| Gemini 3.6 Flash (High)| High-concurrency agent workflows |
| `claude-opus-4-6-thinking` | Claude Opus 4.6 (Thinking) | Extended thinking agent tasks |

---

## Upstream Model Mapping & Aliasing

Google Cloud Code backend uses internal identifiers that differ from common model strings. Antigravity Bridge dynamically maps client requests:

- `gemini-3.8-flash` -> `gemini-3.8-flash-tiered`
- `gemini-3.8-flash-high` -> `gemini-3.8-flash-tiered`
- `gemini-3.7-flash` -> `gemini-3.7-flash-tiered`
- `gemini-3.7-flash-tiered` -> `gemini-3.7-flash-tiered`
- `claude-sonnet-4-6` -> `claude-sonnet-4-6`

If a client sends an unmapped identifier, the bridge passes it directly upstream to preserve future model support.

---

## Gemini Protobuf Schema Compatibility

Google Gemini Cloud Code API enforces strict protobuf schema parsing:
- Keyword `$schema` is rejected -> stripped by bridge.
- Keyword `additionalProperties` is rejected -> stripped by bridge.
- Keyword `title` is rejected -> stripped by bridge.
- Arrays must have a dictionary `items` property -> normalized by bridge.
