"""Background service: launchd user agent (macOS) or systemd unit (Linux)."""
import os
import shutil
import subprocess
import sys

LABEL = "com.llm-bridge"
PLIST = os.path.expanduser("~/Library/LaunchAgents/%s.plist" % LABEL)
UNIT_USER = os.path.expanduser("~/.config/systemd/user/llm-bridge.service")
UNIT_SYSTEM = "/etc/systemd/system/llm-bridge.service"
MAC = sys.platform == "darwin"
ROOT = hasattr(os, "geteuid") and os.geteuid() == 0  # no geteuid on Windows


def _exe():
    return [shutil.which("llm-bridge")] if shutil.which("llm-bridge") else [sys.executable, "-m", "llm_bridge.cli"]


def _unit_path():
    return UNIT_SYSTEM if ROOT else UNIT_USER


def _systemctl(*args):
    if not shutil.which("systemctl"):  # e.g. Windows: report instead of raising FileNotFoundError
        return subprocess.CompletedProcess(args, 1, "", "no systemd or launchd on this system")
    return subprocess.run(["systemctl"] + ([] if ROOT else ["--user"]) + list(args), capture_output=True, text=True)


def installed():
    return os.path.exists(PLIST if MAC else _unit_path())


def install(host, port):
    args = _exe() + ["up", "--host", str(host), "--port", str(port)]
    if MAC:
        os.makedirs(os.path.dirname(PLIST), exist_ok=True)
        log = os.path.expanduser("~/.llm-bridge/service.log")
        os.makedirs(os.path.dirname(log), exist_ok=True)
        items = "".join("<string>%s</string>" % a for a in args)
        with open(PLIST, "w") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                    '<plist version="1.0"><dict><key>Label</key><string>%s</string><key>ProgramArguments</key><array>%s</array>'
                    '<key>RunAtLoad</key><true/><key>KeepAlive</key><true/><key>StandardOutPath</key><string>%s</string><key>StandardErrorPath</key><string>%s</string>'
                    '</dict></plist>\n' % (LABEL, items, log, log))
        subprocess.run(["launchctl", "unload", PLIST], capture_output=True)
        r = subprocess.run(["launchctl", "load", "-w", PLIST], capture_output=True, text=True)
        return r.returncode == 0, r.stderr.strip() or PLIST
    if not shutil.which("systemctl"):
        return False, "no systemd or launchd on this system; run `llm-bridge up` in a terminal multiplexer instead"
    path = _unit_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("[Unit]\nDescription=LLM Bridge\nAfter=network.target\n\n[Service]\nExecStart=%s\nRestart=always\nRestartSec=3\nEnvironment=PYTHONUNBUFFERED=1\n\n[Install]\nWantedBy=%s\n"
                % (" ".join(args), "multi-user.target" if ROOT else "default.target"))
    _systemctl("daemon-reload")
    r = _systemctl("enable", "--now", "llm-bridge.service")
    return r.returncode == 0, r.stderr.strip() or path


def uninstall():
    if MAC:
        subprocess.run(["launchctl", "unload", "-w", PLIST], capture_output=True)
        if os.path.exists(PLIST):
            os.remove(PLIST)
        return True
    _systemctl("disable", "--now", "llm-bridge.service")
    if os.path.exists(_unit_path()):
        os.remove(_unit_path())
    _systemctl("daemon-reload")
    return True


def ctl(action):
    """start | stop | restart | status -> (ok, text)."""
    if MAC:
        if action == "status":
            r = subprocess.run(["launchctl", "list", LABEL], capture_output=True, text=True)
            return r.returncode == 0, "running" if r.returncode == 0 else "not loaded"
        for a in (["stop", "start"] if action == "restart" else [action]):
            r = subprocess.run(["launchctl", a, LABEL], capture_output=True, text=True)
        return r.returncode == 0, r.stderr.strip() or action
    r = _systemctl("is-active" if action == "status" else action, "llm-bridge.service")
    return r.returncode == 0, (r.stdout or r.stderr).strip()
