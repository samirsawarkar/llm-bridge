# Providers

All three reuse the CLI's own login. The bridge reads the CLI's credential store, refreshes through the provider's OAuth endpoint when the access token is within 60s of expiry, and writes the new tokens back so the CLI stays logged in. Refresh tokens rotate on anthropic and openai, so each provider holds a lock around re-read → refresh → write-back.

The endpoints and client ids below are the CLIs' public values at the time of writing and are the most likely thing to drift. If a provider 401s after refresh, compare against the installed CLI.

`llm-bridge accounts list` displays all saved AGY accounts and each provider's
current CLI login, including email and display name when available. Matching
saved and current AGY logins are shown once. Identity comes from local profile
fields or token claims, only for display; missing identities remain unknown.
No token is refreshed and no upstream request is made. Local credential status
does not establish whether the provider accepts the login or has quota left.
Use `accounts label <name> --email <email> --display-name <name>` to label an
older saved AGY account. Only AGY currently supports named saved logins.

## antigravity (`agy`)

- Named logins: `llm-bridge accounts add <name>` snapshots the current AGY login,
  or use `--token-file` for an explicit import. Each account has a private token
  file and its own optional `--project-id`. `accounts use <name>` selects the
  default; `antigravity@<name>/<model>` selects one account explicitly. There is
  no fixed account cap. Authentication files are refreshed atomically under a
  cross-process lock. A named account never falls back to another CLI's login.
  The active AGY CLI login remains unchanged. See the README for setup and
  recovery instructions. No automatic switching between accounts is performed.
  On macOS, account import and inventory prefer AGY 1.3.1's Keychain item
  (service `gemini`, account `antigravity`) over legacy CLI token files. Both
  plain JSON and Go Keyring's base64 wrapper are supported. Explicit token-file
  overrides take precedence; the Keychain is read only.

- Credentials: first of `~/.openclaw/agents/main/agent/auth-profiles.json`, `~/.gemini/antigravity-cli/antigravity-oauth-token`, `~/.gemini/jetski-standalone-oauth-token`, `~/.gemini/oauth_token.json`; override with `ANTIGRAVITY_TOKEN_FILE`.
- Refresh: direct via `oauth2.googleapis.com/token` only when `ANTIGRAVITY_CLIENT_ID` and `ANTIGRAVITY_CLIENT_SECRET` are set (the Antigravity CLI's own installed-app credentials, not shipped here); otherwise falls back to running `agy models`, which refreshes its own token file.
- Upstream: `cloudcode-pa.googleapis.com/v1internal:streamGenerateContent` (+ two fallbacks on 429/503).
- Pro High: the catalog's `gemini-3.1-pro-high` id is translated to the working
  Pro tier generation route `gemini-3.1-pro-low` with
  `generationConfig.thinkingConfig.thinkingBudget=10001` and
  `includeThoughts=true`, matching the High catalog entry's thinking budget.
  The direct High id returns invalid-argument errors on the tested daily
  endpoints. Both routes and catalog metadata were checked on 2026-10-08.
- Quirks: tool schemas are stripped to what Cloud Code's protobuf accepts (`$schema`, `title`, `additionalProperties`, `anyOf` collapsed); thought signatures are cached per tool call; a 429/503 on any model transparently retries on `gemini-3.8-flash-tiered` and reports that model in the response. `ANTIGRAVITY_PROJECT_ID` overrides the project.

## anthropic (Claude Code)

- Credentials: `~/.claude/.credentials.json` → `claudeAiOauth`, or the macOS Keychain item `Claude Code-credentials`. Which one holds the live token varies by Claude Code version (the other may exist with empty placeholders), so the bridge reads both and uses whichever has a token; write-back goes to that same source.
- Refresh: `api.anthropic.com/v1/oauth/token` (needs a `User-Agent`, else Cloudflare returns 403/1010), client id `9d1c250a-e61b-44d9-88ed-5944d1962f5e`. The refresh token is single-use and rotates; the bridge writes the new one back. Because Claude Code and the bridge share this one rotating token via the same store, a refresh by one can invalidate the other's copy if they run at the exact same moment.
- Upstream: `api.anthropic.com/v1/messages` with `anthropic-beta: oauth-2025-04-20`.
- Quirks: OAuth tokens are only honoured when the first system block is `You are Claude Code, Anthropic's official CLI for Claude.` — the bridge prepends it if missing (also on passthrough). Images in user messages are dropped in translated requests (native `/v1/messages` passthrough keeps them). Thinking deltas are forwarded as `reasoning_content` (Chat) / thinking blocks (Messages).

## openai (Codex)

- Credentials: `~/.codex/auth.json` → `tokens.{access_token,refresh_token,id_token,account_id}` (`CODEX_HOME` respected). API-key mode auth files are ignored.
- Refresh: `auth.openai.com/oauth/token`, client id `app_EMoamEEZ73f0CkXaXp7hrann`. Expiry comes from the access-token JWT.
- Upstream: `chatgpt.com/backend-api/codex/responses` with `chatgpt-account-id`, `OpenAI-Beta: responses=experimental`, `originator: codex_cli_rs`.
- Models: fetched from `chatgpt.com/backend-api/codex/models` per account (cached 10 min) — the allowed set differs by plan and changes often; `codex`'s own default model may not be in it.
- Quirks: the backend only streams (non-stream requests are collected by the bridge) and rejects sampling params, so `temperature`/`max_tokens` are dropped. `instructions` must be non-empty; a default is supplied.
