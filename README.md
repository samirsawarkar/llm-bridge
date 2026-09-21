# LLM Bridge

[![CI](https://github.com/samirsawarkar/llm-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/samirsawarkar/llm-bridge/actions)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-0%20(stdlib%20only)-brightgreen.svg)](#architecture)

Your `agy`, `claude` and `codex` logins → one local OpenAI-compatible API with your own keys. Nothing leaves your machine.

Point any app at `http://127.0.0.1:8000/v1`, pick a model like `anthropic/claude-sonnet-5` or `openai/gpt-5.5` or `antigravity/gemini-3.8-flash`, done. Works like OpenRouter, runs on localhost, speaks OpenAI Chat Completions, Anthropic Messages and OpenAI Responses.

> Using subscription OAuth tokens from third-party clients may violate Anthropic's and OpenAI's terms of service. Your account, your call.

## Quickstart

```bash
pip install .          # or ./install.sh (pipx if present)
llm-bridge up
```

```
LLM Bridge  http://127.0.0.1:8000/v1
API key     sk-lb-3f9a2c…c2   (new; shown once — llm-bridge keys list to see masked)

Providers
  antigravity  ✓ authenticated
  anthropic    ✓ authenticated
  openai       ✗ missing          → run: codex login

Models      antigravity/gemini-3.8-flash  anthropic/claude-sonnet-5  …  (llm-bridge models)
```

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-lb-…" -H "Content-Type: application/json" \
  -d '{"model":"anthropic/claude-sonnet-5","messages":[{"role":"user","content":"hi"}]}'
```

Not logged in somewhere? Run that CLI once (`agy`, `claude`, `codex login`) and the bridge picks it up on the next request.

## Use it from

| Client | How |
|---|---|
| curl / any HTTP | `Authorization: Bearer <key>` or `x-api-key: <key>` |
| OpenAI SDK | `OpenAI(base_url="http://127.0.0.1:8000/v1", api_key="<key>")` |
| Anthropic SDK | `Anthropic(base_url="http://127.0.0.1:8000", api_key="<key>")` |
| Claude Code on another model | `ANTHROPIC_BASE_URL=http://127.0.0.1:8000 ANTHROPIC_API_KEY=<key> claude --model openai/gpt-5.5` |
| Cursor / Cline / Continue / Open WebUI | OpenAI-compatible provider, base URL `http://127.0.0.1:8000/v1`, key `<key>` |
| Hermes / OpenClaw | `llm-bridge connect hermes` / `llm-bridge connect openclaw` |

Examples in [`examples/`](examples).

## Providers

| Provider | Log in with | Credentials read from | Models |
|---|---|---|---|
| `antigravity` | `agy` | `~/.gemini/antigravity-cli/…` (or OpenClaw auth-profiles) | Gemini 3.x/2.5, Claude via Antigravity, GPT-OSS |
| `anthropic` | `claude` → `/login` | `~/.claude/.credentials.json` (macOS: Keychain) | Claude 5 family, 4.6 |
| `openai` | `codex login` | `~/.codex/auth.json` | whatever your ChatGPT plan allows (fetched live, e.g. gpt-5.5, gpt-5.6-terra) |

Tokens are refreshed through each provider's own OAuth endpoint and written back, so the CLI stays logged in too. Details and quirks in [docs/providers.md](docs/providers.md).

## Model names

`provider/model` is explicit and always works. Bare names route by prefix (`claude-*` → anthropic, `gpt-*`/`o*`/`codex*` → openai, `gemini-*` → antigravity). Precedence:

```
explicit provider/model  →  known prefix  →  config default_provider  →  400
```

No fuzzy guessing. Per-provider aliases (`claude-sonnet`, `gemini-3.8-flash` → `-tiered`) are listed in [docs/models.md](docs/models.md). Set a default with `~/.llm-bridge/config.json` `{"default_provider": "anthropic"}` or `LLM_BRIDGE_DEFAULT_PROVIDER`.

## Endpoints

| Path | Format |
|---|---|
| `POST /v1/chat/completions` | OpenAI Chat Completions (default) |
| `POST /v1/messages` | Anthropic Messages |
| `POST /v1/responses` | OpenAI Responses |
| `GET /v1/models` | OpenAI model list (only authenticated providers) |
| `GET /health` | `{"status":"ok"}` |

When the inbound format is the provider's native one (Messages → anthropic, Responses → openai) the request is passed through untouched, so thinking blocks, signatures and cache_control survive.

## Commands

| Command | Does |
|---|---|
| `llm-bridge up` | Start the server in the foreground; creates a `default` key on first run |
| `llm-bridge keys create <name>` / `list` / `revoke <name>` | Manage keys (`~/.llm-bridge/keys.json`, mode 0600) |
| `llm-bridge models` | `provider/model` table with live auth state |
| `llm-bridge status` | Server, keys, service, providers, connected clients |
| `llm-bridge test [model]` | Real round-trip through the local server |
| `llm-bridge service install\|uninstall\|start\|stop\|restart\|status` | launchd (macOS) or systemd (Linux) background service |
| `llm-bridge connect hermes\|openclaw [--model]` | Write the client's config to use the bridge |

`up` never installs a service; `service install` does. Host/port: `--host/--port`, `LLM_BRIDGE_HOST/PORT`, or `config.json`. Binding to a non-loopback host prints a warning — keys are the only protection.

## Architecture

```
Client ──(chat | messages | responses)──> llm-bridge ──> anthropic   (api.anthropic.com)
                                              ├────────> openai      (chatgpt.com/backend-api/codex)
                                              └────────> antigravity (cloudcode-pa.googleapis.com)

inbound codec.decode → Request → provider.stream → Event* → codec.encode → client
                                 (native passthrough when formats match)
```

Pure Python 3.8+ stdlib: `http.server`, `urllib`, `json`, `hmac`. ~1.5k lines.

```
src/llm_bridge/
  ir.py          internal request + event shape
  server.py      routing, key auth, pipeline
  store.py       keys.json, config.json
  codecs/        openai_chat, anthropic, responses
  providers/     antigravity, anthropic, openai (+ registry/routing)
  service.py     launchd / systemd
  connect/       hermes, openclaw writers
  cli.py
```

## Testing

```bash
python3 tests/run_tests.py      # unit, no network
llm-bridge test anthropic/claude-sonnet-5   # live
```

## Docs

[Quickstart](docs/quickstart.md) · [Providers](docs/providers.md) · [Models & routing](docs/models.md) · [Hermes](docs/hermes.md) · [OpenClaw](docs/openclaw.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [Changelog](CHANGELOG.md)

## License

[MIT](LICENSE)
