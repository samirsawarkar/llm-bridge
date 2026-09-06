# Quickstart Guide

Get up and running with **Antigravity Bridge** in less than 2 minutes.

---

## 1. Prerequisites

- Python 3.8 or higher.
- Google Antigravity CLI (`agy`) installed and authenticated on your machine:
  ```bash
  agy --version
  ```
  If not authenticated, run `agy` once to complete Google OAuth in your browser or terminal.

---

## 2. Installation

Clone the repository and run the zero-dependency installer:

```bash
git clone https://github.com/samirsawarkar/antigravity-bridge.git
cd antigravity-bridge
./install.sh
```

Alternatively, install with pip:
```bash
pip install -e .
```

Verify the CLI is installed:
```bash
antigravity-bridge --help
```

---

## 3. Verify Authentication

Check the health and expiration of your Antigravity OAuth token:

```bash
antigravity-bridge auth
```

If valid, you'll see:
```
=== Antigravity OAuth Authentication Status ===
[✓] Token file found: ~/.gemini/antigravity-cli/antigravity-oauth-token
    Auth Method: consumer
    Expiry: 2026-09-06T12:00:00Z
[✓] Token is active (~58.0 minutes remaining).
Verifying connection to Google Antigravity Cloud Code backend...
[✓] Backend status: Authenticated (Tier: Antigravity, Plan: Google AI Pro)
```

---

## 4. Run the Interactive Setup

Connect OpenClaw, Hermes, or both:

```bash
antigravity-bridge setup
```

The wizard will prompt you:
1. Select which agent to connect (`1: OpenClaw`, `2: Hermes`, or `3: Both`).
2. Select your default model (e.g. `gemini-3.8-flash` or `claude-sonnet-4-6`).
3. Automatically install & start the background systemd service.
4. Run a live test turn to confirm everything works!

---

## 5. Non-Interactive / Scripted Setup

For automated servers or headless VPS instances, pass CLI flags:

```bash
# Connect only OpenClaw
antigravity-bridge setup --agent openclaw --model gemini-3.8-flash

# Connect only Hermes
antigravity-bridge setup --agent hermes --model claude-sonnet-4-6

# Connect both
antigravity-bridge setup --agent both --model gemini-3.8-flash
```

---

## 6. Check Overall Status

View the status of the proxy daemon, token, and configured agents at any time:

```bash
antigravity-bridge status
```
