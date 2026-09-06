# OpenClaw Agent Integration Guide

This guide explains how **Antigravity Bridge** connects [OpenClaw Agent](https://openclaw.ai) to Google Antigravity models.

---

## Architecture & Credentials

OpenClaw manages its configuration across two files:
1. **JSON Configuration:** `~/.openclaw/openclaw.json` (Defines models, providers, and gateway settings).
2. **SQLite Credential Database:** `~/.openclaw/openclaw-agent.sqlite` (Stores agent auth profiles and tokens).

When you run `antigravity-bridge setup --agent openclaw`, the bridge:
1. Defines the `antigravity` provider in `openclaw.json` with `baseUrl: "http://127.0.0.1:8000/v1"`.
2. Registers available models under the `antigravity/` namespace (e.g. `antigravity/gemini-3.8-flash`).
3. Sets the primary agent model to `antigravity/gemini-3.8-flash`.
4. Injects valid credentials into `openclaw-agent.sqlite` so OpenClaw never prompts for API keys.

---

## Verification & Usage

Run an agent turn through the OpenClaw Gateway:

```bash
openclaw agent --message "Say: Antigravity connection verified!"
```

Check OpenClaw's running gateway status:
```bash
openclaw gateway status
```

Run an end-to-end verification turn via the bridge:
```bash
antigravity-bridge test --agent openclaw
```

---

## Switching Models for OpenClaw

Change the active model for OpenClaw at any time:

```bash
antigravity-bridge models --set gemini-3.8-flash --agent openclaw
```
