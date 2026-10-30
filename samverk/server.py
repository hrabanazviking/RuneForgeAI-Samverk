"""The Samverk HTTP server skeleton (S-002).

Stdlib `http.server`, in the Samtal pattern: one threaded server, a
small explicit route table, JSON answers, and no stack traces or
internals ever sent to a client (error law, S-019 — adopted from the
first slice, not retrofitted).

Routes grow slice by slice; S-002 ships exactly one: the health route.

S-009 adds the HTTP security baseline at the door: every
state-changing method (POST/PUT/PATCH/DELETE) must present a valid
CSRF token bound to its session cookie *before* routing — a request
that fails the check is refused 403 and reaches no handler, so a
route added by a later slice inherits the protection by construction
and cannot forget it. Safe methods never require a token.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from . import __version__
from .config import Config
from .http_security import (
    CSRF_FORM_FIELD,
    CSRF_HEADER,
    build_clear_session_cookie,
    build_session_cookie,
    session_token_from_cookie_header,
    validate_csrf_token,
)
from .platform_seam import ensure_dir

# A CSRF check needs the form field at most; bodies beyond this are
# not read for the gate (payload size law is S-255's, the gate only
# refuses early). Reading is bounded so a hostile Content-Length
# cannot make the handler allocate without limit.
_CSRF_BODY_LIMIT = 64 * 1024


def _health_payload() -> dict:
    return {"status": "ok", "service": "samverk", "version": __version__}


class _Handler(BaseHTTPRequestHandler):
    server_version = "Samverk"
    # Silence the default stderr access log; logging is S-018's domain.
    def log_message(self, format: str, *args) -> None:  # noqa: A003
        pass

    @property
    def _cfg(self) -> Config:
        return self.server.samverk_config  # type: ignore[attr-defined]

    def _send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        pending = getattr(self, "_pending_cookie", None)
        if pending is not None:
            self.send_header("Set-Cookie", pending)
            self._pending_cookie = None
        self.end_headers()
        self.wfile.write(body)

    # -- S-009 cookie helpers (used by the auth slices of Part II) --

    def set_session_cookie(self, token: str) -> None:
        """Queue the baseline session cookie on the next response."""
        self._pending_cookie = build_session_cookie(
            token, secure=self._cfg.secure_cookies
        )

    def clear_session_cookie(self) -> None:
        self._pending_cookie = build_clear_session_cookie(
            secure=self._cfg.secure_cookies
        )

    # -- S-009 CSRF gate --

    def _submitted_csrf_token(self) -> str | None:
        header_token = self.headers.get(CSRF_HEADER)
        if header_token:
            return header_token
        content_type = (self.headers.get("Content-Type") or "")
        if not content_type.startswith("application/x-www-form-urlencoded"):
            return None
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        if length <= 0 or length > _CSRF_BODY_LIMIT:
            return None
        raw = self.rfile.read(length)
        try:
            form = parse_qs(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None
        values = form.get(CSRF_FORM_FIELD)
        return values[0] if values else None

    def _csrf_ok(self) -> bool:
        session_token = session_token_from_cookie_header(
            self.headers.get("Cookie")
        )
        if session_token is None:
            return False
        return validate_csrf_token(session_token, self._submitted_csrf_token())

    def _handle_state_changing(self) -> None:
        """The gate, then routing. Fails closed: no valid token bound
        to the caller's own session cookie means no handler runs."""
        if not self._csrf_ok():
            self._send_json(403, {"error": "csrf_failed"})
            return
        # No state-changing routes exist yet (Part II adds the first);
        # a request that passed the gate honestly reaches routing.
        self._send_json(404, {"error": "not_found"})

    do_POST = _handle_state_changing
    do_PUT = _handle_state_changing
    do_PATCH = _handle_state_changing
    do_DELETE = _handle_state_changing

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send_json(200, _health_payload())
        elif self.path == "/":
            self._send_json(200, {"service": "samverk", "version": __version__})
        else:
            self._send_json(404, {"error": "not_found"})


def make_server(cfg: Config) -> ThreadingHTTPServer:
    """Build (but do not start) the HTTP server for *cfg*."""
    ensure_dir(cfg.data_root)
    httpd = ThreadingHTTPServer((cfg.host, cfg.port), _Handler)
    httpd.samverk_config = cfg  # type: ignore[attr-defined]
    return httpd


def serve(cfg: Config) -> None:
    """Run the server in the foreground until interrupted.

    S-015's bind law is enforced before anything listens:
    non-loopback plaintext without TLS is refused unless the
    operator override is armed, and arming it is audit-logged
    (see tls_policy). When TLS is configured the listening
    socket is wrapped and the scheme is https.
    """
    from .tls_policy import enforce_with_audit, tls_configured

    posture = enforce_with_audit(cfg)
    httpd = make_server(cfg)
    scheme = "http"
    if tls_configured(cfg):
        import ssl

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(str(cfg.tls_cert_file), str(cfg.tls_key_file))
        httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
        scheme = "https"
    host, port = httpd.server_address[:2]
    print(f"samverk {__version__} listening on {scheme}://{host}:{port} "
          f"(data root: {cfg.data_root}, bind posture: {posture})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
