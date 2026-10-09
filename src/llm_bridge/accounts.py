"""Named Antigravity accounts. Credentials stay local; mutations are atomic."""
try:
    import fcntl
except ImportError:  # Windows
    fcntl = None
    import msvcrt
import base64
import hashlib
import json
import math
import os
import re
import tempfile
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone

from . import identity, store


def _lock(fd):
    if fcntl:
        fcntl.flock(fd, fcntl.LOCK_EX)
        return
    os.lseek(fd, 0, os.SEEK_SET)  # Windows: lock byte 0; LK_LOCK gives up after ~10s, so keep waiting like flock
    while True:
        try:
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
            return
        except OSError:
            pass


def _unlock(fd):
    if fcntl:
        fcntl.flock(fd, fcntl.LOCK_UN)
    else:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


@contextmanager
def file_lock(path):
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, "a") as lock:
        _lock(lock.fileno())
        try:
            yield
        finally:
            _unlock(lock.fileno())


def atomic_json(path, data):
    parent = os.path.dirname(path)
    os.makedirs(parent, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".account-", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _path():
    return os.path.join(store.DIR, "accounts.json")


def _agy_cli_source():
    from .providers.antigravity import TOKEN_PATHS
    return (os.environ.get("ANTIGRAVITY_TOKEN_FILE") or
            next((p for p in TOKEN_PATHS if ".gemini/" in p and os.path.isfile(p)), None))


def _windows_credential(target):
    """Blob of a generic credential in Windows Credential Manager, or None if absent."""
    import ctypes
    from ctypes import wintypes

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                    ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME),
                    ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_char)),
                    ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]

    advapi32 = ctypes.WinDLL("advapi32")
    advapi32.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                   ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
    advapi32.CredReadW.restype = wintypes.BOOL
    pcred = ctypes.POINTER(CREDENTIAL)()
    if not advapi32.CredReadW(target, 1, 0, ctypes.byref(pcred)):  # 1 = CRED_TYPE_GENERIC
        return None
    try:
        return ctypes.string_at(pcred.contents.CredentialBlob, pcred.contents.CredentialBlobSize)
    finally:
        advapi32.CredFree(pcred)


def _keyring_value():
    """AGY 1.3's go-keyring entry (service "gemini", user "antigravity"), or None.
    macOS keeps it in the Keychain; Windows in Credential Manager as target "gemini:antigravity"."""
    if sys.platform == "darwin":
        result = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-s", "gemini",
             "-a", "antigravity", "-w"], capture_output=True, text=True, timeout=5)
        return result.stdout.strip() if result.returncode == 0 else None
    if sys.platform == "win32":
        blob = _windows_credential("gemini:antigravity")
        if not blob:
            return None
        return (blob.decode("utf-16-le") if b"\x00" in blob else blob.decode("utf-8")).strip()
    return None


def _agy_cli_login():
    """Read AGY's active login, including 1.3's macOS Keychain / Windows Credential Manager store."""
    if sys.platform in ("darwin", "win32") and not os.environ.get("ANTIGRAVITY_TOKEN_FILE"):
        try:
            value = _keyring_value()
            if value:
                if value.startswith("go-keyring-base64:"):
                    value = base64.b64decode(value.split(":", 1)[1], validate=True).decode("utf-8")
                data = json.loads(value)
                from .providers.antigravity import _parse
                if isinstance(data, dict) and _parse(data).get("access"):
                    return data
        except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, AttributeError, OverflowError):
            pass
    source = _agy_cli_source()
    if source:
        try:
            with open(source, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            raise ValueError("cannot read a valid AGY login from the selected token file") from None
    return None


def token_file(name):
    _validate_name(name)
    return os.path.join(store.DIR, "accounts", name + ".json")


CURRENT_CLI = "current-cli"  # the active AGY login, as `accounts list` shows it; not a saved account


def _validate_name(name):
    if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", name):
        raise ValueError("account name must be 1–64 letters, digits, underscores or hyphens")


def load():
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {"accounts": {}, "default": None}
    except (OSError, ValueError):
        raise ValueError("cannot read accounts.json; repair it before managing accounts") from None
    if not isinstance(data, dict) or not isinstance(data.get("accounts"), dict):
        raise ValueError("invalid accounts.json")
    for name, item in data["accounts"].items():
        _validate_name(name)
        if not isinstance(item, dict) or not isinstance(item.get("project_id"), str) or not item["project_id"].strip():
            raise ValueError("invalid account entry: " + name)
        if any(k in item and item[k] is not None and not isinstance(item[k], str)
               for k in ("created", "fingerprint", "email", "display_name")):
            raise ValueError("invalid account metadata: " + name)
    if data.get("default") is not None and (not isinstance(data["default"], str) or data["default"] not in data["accounts"]):
        raise ValueError("invalid default account in accounts.json")
    return data


def add(name, source=None, project_id=None, email=None, display_name=None):
    """Snapshot an explicitly supplied token file, or the current AGY login."""
    from .providers.antigravity import PROJECT_ID, _parse
    _validate_name(name)
    if name == CURRENT_CLI:
        raise ValueError("'%s' means the active AGY login; choose another name" % CURRENT_CLI)
    # Prefer the actual AGY CLI store over OpenClaw's possibly older copy.
    try:
        if source:
            with open(os.path.expanduser(source), encoding="utf-8") as f:
                raw = json.load(f)
        else:
            raw = _agy_cli_login()
        if raw is None:
            raise FileNotFoundError()
        cred = _parse(raw)
    except FileNotFoundError:
        raise ValueError("no AGY login found; log in with agy or supply --token-file") from None
    except (OSError, ValueError, TypeError, AttributeError, OverflowError):
        raise ValueError("cannot read a valid AGY login from the selected token file") from None
    if not isinstance(cred.get("access"), str) or not cred["access"]:
        raise ValueError("selected token file has no AGY access token")
    if cred.get("refresh") is not None and not isinstance(cred["refresh"], str):
        raise ValueError("selected token file has an invalid refresh token")
    if not math.isfinite(cred["expires_at"]):
        raise ValueError("AGY login has an invalid expiry")
    if cred["expires_at"] <= datetime.now(timezone.utc).timestamp() + 60 and not cred.get("refresh"):
        raise ValueError("AGY login is expired and cannot refresh; log in again first")
    project_id = project_id or raw.get("project_id") or raw.get("projectId") or PROJECT_ID
    if not isinstance(project_id, str) or not project_id.strip():
        raise ValueError("supply a non-empty --project-id for this account")
    try:
        expiry = datetime.fromtimestamp(cred["expires_at"], timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError):
        raise ValueError("AGY login has an invalid expiry") from None
    fingerprint = hashlib.sha256((cred.get("refresh") or cred["access"]).encode()).hexdigest()
    details = identity.extract(raw)
    if email is not None:
        if not identity.email(email):
            raise ValueError("supply a valid account email")
        details["email"] = identity.email(email)
    if display_name is not None:
        details["display_name"] = identity.clean(display_name)
    with file_lock(_path() + ".lock"):
        data = load()
        if name in data["accounts"]:
            raise ValueError("account '%s' already exists; remove it before replacing it" % name)
        duplicate = next((n for n, a in data["accounts"].items() if a.get("fingerprint") == fingerprint), None)
        if duplicate:
            raise ValueError("this AGY login is already saved as '%s'; sign in to the other Google account first" % duplicate)
        path = token_file(name)
        saved = {"access_token": cred["access"], "refresh_token": cred.get("refresh"), "expiry": expiry}
        # Preserve only identity metadata, never unrelated profiles from an import.
        saved.update({k: v for k, v in details.items() if v})
        atomic_json(path, saved)
        data["accounts"][name] = {"project_id": project_id, "fingerprint": fingerprint,
                                   "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                   **details}
        if not data.get("default"):
            data["default"] = name
        try:
            atomic_json(_path(), data)
        except Exception:
            os.unlink(path)
            raise
    return details


def label(name, email=None, display_name=None):
    if email is None and display_name is None:
        raise ValueError("supply --email or --display-name")
    if email is not None and not identity.email(email):
        raise ValueError("supply a valid account email")
    with file_lock(_path() + ".lock"):
        data = load()
        if name not in data["accounts"]:
            raise ValueError("no account named '%s'" % name)
        if email is not None:
            data["accounts"][name]["email"] = identity.email(email)
        if display_name is not None:
            data["accounts"][name]["display_name"] = identity.clean(display_name)
        atomic_json(_path(), data)


def _credential_status(cred):
    if not cred or not cred.get("access"):
        return "missing"
    if cred.get("expires_at", 0) <= datetime.now(timezone.utc).timestamp() + 60 and not cred.get("refresh"):
        return "expired"
    return "authenticated"


def _fingerprint(cred):
    token = (cred or {}).get("refresh") or (cred or {}).get("access")
    return hashlib.sha256(token.encode()).hexdigest() if isinstance(token, str) else None


def _cli_logins():
    from .providers import PROVIDERS
    result = {}
    for provider, instance in PROVIDERS.items():
        if provider not in ("antigravity", "openai", "anthropic"):
            continue
        try:
            if provider == "antigravity":
                from .providers.antigravity import _parse
                raw = _agy_cli_login()
                cred = _parse(raw) if raw else None
                if cred and cred.get("access"):
                    cred["_data"] = raw
                else:
                    cred = None
            else:
                cred = instance._load()  # Listing must never refresh OAuth tokens.
        except (OSError, ValueError, TypeError, AttributeError):
            cred = None
        details = identity.extract((cred or {}).get("_data"))
        if provider == "anthropic" and cred and not details["email"]:
            # This is the active CLI's own profile, not a claim about a saved token.
            config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
            profile = os.path.join(config_dir, ".claude.json") if config_dir else os.path.expanduser("~/.claude.json")
            try:
                with open(profile, encoding="utf-8") as f:
                    info = identity.extract({"oauthAccount": json.load(f).get("oauthAccount")})
                details = {k: details[k] or info[k] for k in details}
            except (OSError, ValueError, AttributeError):
                pass
        result[provider] = {"credential": cred, "identity": details}
    return result


def inventory():
    """Return saved accounts and active CLI logins without tokens or network calls."""
    from .providers.antigravity import Antigravity
    data, cli, rows = load(), _cli_logins(), []
    matched = set()
    current = cli.get("antigravity", {})
    current_cred = current.get("credential")
    for name, item in data["accounts"].items():
        cred = Antigravity(token_file=token_file(name), project_id=item["project_id"])._load()
        details = identity.extract((cred or {}).get("_data"))
        same = current_cred and (item.get("fingerprint") == _fingerprint(current_cred) or
                                (_fingerprint(cred) and _fingerprint(cred) == _fingerprint(current_cred)))
        if same:
            matched.add("antigravity")
            details = {k: details[k] or current["identity"][k] for k in details}
        rows.append({"provider": "antigravity", "name": name, "source": "saved",
                     "email": item.get("email") or details["email"],
                     "display_name": item.get("display_name") or details["display_name"],
                     "default": data.get("default") == name, "status": _credential_status(cred)})
    for provider, info in cli.items():
        if provider in matched:
            continue
        rows.append({"provider": provider, "name": "current-cli", "source": "CLI",
                     "default": provider != "antigravity" or not data.get("default"),
                     "status": _credential_status(info["credential"]), **info["identity"]})
    return rows


def use(name):
    with file_lock(_path() + ".lock"):
        data = load()
        if name == CURRENT_CLI:  # back to AGY's live login; saved accounts stay usable as @name
            data["default"] = None
            atomic_json(_path(), data)
            return
        if name not in data["accounts"]:
            raise ValueError("no account named '%s'" % name)
        data["default"] = name
        atomic_json(_path(), data)


def remove(name):
    with file_lock(_path() + ".lock"):
        data = load()
        if name not in data["accounts"]:
            raise ValueError("no account named '%s'" % name)
        # Use the same lock as refresh, so removal cannot resurrect a token file.
        path = token_file(name)
        with file_lock(path + ".lock"):
            del data["accounts"][name]
            if data.get("default") == name:
                data["default"] = next(iter(data["accounts"]), None)
            atomic_json(_path(), data)
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
