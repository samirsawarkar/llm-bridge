import json, os, sys, tempfile, threading, unittest, urllib.error, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))
os.environ["LLM_BRIDGE_HOME"] = tempfile.mkdtemp()
from http.server import ThreadingHTTPServer
from llm_bridge import providers, server, store
from llm_bridge.providers.base import Provider


class Fake(Provider):
    name, native_fmt, prefixes, catalog, aliases = "fake", None, ("fake-",), [{"id": "fake-1", "name": "Fake"}], {}
    def _load(self):
        return {"access": "t", "refresh": None, "expires_at": 9e9}
    def stream(self, request, model):
        self.last = request
        yield ("text", "ok:" + model)
        yield ("usage", {"prompt_tokens": 1, "completion_tokens": 1})
        yield ("finish", "stop")


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        providers.PROVIDERS["fake"] = cls.fake = Fake()
        cls.key = store.create_key("t")
        server.Handler.cfg = {"default_provider": None}
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def call(self, path, body=None, key=None, headers=None):
        h = {"Content-Type": "application/json"}
        if key is not False:
            h["Authorization"] = "Bearer " + (key or self.key)
        h.update(headers or {})
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_health_and_auth(self):
        self.assertEqual(self.call("/health", key=False)[0], 200)
        s, b = self.call("/v1/models", key="sk-lb-bad")
        self.assertEqual((s, json.loads(b)["error"]["type"]), (401, "authentication_error"))
        s, b = self.call("/v1/messages", {"model": "fake-1", "messages": []}, key=False)
        self.assertEqual((s, json.loads(b)["type"]), (401, "error"))  # anthropic-shaped error
        s, b = self.call("/v1/messages", {"model": "fake-1", "messages": [{"role": "user", "content": "x"}], "max_tokens": 5}, key=False, headers={"x-api-key": self.key})
        self.assertEqual(s, 200)

    def test_models(self):
        s, b = self.call("/v1/models")
        self.assertIn("fake/fake-1", [m["id"] for m in json.loads(b)["data"]])

    def test_chat_nonstream_and_stream(self):
        s, b = self.call("/v1/chat/completions", {"model": "fake/fake-1", "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual((s, json.loads(b)["choices"][0]["message"]["content"]), (200, "ok:fake-1"))
        s, b = self.call("/v1/chat/completions", {"model": "fake-1", "stream": True, "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(s, 200)
        self.assertTrue(b.endswith(b"data: [DONE]\n\n"))
        self.assertIn(b'"content": "ok:fake-1"', b)

    def test_routing_errors(self):
        s, b = self.call("/v1/chat/completions", {"model": "unknown-thing", "messages": []})
        self.assertEqual(s, 400)
        self.assertIn("provider/model", json.loads(b)["error"]["message"])
        s, b = self.call("/v1/chat/completions", {"model": "fake/x", "messages": []}, headers={"Content-Type": "text/plain"})
        self.assertEqual(s, 200)  # content-type is not enforced, body was valid JSON
        req = urllib.request.Request(self.base + "/v1/chat/completions", data=b"{bad", headers={"Authorization": "Bearer " + self.key})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(cm.exception.code, 400)
        cm.exception.close()

    def test_other_formats(self):
        s, b = self.call("/v1/messages", {"model": "fake-1", "max_tokens": 5, "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual((s, json.loads(b)["content"][0]["text"]), (200, "ok:fake-1"))
        s, b = self.call("/v1/responses", {"model": "fake-1", "input": "hi"})
        self.assertEqual((s, json.loads(b)["output"][0]["content"][0]["text"]), (200, "ok:fake-1"))


if __name__ == "__main__":
    unittest.main()
