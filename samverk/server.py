"""The Samverk HTTP server skeleton (S-002).

Stdlib `http.server`, in the Samtal pattern: one threaded server, a
small explicit route table, JSON answers, and no stack traces or
internals ever sent to a client (error law, S-019 — adopted from the
first slice, not retrofitted).

Routes grow slice by slice; S-002 ships exactly one: the health route.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__
from .config import Config
from .platform_seam import ensure_dir


def _health_payload() -> dict:
    return {"status": "ok", "service": "samverk", "version": __version__}


class _Handler(BaseHTTPRequestHandler):
    server_version = "Samverk"
    # Silence the default stderr access log; logging is S-018's domain.
    def log_message(self, format: str, *args) -> None:  # noqa: A003
        pass

    def _send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
    return ThreadingHTTPServer((cfg.host, cfg.port), _Handler)


def serve(cfg: Config) -> None:
    """Run the server in the foreground until interrupted."""
    httpd = make_server(cfg)
    host, port = httpd.server_address[:2]
    print(f"samverk {__version__} listening on http://{host}:{port} "
          f"(data root: {cfg.data_root})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
