import base64
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))
from llm_bridge import accounts, identity, providers, store


def jwt(data):
    body = base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    return "header." + body + ".signature"


class TestIdentity(unittest.TestCase):
    def test_google_and_codex_email_and_name(self):
        google = identity.extract({"id_token": jwt({"email": "google@example.com", "name": "Google User"})})
        self.assertEqual(google, {"email": "google@example.com", "display_name": "Google User"})
        codex = identity.extract({"tokens": {"id_token": jwt({"email": "codex@example.com", "name": "Codex User"})}})
        self.assertEqual(codex["email"], "codex@example.com")
        nested = identity.extract({"tokens": {"access_token": jwt({"https://api.openai.com/profile": {"email": "nested@example.com"}})}})
        self.assertEqual(nested["email"], "nested@example.com")

    def test_claude_profile_and_missing_identity(self):
        claude = identity.extract({"oauthAccount": {"emailAddress": "claude@example.com", "displayName": "Claude User"}})
        self.assertEqual(claude, {"email": "claude@example.com", "display_name": "Claude User"})
        for bad in (None, [], {"tokens": {"access_token": "secret", "id_token": "invalid"}}, {"id_token": jwt([])}):
            self.assertEqual(identity.extract(bad), {"email": None, "display_name": None})

    def test_control_characters_cannot_escape_into_terminal(self):
        got = identity.extract({"email": "one@example.com\n", "name": "Name\x1b\n\t"})
        self.assertEqual(got, {"email": "one@example.com", "display_name": "Name"})
        self.assertIsNone(identity.email("access-secret-without-email"))


class TestInventory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = self.tmp.name
        home = patch.object(store, "DIR", self.home)
        home.start()
        self.addCleanup(home.stop)
        self.agy_path = os.path.join(self.home, "agy.json")
        self.google = {"token": {"access_token": "google-secret", "refresh_token": "google-refresh",
                                  "expiry": "2099-01-01T00:00:00Z"},
                       "id_token": jwt({"email": "google@example.com", "name": "Google User"})}
        with open(self.agy_path, "w") as f:
            json.dump(self.google, f)
        self.oa = Mock()
        self.oa._load.return_value = {"access": "codex-secret", "expires_at": 9e9,
                                     "_data": {"tokens": {"id_token": jwt({"email": "codex@example.com", "name": "Codex User"})}}}
        self.an = Mock()
        self.an._load.return_value = {"access": "claude-secret", "expires_at": 9e9,
                                     "_data": {"claudeAiOauth": {"accessToken": "claude-secret"}}}
        with open(os.path.join(self.home, ".claude.json"), "w") as f:
            json.dump({"oauthAccount": {"emailAddress": "claude@example.com", "displayName": "Claude User"}}, f)
        env = patch.dict(os.environ, {"ANTIGRAVITY_TOKEN_FILE": self.agy_path, "CLAUDE_CONFIG_DIR": self.home})
        env.start()
        self.addCleanup(env.stop)
        registry = patch.dict(providers.PROVIDERS, {"antigravity": Mock(), "openai": self.oa, "anthropic": self.an}, clear=True)
        registry.start()
        self.addCleanup(registry.stop)

    def test_all_current_cli_providers_are_listed_without_refresh_or_tokens(self):
        rows = accounts.inventory()
        self.assertEqual({r["provider"]: r["email"] for r in rows},
                         {"antigravity": "google@example.com", "openai": "codex@example.com", "anthropic": "claude@example.com"})
        for p in (self.oa, self.an):
            p.token.assert_not_called()
            p._refresh.assert_not_called()
        self.assertNotIn("secret", json.dumps(rows))

    def test_legacy_saved_account_recovers_only_its_matching_cli_identity(self):
        accounts.add("personal", self.agy_path)
        # Simulate an old saved account from before identities were kept.
        metadata = accounts.load()
        metadata["accounts"]["personal"].pop("email")
        metadata["accounts"]["personal"].pop("display_name")
        accounts.atomic_json(accounts._path(), metadata)
        with open(accounts.token_file("personal")) as f:
            saved = json.load(f)
        saved.pop("email")
        saved.pop("display_name")
        accounts.atomic_json(accounts.token_file("personal"), saved)
        rows = accounts.inventory()
        self.assertEqual(len(rows), 3)  # Do not duplicate the matching AGY CLI account.
        self.assertEqual(rows[0]["email"], "google@example.com")
        changed = dict(self.google, token=dict(self.google["token"], refresh_token="different-refresh"),
                       id_token=jwt({"email": "other@example.com"}))
        with open(self.agy_path, "w") as f:
            json.dump(changed, f)
        rows = accounts.inventory()
        self.assertIsNone(rows[0]["email"])  # Never label the saved account as the new CLI user.
        self.assertEqual(rows[1]["email"], "other@example.com")

    def test_multiple_saved_accounts_show_their_own_email(self):
        accounts.add("personal", self.agy_path)
        other = dict(self.google, token=dict(self.google["token"], refresh_token="other-refresh"),
                     id_token=jwt({"email": "other@example.com", "name": "Other User"}))
        path = os.path.join(self.home, "other.json")
        with open(path, "w") as f:
            json.dump(other, f)
        accounts.add("work", path)
        rows = accounts.inventory()
        saved = {r["name"]: r["email"] for r in rows if r["source"] == "saved"}
        self.assertEqual(saved, {"personal": "google@example.com", "work": "other@example.com"})
        self.assertEqual(len(rows), 4)

    def test_missing_cli_login_is_explicit(self):
        self.oa._load.return_value = None
        rows = accounts.inventory()
        codex = next(r for r in rows if r["provider"] == "openai")
        self.assertEqual(codex["status"], "missing")
        self.assertIsNone(codex["email"])
