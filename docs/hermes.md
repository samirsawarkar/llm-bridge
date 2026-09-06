# Hermes Agent Integration Guide

This guide explains how **Antigravity Bridge** connects [Hermes Agent](https://github.com/nousresearch/hermes-agent) to Google Antigravity models.

---

## How It Works

Hermes Agent natively supports custom OpenAI-compatible providers configured in `~/.hermes/config.yaml`. Antigravity Bridge runs a local HTTP daemon that exposes:

- **Base URL:** `http://127.0.0.1:8000/v1`
- **Endpoint:** `/v1/chat/completions`

When you run `antigravity-bridge setup --agent hermes`, the bridge automatically updates `~/.hermes/config.yaml` with safe fallback and backup preservation.

---

## Manual Configuration

If you prefer configuring Hermes manually, open `~/.hermes/config.yaml` and ensure the following keys are set:

```yaml
provider: custom
model: claude-sonnet-4-6
custom_base_url: http://127.0.0.1:8000/v1
custom_api_key: antigravity
```

Supported models for Hermes:
- `gemini-3.8-flash` (High-speed, top efficiency)
- `claude-sonnet-4-6` (Deep agentic reasoning and planning)
- `gemini-2.5-pro` (Complex multi-tool reasoning)

---

## Testing Hermes with Antigravity

Run a single query from the command line:

```bash
hermes chat -q "What is 25 * 4?"
```

Launch the interactive Hermes CLI:
```bash
hermes
```

Run an automated test turn via the bridge:
```bash
antigravity-bridge test --agent hermes
```

---

## Switching Models for Hermes

Change the active Hermes model anytime:

```bash
antigravity-bridge models --set claude-sonnet-4-6 --agent hermes
```
