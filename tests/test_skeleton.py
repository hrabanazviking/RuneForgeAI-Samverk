"""S-002 acceptance battery: project skeleton.

Acceptance (roadmap S-002): `samverk serve` on a bare checkout answers
a health route; config loads; the skeleton is not platform-locked
(platform touchpoints exist only behind the platform seam).

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk import platform_seam
from samverk.config import Config, load_config
from samverk.server import make_server


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get(url: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


class ConfigTests(unittest.TestCase):
    def test_defaults_without_file_or_env(self):
        cfg = load_config(config_path="/nonexistent/samverk.ini", env={})
        self.assertEqual(cfg.host, "127.0.0.1")
        self.assertEqual(cfg.port, 8737)
        self.assertTrue(cfg.data_root.is_absolute())
        self.assertEqual(cfg.db_path, cfg.data_root / "samverk.db")

    def test_config_file_honoured(self):
        with tempfile.TemporaryDirectory() as td:
            ini = Path(td) / "samverk.ini"
            ini.write_text("[samverk]\nhost = 0.0.0.0\nport = 9999\n", encoding="utf-8")
            cfg = load_config(config_path=ini, env={})
            self.assertEqual(cfg.host, "0.0.0.0")
            self.assertEqual(cfg.port, 9999)

    def test_env_beats_file(self):
        with tempfile.TemporaryDirectory() as td:
            ini = Path(td) / "samverk.ini"
            ini.write_text("[samverk]\nport = 9999\n", encoding="utf-8")
            cfg = load_config(config_path=ini, env={"SAMVERK_PORT": "7777"})
            self.assertEqual(cfg.port, 7777)


class PlatformSeamTests(unittest.TestCase):
    def test_os_name_is_a_known_family(self):
        self.assertIn(platform_seam.os_name(), {"linux", "windows", "macos"})

    def test_machine_reported(self):
        self.assertTrue(platform_seam.machine())

    def test_default_data_root_is_absolute(self):
        self.assertTrue(platform_seam.data_root_default().is_absolute())

    def test_no_platform_reads_outside_the_seam(self):
        """The seam law, checked mechanically: no other samverk module
        may touch sys.platform directly."""
        pkg = Path(platform_seam.__file__).parent
        offenders = []
        for py in pkg.glob("*.py"):
            if py.name == "platform_seam.py":
                continue
            if "sys.platform" in py.read_text(encoding="utf-8"):
                offenders.append(py.name)
        self.assertEqual(offenders, [])


class ServerTests(unittest.TestCase):
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

    def test_health_route(self):
        status, payload = _get(f"http://127.0.0.1:{self.port}/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["service"], "samverk")

    def test_unknown_route_is_a_clean_404(self):
        status, payload = _get(f"http://127.0.0.1:{self.port}/no-such-route")
        self.assertEqual(status, 404)
        self.assertEqual(payload, {"error": "not_found"})


class ServeSubprocessTests(unittest.TestCase):
    def test_samverk_serve_answers_health_route(self):
        """The S-002 acceptance in its literal form: the `serve`
        command, run as a fresh process on a bare checkout, answers
        the health route."""
        port = _free_port()
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ)
            env["SAMVERK_DATA_ROOT"] = td
            env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
            proc = subprocess.Popen(
                [sys.executable, "-m", "samverk", "serve",
                 "--host", "127.0.0.1", "--port", str(port)],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
            )
            try:
                payload = None
                for _ in range(50):
                    try:
                        status, payload = _get(f"http://127.0.0.1:{port}/healthz")
                        if status == 200:
                            break
                    except Exception:
                        pass
                    if proc.poll() is not None:
                        out = proc.stdout.read().decode("utf-8", "replace")
                        self.fail(f"serve exited early ({proc.returncode}): {out}")
                    threading.Event().wait(0.2)
                self.assertIsNotNone(payload)
                self.assertEqual(payload["status"], "ok")
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                if proc.stdout is not None:
                    proc.stdout.close()


if __name__ == "__main__":
    unittest.main()
