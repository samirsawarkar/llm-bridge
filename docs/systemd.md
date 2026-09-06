# Systemd Service & Deployment Guide

Antigravity Bridge includes built-in systemd lifecycle management for Linux servers and VPS instances.

---

## Managing the Service via CLI

You can control the proxy service directly through the bridge CLI:

```bash
# Install and enable the systemd service (auto-starts on boot)
antigravity-bridge service install

# Check status
antigravity-bridge service status

# Restart service
antigravity-bridge service restart

# Stop service
antigravity-bridge service stop

# Completely remove service unit
antigravity-bridge service uninstall
```

---

## Service Unit Specification

The service file is installed at `/etc/systemd/system/antigravity-proxy.service`:

```ini
[Unit]
Description=Antigravity OpenAI-Compatible Proxy Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root
ExecStart=/usr/bin/python3 -m antigravity_bridge.cli serve --port 8000 --host 127.0.0.1
Restart=always
RestartSec=3
Environment=PORT=8000
Environment=HOST=127.0.0.1
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

---

## Checking Logs

View live streaming logs of the proxy server:

```bash
journalctl -u antigravity-proxy.service -f
```

View recent errors or restarts:
```bash
journalctl -u antigravity-proxy.service -n 50 --no-pager
```

---

## Running on macOS (Non-Systemd)

On macOS, you can run the bridge as a background daemon using nohup or a launchd plist:

```bash
# Run in background
nohup antigravity-bridge serve > /tmp/antigravity-bridge.log 2>&1 &
```
