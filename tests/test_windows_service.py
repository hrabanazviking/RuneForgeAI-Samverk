"""S-410 battery -- Windows service: definition, commands, walk.

Real runs only. Everything this battery proves is platform-
independent by construction: the spec, the validation refusals,
the rendered sc.exe command lines and PowerShell scripts, the
install walk's completeness, and the service host's structure
and off-Windows refusal. A real Windows host install, start,
and SCM recovery run are NOT PROVEN by this battery and are
never claimed by it -- no Windows machine ran any of this.
"""
import subprocess, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from samverk.windows_service import (
    DEFAULT_DATA_ROOT, HOST_MODULE, INSTALL_WALK_STEPS,
    RECOVERY_ACTIONS, SERVICE_ACCOUNT, SERVICE_NAME,
    WindowsServiceError, build_service_spec, check_spec,
    install_commands, render_command_line, render_install_script,
    render_uninstall_script, server_command, start_commands,
    status_commands, stop_commands, uninstall_commands,
    validate_spec, worker_commands)
from samverk.windows_service_host import build_child_command, main as host_main, parse_args

PY = r"C:\Program Files\Python311\python.exe"
ROOT_WIN = r"D:\SamverkData"


def spec():
    return build_service_spec(PY, ROOT_WIN)


class SpecTests(unittest.TestCase):
    def test_defaults_are_the_declared_law(self):
        s = spec()
        self.assertEqual(s.service_name, SERVICE_NAME)
        self.assertEqual(s.account, SERVICE_ACCOUNT)
        self.assertEqual(s.account, r"NT SERVICE\Samverk")
        self.assertEqual(s.start_mode, "auto")
        self.assertEqual(s.recovery_actions, RECOVERY_ACTIONS)
        self.assertEqual(s.recovery_reset_seconds, 86400)
        self.assertEqual(s.host_module, HOST_MODULE)

    def test_config_and_db_default_inside_data_root(self):
        s = spec()
        self.assertEqual(s.config_path, ROOT_WIN + r"\samverk.ini")
        self.assertEqual(s.db_path, ROOT_WIN + r"\samverk.db")
        d = build_service_spec(PY)
        self.assertEqual(d.data_root, DEFAULT_DATA_ROOT)

    def test_bin_path_is_host_with_config_and_root(self):
        s = spec()
        self.assertEqual(s.bin_path_argv[:3], [PY, "-m", HOST_MODULE])
        self.assertIn("--config", s.bin_path_argv)
        self.assertIn(s.config_path, s.bin_path_argv)
        self.assertIn("--data-root", s.bin_path_argv)

    def test_bin_path_quotes_the_spaced_interpreter(self):
        s = spec()
        self.assertTrue(s.bin_path.startswith('"' + PY + '"'))

    def test_server_command_is_the_run_model_entry(self):
        self.assertEqual(server_command(spec()),
                         [PY, "-m", "samverk", "serve",
                          "--config", ROOT_WIN + r"\samverk.ini"])
        from samverk.run_model import build_topology
        self.assertTrue(build_topology().server.entry.endswith(
            "samverk serve"))


class RefusalTests(unittest.TestCase):
    def _reason(self, *a, **k):
        with self.assertRaises(WindowsServiceError) as cm:
            build_service_spec(*a, **k)
        return cm.exception.reason

    def test_relative_python_refused(self):
        self.assertEqual(self._reason(r"Python311\python.exe"),
                         "path_not_absolute")

    def test_relative_data_root_refused(self):
        self.assertEqual(self._reason(PY, r"data\samverk"),
                         "path_not_absolute")

    def test_posix_path_refused(self):
        self.assertEqual(self._reason("/usr/bin/python3"),
                         "path_not_absolute")

    def test_wsl_unc_path_refused(self):
        self.assertEqual(
            self._reason(PY, r"\\wsl$\Ubuntu\home\samverk"),
            "container_or_wsl_path")

    def test_docker_path_refused(self):
        self.assertEqual(
            self._reason(PY, r"C:\ProgramData\Docker\samverk"),
            "container_or_wsl_path")

    def test_non_exe_python_refused(self):
        self.assertEqual(self._reason(r"C:\Python311\python"),
                         "python_not_executable")

    def test_validate_names_a_renamed_service(self):
        from dataclasses import replace
        problems = validate_spec(replace(spec(), service_name="Other"))
        self.assertTrue(any("service name" in p for p in problems))
        with self.assertRaises(WindowsServiceError):
            check_spec(replace(spec(), account="Administrator"))

    def test_standing_spec_validates_clean(self):
        self.assertEqual(validate_spec(spec()), [])


class CommandTests(unittest.TestCase):
    def test_install_sequence_shape_and_order(self):
        cmds = install_commands(spec())
        verbs = [c[1] for c in cmds]
        self.assertEqual(verbs, ["create", "description", "config",
                                 "failure", "failureflag"])
        create = cmds[0]
        self.assertEqual(create[0], "sc.exe")
        self.assertIn("binPath=", create)
        self.assertIn(spec().bin_path, create)
        self.assertIn("start=", create)
        self.assertIn("auto", create)

    def test_install_registers_virtual_account_and_recovery(self):
        cmds = install_commands(spec())
        config = [c for c in cmds if c[1] == "config"][0]
        self.assertIn("obj=", config)
        self.assertIn(SERVICE_ACCOUNT, config)
        failure = [c for c in cmds if c[1] == "failure"][0]
        self.assertIn(RECOVERY_ACTIONS, failure)
        self.assertIn("86400", failure)

    def test_install_never_starts_the_service(self):
        verbs = [c[1] for c in install_commands(spec())]
        self.assertNotIn("start", verbs)

    def test_start_stop_status_commands(self):
        self.assertEqual(start_commands(spec()),
                         [["sc.exe", "start", "Samverk"]])
        self.assertEqual(stop_commands(spec()),
                         [["sc.exe", "stop", "Samverk"]])
        self.assertEqual([c[1] for c in status_commands(spec())],
                         ["query", "queryex"])

    def test_uninstall_stops_before_delete_and_keeps_data(self):
        cmds = uninstall_commands(spec())
        self.assertEqual([c[1] for c in cmds], ["stop", "delete"])
        flat = " ".join(" ".join(c) for c in cmds)
        self.assertNotIn(ROOT_WIN, flat)

    def test_render_command_line_quotes_spaces(self):
        line = render_command_line(["sc.exe", "config", "Samverk",
                                    "obj=", SERVICE_ACCOUNT])
        self.assertIn('"NT SERVICE\\Samverk"', line)

    def test_worker_commands_from_the_topology(self):
        workers = dict((n, a) for n, a, _ in worker_commands(spec()))
        self.assertEqual(workers["webhook-delivery"][:3],
                         [PY, "-m", "samverk.webhook_delivery"])
        self.assertIn(ROOT_WIN + r"\samverk.db",
                      workers["webhook-delivery"])
        self.assertIn(ROOT_WIN, workers["weekly-digest"])
        # mirror-sync has no CLI: rendered None, never fabricated.
        self.assertIsNone(workers["mirror-sync"])


class ScriptTests(unittest.TestCase):
    def test_install_script_is_elevated_guarded_registration_only(self):
        text = render_install_script(spec())
        self.assertIn("#Requires -RunAsAdministrator", text)
        self.assertIn("WSL_DISTRO_NAME", text)
        self.assertIn("param([switch]$Start)", text)
        for argv in install_commands(spec()):
            self.assertIn(argv[1], text)
        self.assertIn("icacls", text)
        self.assertIn("if ($Start)", text)
        self.assertIn("NOT started", text)

    def test_uninstall_script_keeps_the_data_root(self):
        text = render_uninstall_script(spec())
        self.assertIn("sc.exe delete", text)
        self.assertIn("NOT deleted", text)
        self.assertIn(ROOT_WIN, text)  # named as kept, never removed
        self.assertNotIn("Remove-Item", text)


class HostTests(unittest.TestCase):
    def test_host_child_command_matches_server_command(self):
        self.assertEqual(
            build_child_command(PY, ROOT_WIN + r"\samverk.ini", ROOT_WIN),
            server_command(spec()))

    def test_host_parse_args(self):
        a = parse_args(["--config", "c.ini", "--data-root", "d"])
        self.assertEqual((a.config, a.data_root), ("c.ini", "d"))

    def test_host_refuses_off_windows(self):
        if sys.platform.startswith("win"):
            self.skipTest("host runs on Windows; refusal is off-Windows law")
        self.assertEqual(host_main(["--config", "c", "--data-root", "d"]), 2)

    def test_host_source_speaks_scm_and_imports_clean(self):
        src = (ROOT / "samverk" / "windows_service_host.py").read_text()
        for token in ("StartServiceCtrlDispatcherW",
                      "RegisterServiceCtrlHandlerW", "SetServiceStatus",
                      "SERVICE_CONTROL_STOP"):
            self.assertIn(token, src)
        self.assertNotIn("docker", src.lower().replace("no docker", ""))


class WalkAndDocsTests(unittest.TestCase):
    def test_walk_steps_complete_and_unique(self):
        names = [s["name"] for s in INSTALL_WALK_STEPS]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(names), 8)
        for s in INSTALL_WALK_STEPS:
            for key in ("title", "action", "failure", "failure_words", "remedy"):
                self.assertTrue(s[key], (s["name"], key))

    def test_guide_carries_every_step_failure_and_the_honest_words(self):
        doc = (ROOT / "docs" / "WINDOWS_SERVICE.md").read_text()
        for s in INSTALL_WALK_STEPS:
            self.assertIn(s["name"], doc)
            self.assertIn(s["failure"], doc)
        self.assertIn("NOT PROVEN", doc)
        self.assertIn("No Docker", doc)
        self.assertIn("WSL", doc)

    def test_no_migration_no_taxonomy_event_pins_stand(self):
        import samverk.db as db
        from samverk.taxonomy import AUDIT_EVENTS
        self.assertEqual(len(db.MIGRATIONS), 140)
        self.assertEqual(len(AUDIT_EVENTS), 142)


if __name__ == "__main__":
    unittest.main()
