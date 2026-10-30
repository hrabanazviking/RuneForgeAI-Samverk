"""S-009 acceptance battery: HTTP security baseline.

Acceptance (roadmap S-009): HttpOnly/Secure/SameSite cookies, CSRF
tokens on state-changing forms — *a CSRF attack test fails closed.*

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk.config import Config, load_config
from samverk.http_security import (
    build_clear_session_cookie,
    build_session_cookie,
    issue_csrf_token,
    parse_cookie_header,
    validate_csrf_token,
)
from samverk.server import make_server

SESSION_TOKEN = "dGVzdC1zZXNzaW9uLXRva2VuLXdpdGgtZW5vdWdoLWVudHJvcHk"  # test only


class CookieTests(unittest.TestCase):
    def test_session_cookie_carries_the_baseline_flags(self):
        cookie = build_session_cookie(SESSION_TOKEN, secure=False)
        self.assertTrue(cookie.startswith(f"session={SESSION_TOKEN}"))
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertIn("Path=/", cookie)
        self.assertNotIn("Domain=", cookie)
        # Plain-HTTP dev serving must not claim Secure it cannot keep.
        self.assertNotIn("Secure", cookie)

    def test_secure_flag_present_when_operator_says_https(self):
        cookie = build_session_cookie(SESSION_TOKEN, secure=True)
        self.assertIn("Secure", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)

    def test_clear_cookie_expires_with_the_same_flags(self):
        cookie = build_clear_session_cookie(secure=True)
        self.assertTrue(cookie.startswith("session=;"))
        self.assertIn("Max-Age=0", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertIn("Secure", cookie)

    def test_cookie_value_injection_is_refused(self):
        for bad in ("", "a;b", "a\r\nSet-Cookie: evil=1", "a b", 'a"b'):
            with self.assertRaises(ValueError):
                build_session_cookie(bad, secure=False)

    def test_parse_cookie_header_is_tolerant(self):
        parsed = parse_cookie_header("session=abc123; theme=dark; broken; =x")
        self.assertEqual(parsed, {"session": "abc123", "theme": "dark"})
        self.assertEqual(parse_cookie_header(None), {})
        self.assertEqual(parse_cookie_header(""), {})

    def test_secure_cookies_config_from_env_and_file(self):
        cfg = load_config(config_path="/nonexistent/samverk.ini",
                          env={"SAMVERK_SECURE_COOKIES": "true"})
        self.assertTrue(cfg.secure_cookies)
        cfg = load_config(config_path="/nonexistent/samverk.ini", env={})
        self.assertFalse(cfg.secure_cookies)


class CsrfTokenTests(unittest.TestCase):
    def test_token_validates_for_its_own_session(self):
        token = issue_csrf_token(SESSION_TOKEN)
        self.assertTrue(validate_csrf_token(SESSION_TOKEN, token))

    def test_token_is_not_the_session_token_and_reveals_nothing(self):
        token = issue_csrf_token(SESSION_TOKEN)
        self.assertNotEqual(token, SESSION_TOKEN)
        self.assertNotIn(SESSION_TOKEN, token)

    def test_token_for_another_session_is_refused(self):
        foreign = issue_csrf_token("a-different-session-token")
        self.assertFalse(validate_csrf_token(SESSION_TOKEN, foreign))

    def test_missing_empty_and_tampered_tokens_fail_closed(self):
        token = issue_csrf_token(SESSION_TOKEN)
        self.assertFalse(validate_csrf_token(SESSION_TOKEN, None))
        self.assertFalse(validate_csrf_token(SESSION_TOKEN, ""))
        self.assertFalse(validate_csrf_token(None, token))
        self.assertFalse(validate_csrf_token("", token))
        tampered = ("A" if token[0] != "A" else "B") + token[1:]
        self.assertFalse(validate_csrf_token(SESSION_TOKEN, tampered))

    def test_session_rotation_invalidates_the_old_csrf_token(self):
        old = issue_csrf_token(SESSION_TOKEN)
        self.assertFalse(validate_csrf_token("rotated-session-token", old))


class ServerCsrfGateTests(unittest.TestCase):
    """The acceptance in its literal form, over real HTTP: a forged
    cross-site POST — a session cookie riding along, no (or a wrong)
    CSRF token — is refused at the gate and reaches no handler."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        cfg = Config(host="127.0.0.1", port=0, data_root=Path(self._td.name))
        self.httpd = make_server(cfg)
        self.port = self.httpd.server_address[1]
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._td.cleanup()

    def _request(self, method: str, path: str, *, cookie=None, headers=None,
                 data: bytes | None = None) -> int:
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data, method=method
        )
        if cookie is not None:
            req.add_header("Cookie", cookie)
        for name, value in (headers or {}).items():
            req.add_header(name, value)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status
        except urllib.error.HTTPError as e:
            return e.code

    def test_csrf_attack_without_token_fails_closed(self):
        status = self._request(
            "POST", "/anything", cookie=f"session={SESSION_TOKEN}", data=b"x=1"
        )
        self.assertEqual(status, 403)

    def test_csrf_attack_with_foreign_token_fails_closed(self):
        foreign = issue_csrf_token("attacker-known-session")
        status = self._request(
            "POST", "/anything",
            cookie=f"session={SESSION_TOKEN}",
            headers={"X-CSRF-Token": foreign}, data=b"x=1",
        )
        self.assertEqual(status, 403)

    def test_post_without_any_session_fails_closed(self):
        status = self._request("POST", "/anything", data=b"x=1")
        self.assertEqual(status, 403)

    def test_legitimate_post_with_header_token_passes_the_gate(self):
        token = issue_csrf_token(SESSION_TOKEN)
        status = self._request(
            "POST", "/anything",
            cookie=f"session={SESSION_TOKEN}",
            headers={"X-CSRF-Token": token}, data=b"x=1",
        )
        # No state-changing route exists yet: passing the gate means
        # routing answered 404, not the gate's 403.
        self.assertEqual(status, 404)

    def test_legitimate_post_with_form_token_passes_the_gate(self):
        token = issue_csrf_token(SESSION_TOKEN)
        body = f"csrf_token={urllib.parse.quote(token)}&x=1".encode()
        status = self._request(
            "POST", "/anything",
            cookie=f"session={SESSION_TOKEN}",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=body,
        )
        self.assertEqual(status, 404)

    def test_safe_methods_need_no_token(self):
        status = self._request("GET", "/healthz")
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
