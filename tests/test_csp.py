"""S-016 acceptance battery: Content Security Policy.

Acceptance (roadmap S-016): *CSP report-only period clean on all
core pages, then enforced.* In code: one canonical policy value
travels under either header name, the mode is the operator's
switch, and every response of the server's core pages carries it.

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import http.client
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk.config import Config
from samverk.csp import csp_header, policy_value
from samverk.server import make_server


class PolicyTests(unittest.TestCase):
    def test_policy_is_self_only_with_no_inline_anything(self):
        value = policy_value()
        self.assertNotIn("unsafe-inline", value)
        self.assertNotIn("unsafe-eval", value)
        self.assertNotIn("*", value)
        for directive in (
            "default-src 'self'", "script-src 'self'",
            "style-src 'self'", "img-src 'self'",
            "connect-src 'self'", "object-src 'none'",
            "frame-ancestors 'none'", "base-uri 'self'",
            "form-action 'self'",
        ):
            self.assertIn(directive, value)

    def test_modes_share_one_value_under_two_header_names(self):
        enforce_name, enforce_value = csp_header("enforce")
        report_name, report_value = csp_header("report-only")
        self.assertEqual(enforce_name, "Content-Security-Policy")
        self.assertEqual(
            report_name, "Content-Security-Policy-Report-Only")
        self.assertEqual(enforce_value, report_value)

    def test_unknown_mode_fails_loudly(self):
        with self.assertRaises(ValueError):
            csp_header("enforced-ish")


class ServerIntegrationTests(unittest.TestCase):
    def _serve(self, cfg: Config):
        httpd = make_server(cfg)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        return httpd.server_address[1]

    def _get(self, port: int, path: str, method: str = "GET"):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request(method, path)
        resp = conn.getresponse()
        resp.read()
        headers = {k.lower(): v for k, v in resp.getheaders()}
        conn.close()
        return resp.status, headers

    def test_every_core_response_carries_the_enforced_csp(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Config(host="127.0.0.1", port=0, data_root=Path(td))
            port = self._serve(cfg)
            expected = policy_value()
            for path, method in (("/healthz", "GET"), ("/", "GET"),
                                 ("/missing", "GET"),
                                 ("/healthz", "POST")):
                status, headers = self._get(port, path, method)
                self.assertEqual(
                    headers.get("content-security-policy"), expected,
                    msg=f"{method} {path} -> {status}")
                self.assertNotIn(
                    "content-security-policy-report-only", headers)

    def test_report_only_mode_uses_the_report_only_header(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Config(host="127.0.0.1", port=0, data_root=Path(td),
                         csp_mode="report-only")
            port = self._serve(cfg)
            _, headers = self._get(port, "/healthz")
            self.assertEqual(
                headers.get("content-security-policy-report-only"),
                policy_value())
            self.assertNotIn("content-security-policy", headers)


if __name__ == "__main__":
    unittest.main()
