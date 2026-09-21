# LLM Bridge — Design

Date: 2026-09-21
Status: approved for planning
Supersedes: antigravity-bridge 1.0.0

## 1. Goal

One local gateway that turns the OAuth sessions of installed AI CLIs
(`agy`, `claude`, `codex`) into an OpenRouter-style API any app can use:
a base URL, a model name, and a generated API key. Everything stays on
the user's machine. Zero runtime dependencies (Python 3.8+ stdlib only).

Non-goals for v1: own OAuth login flows, per-key model allowlists, usage
metering, a web UI, Gemini CLI / Copilot providers.

## 2. User experience

```bash
pip install .            # canonical; ./install.sh is a thin wrapper (pipx if present, else pip --user)
llm-bridge up            # foreground server; prints the summary screen below
llm-bridge service install   # explicit: launchd (macOS) / systemd (Linux)
```

`up` output:

```
LLM Bridge  http://127.0.0.1:8000/v1
API key     sk-lb-3f9a…c2            (llm-bridge keys list)

Providers   antigravity  ✓ authenticated   agy
            anthropic    ✓ authenticated   claude
            openai       ✗ not logged in   → run: codex login

Models      anthropic/claude-sonnet-4-6  openai/gpt-5-codex  antigravity/gemini-3.8-flash  …  (llm-bridge models)
```

Commands:

| Command | Behaviour |
|---|---|
| `up [--host] [--port]` | Create `default` key if none (print full secret once), start foreground server, print summary. Never installs a service. |
| `keys create <name>` | Print full secret once. `keys list` masks (`sk-lb-3f9a…c2`). `keys revoke <name>`. |
| `models` | Aggregated `provider/model` table with provider state: `✓ authenticated`, `✗ expired`, `✗ not logged in`. Model rows inherit provider state. |
| `status` | Server reachable? key count, provider states, service state. |
| `test [model]` | Live round-trip through the local server (default: first available model). The real per-model probe. |
| `service install\|uninstall\|start\|stop\|restart\|status` | launchd user agent on macOS, systemd (user unit; system unit when root) on Linux. |
| `connect hermes\|openclaw [--model]` | Existing config writers, now an optional integration layer. |

Model naming is `provider/model`. Bare names route by prefix (see §5).
Alias resolution inside a provider (e.g. `gemini-3.8-flash` → `gemini-3.8-flash-tiered`)
is an explicit table; the old substring heuristics are deleted.

Inbound API formats, all under one server:

| Path | Format | Default? |
|---|---|---|
| `POST /v1/chat/completions` | OpenAI Chat Completions | yes |
| `POST /v1/messages` | Anthropic Messages | |
| `POST /v1/responses` | OpenAI Responses | |
| `GET /v1/models`, `/v1/models/{id}` | OpenAI list | |
| `GET /health` | `{"status":"ok"}` | |

## 3. Architecture

```
Client ──(any of 3 formats)──> server.py
   codec.decode ──> Request (ir.py) ──> router ──> provider.stream ──> Event* ──> codec.encode ──> client
                                                  └─ native passthrough when codec.fmt == provider.native_fmt
```

**Hub = an internal normalized structure**, deliberately *shaped like* Chat
Completions (so the Antigravity translate code carries over) but named and
owned by `ir.py`. Only `codecs/openai_chat.py` knows it is nearly identical
to the public schema.

**Native passthrough**: if the inbound format is the provider's native
format (Messages→anthropic, Responses→openai), the raw body is forwarded
with auth headers swapped and the upstream bytes streamed back verbatim.
Thinking blocks, signatures, cache_control etc. survive untouched.

### 3.1 File layout

```
src/llm_bridge/
  ir.py                 Request dict spec + Event constructors. The only place the shape is defined.
  server.py             ThreadingHTTPServer, routing, key auth, pipeline (~40 lines of glue).
  router.py             model string → (provider, upstream_model). 4-step precedence.
  keys.py               ~/.llm-bridge/keys.json  create/list/revoke/verify.
  config.py             ~/.llm-bridge/config.json + env overrides.
  service.py            launchd / systemd install, uninstall, start, stop, status.
  cli.py                argparse: up, keys, models, status, test, service, connect.
  codecs/
    __init__.py         by_path(): "/v1/chat/completions" → openai_chat, …
    openai_chat.py      decode / encode_stream / encode_final / encode_error
    anthropic.py        same four functions for Messages
    responses.py        same four functions for Responses
  providers/
    __init__.py         registry: {"antigravity": …, "anthropic": …, "openai": …}
    base.py             Provider contract (below)
    antigravity.py      today's auth.py + models.py + Gemini translate half of proxy.py
    anthropic.py        Claude Code OAuth + api.anthropic.com/v1/messages
    openai.py           Codex OAuth + chatgpt.com/backend-api/codex/responses
  connect/
    hermes.py, openclaw.py   moved from config_hermes.py / config_openclaw.py
```

Old `antigravity_bridge` package is removed. CLI entry points: `llm-bridge`, alias `lbr`.

### 3.2 ir.py — Request and Events

Request (plain dict):

```python
{
  "model": "anthropic/claude-sonnet-4-6",      # as sent by client
  "messages": [                                # roles: system | user | assistant | tool
    {"role": "system",    "content": "…"},
    {"role": "user",      "content": "…" | [{"type":"text","text":…}, {"type":"image_url",…}]},
    {"role": "assistant", "content": "…" | None, "tool_calls": [{"id","name","arguments": "<json str>"}]},
    {"role": "tool",      "tool_call_id": "…", "name": "…", "content": "…"},
  ],
  "tools": [{"name", "description", "parameters": <json schema>}],   # flattened; no {"type":"function"} wrapper
  "stream": bool,
  "max_tokens": int | None,
  "temperature": float | None,
  "extra": {}                                   # decoder-preserved fields codecs may want back (e.g. metadata); providers ignore
}
```

Events (tuples, yielded in order by `provider.stream`):

| Event | Payload | Notes |
|---|---|---|
| `("thinking", str)` | reasoning delta | codecs may drop; openai_chat emits `delta.reasoning_content` |
| `("text", str)` | content delta | |
| `("tool_call", {"id","name","arguments": str})` | one complete call | providers buffer partial args; all three upstreams deliver complete args by item end |
| `("usage", {"prompt_tokens","completion_tokens"})` | may arrive once, anywhere | |
| `("finish", "stop"\|"tool_calls"\|"length")` | last event | exactly once |
| `("error", {"status": int, "message": str})` | terminal | replaces finish; codec emits format-native error then closes |

Non-stream responses are collected from the same event stream — no separate non-stream path anywhere.

### 3.3 Provider contract (`providers/base.py`)

```python
class Provider:
    name: str                       # "anthropic"
    native_fmt: str | None          # "anthropic" | "responses" | None
    prefixes: tuple                 # bare-name routing: ("claude-",)
    catalog: list[dict]             # [{"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6"}]
    aliases: dict                   # explicit id → upstream id

    def auth_status(self) -> dict:  # {"ok": bool, "state": "authenticated"|"expired"|"missing", "detail": str, "fix": "run: codex login"}
    def token(self, force_refresh=False) -> str | None
    def stream(self, request: dict, upstream_model: str) -> Iterator[Event]
    def passthrough(self, fmt: str, body: bytes, headers: dict) -> HTTPResponse | None   # default None
```

`auth_status()` is cheap (file read + expiry check) and cached 60s for the
`models` listing; `test` is the live probe.

### 3.4 Codec contract (`codecs/*.py`)

```python
fmt: str                                  # "openai_chat" | "anthropic" | "responses"
decode(body: dict) -> Request
encode_stream(events, request, model) -> Iterator[bytes]     # SSE frames
encode_final(events, request, model) -> bytes                # JSON body
encode_error(status, message, kind) -> bytes                 # format-native error shape
```

## 4. Providers

All OAuth specifics below are taken from the CLIs' current public
behaviour and **must be verified against the installed CLI's real files
during implementation** — they are the parts most likely to drift.

### 4.1 antigravity (existing, refactored)

- Token: existing path list + refresh via Google token endpoint + `agy models` fallback (from uncommitted `auth.py` work).
- Upstream: `cloudcode-pa.googleapis.com/v1internal:streamGenerateContent?alt=sse` + fallbacks.
- Translate: `transform_messages`, `transform_tools`, `clean_json_schema`, thought-signature cache, all moved in as-is.
- Keeps the transparent 429/503 fallback to `gemini-3.8-flash-tiered` (existing behaviour); response `model` field reports the model actually used.
- `native_fmt = None`, `prefixes = ("gemini-",)`. `gpt-oss-*` is reachable only as explicit `antigravity/gpt-oss-…` (bare `gpt-` belongs to openai).

### 4.2 anthropic (Claude Code)

- Credentials: `~/.claude/.credentials.json` → `claudeAiOauth: {accessToken, refreshToken, expiresAt(ms), scopes, subscriptionType}`.
  macOS: Keychain generic password, service `Claude Code-credentials`; read `security find-generic-password -s … -w`, write back `security add-generic-password -U …`.
- Refresh: `POST https://console.anthropic.com/v1/oauth/token` `{grant_type: refresh_token, refresh_token, client_id: 9d1c250a-e61b-44d9-88ed-5944d1962f5e}`. Refresh tokens rotate → write back immediately.
- Upstream: `POST https://api.anthropic.com/v1/messages` with `Authorization: Bearer`, `anthropic-version: 2023-06-01`, `anthropic-beta: oauth-2025-04-20` (+ `interleaved-thinking-2025-05-14` when thinking requested).
- Quirk: OAuth tokens are only accepted when the system prompt's first block is the Claude Code identity line (`You are Claude Code, Anthropic's official CLI for Claude.`). Adapter prepends it when absent. Passthrough requests from Claude Code already carry it.
- Translate: Request → Messages (system blocks, tool_use/tool_result, `input_schema`), Messages SSE → Events (`content_block_delta` text/thinking/input_json, `message_delta` stop_reason+usage).
- `native_fmt = "anthropic"`, `prefixes = ("claude-",)`.

### 4.3 openai (Codex)

- Credentials: `~/.codex/auth.json` → `tokens: {id_token, access_token, refresh_token, account_id}`, `last_refresh`. Access token is a JWT; expiry from `exp`. `account_id` from file or `id_token` claim `https://api.openai.com/auth.chatgpt_account_id`.
- Refresh: `POST https://auth.openai.com/oauth/token` `{grant_type: refresh_token, refresh_token, client_id: app_EMoamEEZ73f0CkXaXp7hrann}`. Rotates → write back.
- Upstream: `POST https://chatgpt.com/backend-api/codex/responses` with `Authorization: Bearer`, `chatgpt-account-id`, `OpenAI-Beta: responses=experimental`, `originator: codex_cli_rs`, `Accept: text/event-stream`. Body is Responses API, `stream: true`, `store: false`, non-empty `instructions` required.
- Translate: Request → Responses `input` items (message / function_call / function_call_output), Responses SSE → Events (`response.output_text.delta`, `response.output_item.done` for function_call, `response.completed` usage).
- `native_fmt = "responses"`, `prefixes = ("gpt-", "o1", "o3", "o4", "codex")`.

### 4.4 Token refresh safety

Refresh tokens rotate on two of three providers; a double refresh with a
stale refresh token logs the CLI out. Each provider holds one
`threading.Lock` around *re-read file → check still expired → refresh →
write back*. The 401/403 retry path calls `token(force_refresh=True)`
once, never loops.

## 5. Routing (`router.py`)

Precedence, first hit wins, no fuzzy matching. Provider prefix sets are disjoint by construction (a unit test asserts it):

1. `provider/model` explicit → that provider, `model` (through its alias table). Unknown provider → 400.
2. Bare name matches a provider's `prefixes` → that provider.
3. `config.default_provider` set → that provider.
4. 400 `model_not_found` with message listing the format `provider/model`.

If the chosen provider's `auth_status().ok` is false → 401 with its `fix` string.

## 6. Keys and config

- `~/.llm-bridge/keys.json` (mode 0600): `{"<name>": {"key": "sk-lb-<40 hex>", "created": "<iso>"}}`. Plaintext by design — it is the user's own machine and `keys list` must be able to mask, not hash.
- Accepted headers: `Authorization: Bearer <key>` or `x-api-key: <key>` (Anthropic SDKs). Verified with `hmac.compare_digest` against every stored key.
- Full secret printed only by `keys create` and by `up` on first-run creation.
- `~/.llm-bridge/config.json`: `{"host": "127.0.0.1", "port": 8000, "default_provider": null}`. Env `LLM_BRIDGE_HOST/PORT/DEFAULT_PROVIDER` override file; CLI flags override env.
- Binding to a non-loopback host prints a one-line warning that keys are the only protection.

## 7. Errors

| Situation | Response |
|---|---|
| Missing/invalid key | 401, format-native error body (OpenAI `{error:{message,type,code}}`, Anthropic `{type:"error",error:{type,message}}`) |
| Bad JSON / unknown model | 400 |
| Provider not authenticated | 401 with `fix` text, e.g. `run: codex login` |
| Upstream 401/403 | force refresh once, retry once, then 502 |
| Upstream 429 / 5xx | pass status + upstream message through (antigravity keeps its endpoint and model fallbacks) |
| Error after stream started | `("error", …)` event → codec emits native error frame → connection closed |

Server log line per request: method, path, provider/model, status, ms.

## 8. Testing

Stdlib `unittest`, runnable with `python3 tests/run_tests.py`; no network in unit tests.

- `test_codecs.py` — for each codec: decode fixture → Request; encode a fixed Event list → compare to expected SSE frames and final JSON.
- `test_router.py` — the four precedence rules + ambiguous/unknown cases.
- `test_keys.py` — create/verify/revoke, masking, 0600.
- `test_antigravity.py` — existing transform/schema tests moved.
- `test_providers.py` — per provider: Request → upstream body dict, upstream SSE fixture → Events. Credential parsing from fixture files including JWT expiry.
- Live: `llm-bridge test <model>` and CI matrix (3.8–3.12, Ubuntu + macOS) unchanged except paths.

## 9. Migration and docs

- Package rename → `llm-bridge` 2.0.0; `pyproject.toml`, `setup.py`, `install.sh`, systemd unit, README, `docs/*`, `examples/*`, CHANGELOG updated. Old package directory deleted.
- README leads with the 3-command quickstart and the `up` screen; per-provider "how to log in" one-liners; per-client pointers (curl, OpenAI SDK, Anthropic SDK, Cursor/Cline base-URL, Hermes, OpenClaw).
- Uncommitted `auth.py`/`models.py`/`proxy.py` changes are carried into `providers/antigravity.py`, not lost.
