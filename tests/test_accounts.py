import contextlib
import base64
import io
import json
import os
import stat
import sys
import tempfile
import unittest
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch, Mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))
from llm_bridge import accounts, cli, providers, server, store
from llm_bridge.providers import antigravity as ag


class TestAccounts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = self.tmp.name
        self.patch = patch.object(store, "DIR", self.home)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        cli_logins = patch.object(accounts, "_cli_logins", return_value={})
        cli_logins.start()
        self.addCleanup(cli_logins.stop)
        providers._named_account.cache_clear()
        self.addCleanup(providers._named_account.cache_clear)

    def test_file_lock_excludes_second_holder(self):
        path = os.path.join(self.home, "accounts.lock")
        held, release, second_in = threading.Event(), threading.Event(), threading.Event()

        def first():
            with accounts.file_lock(path):
                held.set()
                release.wait(5)

        def second():
            with accounts.file_lock(path):
                second_in.set()

        a = threading.Thread(target=first)
        a.start()
        self.assertTrue(held.wait(5))
        b = threading.Thread(target=second)
        b.start()
        self.assertFalse(second_in.wait(0.3))  # blocked while the first holder has the lock
        release.set()
        self.assertTrue(second_in.wait(5))
        a.join(5)
        b.join(5)

    def source(self, name, expiry="2099-01-01T00:00:00+00:00"):
        path = os.path.join(self.home, "source-" + name + ".json")
        with open(path, "w") as f:
            json.dump({"access_token": "access-" + name, "refresh_token": "refresh-" + name,
                       "expiry": expiry, "project_id": "project-" + name}, f)
        return path

    def add(self, name, expiry="2099-01-01T00:00:00+00:00"):
        source = self.source(name, expiry)
        accounts.add(name, source)
        return source

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(sys, "argv", ["llm-bridge"] + list(args)), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main()
        return code, out.getvalue() + err.getvalue()

    def test_keep_many_accounts_across_reload_and_select_default(self):
        for i in range(12):
            self.add("account-%d" % i)
        self.assertEqual(len(accounts.load()["accounts"]), 12)
        self.assertEqual(accounts.load()["default"], "account-0")
        accounts.use("account-11")
        for model in ("antigravity/gemini-2.5-pro", "gemini-2.5-pro"):
            p, _ = providers.resolve(model)
            self.assertEqual(p.token(), "access-account-11")
        providers._named_account.cache_clear()  # Simulates a new server process.
        p, _ = providers.resolve("antigravity/gemini-2.5-pro")
        self.assertEqual(p.token(), "access-account-11")

    def test_snapshot_is_private_and_cli_changes_do_not_replace_saved_login(self):
        source = self.add("personal")
        saved = accounts.token_file("personal")
        if os.name != "nt":  # Windows has no POSIX mode bits; files inherit the user-profile ACL
            for path in (saved, accounts._path()):
                self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(saved)).st_mode), 0o700)
        with open(source, "w") as f:
            f.write('{}')
        p, _ = providers.resolve("antigravity@personal/gemini-2.5-pro")
        self.assertEqual(p.token(), "access-personal")

    def test_account_identity_is_preserved_after_cli_login_changes(self):
        source = self.source("one")
        with open(source) as f:
            raw = json.load(f)
        raw.update({"email": "one@example.com", "name": "First Account"})
        with open(source, "w") as f:
            json.dump(raw, f)
        accounts.add("one", source)
        with open(source, "w") as f:
            f.write('{}')
        row = accounts.inventory()[0]
        self.assertEqual((row["email"], row["display_name"]), ("one@example.com", "First Account"))
        self.assertEqual(accounts.load()["accounts"]["one"]["email"], "one@example.com")

    def test_label_old_account_without_touching_tokens(self):
        self.add("one")
        path = accounts.token_file("one")
        with open(path, "rb") as f:
            before = f.read()
        code, out = self.run_cli("accounts", "label", "one", "--email", "one@example.com", "--display-name", "One")
        self.assertEqual(code, 0, out)
        with open(path, "rb") as f:
            self.assertEqual(f.read(), before)
        self.assertEqual(accounts.inventory()[0]["email"], "one@example.com")
        code, out = self.run_cli("accounts", "list")
        self.assertIn("one@example.com", out)
        self.assertIn("One", out)
        self.assertEqual(self.run_cli("accounts", "label", "one", "--email", "not-an-email")[0], 1)
        self.assertEqual(self.run_cli("accounts", "label", "missing", "--email", "one@example.com")[0], 1)

    def test_invalid_and_duplicate_imports_do_not_overwrite_accounts(self):
        source = self.add("personal")
        with self.assertRaises(ValueError):
            accounts.add("personal", self.source("other"))
        with self.assertRaises(ValueError):
            accounts.add("duplicate", source)
        for name in ("../escape", "", "bad/name", "x" * 65):
            with self.assertRaises(ValueError):
                accounts.add(name, source)
        invalid = self.source("bad")
        with open(invalid, "w") as f:
            f.write('{"access_token": "secret-not-for-errors", broken')
        code, out = self.run_cli("accounts", "add", "bad", "--token-file", invalid)
        self.assertEqual(code, 1)
        self.assertNotIn("secret-not-for-errors", out)
        self.assertEqual(list(accounts.load()["accounts"]), ["personal"])

    def test_expired_login_without_refresh_is_rejected(self):
        path = self.source("expired", "2000-01-01T00:00:00Z")
        with open(path) as f:
            data = json.load(f)
        data.pop("refresh_token")
        with open(path, "w") as f:
            json.dump(data, f)
        with self.assertRaisesRegex(ValueError, "expired"):
            accounts.add("expired", path)

    def test_cli_add_list_use_remove_never_prints_tokens(self):
        for name in ("one", "two"):
            code, out = self.run_cli("accounts", "add", name, "--token-file", self.source(name))
            self.assertEqual(code, 0, out)
        code, out = self.run_cli("accounts", "list")
        self.assertEqual(code, 0)
        self.assertIn("one", out)
        self.assertIn("two", out)
        self.assertNotIn("access-", out)
        self.assertNotIn("refresh-", out)
        self.assertEqual(self.run_cli("accounts", "use", "two")[0], 0)
        self.assertEqual(accounts.load()["default"], "two")
        self.assertEqual(self.run_cli("accounts", "remove", "two")[0], 0)
        self.assertFalse(os.path.exists(accounts.token_file("two")))
        self.assertTrue(os.path.exists(os.path.join(self.home, "source-two.json")))
        self.assertEqual(accounts.load()["default"], "one")
        self.assertEqual(self.run_cli("accounts", "use", "missing")[0], 1)

    def test_import_current_cli_login(self):
        with patch.dict(os.environ, {"ANTIGRAVITY_TOKEN_FILE": self.source("current")}):
            self.assertEqual(self.run_cli("accounts", "add", "current")[0], 0)
        self.assertIn("current", accounts.load()["accounts"])

    def test_default_import_prefers_current_agy_over_openclaw(self):
        source = self.source("current")
        with patch.dict(os.environ, {}, clear=True), patch.object(accounts.sys, "platform", "linux"), patch.object(ag, "TOKEN_PATHS", ["/fake/.openclaw/auth.json", source.replace("source-current", ".gemini/current")]):
            nested = os.path.join(self.home, ".gemini")
            os.mkdir(nested)
            target = os.path.join(nested, "current.json")
            with open(source) as f, open(target, "w") as out:
                out.write(f.read())
            self.assertEqual(self.run_cli("accounts", "add", "current")[0], 0)

    def test_import_keychain_login_keeps_identity_and_isolates_snapshot(self):
        raw = {"token": {"access_token": "keychain-access", "refresh_token": "keychain-refresh",
                         "expiry": "2099-01-01T00:00:00Z"},
               "email": "new@example.com", "name": "New User"}
        for i, wrapped in enumerate((False, True)):
            value = json.dumps(raw)
            if wrapped:
                value = "go-keyring-base64:" + base64.b64encode(value.encode()).decode()
            result = Mock(returncode=0, stdout=value)
            with patch.dict(os.environ, {}, clear=True), patch.object(accounts.sys, "platform", "darwin"), patch.object(accounts.subprocess, "run", return_value=result) as run:
                accounts.add("keychain-%d" % i)
                run.assert_called_once_with(
                    ["/usr/bin/security", "find-generic-password", "-s", "gemini", "-a", "antigravity", "-w"],
                    capture_output=True, text=True, timeout=5)
            row = accounts.inventory()[0]
            self.assertEqual(row["email"], "new@example.com")
            with open(accounts.token_file("keychain-%d" % i)) as f:
                self.assertEqual(json.load(f)["access_token"], "keychain-access")
            accounts.remove("keychain-%d" % i)

    def test_windows_credential_manager_login_is_saved(self):
        raw = {"token": {"access_token": "wincred-access", "refresh_token": "wincred-refresh",
                         "expiry": "2099-01-01T00:00:00Z"},
               "email": "win@example.com", "name": "Win User"}
        value = json.dumps(raw)
        blobs = (value.encode("utf-8"), value.encode("utf-16-le"),
                 ("go-keyring-base64:" + base64.b64encode(value.encode()).decode()).encode("utf-8"))
        for i, blob in enumerate(blobs):
            with patch.dict(os.environ, {}, clear=True), patch.object(accounts.sys, "platform", "win32"), \
                 patch.object(accounts, "_windows_credential", return_value=blob) as read:
                accounts.add("wincred-%d" % i)
                read.assert_called_once_with("gemini:antigravity")
            self.assertEqual(accounts.inventory()[0]["email"], "win@example.com")
            with open(accounts.token_file("wincred-%d" % i)) as f:
                self.assertEqual(json.load(f)["access_token"], "wincred-access")
            accounts.remove("wincred-%d" % i)

    def test_missing_windows_credential_falls_back_to_file(self):
        source = self.source("winfallback")
        for blob in (None, b"", b"not-json"):
            with patch.dict(os.environ, {}, clear=True), patch.object(accounts.sys, "platform", "win32"), \
                 patch.object(accounts, "_windows_credential", return_value=blob), \
                 patch.object(accounts, "_agy_cli_source", return_value=source):
                self.assertEqual(accounts._agy_cli_login()["access_token"], "access-winfallback")

    @unittest.skipUnless(sys.platform == "win32", "Windows Credential Manager")
    def test_windows_credential_reader_returns_none_for_absent_target(self):
        self.assertIsNone(accounts._windows_credential("llm-bridge-test:absent-" + os.urandom(6).hex()))

    def test_explicit_login_override_does_not_read_keychain(self):
        with patch.dict(os.environ, {"ANTIGRAVITY_TOKEN_FILE": self.source("override")}), patch.object(accounts.sys, "platform", "darwin"), patch.object(accounts.subprocess, "run") as run:
            accounts.add("override")
            run.assert_not_called()

    def test_switching_keychain_logins_saves_multiple_independent_accounts(self):
        result = Mock(returncode=0)
        with patch.dict(os.environ, {}, clear=True), patch.object(accounts.sys, "platform", "darwin"), patch.object(accounts.subprocess, "run", return_value=result) as read:
            for i in range(3):
                result.stdout = json.dumps({"token": {"access_token": "access-%d" % i,
                    "refresh_token": "refresh-%d" % i, "expiry": "2099-01-01T00:00:00Z"},
                    "email": "user%d@example.com" % i})
                code, output = self.run_cli("accounts", "add", "account%d" % i)
                self.assertEqual(code, 0, output)
                self.assertIn("user%d@example.com" % i, output)
            code, output = self.run_cli("accounts", "add", "duplicate")
            self.assertEqual(code, 1)
            self.assertIn("already saved as 'account2'", output)
            for call in read.call_args_list:
                self.assertEqual(call[0][0][1], "find-generic-password")
        self.assertEqual(accounts.load()["default"], "account0")
        for i in range(3):
            with open(accounts.token_file("account%d" % i)) as f:
                saved = json.load(f)
            self.assertEqual(saved["access_token"], "access-%d" % i)
            self.assertEqual(saved["email"], "user%d@example.com" % i)

    def test_invalid_or_missing_keychain_falls_back_to_file(self):
        source = self.source("fallback")
        for result in (Mock(returncode=1, stdout=""), Mock(returncode=0, stdout="not-json"),
                       Mock(returncode=0, stdout="go-keyring-base64:!invalid"), Mock(returncode=0, stdout="[]")):
            with patch.dict(os.environ, {}, clear=True), patch.object(accounts.sys, "platform", "darwin"), patch.object(accounts.subprocess, "run", return_value=result), patch.object(accounts, "_agy_cli_source", return_value=source):
                self.assertEqual(accounts._agy_cli_login()["access_token"], "access-fallback")

    def test_gemini_numeric_expiry_and_timezone_are_supported(self):
        numeric = ag._parse({"access_token": "x", "expiry_date": 1900000000000})
        offset = ag._parse({"access_token": "x", "expiry": "2030-01-01T05:30:00.123+05:30"})
        utc = ag._parse({"access_token": "x", "expiry": "2030-01-01T00:00:00.123Z"})
        self.assertEqual(numeric["expires_at"], 1900000000)
        self.assertEqual(offset["expires_at"], utc["expires_at"])

    def test_concurrent_adds_are_not_lost(self):
        sources = [("parallel-%d" % i, self.source("parallel-%d" % i)) for i in range(10)]
        with ThreadPoolExecutor(max_workers=5) as pool:
            list(pool.map(lambda item: accounts.add(*item), sources))
        self.assertEqual(len(accounts.load()["accounts"]), 10)

    def test_parallel_requests_keep_tokens_and_projects_separate(self):
        self.add("one")
        self.add("two")
        seen = []
        def fake_http(url, body, headers):
            seen.append((body["project"], headers["Authorization"]))
            return iter([b'data: {"response":{"candidates":[{"content":{"parts":[{"text":"ok"}]}}]}}\n'])
        def request(name):
            p, model = providers.resolve("antigravity@%s/gemini-2.5-pro" % name)
            return list(p.stream({"messages": [{"role": "user", "content": "hi"}]}, model))
        with patch.object(ag, "http", side_effect=fake_http), ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(request, ["one", "two"] * 20))
        self.assertTrue(all(("text", "ok") in r for r in results))
        self.assertEqual(set(seen), {("project-one", "Bearer access-one"), ("project-two", "Bearer access-two")})

    def test_real_local_api_routes_accounts_and_reports_bad_configuration(self):
        self.add("one")
        self.add("two")
        seen = []
        def fake_http(url, body, headers):
            seen.append((body["project"], headers["Authorization"]))
            return iter([b'data: {"response":{"candidates":[{"content":{"parts":[{"text":"account reply"}]}}]}}\n'])
        with patch.object(store, "KEYS", os.path.join(self.home, "keys.json")):
            key = store.create_key("api-test")
            srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
            thread = threading.Thread(target=srv.serve_forever, daemon=True)
            thread.start()
            base = "http://127.0.0.1:%d" % srv.server_address[1]
            def call(path, model=None, stream=False):
                body = None if model is None else json.dumps({"model": model, "messages": [{"role": "user", "content": "hi"}], "stream": stream}).encode()
                req = urllib.request.Request(base + path, data=body, headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=5) as response:
                    return response.read()
            try:
                with patch.object(ag, "http", side_effect=fake_http):
                    result = json.loads(call("/v1/chat/completions", "antigravity@one/gemini-2.5-pro"))
                    self.assertEqual(result["choices"][0]["message"]["content"], "account reply")
                    self.assertIn(b'account reply', call("/v1/chat/completions", "antigravity@two/gemini-2.5-pro", stream=True))
                    accounts.use("two")
                    call("/v1/messages", "antigravity/gemini-2.5-pro")
                    call("/v1/responses", "antigravity@one/gemini-2.5-pro")
                self.assertEqual(seen, [("project-one", "Bearer access-one"), ("project-two", "Bearer access-two"),
                                        ("project-two", "Bearer access-two"), ("project-one", "Bearer access-one")])
                ids = {m["id"] for m in json.loads(call("/v1/models"))["data"]}
                self.assertIn("antigravity@one/gemini-2.5-pro", ids)
                with self.assertRaises(urllib.error.HTTPError) as missing:
                    call("/v1/chat/completions", "antigravity@missing/gemini-2.5-pro")
                self.assertEqual(missing.exception.code, 400)
                missing.exception.close()
                with open(accounts._path(), "w") as f:
                    f.write('{broken')
                with self.assertRaises(urllib.error.HTTPError) as broken:
                    call("/v1/models")
                self.assertEqual(broken.exception.code, 503)
                self.assertNotIn(b"access-", broken.exception.read())
                broken.exception.close()
            finally:
                srv.shutdown()
                srv.server_close()
                thread.join(timeout=5)

    def test_quota_failure_does_not_switch_to_another_account(self):
        self.add("one")
        self.add("two")
        seen = []
        def exhausted(url, body, headers):
            seen.append(headers["Authorization"])
            raise urllib.error.HTTPError(url, 429, "quota exhausted", {}, io.BytesIO(b'{"error":{"message":"quota exhausted"}}'))
        p, model = providers.resolve("antigravity@one/gemini-2.5-pro")
        with patch.object(ag, "http", side_effect=exhausted):
            events = list(p.stream({"messages": [{"role": "user", "content": "hi"}]}, model))
        self.assertEqual(events[-1][0], "error")
        self.assertEqual(events[-1][1]["status"], 429)
        self.assertEqual(set(seen), {"Bearer access-one"})

    def test_refresh_writes_only_selected_account_once_across_instances(self):
        source = self.add("one", "2000-01-01T00:00:00Z")
        self.add("two")
        p1, _ = providers.resolve("antigravity@one/gemini-2.5-pro")
        p2 = ag.Antigravity(token_file=accounts.token_file("one"), project_id="project-one")
        reply = io.BytesIO(json.dumps({"access_token": "new-one", "refresh_token": "rotated-one", "expires_in": 3600}).encode())
        with patch.object(ag, "CLIENT_ID", "test"), patch.object(ag, "CLIENT_SECRET", "test"), patch.object(ag.urllib.request, "urlopen", return_value=reply) as refresh:
            with ThreadPoolExecutor(max_workers=2) as pool:
                tokens = list(pool.map(lambda p: p.token(), [p1, p2]))
        self.assertEqual(tokens, ["new-one", "new-one"])
        self.assertEqual(refresh.call_count, 1)
        with open(accounts.token_file("one")) as f:
            self.assertEqual(json.load(f)["refresh_token"], "rotated-one")
        with open(source) as f:
            self.assertEqual(json.load(f)["access_token"], "access-one")
        p, _ = providers.resolve("antigravity@two/gemini-2.5-pro")
        self.assertEqual(p.token(), "access-two")

    def test_named_account_never_refreshes_through_current_cli(self):
        self.add("one", "2000-01-01T00:00:00Z")
        p, _ = providers.resolve("antigravity@one/gemini-2.5-pro")
        with patch.object(ag, "CLIENT_ID", ""), patch.object(ag, "agy_bin") as current:
            p.token(force_refresh=True)
        current.assert_not_called()

    def test_missing_and_removed_names_do_not_fall_back(self):
        self.add("one")
        for model in ("antigravity@missing/gemini-2.5-pro", "antigravity@/gemini-2.5-pro", "anthropic@one/claude-sonnet", "antigravity@one/"):
            with self.assertRaises(providers.RouteError):
                providers.resolve(model)
        accounts.remove("one")
        with self.assertRaises(providers.RouteError):
            providers.resolve("antigravity@one/gemini-2.5-pro")

    def test_models_include_each_named_account_and_default(self):
        self.add("one")
        self.add("two")
        ids = {m["id"] for m in providers.list_models()}
        self.assertIn("antigravity/gemini-2.5-pro", ids)
        self.assertIn("antigravity@one/gemini-2.5-pro", ids)
        self.assertIn("antigravity@two/gemini-2.5-pro", ids)

    def test_corrupt_registry_fails_closed_without_overwriting(self):
        with open(accounts._path(), "w") as f:
            f.write('{broken')
        with self.assertRaises(ValueError):
            accounts.add("one", self.source("one"))
        with self.assertRaises(providers.RouteError):
            providers.resolve("antigravity/gemini-2.5-pro")
        with open(accounts._path()) as f:
            self.assertEqual(f.read(), '{broken')

    def test_failed_registry_write_rolls_back_import(self):
        real_write = accounts.atomic_json
        def fail(path, data):
            if path == accounts._path():
                raise OSError("disk full")
            return real_write(path, data)
        with patch.object(accounts, "atomic_json", side_effect=fail):
            with self.assertRaises(OSError):
                accounts.add("one", self.source("one"))
        self.assertFalse(os.path.exists(accounts.token_file("one")))
        self.assertFalse(accounts.load()["accounts"])


if __name__ == "__main__":
    unittest.main()
