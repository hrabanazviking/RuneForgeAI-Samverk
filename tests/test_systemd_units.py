"""S-348 battery: the systemd units in deploy/systemd/.

The units are deployment data, so this battery reads them as data and
proves: the files exist and parse as unit files; each names an entry
point that actually exists in the code (the server's serve subcommand,
the two batch workers' module mains, each with its real argument
shape); the hardening baseline is set on every service; logging goes
to the journal; the timers point at the workers; and the install
script installs exactly the shipped units without enabling anything
unless the operator passes --enable. Where systemd-analyze exists,
its verify verdict over the shipped units is part of the battery.
"""
from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEPLOY = ROOT / "deploy" / "systemd"
SERVICES = ("samverk-server.service", "samverk-webhook-worker.service",
            "samverk-digest-worker.service")
TIMERS = ("samverk-webhook-worker.timer", "samverk-digest-worker.timer")
HARDENING = ("NoNewPrivileges=true", "PrivateTmp=true",
             "ProtectSystem=strict", "ReadWritePaths=/var/lib/samverk",
             "ProtectHome=true", "ProtectKernelTunables=true",
             "ProtectKernelModules=true", "ProtectControlGroups=true",
             "RestrictSUIDSGID=true", "LockPersonality=true",
             "PrivateDevices=true", "CapabilityBoundingSet=")


def _text(name: str) -> str:
    return (DEPLOY / name).read_text(encoding="utf-8")


def _directives(name: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for line in _text(name).splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "[")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out.setdefault(key.strip(), []).append(value.strip())
    return out


class TestUnitFilesExist(unittest.TestCase):
    def test_all_units_and_support_files_ship(self):
        for name in SERVICES + TIMERS + ("install.sh", "verify.sh",
                                         "samverk.ini.example"):
            self.assertTrue((DEPLOY / name).is_file(), name)

    def test_every_service_has_unit_service_install_shape(self):
        for name in SERVICES:
            text = _text(name)
            for section in ("[Unit]", "[Service]"):
                self.assertIn(section, text, name)
            d = _directives(name)
            self.assertEqual(d["User"], ["samverk"], name)
            self.assertEqual(d["Group"], ["samverk"], name)
            self.assertIn("ExecStart", d, name)

    def test_server_is_the_long_running_install_unit(self):
        d = _directives("samverk-server.service")
        self.assertEqual(d["Type"], ["simple"])
        self.assertEqual(d["Restart"], ["on-failure"])
        text = _text("samverk-server.service")
        self.assertIn("[Install]", text)
        self.assertIn("WantedBy=multi-user.target", text)


class TestEntryPointsAreReal(unittest.TestCase):
    def test_server_execstart_is_the_real_serve_subcommand(self):
        d = _directives("samverk-server.service")
        self.assertEqual(d["ExecStart"], [
            "/usr/bin/python3 -m samverk serve "
            "--config /etc/samverk/samverk.ini"])
        # The named entry exists: __main__ delegates to cli.main, the
        # parser owns a serve subcommand, server.serve is callable.
        from samverk import cli, server
        parser = cli.build_parser()
        args = parser.parse_args(["serve"])
        self.assertEqual(args.command, "serve")
        self.assertTrue(callable(server.serve))
        self.assertTrue(callable(server.make_server))
        main_text = (ROOT / "samverk" / "__main__.py").read_text(
            encoding="utf-8")
        self.assertIn("from .cli import main", main_text)

    def test_worker_execstarts_match_the_modules_own_usage(self):
        import importlib
        cases = {
            "samverk-webhook-worker.service": "samverk.webhook_delivery",
            "samverk-digest-worker.service": "samverk.digest_job",
        }
        for unit, module_name in cases.items():
            d = _directives(unit)
            self.assertEqual(d["ExecStart"], [
                f"/usr/bin/python3 -m {module_name} "
                "/var/lib/samverk/samverk.db /var/lib/samverk"], unit)
            self.assertEqual(d["Type"], ["oneshot"], unit)
            module = importlib.import_module(module_name)
            self.assertTrue(callable(module.main), module_name)
            source = Path(module.__file__).read_text(encoding="utf-8")
            self.assertIn('if __name__ == "__main__":', source)
            # Each module's own usage line names the same two args.
            self.assertIn("<db-path> <repos-root>", source, module_name)

    def test_worker_db_path_is_the_config_db_path(self):
        # Config.db_path is <data_root>/samverk.db; the shipped example
        # config sets data_root=/var/lib/samverk, so the workers' db
        # argument must be /var/lib/samverk/samverk.db.
        from samverk.config import Config
        cfg = Config(data_root=Path("/var/lib/samverk"))
        self.assertEqual(cfg.db_path, Path("/var/lib/samverk/samverk.db"))
        example = _text("samverk.ini.example")
        self.assertIn("data_root = /var/lib/samverk", example)
        self.assertIn("port = 8737", example)


class TestHardeningAndLogging(unittest.TestCase):
    def test_hardening_baseline_on_every_service(self):
        for name in SERVICES:
            text = _text(name)
            for directive in HARDENING:
                self.assertIn(directive, text, f"{name}: {directive}")

    def test_address_families_tightened_per_unit(self):
        self.assertIn("RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
                      _text("samverk-server.service"))
        self.assertIn("RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
                      _text("samverk-webhook-worker.service"))
        # The digest worker sends nothing: unix sockets only.
        self.assertIn("RestrictAddressFamilies=AF_UNIX\n",
                      _text("samverk-digest-worker.service"))

    def test_no_unit_claims_memory_deny_write_execute(self):
        # Deliberate omission, reasoned in docs/SYSTEMD_UNITS.md.
        for name in SERVICES:
            self.assertNotIn("MemoryDenyWriteExecute", _text(name), name)

    def test_journal_logging_on_every_service(self):
        for name in SERVICES:
            d = _directives(name)
            self.assertEqual(d["StandardOutput"], ["journal"], name)
            self.assertEqual(d["StandardError"], ["journal"], name)
            self.assertEqual(len(d["SyslogIdentifier"]), 1, name)

    def test_no_docker_no_shell_no_root_anywhere(self):
        for name in SERVICES + TIMERS:
            text = _text(name).lower()
            self.assertNotIn("docker", text, name)
            self.assertNotIn("user=root", text, name)
            self.assertNotIn("/bin/sh", text, name)
            self.assertNotIn("/bin/bash", text, name)


class TestTimers(unittest.TestCase):
    def test_timers_point_at_their_workers(self):
        pairs = {"samverk-webhook-worker.timer":
                 "samverk-webhook-worker.service",
                 "samverk-digest-worker.timer":
                 "samverk-digest-worker.service"}
        for timer, service in pairs.items():
            d = _directives(timer)
            self.assertEqual(d["Unit"], [service], timer)
            self.assertIn("WantedBy=timers.target", _text(timer), timer)
            self.assertEqual(d["Persistent"], ["true"], timer)

    def test_timer_cadences(self):
        self.assertIn("OnUnitActiveSec=1min",
                      _text("samverk-webhook-worker.timer"))
        self.assertIn("OnCalendar=Mon 06:00",
                      _text("samverk-digest-worker.timer"))


class TestInstallPath(unittest.TestCase):
    def test_install_script_installs_exactly_the_shipped_units(self):
        script = _text("install.sh")
        for name in SERVICES + TIMERS:
            self.assertIn(name, script)
        self.assertIn("systemctl daemon-reload", script)
        self.assertIn("systemd-analyze verify", script)
        self.assertIn("useradd", script)
        self.assertIn("/etc/systemd/system/", script)
        # Enabling is the operator's explicit word, never the default.
        self.assertIn('"${1:-}" = "--enable"', script)
        code_only = "\n".join(line for line in script.splitlines()
                              if not line.lstrip().startswith("#"))
        self.assertNotIn("docker", code_only.lower())

    def test_verify_script_verifies_without_installing(self):
        script = _text("verify.sh")
        self.assertIn("systemd-analyze verify", script)
        self.assertNotIn("systemctl", script.replace(
            "systemd-analyze", ""))

    def test_docs_name_every_unit_and_the_pi_remainder(self):
        doc = (ROOT / "docs" / "SYSTEMD_UNITS.md").read_text(
            encoding="utf-8")
        for name in SERVICES + TIMERS:
            self.assertIn(name, doc)
        self.assertIn("NOT tested", doc)  # the Debian/Pi leg, honestly
        self.assertIn("journalctl -u samverk-server", doc)


@unittest.skipUnless(shutil.which("systemd-analyze"),
                     "systemd-analyze not available on this host")
class TestSystemdAnalyzeVerify(unittest.TestCase):
    def test_shipped_service_units_verify_clean(self):
        for name in SERVICES:
            proc = subprocess.run(
                ["systemd-analyze", "verify", str(DEPLOY / name)],
                capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 0,
                             f"{name}: {proc.stdout} {proc.stderr}")
            self.assertNotIn(name, proc.stderr)


if __name__ == "__main__":
    unittest.main()
