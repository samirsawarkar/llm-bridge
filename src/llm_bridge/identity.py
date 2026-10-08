"""Read display-only identity metadata. JWT claims never decide authentication."""
import base64
import json
import re


def clean(value):
    if not isinstance(value, str):
        return None
    value = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", value).strip()
    return value[:254] or None


def email(value):
    value = clean(value)
    return value if value and re.fullmatch(r"[^\s@]+@[^\s@]+", value) else None


def claims(token):
    try:
        part = token.split(".")[1]
        data = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        return data if isinstance(data, dict) else {}
    except (AttributeError, IndexError, TypeError, ValueError, UnicodeError):
        return {}


def extract(data):
    """Only inspect known identity fields; never return tokens or arbitrary values."""
    found = {"email": None, "display_name": None}
    if not isinstance(data, dict):
        return found
    candidates = [data]
    for key in ("token", "tokens", "credential", "claudeAiOauth", "oauthAccount", "account", "user", "profile"):
        if isinstance(data.get(key), dict):
            candidates.append(data[key])
    for candidate in list(candidates):
        for key in ("id_token", "idToken", "access_token", "accessToken"):
            decoded = claims(candidate.get(key))
            if decoded:
                candidates.append(decoded)
                profile = decoded.get("https://api.openai.com/profile")
                if isinstance(profile, dict):
                    candidates.append(profile)
    for candidate in candidates:
        for key in ("email", "emailAddress", "email_address"):
            found["email"] = found["email"] or email(candidate.get(key))
        for key in ("display_name", "displayName", "fullName", "name"):
            found["display_name"] = found["display_name"] or clean(candidate.get(key))
    return found
