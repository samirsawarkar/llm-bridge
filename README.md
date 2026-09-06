# Antigravity Bridge 🌉

[![CI](https://github.com/samirsawarkar/antigravity-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/samirsawarkar/antigravity-bridge/actions)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-0%20(stdlib%20only)-brightgreen.svg)](#-architecture--design)
[![OpenClaw](https://img.shields.io/badge/OpenClaw-Supported-blueviolet.svg)](docs/openclaw.md)
[![Hermes](https://img.shields.io/badge/Hermes-Supported-ff69b4.svg)](docs/hermes.md)

> Connect **OpenClaw** and **Hermes** agents to your **Google Antigravity** OAuth session via a high-reliability, local OpenAI-compatible proxy with zero external dependencies.

---

## ⚡ Why Antigravity Bridge?

Google Antigravity (`agy`) gives developers high-quota access to frontier intelligence—including **Gemini 3.8 Flash**, **Claude 3.7 / 3.8 / Sonnet 4.6**, and **Gemini 2.5 Pro**. However, connecting autonomous agents to it traditionally hits multiple friction points:

- **Proprietary Protocol:** Google Cloud Code uses internal protobuf endpoints rather than OpenAI-compatible APIs.
- **Short-Lived Tokens:** OAuth tokens expire every 60 minutes and need seamless background refresh.
- **Schema Validation Errors:** Google Gemini strictly rejects standard JSON Schema keywords (like `$schema`, `additionalProperties`, and `title`).
- **Tool-Call ID Quirks:** Multi-turn tool calling requires exact function name alignment and thought signatures.
- **Model Name Discrepancies:** Requests to `gemini-3.8-flash` return HTTP 404 upstream unless mapped to `gemini-3.8-flash-tiered`.

**Antigravity Bridge solves all of this automatically.** It runs locally on your machine or VPS, handles token refreshes, sanitizes schemas, maps models, and lets your agents work out-of-the-box.

---

## 🏗 Architecture

```
  ┌─────────────────────────────────────────────────────────────┐
  │                    YOUR LOCAL SYSTEM / VPS                  │
  │                                                             │
  │   ┌────────────────┐          ┌───────────────┐             │
  │   │ OpenClaw Agent │          │ Hermes Agent  │             │
  │   └───────┬────────┘          └───────┬───────┘             │
  │           │                           │                     │
  │           └─────────────┬─────────────┘                     │
  │                         │ OpenAI-compatible                 │
  │                         ▼ (http://127.0.0.1:8000/v1)        │
  │           ┌───────────────────────────────┐                 │
  │           │      Antigravity Bridge       │                 │
  │           │  - Auto Token Refresh (agy)   │                 │
  │           │  - JSON Schema Sanitizer      │                 │
  │           │  - Thought Signature Fallback │                 │
  │           │  - Upstream Model Aliasing    │                 │
  │           └──────────────┬────────────────┘                 │
  └──────────────────────────┼──────────────────────────────────┘
                             │ Google Cloud Code TLS
                             ▼
              ┌─────────────────────────────┐
              │ Google Antigravity Backend  │
              │  Gemini 3.8 Flash / Tiered  │
              │  Claude Sonnet 4.6          │
              │  Gemini 2.5 Pro             │
              └─────────────────────────────┘
```

---

## ✨ Features

- **Zero External Dependencies:** Built 100% on the Python 3.8+ standard library. No pip dependency conflicts.
- **Agent Flexibility:** Choose **OpenClaw only**, **Hermes only**, or **both**.
- **Interactive Wizard:** One command (`antigravity-bridge setup`) configures agents, writes credentials, and enables background daemons.
- **Proactive Auto-Refresh:** Detects expiring tokens and refreshes them via `agy` before requests fail.
- **Protobuf-Compliant Tool Calling:** Recursively strips proto-violating schema keys so tool calling never breaks.
- **Built-in Systemd Management:** Native Linux background service commands (`install`, `start`, `restart`, `status`).
- **Full Model Support:** Seamlessly aliases `gemini-3.8-flash`, `claude-sonnet-4-6`, `gemini-2.5-pro`, and more.

---

## 🚀 30-Second Quickstart

### 1. Install

```bash
git clone https://github.com/samirsawarkar/antigravity-bridge.git
cd antigravity-bridge
./install.sh
```

*(Or install via pip: `pip install -e .`)*

### 2. Check Antigravity OAuth

```bash
antigravity-bridge auth
```

*If you haven't logged into Antigravity yet, simply run `agy` once to authenticate with Google.*

### 3. Run the Setup Wizard

```bash
antigravity-bridge setup
```

The wizard will:
1. Ask which agent you want to connect (**OpenClaw**, **Hermes**, or **Both**).
2. Let you choose your default model.
3. Automatically configure agent configs and credentials.
4. Start the background proxy service.
5. Run a live verification test.

---

## 💻 CLI Command Reference

| Command | Description |
| :--- | :--- |
| `antigravity-bridge setup` | Interactive setup wizard (or use `--agent openclaw/hermes/both`) |
| `antigravity-bridge auth` | Verify Antigravity OAuth token health and upstream backend access |
| `antigravity-bridge status` | Diagnostic overview of token, proxy service, and connected agents |
| `antigravity-bridge models` | List available models or set active default model (`--set <id>`) |
| `antigravity-bridge test` | Run live end-to-end verification across direct proxy and agents |
| `antigravity-bridge service` | Control background systemd service (`start`, `stop`, `restart`, `status`, `install`) |
| `antigravity-bridge serve` | Run proxy foreground daemon (for headless / macOS / containers) |

> 💡 **Tip:** `agy-bridge` is available as a shorter alias for `antigravity-bridge`.

---

## 🤖 Supported Agents

### 1. Hermes Agent
[Hermes Agent](https://github.com/nousresearch/hermes-agent) connects natively to Antigravity Bridge as a custom OpenAI provider.
```bash
# Configure Hermes only
antigravity-bridge setup --agent hermes --model claude-sonnet-4-6

# Test Hermes
hermes chat -q "Say hello!"
```
*See [Hermes Integration Guide](docs/hermes.md) for full details.*

### 2. OpenClaw Agent
[OpenClaw](https://openclaw.ai) connects via its multi-agent gateway and local SQLite credential store.
```bash
# Configure OpenClaw only
antigravity-bridge setup --agent openclaw --model gemini-3.8-flash

# Test OpenClaw
openclaw agent --message "Say hello!"
```
*See [OpenClaw Integration Guide](docs/openclaw.md) for full details.*

---

## 🎯 Model Catalog

| Model ID | Display Name | Highlights |
| :--- | :--- | :--- |
| `gemini-3.8-flash` | Gemini 3.8 Flash | Ultra-fast execution, recommended for agent tool loops |
| `claude-sonnet-4-6` | Claude Sonnet 4.6 | High-level reasoning, complex code refactors, diffs |
| `gemini-2.5-pro` | Gemini 2.5 Pro | Deep context window, complex multi-turn logic |
| `gemini-2.5-flash` | Gemini 2.5 Flash | High-throughput subagent tasks |
| `claude-opus-4-6-thinking` | Claude Opus 4.6 | Extended reasoning and deep analysis |

Switch models at any time:
```bash
antigravity-bridge models --set claude-sonnet-4-6
```
*See [Models Reference](docs/models.md) for alias mappings and token constraints.*

---

## 🧪 Testing & Verification

Antigravity Bridge includes an automated test suite with zero dependencies:

```bash
# Run unit tests
python3 tests/run_tests.py

# Run live multi-agent verification turn
antigravity-bridge test --agent both
```

---

## 📚 Documentation

- [Quickstart Guide](docs/quickstart.md)
- [Hermes Integration](docs/hermes.md)
- [OpenClaw Integration](docs/openclaw.md)
- [Model Reference & Schema Notes](docs/models.md)
- [Systemd & Production Deployment](docs/systemd.md)
- [Contributing Guidelines](CONTRIBUTING.md)
- [Security Policy](SECURITY.md)
- [Changelog](CHANGELOG.md)

---

## 🤝 Contributing

We welcome community contributions! Please read our [Contributing Guidelines](CONTRIBUTING.md) and [Code of Conduct](CODE_OF_CONDUCT.md).

1. Fork the repo and create your branch: `git checkout -b feature/amazing-feature`
2. Make your changes adhering to the zero-dependency philosophy.
3. Ensure all tests pass: `python3 tests/run_tests.py`
4. Open a Pull Request.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE) - see the [LICENSE](LICENSE) file for details.
