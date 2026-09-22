# AGENTS.md

Guidance for AI agents and coding tools working with **llm-bridge** — a local, OpenAI-compatible gateway that exposes your `agy` (Google Antigravity), `claude` (Claude Code) and `codex` (OpenAI Codex) CLI OAuth sessions as one API with your own keys. Everything runs on `localhost`; nothing leaves the machine.

## Use llm-bridge as your model backend

Point any OpenAI-, Anthropic- or Responses-compatible client at the local server:

- Base URL (OpenAI Chat/Responses): `http://127.0.0.1:8000/v1`
- Base URL (Anthropic Messages): `http://127.0.0.1:8000`
- Auth: `Authorization: Bearer <key>` or `x-api-key: <key>`, where `<key>` comes from `llm-bridge keys create <name>`
- Models: `provider/model`, e.g. `anthropic/claude-sonnet-5`, `openai/gpt-5.5`, `antigravity/gemini-3.8-flash`. List live ones with `GET /v1/models` or `llm-bridge models`.

```bash
llm-bridge up                        # prints base URL + key, starts the server (foreground)
llm-bridge keys create my-agent      # a dedicated key for this agent (printed once)
```

```python
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8000/v1", api_key="<key>")
client.chat.completions.create(model="anthropic/claude-sonnet-5",
                               messages=[{"role": "user", "content": "hi"}])
```

### Endpoints

| Path | Format |
|---|---|
| `POST /v1/chat/completions` | OpenAI Chat Completions (default) |
| `POST /v1/messages` | Anthropic Messages (native passthrough for `anthropic/*`) |
| `POST /v1/responses` | OpenAI Responses (native passthrough for `openai/*`) |
| `GET /v1/models` | Model list — only providers currently authenticated |
| `GET /health` | Liveness |

Routing precedence: explicit `provider/model` → bare-name prefix (`claude-*`→anthropic, `gpt-*`/`o*`/`codex*`→openai, `gemini-*`→antigravity) → configured `default_provider` → 400. No fuzzy matching.

## Working on this repository

- **Language/runtime:** Python 3.8+, **standard library only**. Do not add runtime dependencies — it is a hard constraint (`pyproject.toml` `dependencies = []`). No `match`, no `str.removeprefix`, no f-string `=` — keep 3.8 compatible.
- **Layout:** `src/llm_bridge/` — `ir.py` (internal request/event shape, the single source of truth), `server.py` (routing, key auth, pipeline), `store.py` (keys/config), `codecs/` (per inbound format), `providers/` (antigravity, anthropic, openai + registry/routing), `service.py`, `connect/`, `cli.py`.
- **Architecture:** inbound codec `decode` → internal `Request` → `provider.stream` → `Event` tuples → codec `encode`; native passthrough when the inbound format is the provider's own. Add a provider by subclassing `providers/base.py:Provider`; add an inbound format as a new `codecs/*` module.
- **Tests:** `python3 tests/run_tests.py` (stdlib `unittest`, **no network**). Every non-trivial change ships a test. Live check: `llm-bridge test <provider/model>`.
- **Never** commit real tokens, keys, or `~/.llm-bridge/` / `~/.claude/` / `~/.codex/` contents. Do not add throwaway OAuth-refresh probes — refresh tokens are single-use and rotate; a discarded result logs the user's CLI out. Refresh only through a provider's `token()`/`_refresh()` write-back path.
- **Design & plan of record:** `docs/superpowers/specs/` and `docs/superpowers/plans/`. Provider endpoints and quirks: `docs/providers.md`.

## Safety

llm-bridge reuses the user's existing CLI logins. Using subscription OAuth tokens through third-party clients may violate provider terms of service. Do not add features that obscure this, harvest credentials beyond the three supported CLIs, or transmit tokens off-device.
