# Antigravity Bridge for Autonomous Agents

> Power **OpenClaw** and **Hermes** with your authenticated **Google Antigravity (`agy`) account** — 100% free from third-party key costs and subscription quotas.

---

## Highlights

- **Zero Third-Party Cost:** Uses your existing Google Antigravity OAuth token (`~/.gemini/antigravity-cli/antigravity-oauth-token`) to run Gemini & Claude models.
- **Agent Choice:** Connect **OpenClaw**, **Hermes**, or **both**. Switch anytime.
- **Top-Tier Models:** Supports `gemini-3.8-flash` (blazing fast), `claude-sonnet-4-6` (deep agentic reasoning), `gemini-2.5-pro`, and `gemini-3.7-flash`.
- **Zero External Dependencies:** Built with Python 3 standard library only (`urllib`, `http.server`, `sqlite3`, `json`).
- **Production Reliability:**
  - **Tool Name Binding:** Automatically binds `tool_call_id` to exact function names across multi-turn histories.
  - **Thought Signature Fallback:** Guarantees Gemini thinking models never fail on replayed function calls.
  - **JSON Schema Sanitizer:** Converts standard JSON Schema into Google Cloud Code protobuf specifications.
  - **Automatic OAuth Refresh:** Proactively refreshes tokens before expiry without user intervention.
  - **Loopback Security:** Binds strictly to `127.0.0.1:8000` (zero public port exposure).

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                       Your Host                         │
│                                                         │
│   ┌───────────────┐     ┌───────────────┐               │
│   │    Hermes     │     │   OpenClaw    │               │
│   └───────┬───────┘     └───────┬───────┘               │
│           │ OpenAI /v1          │ OpenAI /v1            │
│           ▼                     ▼                       │
│   ┌─────────────────────────────────────┐               │
│   │   antigravity-bridge (127.0.0.1)    │               │
│   │   (OpenAI-compatible proxy daemon)  │               │
│   └──────────────────┬──────────────────┘               │
│                      │ Google Cloud Code REST / SSE     │
│                      ▼                                  │
│   ┌─────────────────────────────────────┐               │
│   │  Google Antigravity Prediction API  │               │
│   │  (daily-cloudcode-pa.googleapis.com)│               │
│   └─────────────────────────────────────┘               │
└─────────────────────────────────────────────────────────┘
```

---

## Quickstart

### 1. Prerequisites
- **Python 3.8+**
- **Antigravity CLI (`agy`)** installed and logged in (`agy` or `agy login`).

### 2. One-Line Install

```bash
git clone https://github.com/your-repo/antigravity-bridge.git
cd antigravity-bridge
./install.sh
```

Or install via pip:

```bash
pip install -e .
```

### 3. Setup (Interactive Wizard)

```bash
antigravity-bridge setup
```

The wizard will:
1. Verify your `agy` authentication.
2. Ask which agent you want to connect (`1) OpenClaw`, `2) Hermes`, or `3) Both`).
3. Let you select your default model (e.g. `gemini-3.8-flash` or `claude-sonnet-4-6`).
4. Install and start the background proxy service (`antigravity-proxy.service`).
5. Run a live verification test.

---

## CLI Reference

### `antigravity-bridge status`
Displays a comprehensive health report:
```bash
antigravity-bridge status
```
```
=========================================================
               Antigravity Bridge Status                 
=========================================================
Antigravity Token:   [✓] Present (VALID, ~55.2m remaining)
  Token Path:        /root/.gemini/antigravity-cli/antigravity-oauth-token
Proxy Service:       [✓] systemd (active)
Hermes Agent:        [✓] Installed (Model: claude-sonnet-4-6)
OpenClaw Agent:      [✓] Installed (Model: antigravity/gemini-3.8-flash)
=========================================================
```

### `antigravity-bridge auth`
Checks token expiration, runs a backend handshake verification, and refreshes the token if needed:
```bash
antigravity-bridge auth
```

### `antigravity-bridge models`
Lists all supported models:
```bash
antigravity-bridge models
```
Switch active default model on connected agents:
```bash
# Set default to Gemini 3.8 Flash on all agents
antigravity-bridge models --set gemini-3.8-flash

# Set default on OpenClaw only
antigravity-bridge models --set gemini-3.8-flash --agent openclaw

# Set default on Hermes only
antigravity-bridge models --set claude-sonnet-4-6 --agent hermes
```

### `antigravity-bridge test`
Runs an end-to-end verification turn through the proxy and agent CLIs:
```bash
antigravity-bridge test
antigravity-bridge test --agent openclaw
antigravity-bridge test --agent hermes
```

### `antigravity-bridge service`
Manages the background systemd service:
```bash
antigravity-bridge service status
antigravity-bridge service restart
antigravity-bridge service stop
antigravity-bridge service start
```

### `antigravity-bridge serve`
Run in the foreground (useful for development or Docker):
```bash
antigravity-bridge serve --port 8000 --host 127.0.0.1
```

---

## Non-Interactive / Scripted Setup

For automated provisioning or Docker containers:

```bash
# Setup OpenClaw only with Gemini 3.8 Flash
antigravity-bridge setup --agent openclaw --model gemini-3.8-flash --no-test

# Setup Hermes only with Claude Sonnet 4.6
antigravity-bridge setup --agent hermes --model claude-sonnet-4-6 --no-test

# Setup both agents
antigravity-bridge setup --agent both --model gemini-3.8-flash
```

---

## Supported Models

| Model Name | Upstream Identifier | Best For |
|---|---|---|
| `gemini-3.8-flash` | `gemini-3.8-flash-tiered` | Blazing speed, everyday coding, real-time agent loops |
| `claude-sonnet-4-6` | `claude-sonnet-4-6` | Deep agentic reasoning, long multi-step workflows |
| `gemini-2.5-pro` | `gemini-2.5-pro` | Complex analysis, large context reasoning |
| `gemini-2.5-flash` | `gemini-2.5-flash` | Ultra-fast responses |
| `gemini-3.7-flash` | `gemini-3.7-flash-tiered` | High performance intermediate flash model |
| `claude-opus-4-6-thinking` | `claude-opus-4-6-thinking` | Maximum reasoning depth |
| `gpt-oss-120b-medium` | `gpt-oss-120b-medium` | Open weights reasoning model |

---

## Running Tests

```bash
python3 tests/run_tests.py
```

---

## License

MIT License. See [LICENSE](LICENSE) for details.
