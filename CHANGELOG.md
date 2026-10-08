# Changelog

## Unreleased

### Added
- Full CLI command guide, Pi custom-provider setup, LAN instructions, update
  commands, and account/Keychain/Pro troubleshooting. Search-oriented README,
  package metadata and llms.txt document the supported providers and limits.
- Account inventory with emails, display names, provider, default, source, and
  local credential status for saved AGY accounts and current AGY/Codex/Claude
  logins. Optional identity labels on account add and the new accounts label
  command; listing never refreshes credentials or calls upstream providers.
- Multiple named AGY accounts, with independent private credential files and
  per-account Google projects. Add/list/select/remove accounts from the CLI;
  select a specific account with `antigravity@name/model`. No fixed account cap
  and no account rotation on quota errors.
- Tests for concurrent use, account isolation, token refresh, secure storage,
  and account routing through all three HTTP formats.

### Fixed
- Gemini 3.1 Pro High generation uses the accepted Pro tier route with the
  High catalog entry's thinking budget, avoiding the direct High id's 400.
- Account-add confirmations include the saved email; duplicate-login errors
  identify the saved label. Tests cover switching between three Keychain logins.
- AGY 1.3.1 account import and listing detect the macOS Keychain login when
  legacy token files are absent; explicit token-file overrides still win.
- Source launcher finds its own package from any working directory.
- AGY expiry parsing preserves time-zone offsets and accepts `expiry_date`.
- Test discovery isolates bridge data before importing modules.

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-09-21

Renamed **antigravity-bridge → llm-bridge**. One local gateway over three CLI OAuth sessions.

### Added
- Providers `anthropic` (Claude Code OAuth → api.anthropic.com) and `openai` (Codex OAuth → chatgpt.com codex backend), alongside `antigravity`.
- Inbound `POST /v1/messages` (Anthropic Messages) and `POST /v1/responses` (OpenAI Responses) next to `/v1/chat/completions`; native passthrough when the inbound format matches the provider.
- API keys: `llm-bridge keys create|list|revoke`, stored in `~/.llm-bridge/keys.json` (0600); `Authorization: Bearer` or `x-api-key`.
- `llm-bridge up` prints base URL, key (once), provider auth state and model ids.
- launchd service on macOS (`service install`); systemd user unit on Linux (system unit when root).
- `llm-bridge models` reports per-provider auth state; `llm-bridge test [model]` does a live round-trip.
- Explicit routing: `provider/model` → bare-name prefix → `default_provider` → 400.

### Changed
- `setup` wizard replaced by `up` + optional `connect hermes|openclaw`.
- Streaming and non-streaming share one event pipeline; usage reported on both.
- Thinking deltas forwarded (`reasoning_content` in Chat, thinking blocks in Messages).

### Removed
- Fuzzy substring model matching; only explicit alias tables remain.
- `antigravity-bridge` / `agy-bridge` commands, `systemd/` unit file, `bin/` shims.

### Breaking
- Package, module and CLI names changed. A Bearer key is now required on every request.

## [1.0.0] - 2026-09-06

### Added
- **Unified CLI (`antigravity-bridge` / `agy-bridge`):**
  - `setup`: Interactive setup wizard allowing users to select OpenClaw only, Hermes only, or both agents with automated configuration.
  - `auth`: Token inspection, expiration monitoring, automatic re-auth trigger via `agy`, and live upstream Google backend connectivity verification.
  - `status`: Consolidated diagnostic table displaying proxy health, token validity, systemd daemon status, and agent configurations.
  - `models`: Catalog listing available Antigravity models and dynamic active model switching (`--set`).
  - `test`: End-to-end multi-agent verification turn testing direct HTTP proxy, Hermes CLI, and OpenClaw CLI.
  - `service`: Complete systemd background service management (`install`, `start`, `stop`, `restart`, `status`, `uninstall`).
  - `serve`: Foreground proxy server for headless or non-systemd environments.
- **Zero-Dependency Core Proxy Engine:**
  - OpenAI-compatible `/v1/chat/completions` streaming (SSE) and non-streaming HTTP server.
  - Google Cloud Code turn transformer mapping OpenAI chat history to Gemini `contents`.
  - Upstream model alias routing (maps `gemini-3.8-flash` to `gemini-3.8-flash-tiered`).
  - Protobuf-compliant JSON Schema sanitizer stripping `$schema`, `additionalProperties`, and `title` from tool declarations.
  - Turn guard ensuring conversations strictly end with a user turn.
  - Function call response name tracking mapping `tool_call_id` to matching function names.
  - Thought signature fallback and caching for Gemini reasoning models.
- **Agent Integrations:**
  - Automated YAML updater for Hermes Agent (`~/.hermes/config.yaml`).
  - Automated JSON config & SQLite credential injector for OpenClaw Agent (`~/.openclaw/openclaw.json`, `openclaw-agent.sqlite`).
- **Packaging & CI:**
  - Pure-Python PEP 517/518 build setup (`pyproject.toml`, `setup.py`).
  - GitHub Actions CI matrix workflow for Python 3.8 through 3.12 on Ubuntu and macOS.
  - Standalone unit test suite (`tests/`) with 100% test pass rate.
