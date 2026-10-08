# LLM Bridge quickstart: Gemini, Claude Code and Codex CLI

Requirements: Python 3.8+, macOS or Linux, and a supported CLI login. The gateway
has no runtime Python dependencies. Model requests still require internet
access and your provider's permission/quota.

## Install

```bash
git clone https://github.com/samirsawarkar/llm-bridge.git
cd llm-bridge
./install.sh
```

The installer uses pipx when available. For a Python environment you already
manage, `python3 -m pip install .` also works. From the checkout,
`./bin/llm-bridge --help` works without installing the package.

## Log in and save a Google account

Run `agy`, sign in to Google, then exit AGY. Save the current login:

```bash
llm-bridge accounts add personal
llm-bridge accounts list
```

Account import automatically reads AGY 1.3.1's macOS Keychain login or supported
legacy files. For another Google account, use `/logout` inside AGY, reopen it,
sign in to the next account, then `llm-bridge accounts add work`.

For saved AGY token refresh, configure the installed CLI's OAuth client settings:
[refresh setup](commands.md#oauth-refresh-for-saved-agy-accounts). Supply
`--project-id` when an account needs a different assigned Google project.

For Codex, use `codex login`. For Claude Code, run `claude` and use `/login`.
Those providers use their current CLI login; named saved accounts support AGY.

## Start the gateway

```bash
llm-bridge up
```

Keep this terminal open. The bridge prints its base URL and a new API key once.
In a second terminal, verify a request:

```bash
llm-bridge test antigravity@personal/gemini-3.8-flash
llm-bridge test antigravity@personal/gemini-3.1-pro-high
```

## Connect an app or agent

Use base URL `http://127.0.0.1:8000/v1`, your bridge API key, and a model ID from
the bridge. For Pi, follow [Pi setup](pi.md). For curl:

```bash
export LLM_BRIDGE_API_KEY="YOUR_BRIDGE_KEY"
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Authorization: Bearer $LLM_BRIDGE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"antigravity@personal/gemini-3.8-flash","messages":[{"role":"user","content":"Say hi"}]}'
```

To create another key: `llm-bridge keys create my-agent`. Inventory and health:
`llm-bridge accounts list`, `llm-bridge status`, `llm-bridge models`.

## Update

From the checkout:

```bash
git pull --ff-only
./install.sh
```

Restart the bridge after changing installed code. Saved accounts and keys
remain in the bridge data directory. Use the same `LLM_BRIDGE_HOME` everywhere
if you chose a custom location.

[All commands](commands.md) · [Troubleshooting](troubleshooting.md) ·
[Local network](commands.md#local-network--lan) · [Providers](providers.md)
