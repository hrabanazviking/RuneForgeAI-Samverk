"""S-346 battery: configuration -- one config file
(documented key by key), environment overrides,
config check command that explains errors in
plain words."""
import tempfile
import unittest
from pathlib import Path

from samverk.configuration import (
    KEY_SPECS, SPECS_BY_KEY, ConfigurationService,
    audit_configuration, check_configuration,
    example_config_text, format_check_report,
    parse_config_text, render_configuration_page,
    validate_value)
from samverk.config import load_config
from samverk.db import init_db


def write_ini(text):
    td = tempfile.TemporaryDirectory()
    p = Path(td.name) / "samverk.ini"
    p.write_text(text, encoding="utf-8")
    return td, p


class KeySetTests(unittest.TestCase):
    def test_ten_keys_documented(self):
        self.assertEqual(len(KEY_SPECS), 10)
        for spec in KEY_SPECS:
            self.assertTrue(spec.summary)
            self.assertTrue(spec.example)
            self.assertTrue(spec.env_var.startswith("SAMVERK_"))

    def test_docs_carry_every_key(self):
        docs = (Path(__file__).parent.parent / "docs"
                / "CONFIGURATION.md").read_text(encoding="utf-8")
        for spec in KEY_SPECS:
            self.assertIn(f"`{spec.key}`", docs)
            self.assertIn(f"`{spec.env_var}`", docs)

    def test_example_round_trips_clean(self):
        td, p = write_ini(example_config_text())
        self.addCleanup(td.cleanup)
        check = check_configuration(config_path=p, env={})
        self.assertTrue(check.ok, check.problems)


class ValidateTests(unittest.TestCase):
    def test_bad_port_plain_words(self):
        value, problem = validate_value(
            SPECS_BY_KEY["port"], "abc", "config file")
        self.assertIsNone(value)
        self.assertIn("port", problem.words)
        self.assertIn("not a whole number", problem.words)
        self.assertIn("8737", problem.words)

    def test_port_range(self):
        _, problem = validate_value(
            SPECS_BY_KEY["port"], "70000", "environment")
        self.assertIn("outside the port range", problem.words)

    def test_bad_bool_and_level_and_csp(self):
        for key, raw in (("secure_cookies", "maybe"),
                         ("log_level", "LOUD"),
                         ("csp_mode", "strict")):
            _, problem = validate_value(
                SPECS_BY_KEY[key], raw, "environment")
            self.assertIsNotNone(problem, key)
            self.assertIn(key, problem.words)

    def test_good_values_convert(self):
        self.assertEqual(validate_value(
            SPECS_BY_KEY["port"], "8737", "config file"), (8737, None))
        self.assertEqual(validate_value(
            SPECS_BY_KEY["secure_cookies"], "yes", "config file"),
            (True, None))
        self.assertEqual(validate_value(
            SPECS_BY_KEY["log_level"], "debug", "environment"),
            ("DEBUG", None))


class ParseTests(unittest.TestCase):
    def test_unknown_key_named(self):
        _, problems = parse_config_text("[samverk]\nprot = 1\n")
        self.assertEqual(len(problems), 1)
        self.assertIn("prot", problems[0].words)
        self.assertIn("not a Samverk setting", problems[0].words)

    def test_unknown_section_named(self):
        _, problems = parse_config_text("[other]\nx = 1\n")
        self.assertEqual(len(problems), 1)
        self.assertIn("[other]", problems[0].words)

    def test_syntax_error_plain(self):
        _, problems = parse_config_text("not an ini at all\n")
        self.assertEqual(len(problems), 1)
        self.assertIn("[samverk]", problems[0].words)


class CheckTests(unittest.TestCase):
    def test_defaults_stand(self):
        check = check_configuration(
            config_path="/nonexistent/samverk.ini", env={})
        self.assertTrue(check.ok)
        self.assertEqual(check.config.port, 8737)
        self.assertTrue(all(s.source == "default"
                            for s in check.settings))

    def test_file_then_env_precedence(self):
        td, p = write_ini("[samverk]\nport = 9000\nhost = 10.0.0.1\n")
        self.addCleanup(td.cleanup)
        check = check_configuration(
            config_path=p, env={"SAMVERK_PORT": "9100"})
        self.assertTrue(check.ok, check.problems)
        self.assertEqual(check.config.port, 9100)
        self.assertEqual(check.config.host, "10.0.0.1")
        by_key = {s.key: s for s in check.settings}
        self.assertEqual(by_key["port"].source, "environment")
        self.assertEqual(by_key["host"].source, "config file")

    def test_bad_env_value_blocks_and_names_source(self):
        check = check_configuration(
            config_path="/nonexistent/samverk.ini",
            env={"SAMVERK_PORT": "abc"})
        self.assertFalse(check.ok)
        self.assertIsNone(check.config)
        self.assertIn("environment", check.errors[0].words)

    def test_bad_file_value_falls_back_not_crash(self):
        td, p = write_ini("[samverk]\nport = abc\n")
        self.addCleanup(td.cleanup)
        check = check_configuration(config_path=p, env={})
        self.assertFalse(check.ok)
        by_key = {s.key: s for s in check.settings}
        self.assertEqual(by_key["port"].value_text, "8737")

    def test_tls_pair_law(self):
        td, p = write_ini(
            "[samverk]\ntls_cert_file = /tmp/cert.pem\n")
        self.addCleanup(td.cleanup)
        check = check_configuration(config_path=p, env={})
        self.assertFalse(check.ok)
        self.assertTrue(any("tls_key_file" in pr.words
                            for pr in check.errors))

    def test_unknown_env_warns_known_env_silent(self):
        check = check_configuration(
            config_path="/nonexistent/samverk.ini",
            env={"SAMVERK_PROT": "1", "SAMVERK_JOB_ID": "7",
                 "SAMVERK_SECRET_TOKEN": "x"})
        self.assertTrue(check.ok)
        prot = [w for w in check.warnings
                if "SAMVERK_PROT" in w.words]
        self.assertEqual(len(prot), 1)

    def test_missing_named_file_warns(self):
        td, p = write_ini(
            "[samverk]\nsecret_file = /nope/secrets.ini\n")
        self.addCleanup(td.cleanup)
        check = check_configuration(config_path=p, env={})
        self.assertTrue(check.ok)
        self.assertTrue(any("does not exist" in w.words
                            for w in check.warnings))

    def test_report_and_page_render(self):
        check = check_configuration(
            config_path="/nonexistent/samverk.ini", env={})
        report = format_check_report(check)
        self.assertIn("Effective settings:", report)
        self.assertIn("port = 8737", report)
        page = render_configuration_page(check)
        self.assertIn("Configuration", page)
        self.assertIn("SAMVERK_PORT", page)

    def test_service_matches_pure(self):
        service = ConfigurationService(
            config_path="/nonexistent/samverk.ini", env={})
        self.assertTrue(service.check().ok)
        self.assertIn("[samverk]", service.example())

    def test_load_config_compat_unchanged(self):
        td, p = write_ini("[samverk]\nport = 9001\n")
        self.addCleanup(td.cleanup)
        cfg = load_config(config_path=p, env={})
        self.assertEqual(cfg.port, 9001)


class AuditTests(unittest.TestCase):
    def test_audit_stands_cleanly(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        conn = init_db(Path(td.name) / "t.db")
        try:
            audit = audit_configuration(conn)
        finally:
            conn.close()
        self.assertTrue(audit.stands_cleanly, audit)
        self.assertEqual(audit.schema_version, 139)
        self.assertEqual(audit.events_scanned, 138)


class CliTests(unittest.TestCase):
    def test_config_check_cli(self):
        from samverk.cli import main
        self.assertEqual(
            main(["config", "check", "--config",
                  "/nonexistent/samverk.ini"]), 0)
        self.assertEqual(
            main(["config", "example"]), 0)


if __name__ == "__main__":
    unittest.main()
