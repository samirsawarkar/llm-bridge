# Changelog

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
