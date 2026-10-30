"""S-022: security battery v1.

Acceptance (roadmap S-022): *auth bypass, IDOR, and injection
attempts as an automated suite; suite green, failures named
honestly.*

This battery attacks the *assembled* Part I system — the real
HTTP server, the real session store, the real path/subprocess/
escaping seams — the way an adversary would, rather than
re-testing each unit's internals (the per-slice batteries did
that; some headline attacks are deliberately re-proven here at
system level).

Named honestly — what v1 cannot yet attack, because it does not
exist yet: there are no authenticated routes, accounts, or
per-user resources in Part I, so classic IDOR (asking for
*another user's* object by id) has no surface to strike. The
identifier-manipulation class below strikes the identifier
surfaces that *do* exist (repository names, URL paths, session
identifiers). Part II's gate (S-048) inherits this file; the
IDOR class grows teeth the moment routes carry owners.

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk.audit import AuditLog, verify_chain
from samverk.config import Config
from samverk.db import init_db
from samverk.escaping import escape_html_attr, escape_html_text, safe_url
from samverk.http_security import (
    build_session_cookie,
    issue_csrf_token,
    validate_csrf_token,
)
from samverk.proc import ProcRefused, run_git
from samverk.repo_paths import RepoPathError, repo_path
from samverk.server import make_server
from samverk.sessions import SessionStore


class _ServerMixin(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        cfg = Config(host="127.0.0.1", port=0,
                     data_root=Path(self._td.name))
        self.httpd = make_server(cfg)
        thread = threading.Thread(
            target=self.httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.httpd.shutdown)
        self.addCleanup(self.httpd.server_close)
        self.port = self.httpd.server_address[1]

    def request(self, method: str, path: str, headers=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        return resp.status, raw


class AuthBypassBattery(_ServerMixin):
    def test_fabricated_session_cookie_buys_nothing(self):
        """A made-up session token, with the CSRF token correctly
        computed *for that forgery*, passes the CSRF gate by
        construction (the gate binds CSRF to the presented
        session) — and buys exactly nothing: no handler exists
        for it to reach (404), and the session store refuses the
        fabricated token outright. Authentication is the store's
        verdict, never the cookie's mere presence. The gate's own
        teeth are the cross-site case, next."""
        forged = "f" * 64
        csrf = issue_csrf_token(forged)
        status, raw = self.request(
            "POST", "/account/delete",
            headers={"Cookie": f"session={forged}",
                     "X-CSRF-Token": csrf})
        self.assertEqual(status, 404)  # no route exists to reach
        conn = init_db(Path(self._td.name) / "samverk.db")
        try:
            self.assertIsNone(SessionStore(conn).authenticate(forged))
        finally:
            conn.close()

    def test_cross_site_post_without_csrf_is_refused(self):
        """The classic CSRF shape: a real session cookie rides
        along (as a browser would send it cross-site), but no
        token the attacker could know is presented."""
        conn = init_db(Path(self._td.name) / "samverk.db")
        try:
            token = SessionStore(conn).create(user_id=1)
        finally:
            conn.close()
        for headers in (
            {"Cookie": f"session={token}"},  # no CSRF at all
            {"Cookie": f"session={token}",
             "X-CSRF-Token": issue_csrf_token("attacker-guess")},
            {"Cookie": f"session={token}",
             "X-CSRF-Token": issue_csrf_token(token)[::-1]},
        ):
            status, _ = self.request("POST", "/anything", headers=headers)
            self.assertEqual(status, 403, msg=str(headers))

    def test_stolen_database_values_are_not_credentials(self):
        """DB-leak drill at system level: everything in the
        sessions table, presented back, authenticates no one."""
        conn = init_db(Path(self._td.name) / "samverk.db")
        try:
            store = SessionStore(conn)
            token = store.create(user_id=7)
            stolen_hash = conn.execute(
                "SELECT token_hash FROM sessions").fetchone()[0]
            self.assertIsNone(store.authenticate(stolen_hash))
            self.assertFalse(validate_csrf_token(stolen_hash, stolen_hash))
            self.assertEqual(store.authenticate(token), 7)
            store.revoke(token)
            self.assertIsNone(store.authenticate(token))
        finally:
            conn.close()


class InjectionBattery(_ServerMixin):
    def test_sql_injection_is_stored_as_data_never_executed(self):
        conn = init_db(Path(self._td.name) / "samverk.db")
        try:
            log = AuditLog(conn)
            payload = "x'); DROP TABLE audit_log; --"
            log.append(actor_kind="user", actor_id=1,
                       action="auth.login.failure", target_kind="user",
                       target_id=payload, outcome="failure",
                       detail={"note": "' OR 1=1 --"})
            rows = conn.execute(
                "SELECT COUNT(*) FROM audit_log").fetchone()[0]
            self.assertEqual(rows, 1)  # the table, un-dropped, holds it
            ok, bad, _ = verify_chain(conn)
            self.assertTrue(ok, msg=f"chain broken at {bad}")
            with self.assertRaises(ValueError):
                log.append(actor_kind="user",
                           action="auth.login.failure' OR '1'='1",
                           target_kind="user", outcome="failure")
        finally:
            conn.close()

    def test_shell_injection_through_git_args_creates_nothing(self):
        marker = Path(self._td.name) / "pwned"
        for payload in (f"; touch {marker}", f"$(touch {marker})",
                        f"HEAD && touch {marker}"):
            done = run_git(["rev-parse", payload])
            self.assertNotEqual(done.returncode, 0, msg=payload)
        self.assertFalse(marker.exists())
        with self.assertRaises(ProcRefused):
            run_git(["--upload-pack=touch " + str(marker), "x"])

    def test_header_injection_through_cookie_value_is_refused(self):
        with self.assertRaises(ValueError):
            build_session_cookie("ok\r\nSet-Cookie: evil=1", secure=False)
        with self.assertRaises(ValueError):
            build_session_cookie("a;b", secure=False)


class IdentifierManipulationBattery(_ServerMixin):
    """IDOR's Part I surface: identifiers an attacker controls —
    repository names, URL paths — must never resolve outside
    their owner's ground."""

    def test_traversal_names_never_leave_the_repos_root(self):
        root = Path(self._td.name)
        for owner, repo in (("..", "x"), ("victim", ".."),
                            ("victim", "../victim2"),
                            ("a/b", "x"), ("victim", "/etc/passwd")):
            with self.assertRaises(RepoPathError, msg=f"{owner}/{repo}"):
                repo_path(root, owner, repo)

    def test_url_encoded_traversal_reaches_no_file(self):
        for path in ("/%2e%2e/%2e%2e/etc/passwd",
                     "/repos/../../samverk.db",
                     "/..%2f..%2fsamverk.db"):
            status, raw = self.request("GET", path)
            self.assertEqual(status, 404, msg=path)
            self.assertNotIn(b"root:", raw)


class StoredPayloadBattery(unittest.TestCase):
    PAYLOADS = (
        "<script>alert(1)</script>",
        '"><img src=x onerror=alert(1)>',
        "'; DROP TABLE users; --",
        "javascript:alert(1)",
    )

    def test_stored_payloads_render_inert(self):
        for payload in self.PAYLOADS:
            rendered = escape_html_text(payload)
            self.assertNotIn("<script>", rendered, msg=payload)
            self.assertNotIn("<img", rendered, msg=payload)
            attr = escape_html_attr(payload)
            self.assertNotIn('">', attr, msg=payload)
        self.assertIsNone(safe_url("javascript:alert(1)"))
        self.assertIsNone(safe_url("&#106;avascript:alert(1)"))


if __name__ == "__main__":
    unittest.main()
