# LLM Bridge — Multi-account Gemini, Claude Code & Codex API Gateway

[![CI](https://github.com/samirsawarkar/llm-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/samirsawarkar/llm-bridge/actions)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-0%20(stdlib%20only)-brightgreen.svg)](#architecture)

**LLM Bridge is a local OpenAI-compatible LLM proxy for Google Antigravity (AGY), Gemini, Claude Code, and Codex CLI logins.** Save multiple Google accounts, see their emails, and choose an account for each request. Python 3.8+, zero runtime dependencies.

Point Pi, Cline, Cursor, Continue, Open WebUI, Hermes, OpenClaw, or an API client at `http://127.0.0.1:8000/v1`. The gateway supports OpenAI Chat Completions, Anthropic Messages, and OpenAI Responses. It runs on your machine and sends inference requests to the selected provider's cloud service.

Named saved accounts currently apply to AGY. Codex and Claude use their active CLI login. There is no fixed AGY account-count limit and no automatic account switching on quota errors.

[Install](#quickstart) · [Add Google accounts](#keep-multiple-google--agy-accounts-connected) · [All commands](docs/commands.md) · [Pi setup](docs/pi.md) · [Troubleshooting](docs/troubleshooting.md)

> Using subscription OAuth tokens from third-party clients may violate Anthropic's and OpenAI's terms of service. Your account, your call.

## Quickstart

```bash
git clone https://github.com/samirsawarkar/llm-bridge.git
cd llm-bridge
./install.sh           # uses pipx when available
agy                    # sign in to Google; exit AGY after login
llm-bridge accounts add personal
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

For AGY, sign in with `agy` and save the login with `llm-bridge accounts add personal`. For Claude or Codex, sign in through that CLI (`claude` → `/login`, `codex login`); the bridge reads its current login.

Run `llm-bridge up` in one terminal and the other bridge commands in another.
For Codex or Claude, sign in using `codex login` or `claude` → `/login`.
Named AGY accounts need the installed CLI's OAuth client settings for future
refreshes; see [refresh setup](docs/commands.md#oauth-refresh-for-saved-agy-accounts).

To update an existing checkout:

```bash
git pull --ff-only
./install.sh
```

Restart a running bridge after updating its code. Saved accounts and API keys
stay in the bridge data directory. You can also run `./bin/llm-bridge` directly
from the checkout. For shorter commands, `alias bridge=llm-bridge` enables
`bridge accounts list` in your current shell.

## Use it from

| Client | How |
|---|---|
| curl / any HTTP | `Authorization: Bearer <key>` or `x-api-key: <key>` |
| OpenAI SDK | `OpenAI(base_url="http://127.0.0.1:8000/v1", api_key="<key>")` |
| Anthropic SDK | `Anthropic(base_url="http://127.0.0.1:8000", api_key="<key>")` |
| Claude Code on another model | `ANTHROPIC_BASE_URL=http://127.0.0.1:8000 ANTHROPIC_API_KEY=<key> claude --model openai/gpt-5.5` |
| Cursor / Cline / Continue / Open WebUI | OpenAI-compatible provider, base URL `http://127.0.0.1:8000/v1`, key `<key>` |
| Hermes / OpenClaw | `llm-bridge connect hermes` / `llm-bridge connect openclaw` |
| Pi coding agent | Add the bridge to Pi’s `models.json`; see [Pi setup](docs/pi.md) |

Examples in [`examples/`](examples).

## Providers

### Keep multiple Google / AGY accounts connected

Save each account after signing in to it with the normal AGY CLI. Saved accounts
are independent snapshots: signing AGY into the next account does not replace
the earlier saved login. There is no fixed account-count limit.
On macOS, AGY 1.3.1's Keychain login is detected automatically; older token
files remain supported. An explicit `--token-file` or `ANTIGRAVITY_TOKEN_FILE`
overrides automatic detection. Importing copies the login into the bridge's
private account file without changing the Keychain entry.

```bash
# Sign in to your first account with agy, then:
llm-bridge accounts add personal
# Sign AGY in to your second account, then:
llm-bridge accounts add work
# Repeat with a different name for any additional account.
llm-bridge accounts list
llm-bridge accounts use work
```

Each successful add prints the email it saved. To add the next Google account,
sign out inside AGY with `/logout`, reopen AGY and sign in to that account, then
run `llm-bridge accounts add account3` (use a new label each time). The bridge
re-reads the current login on every add; earlier saved accounts stay separate.
If the login was already saved, the error identifies its existing label.

`accounts list` shows provider, account label, email, display name, default,
local credential status, and source. It includes every saved AGY account and
the current AGY, Codex, and Claude CLI logins (matching AGY entries appear once).
Codex and Claude currently use their CLI's active login; named saved accounts
are supported for AGY. Listing reads local metadata without refreshing tokens
or checking provider access or quota.

Emails and names are captured when saving an account, when the login contains
them. Older accounts with no recoverable identity show `unknown`. To label one:

```bash
llm-bridge accounts label personal --email you@example.com --display-name "Your Name"
```

You can also pass `--email` and `--display-name` to `accounts add`. Labels are
display metadata and do not change the authenticated account.

You can also import a specific AGY OAuth file and its Google project:

```bash
llm-bridge accounts add work --token-file /path/to/agy-token.json --project-id your-project-id
llm-bridge test antigravity@work/gemini-2.5-pro
```

Use `antigravity@personal/gemini-2.5-pro` or
`antigravity@work/gemini-2.5-pro` as the model to select an account per request.
Plain `antigravity/gemini-2.5-pro` and bare Gemini model names use the selected
default. Multiple clients can use different accounts simultaneously. Both
account selection and additions take effect without restarting the server.
`GET /v1/models` includes each locally authenticated named account.

Gemini 3.1 Pro High uses Google's working Pro generation route
(`gemini-3.1-pro-low`) with the High catalog entry's 10001-token thinking
budget. The direct `gemini-3.1-pro-high` generation id rejects requests on the
tested upstream endpoints. The bridge requests Pro with High thinking settings;
Google still controls how much thinking each response uses.

`llm-bridge accounts remove work` deletes only the saved bridge login; it does
not sign out AGY or revoke access at Google. Removing the default selects the
next saved account; with none left, the original CLI-based behavior resumes.

Credentials are stored in private files (0600) under
`$LLM_BRIDGE_HOME/accounts/`; the default bridge home is `~/.llm-bridge`.
Set `LLM_BRIDGE_HOME` consistently for the CLI and server if using another disk.
Account lists and errors never print tokens. Each saved account refreshes its
own credentials, with atomic writes and a lock shared across bridge processes.
Named accounts require direct OAuth refresh; they never refresh through a
different account's active AGY session. If the saved refresh token is revoked,
remove and re-add that account after signing in again.

The project defaults to the imported `project_id` / `projectId`, then the
bridge's `ANTIGRAVITY_PROJECT_ID` / existing project default. Use `--project-id`
when the accounts have different assigned projects. Listing checks local token
presence/expiry; `llm-bridge test` is the live check of Google access and quota.
This feature does not switch accounts on quota errors. Existing model fallback
behavior is unchanged. Multi-account support currently applies to AGY only.

From a source checkout, `./bin/llm-bridge accounts ...` works without installing
packages. If your installed `llm-bridge` lacks `accounts`, reinstall from the
updated checkout or use this launcher.

| Provider | Log in with | Credentials read from | Models |
|---|---|---|---|
| `antigravity` | `agy` | Saved bridge accounts; import reads macOS Keychain (AGY 1.3.1) or legacy `~/.gemini/…` files | Gemini 3.x/2.5, Claude via Antigravity, GPT-OSS |
| `anthropic` | `claude` → `/login` | `~/.claude/.credentials.json` (macOS: Keychain) | Claude 5 family, 4.6 |
| `openai` | `codex login` | `~/.codex/auth.json` | whatever your ChatGPT plan allows (fetched live, e.g. gpt-5.5, gpt-5.6-terra) |

Tokens are refreshed through each provider's own OAuth endpoint and written back, so the CLI stays logged in too. Details and quirks in [docs/providers.md](docs/providers.md).

## Model names

`provider/model` selects a provider explicitly. Availability depends on your login and provider access. Bare names route by prefix (`claude-*` → anthropic, `gpt-*`/`o*`/`codex*` → openai, `gemini-*` → antigravity). Precedence:

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
| `llm-bridge accounts add <name> [--token-file <file>] [--project-id <id>]` | Save an independent AGY account login |
| `llm-bridge accounts list` | Show saved AGY accounts and current CLI logins with emails and names |
| `llm-bridge accounts use <name>\|remove <name>` | Choose the default saved AGY account or remove one |
| `llm-bridge accounts label <name> [--email <email>] [--display-name <name>]` | Set identity labels for a saved AGY account |
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

Pure Python 3.8+ stdlib: `http.server`, `urllib`, `json`, `hmac`, and `fcntl`.

```
src/llm_bridge/
  accounts.py    saved AGY logins, identity inventory, account selection
  identity.py    display-only email and name extraction
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

[Quickstart](docs/quickstart.md) · [All commands](docs/commands.md) · [Pi](docs/pi.md) · [Troubleshooting](docs/troubleshooting.md) · [Providers](docs/providers.md) · [Models & routing](docs/models.md) · [AGENTS.md](AGENTS.md) · [Hermes](docs/hermes.md) · [OpenClaw](docs/openclaw.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [Changelog](CHANGELOG.md)

## License

[MIT](LICENSE)
