"""S-015 acceptance battery: TLS and secure defaults.

Acceptance (roadmap S-015): *config refuses plaintext HTTP
outside loopback without an explicit operator override that is
audit-logged.*

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk.audit import AuditLog, verify_chain
from samverk.config import Config, load_config
from samverk.db import init_db
from samverk.server import serve
from samverk.tls_policy import (
    BindRefused,
    enforce_bind_policy,
    is_loopback_host,
)


def _cfg(tmp: str, **kw) -> Config:
    cfg = Config(data_root=Path(tmp))
    for key, value in kw.items():
        setattr(cfg, key, value)
    return cfg


class LoopbackTests(unittest.TestCase):
    def test_loopback_hosts_are_recognised_literally(self):
        for host in ("127.0.0.1", "127.0.0.53", "localhost",
                     "LOCALHOST", "::1"):
            self.assertTrue(is_loopback_host(host), msg=host)
        for host in ("0.0.0.0", "::", "", "192.168.1.5", "10.0.0.2",
                     "samverk.example", "localhost.evil.example"):
            self.assertFalse(is_loopback_host(host), msg=host)

    def test_loopback_plaintext_needs_no_override(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(
                enforce_bind_policy(_cfg(td, host="127.0.0.1")),
                "loopback")


class RefusalTests(unittest.TestCase):
    def test_non_loopback_plaintext_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            for host in ("0.0.0.0", "192.168.1.5"):
                with self.assertRaises(BindRefused) as caught:
                    enforce_bind_policy(_cfg(td, host=host))
                self.assertEqual(
                    caught.exception.reason, "plaintext_outside_loopback")

    def test_serve_refuses_before_listening(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(BindRefused):
                serve(_cfg(td, host="0.0.0.0", port=0))

    def test_half_configured_tls_is_refused_everywhere(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(BindRefused) as caught:
                enforce_bind_policy(
                    _cfg(td, host="127.0.0.1",
                         tls_cert_file=Path(td) / "cert.pem"))
            self.assertEqual(caught.exception.reason, "tls_half_configured")


class TlsPostureTests(unittest.TestCase):
    def test_tls_posture_passes_and_secures_cookies(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = _cfg(td, host="0.0.0.0",
                       tls_cert_file=Path(td) / "cert.pem",
                       tls_key_file=Path(td) / "key.pem")
            self.assertFalse(cfg.secure_cookies)
            self.assertEqual(enforce_bind_policy(cfg), "tls")
            self.assertTrue(cfg.secure_cookies)


class OverrideTests(unittest.TestCase):
    def test_override_without_an_audit_log_does_not_exist(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = _cfg(td, host="0.0.0.0", allow_plaintext_http=True)
            with self.assertRaises(BindRefused) as caught:
                enforce_bind_policy(cfg)
            self.assertEqual(
                caught.exception.reason, "override_requires_audit")

    def test_override_is_audit_logged_exactly_once(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = _cfg(td, host="0.0.0.0", allow_plaintext_http=True)
            conn = init_db(cfg.db_path)
            try:
                posture = enforce_bind_policy(cfg, audit=AuditLog(conn))
                self.assertEqual(posture, "override")
                rows = conn.execute(
                    "SELECT action, target_id, outcome FROM audit_log"
                ).fetchall()
                self.assertEqual(len(rows), 1)
                self.assertEqual(
                    rows[0]["action"], "admin.plaintext_http_override")
                self.assertEqual(rows[0]["target_id"], "0.0.0.0:8737")
                ok, bad, count = verify_chain(conn)
                self.assertTrue(ok, msg=f"chain broken at {bad}")
                self.assertEqual(count, 1)
            finally:
                conn.close()


class ConfigWiringTests(unittest.TestCase):
    def test_tls_and_override_settings_load_from_env(self):
        cfg = load_config(env={
            "SAMVERK_TLS_CERT_FILE": "/srv/samverk/cert.pem",
            "SAMVERK_TLS_KEY_FILE": "/srv/samverk/key.pem",
            "SAMVERK_ALLOW_PLAINTEXT_HTTP": "true",
        })
        self.assertEqual(cfg.tls_cert_file, Path("/srv/samverk/cert.pem"))
        self.assertEqual(cfg.tls_key_file, Path("/srv/samverk/key.pem"))
        self.assertTrue(cfg.allow_plaintext_http)


if __name__ == "__main__":
    unittest.main()
