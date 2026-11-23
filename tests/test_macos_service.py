"""S-411 battery -- macOS launchd service: definition, plists, walk.

Real runs only. Everything this battery proves is platform-
independent by construction: the spec, the validation refusals,
the rendered plists and launchctl command lines and scripts, the
shipped deploy files' identity with the rendered ones, and the
install walk's completeness. A real macOS host install, launchd
bootstrap, KeepAlive restart, and health answer are NOT PROVEN
by this battery and are never claimed by it -- no Mac ran any
of this.
"""
import plistlib, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from samverk.macos_service import (
    DAEMON_DOMAIN, DAEMONS_DIR, DEFAULT_DATA_ROOT, INSTALL_WALK_STEPS,
    SERVER_LABEL, SERVICE_USER, SHIPPED_WORKERS, THROTTLE_INTERVAL_SECONDS,
    MacosServiceError, build_service_spec, check_spec, install_commands,
    load_commands, render_command_line, render_install_script,
    render_plist, render_uninstall_script, restart_commands,
    server_command, server_plist, status_commands, unload_commands,
    uninstall_commands, validate_spec, worker_commands, worker_label,
    worker_plist)

PY = "/usr/local/bin/python3"
ROOT_MAC = "/Library/Application Support/SamverkData"
SRC = "/checkout/deploy/launchd"


def spec():
    return build_service_spec(PY, ROOT_MAC)


class SpecTests(unittest.TestCase):
    def test_defaults_are_the_declared_law(self):
        s = spec()
        self.assertEqual(s.label, SERVER_LABEL)
        self.assertEqual(s.label, "org.samverk.server")
        self.assertEqual(s.user_name, SERVICE_USER)
        self.assertEqual(s.user_name, "_samverk")
        self.assertEqual(s.domain, DAEMON_DOMAIN)
        self.assertEqual(s.domain, "system")
        self.assertEqual(s.daemons_dir, DAEMONS_DIR)
        self.assertEqual(s.throttle_interval, THROTTLE_INTERVAL_SECONDS)
        self.assertEqual(s.throttle_interval, 60)

    def test_config_and_db_default_inside_data_root(self):
        s = spec()
        self.assertEqual(s.config_path, ROOT_MAC + "/samverk.ini")
        self.assertEqual(s.db_path, ROOT_MAC + "/samverk.db")
        d = build_service_spec(PY)
        self.assertEqual(d.data_root, DEFAULT_DATA_ROOT)

    def test_plist_path_and_target_derive_from_label(self):
        s = spec()
        self.assertEqual(s.plist_path,
                         DAEMONS_DIR + "/org.samverk.server.plist")
        self.assertEqual(s.target, "system/org.samverk.server")

    def test_program_arguments_are_the_server_entry_no_wrapper(self):
        s = spec()
        self.assertEqual(s.program_arguments,
                         [PY, "-m", "samverk", "serve",
                          "--config", ROOT_MAC + "/samverk.ini"])
        self.assertNotIn("macos_service", " ".join(s.program_arguments))

    def test_server_command_is_the_run_model_entry(self):
        self.assertEqual(server_command(spec()),
                         [PY, "-m", "samverk", "serve",
                          "--config", ROOT_MAC + "/samverk.ini"])
        from samverk.run_model import build_topology
        self.assertTrue(build_topology().server.entry.endswith(
            "samverk serve"))


class RefusalTests(unittest.TestCase):
    def _reason(self, *a, **k):
        with self.assertRaises(MacosServiceError) as cm:
            build_service_spec(*a, **k)
        return cm.exception.reason

    def test_relative_python_refused(self):
        self.assertEqual(self._reason("bin/python3"), "path_not_absolute")

    def test_relative_data_root_refused(self):
        self.assertEqual(self._reason(PY, "data/samverk"),
                         "path_not_absolute")

    def test_windows_path_refused(self):
        self.assertEqual(self._reason(r"C:\Python311\python.exe"),
                         "path_not_absolute")

    def test_docker_path_refused(self):
        self.assertEqual(
            self._reason(PY, "/var/lib/docker/samverk"),
            "container_path")

    def test_empty_path_refused(self):
        self.assertEqual(self._reason("", ROOT_MAC), "path_missing")

    def test_validate_names_a_renamed_daemon(self):
        from dataclasses import replace
        problems = validate_spec(replace(spec(), label="org.other.x"))
        self.assertTrue(any("label" in p for p in problems))
        with self.assertRaises(MacosServiceError):
            check_spec(replace(spec(), user_name="root"))
        with self.assertRaises(MacosServiceError):
            check_spec(replace(spec(), domain="gui/501"))

    def test_standing_spec_validates_clean(self):
        self.assertEqual(validate_spec(spec()), [])


class PlistTests(unittest.TestCase):
    def test_server_plist_shape(self):
        job = server_plist(spec())
        self.assertEqual(job["Label"], "org.samverk.server")
        self.assertEqual(job["ProgramArguments"], spec().program_arguments)
        self.assertEqual(job["UserName"], "_samverk")
        self.assertEqual(job["WorkingDirectory"], ROOT_MAC)
        self.assertTrue(job["RunAtLoad"])
        self.assertEqual(job["KeepAlive"], {"SuccessfulExit": False})
        self.assertEqual(job["ThrottleInterval"], 60)
        self.assertTrue(job["StandardOutPath"].endswith(".out.log"))
        self.assertTrue(job["StandardErrorPath"].endswith(".err.log"))

    def test_rendered_plist_parses_back_identical(self):
        job = server_plist(spec())
        self.assertEqual(plistlib.loads(render_plist(job).encode()), job)

    def test_worker_plists_carry_s348_cadences(self):
        hook = worker_plist(spec(), "webhook-delivery")
        self.assertEqual(hook["Label"], "org.samverk.webhook-delivery")
        self.assertEqual(hook["StartInterval"], 60)
        self.assertNotIn("KeepAlive", hook)
        self.assertNotIn("RunAtLoad", hook)
        digest = worker_plist(spec(), "weekly-digest")
        self.assertEqual(digest["StartCalendarInterval"],
                         {"Weekday": 1, "Hour": 6, "Minute": 0})

    def test_unshipped_workers_refused_plainly(self):
        for name in ("artifact-expiry", "mirror-sync"):
            with self.assertRaises(MacosServiceError) as cm:
                worker_plist(spec(), name)
            self.assertEqual(cm.exception.reason, "worker_not_shipped")

    def test_shipped_files_are_the_rendered_plists(self):
        deploy = ROOT / "deploy" / "launchd"
        # Shipped files render the DEFAULT spec, not this battery's.
        default = build_service_spec()
        pairs = [(SERVER_LABEL, server_plist(default))]
        for name in SHIPPED_WORKERS:
            pairs.append((worker_label(name), worker_plist(default, name)))
        for label, job in pairs:
            got = plistlib.loads(
                (deploy / (label + ".plist")).read_bytes())
            self.assertEqual(got, job, label)


class CommandTests(unittest.TestCase):
    def test_install_copies_and_lints_never_bootstraps(self):
        cmds = install_commands(spec(), SRC)
        verbs = [c[0] for c in cmds]
        self.assertEqual(verbs, ["install", "plutil"] * 3)
        flat = " ".join(" ".join(c) for c in cmds)
        self.assertNotIn("bootstrap", flat)
        self.assertIn(DAEMONS_DIR, flat)

    def test_load_bootstraps_all_three_into_system(self):
        cmds = load_commands(spec())
        self.assertEqual(len(cmds), 3)
        for c in cmds:
            self.assertEqual(c[:3], ["launchctl", "bootstrap", "system"])

    def test_status_restart_unload_commands(self):
        self.assertEqual(status_commands(spec()),
                         [["launchctl", "print",
                           "system/org.samverk.server"]])
        self.assertEqual(restart_commands(spec()),
                         [["launchctl", "kickstart", "-k",
                           "system/org.samverk.server"]])
        self.assertTrue(all(c[1] == "bootout"
                            for c in unload_commands(spec())))

    def test_uninstall_boots_out_removes_plists_keeps_data(self):
        cmds = uninstall_commands(spec())
        self.assertEqual([c[0] for c in cmds],
                         ["launchctl"] * 3 + ["rm"] * 3)
        flat = " ".join(" ".join(c) for c in cmds)
        self.assertNotIn(ROOT_MAC, flat)

    def test_render_command_line_quotes_spaces(self):
        line = render_command_line(
            ["install", "-m", "0644", "a.plist",
             ROOT_MAC + "/x.plist"])
        self.assertIn("'" + ROOT_MAC + "/x.plist'", line)

    def test_worker_commands_from_the_topology(self):
        workers = dict((n, a) for n, a, _ in worker_commands(spec()))
        self.assertEqual(workers["webhook-delivery"][:3],
                         [PY, "-m", "samverk.webhook_delivery"])
        self.assertIn(ROOT_MAC + "/samverk.db",
                      workers["webhook-delivery"])
        self.assertIn(ROOT_MAC, workers["weekly-digest"])
        self.assertIn(ROOT_MAC, workers["artifact-expiry"])
        # mirror-sync has no CLI: rendered None, never fabricated.
        self.assertIsNone(workers["mirror-sync"])


class ScriptTests(unittest.TestCase):
    def test_install_script_is_root_checked_registration_only(self):
        text = render_install_script(spec(), SRC)
        self.assertIn("id -u", text)
        self.assertIn("--load", text)
        self.assertIn("bootstrap", text)  # only inside the --load arm
        self.assertIn("NOT loaded", text)
        load_at = text.index("--load\"")
        self.assertLess(text.index("plutil"), load_at)

    def test_uninstall_script_keeps_the_data_root(self):
        text = render_uninstall_script(spec())
        self.assertIn("bootout", text)
        self.assertIn("NOT deleted", text)
        self.assertIn(ROOT_MAC, text)  # named as kept, never removed
        self.assertNotIn("rm -rf", text)

    def test_shipped_scripts_carry_the_same_law(self):
        deploy = ROOT / "deploy" / "launchd"
        install = (deploy / "install.sh").read_text()
        self.assertIn("--load", install)
        self.assertIn("NOT", install)
        self.assertIn("bootstrap", install)
        uninstall = (deploy / "uninstall.sh").read_text()
        self.assertIn("NOT deleted", uninstall)
        self.assertNotIn("rm -rf", uninstall)
        ini = (deploy / "samverk.ini.example").read_text()
        self.assertIn("data_root = /Library/Application Support/Samverk",
                      ini)


class WalkAndDocsTests(unittest.TestCase):
    def test_walk_steps_complete_and_unique(self):
        names = [s["name"] for s in INSTALL_WALK_STEPS]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(names), 8)
        for s in INSTALL_WALK_STEPS:
            for key in ("title", "action", "failure",
                        "failure_words", "remedy"):
                self.assertTrue(s[key], (s["name"], key))

    def test_guide_carries_every_step_failure_and_the_honest_words(self):
        doc = (ROOT / "docs" / "MACOS_SERVICE.md").read_text()
        for s in INSTALL_WALK_STEPS:
            self.assertIn(s["name"], doc)
            self.assertIn(s["failure"], doc)
        self.assertIn("NOT PROVEN", doc)
        self.assertIn("No Docker", doc)
        self.assertIn("launchd", doc)

    def test_no_migration_no_taxonomy_event_pins_stand(self):
        import samverk.db as db
        from samverk.taxonomy import AUDIT_EVENTS
        self.assertEqual(len(db.MIGRATIONS), 140)
        self.assertEqual(len(AUDIT_EVENTS), 142)


if __name__ == "__main__":
    unittest.main()
