# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |

---

## Security Architecture & Threat Model

Antigravity Bridge is designed with security-first defaults:

1. **Loopback Only:**
   The proxy server binds exclusively to `127.0.0.1` (localhost) by default. It is not exposed to public network interfaces.
2. **Local Credential Handling:**
   OAuth tokens are read directly from `~/.gemini/antigravity-cli/antigravity-oauth-token` or resolved via `agy`. Tokens are transmitted over standard HTTPS TLS to Google Cloud Code upstream endpoints. No tokens or request payloads are ever logged, sent to external telemetry, or tracked.
3. **Local Database Security:**
   For OpenClaw, credentials in SQLite (`openclaw-agent.sqlite`) are stored locally with permissions restricted to the current user.

---

## Reporting a Vulnerability

If you discover a security vulnerability within Antigravity Bridge, please **do NOT open a public GitHub issue**.

Instead, please send a report directly to:
**samirsawarkars@gmail.com**

Please include:
- A description of the vulnerability and its potential impact.
- Steps to reproduce the issue or a proof-of-concept.
- Affected environment (OS, Python version, agent version).

We will acknowledge receipt of your vulnerability report within 48 hours and work with you to remediate and publish a security advisory.
