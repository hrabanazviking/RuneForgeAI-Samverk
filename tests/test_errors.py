"""S-019 acceptance battery: error law.

Acceptance (roadmap S-019): no stack traces, paths, or secrets
to clients; opaque error ids correlate to server logs —
*error-shape tests.*

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import http.client
import io
import json
import logging
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk.config import Config
from samverk.errors import (
    PublicError,
    log_internal_error,
    new_error_id,
    public_error_body,
)
from samverk.log_redaction import RedactingFilter, clear_registered_secrets
from samverk.server import _Handler, make_server


class ShapeTests(unittest.TestCase):
    def test_error_body_is_exactly_code_and_id(self):
        body = public_error_body("not_found")
        self.assertEqual(set(body), {"error", "error_id"})
        self.assertEqual(body["error"], "not_found")
        self.assertEqual(len(body["error_id"]), 16)
        int(body["error_id"], 16)  # opaque hex, decodes as nothing else

    def test_ids_are_unique_and_unregistered_codes_raise(self):
        self.assertNotEqual(new_error_id(), new_error_id())
        with self.assertRaises(ValueError):
            public_error_body("some_invented_code")
        with self.assertRaises(ValueError):
            PublicError("some_invented_code", 400)

    def test_public_error_carries_only_what_is_safe(self):
        err = PublicError("unauthorized", 401)
        self.assertEqual((err.code, err.status), ("unauthorized", 401))


class LogCorrelationTests(unittest.TestCase):
    def tearDown(self):
        clear_registered_secrets()

    def test_log_carries_detail_under_the_id_and_redacted(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.addFilter(RedactingFilter())
        logger = logging.getLogger("samverk.error")
        old_level, old_propagate = logger.level, logger.propagate
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        try:
            try:
                raise RuntimeError("boom at /srv/samverk/x password=hunter2-x")
            except RuntimeError as exc:
                log_internal_error("deadbeefcafef00d", exc)
        finally:
            logger.removeHandler(handler)
            logger.setLevel(old_level)
            logger.propagate = old_propagate
        out = stream.getvalue()
        self.assertIn("deadbeefcafef00d", out)     # correlation id
        self.assertIn("RuntimeError", out)          # full detail server-side
        self.assertIn("/srv/samverk/x", out)        # paths are fine *here*
        self.assertNotIn("hunter2-x", out)          # secrets are not


class ServerShapeTests(unittest.TestCase):
    def _serve(self) -> int:
        httpd = make_server(Config(host="127.0.0.1", port=0,
                                   data_root=Path(self._td.name)))
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        return httpd.server_address[1]

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)

    def _request(self, port: int, method: str, path: str):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request(method, path)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        return resp.status, json.loads(raw) if raw else {}

    def test_404_and_403_bodies_follow_the_law(self):
        port = self._serve()
        status, body = self._request(port, "GET", "/missing")
        self.assertEqual(status, 404)
        self.assertEqual(set(body), {"error", "error_id"})
        self.assertEqual(body["error"], "not_found")
        status, body = self._request(port, "POST", "/healthz")
        self.assertEqual(status, 403)
        self.assertEqual(set(body), {"error", "error_id"})
        self.assertEqual(body["error"], "csrf_failed")

    def test_unknown_method_gets_the_json_shape_not_html(self):
        port = self._serve()
        status, body = self._request(port, "BREW", "/healthz")
        self.assertEqual(status, 501)
        self.assertEqual(body["error"], "method_not_allowed")
        self.assertEqual(set(body), {"error", "error_id"})

    def test_unexpected_failure_is_an_opaque_500(self):
        """A handler that blows up leaks nothing: the body is the
        law's shape, and neither the exception, its message, nor
        a traceback appears in it."""
        port = self._serve()
        original = _Handler._route_get

        def boom(self):
            raise RuntimeError("secret path /srv/samverk/x password=hunter2-x")

        _Handler._route_get = boom
        self.addCleanup(setattr, _Handler, "_route_get", original)
        status, body = self._request(port, "GET", "/healthz")
        self.assertEqual(status, 500)
        self.assertEqual(set(body), {"error", "error_id"})
        self.assertEqual(body["error"], "internal")
        rendered = json.dumps(body)
        for leaked in ("hunter2", "/srv", "RuntimeError", "Traceback"):
            self.assertNotIn(leaked, rendered)


if __name__ == "__main__":
    unittest.main()
