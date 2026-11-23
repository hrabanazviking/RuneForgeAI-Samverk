"""S-412 battery -- Linux services parity: the systemd
citizen re-verified as one of three equal citizens.

Real runs only. Everything this battery proves is
platform-independent by construction, plus one real-host
proof this citizen honestly has and the others do not
claim from a Linux seat: the shipped units are the exact
directives this module renders for the standing spec, and
S-348's neighbour battery re-proves systemd-analyze
verify over them. A real install, enable, boot, restart
or health answer on a dedicated host is NOT PROVEN by
this battery and is never claimed by it.
"""
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from samverk.linux_service import (
    ALL_UNITS, CAPABILITIES, CITIZENS, DEFAULT_CONFIG,
    DEFAULT_DATA_ROOT, INSTALL_WALK_STEPS, PARITY_MATRIX,
    RESTART_DELAY_SECONDS, RESTART_MODE, SERVER_UNIT,
    SERVICE_USER, SHIPPED_WORKERS, SYSTEM_DIR, TIMER_UNITS,
    WORKER_UNITS, LinuxServiceError, build_service_spec,
    check_spec, disable_commands, enable_commands,
    install_commands, parity_capabilities, parse_unit,
    render_command_line, render_install_script, render_unit,
    render_uninstall_script, restart_commands, server_command,
    server_unit, status_commands, timer_unit, uninstall_commands,
    validate_spec, verify_commands, worker_commands, worker_unit)

PY = "/usr/bin/python3"
ROOT_LIN = "/srv/samverk-data"
SRC = "/checkout/deploy/systemd"
DEPLOY = ROOT / "deploy" / "systemd"


def spec():
    return build_service_spec(PY, ROOT_LIN, "/etc/samverk/other.ini")


def standing():
    return build_service_spec()


class SpecTests(unittest.TestCase):
    def test_defaults_are_the_declared_law(self):
        s = standing()
        self.assertEqual(s.unit_name, SERVER_UNIT)
        self.assertEqual(s.unit_name, "samverk-server.service")
        self.assertEqual(s.user_name, SERVICE_USER)
        self.assertEqual(s.user_name, "samverk")
        self.assertEqual(s.group_name, "samverk")
        self.assertEqual(s.system_dir, SYSTEM_DIR)
        self.assertEqual(s.restart_mode, RESTART_MODE)
        self.assertEqual(s.restart_mode, "on-failure")
        self.assertEqual(s.restart_delay, RESTART_DELAY_SECONDS)
        self.assertEqual(s.restart_delay, 5)

    def test_config_and_db_defaults(self):
        s = standing()
        self.assertEqual(s.data_root, DEFAULT_DATA_ROOT)
        self.assertEqual(s.config_path, DEFAULT_CONFIG)
        self.assertEqual(s.config_path, "/etc/samverk/samverk.ini")
        self.assertEqual(s.db_path, "/var/lib/samverk/samverk.db")
        self.assertEqual(s.unit_path,
                         "/etc/systemd/system/samverk-server.service")

    def test_custom_spec_derives_db_from_data_root(self):
        self.assertEqual(spec().db_path, ROOT_LIN + "/samverk.db")

    def test_server_command_is_the_run_model_entry(self):
        self.assertEqual(server_command(standing()),
                         [PY, "-m", "samverk", "serve", "--config",
                          "/etc/samverk/samverk.ini"])
        from samverk.run_model import build_topology
        self.assertTrue(build_topology().server.entry.endswith(
            "samverk serve"))
        self.assertNotIn("linux_service",
                         " ".join(server_command(standing())))


class RefusalTests(unittest.TestCase):
    def _reason(self, *a, **k):
        with self.assertRaises(LinuxServiceError) as cm:
            build_service_spec(*a, **k)
        return cm.exception.reason

    def test_relative_python_refused(self):
        self.assertEqual(self._reason("bin/python3"),
                         "path_not_absolute")

    def test_relative_data_root_refused(self):
        self.assertEqual(self._reason(PY, "data/samverk"),
                         "path_not_absolute")

    def test_windows_path_refused(self):
        self.assertEqual(self._reason(r"C:\Python311\python.exe"),
                         "path_not_absolute")

    def test_docker_path_refused(self):
        self.assertEqual(self._reason(PY, "/var/lib/docker/samverk"),
                         "container_path")

    def test_empty_path_refused(self):
        self.assertEqual(self._reason("", ROOT_LIN), "path_missing")

    def test_validate_names_a_renamed_or_root_unit(self):
        from dataclasses import replace
        problems = validate_spec(replace(standing(),
                                         unit_name="other.service"))
        self.assertTrue(any("unit" in p for p in problems))
        with self.assertRaises(LinuxServiceError):
            check_spec(replace(standing(), user_name="root"))
        with self.assertRaises(LinuxServiceError):
            check_spec(replace(standing(), restart_mode="always"))

    def test_standing_spec_validates_clean(self):
        self.assertEqual(validate_spec(standing()), [])
        self.assertEqual(validate_spec(spec()), [])


class UnitTests(unittest.TestCase):
    def test_server_unit_shape(self):
        u = parse_unit(render_unit(server_unit(standing())))
        svc = u["Service"]
        self.assertEqual(svc["Type"], ["simple"])
        self.assertEqual(svc["User"], ["samverk"])
        self.assertEqual(svc["Restart"], ["on-failure"])
        self.assertEqual(svc["RestartSec"], ["5s"])
        self.assertEqual(svc["ExecStart"], [
            "/usr/bin/python3 -m samverk serve "
            "--config /etc/samverk/samverk.ini"])
        self.assertEqual(svc["StandardOutput"], ["journal"])
        self.assertEqual(svc["SyslogIdentifier"], ["samverk-server"])
        self.assertEqual(u["Install"]["WantedBy"],
                         ["multi-user.target"])

    def test_shipped_units_are_the_rendered_directives(self):
        s = standing()
        pairs = [(SERVER_UNIT, server_unit(s))]
        for role, unit in zip(SHIPPED_WORKERS, WORKER_UNITS):
            pairs.append((unit, worker_unit(s, role)))
        for role, timer in zip(SHIPPED_WORKERS, TIMER_UNITS):
            pairs.append((timer, timer_unit(s, role)))
        self.assertEqual(len(pairs), 5)
        for name, sections in pairs:
            shipped = parse_unit((DEPLOY / name).read_text())
            rendered = parse_unit(render_unit(sections))
            self.assertEqual(shipped, rendered, name)

    def test_worker_units_are_oneshot_with_s348_cadences(self):
        hook = parse_unit(render_unit(
            worker_unit(standing(), "webhook-delivery")))
        self.assertEqual(hook["Service"]["Type"], ["oneshot"])
        self.assertNotIn("Restart", hook["Service"])
        timer = parse_unit(render_unit(
            timer_unit(standing(), "webhook-delivery")))
        self.assertEqual(timer["Timer"]["OnUnitActiveSec"], ["1min"])
        self.assertEqual(timer["Timer"]["Persistent"], ["true"])
        digest = parse_unit(render_unit(
            timer_unit(standing(), "weekly-digest")))
        self.assertEqual(digest["Timer"]["OnCalendar"],
                         ["Mon 06:00"])

    def test_digest_worker_sends_nothing(self):
        u = parse_unit(render_unit(
            worker_unit(standing(), "weekly-digest")))
        self.assertEqual(u["Service"]["RestrictAddressFamilies"],
                         ["AF_UNIX"])

    def test_unshipped_workers_refused_plainly(self):
        for name in ("artifact-expiry", "mirror-sync"):
            with self.assertRaises(LinuxServiceError) as cm:
                worker_unit(standing(), name)
            self.assertEqual(cm.exception.reason,
                             "worker_not_shipped")

    def test_worker_commands_from_the_topology(self):
        workers = dict((n, a) for n, a, _ in
                       worker_commands(standing()))
        self.assertEqual(workers["webhook-delivery"][:3],
                         [PY, "-m", "samverk.webhook_delivery"])
        self.assertIn("/var/lib/samverk/samverk.db",
                      workers["webhook-delivery"])
        self.assertIn("/var/lib/samverk",
                      workers["artifact-expiry"])
        self.assertIsNone(workers["mirror-sync"])


class ParityTests(unittest.TestCase):
    def test_matrix_covers_exactly_the_capabilities(self):
        self.assertEqual(tuple(PARITY_MATRIX), CAPABILITIES)
        for cap in CAPABILITIES:
            self.assertEqual(tuple(PARITY_MATRIX[cap]),
                             CITIZENS, cap)
            for citizen in CITIZENS:
                self.assertTrue(PARITY_MATRIX[cap][citizen],
                                (cap, citizen))

    def test_all_three_citizens_are_equal(self):
        sets = {c: parity_capabilities(c) for c in CITIZENS}
        self.assertEqual(sets["linux"], sets["windows"])
        self.assertEqual(sets["linux"], sets["macos"])
        self.assertEqual(sets["linux"], frozenset(CAPABILITIES))

    def test_no_linux_only_feature_in_the_tree(self):
        # Every Linux mechanism in the matrix is a mechanism
        # for a shared capability (the matrix test above);
        # here: the shipped units carry no ExecStart beyond
        # the topology's entries -- no Linux-only process.
        entries = {tuple(a) for _, a, _ in worker_commands(standing())
                   if a}
        entries.add(tuple(server_command(standing())))
        for name in (SERVER_UNIT,) + WORKER_UNITS:
            u = parse_unit((DEPLOY / name).read_text())
            got = tuple(u["Service"]["ExecStart"][0].split())
            self.assertIn(got, entries, name)

    def test_restart_delay_difference_is_declared_not_hidden(self):
        cell = PARITY_MATRIX["restart_on_failure"]
        self.assertIn("5s", cell["linux"])
        self.assertIn("60000", cell["windows"])
        self.assertIn("60", cell["macos"])

    def test_unknown_citizen_refused(self):
        with self.assertRaises(LinuxServiceError) as cm:
            parity_capabilities("plan9")
        self.assertEqual(cm.exception.reason, "unknown_citizen")


class CommandTests(unittest.TestCase):
    def test_install_copies_verifies_never_enables(self):
        cmds = install_commands(standing(), SRC)
        verbs = [c[0] for c in cmds]
        self.assertEqual(verbs, ["install"] * 5 +
                         ["systemctl"] + ["systemd-analyze"] * 3)
        flat = " ".join(" ".join(c) for c in cmds)
        self.assertNotIn("enable", flat)
        self.assertIn(SYSTEM_DIR, flat)

    def test_enable_is_the_separate_operator_word(self):
        cmds = enable_commands(standing())
        self.assertEqual(cmds, [["systemctl", "enable", "--now",
                                 SERVER_UNIT, *TIMER_UNITS]])
        self.assertEqual(disable_commands(standing())[0][1],
                         "disable")

    def test_status_restart_verify_commands(self):
        self.assertEqual(status_commands(standing())[0],
                         ["systemctl", "status", SERVER_UNIT])
        self.assertEqual(restart_commands(standing()),
                         [["systemctl", "restart", SERVER_UNIT]])
        cmds = verify_commands(standing(), SRC)
        self.assertTrue(all(c[:2] == ["systemd-analyze", "verify"]
                            for c in cmds))
        self.assertEqual(len(cmds), 3)

    def test_uninstall_disables_removes_units_keeps_data(self):
        cmds = uninstall_commands(standing())
        self.assertEqual(cmds[0][1], "disable")
        flat = " ".join(" ".join(c) for c in cmds)
        for name in ALL_UNITS:
            self.assertIn(name, flat)
        self.assertNotIn(DEFAULT_DATA_ROOT, flat)
        self.assertNotIn("/etc/samverk", flat)

    def test_render_command_line_quotes_spaces(self):
        line = render_command_line(
            ["install", "-m", "0644", "a.service",
             "/etc/systemd/system/a b.service"])
        self.assertIn("'/etc/systemd/system/a b.service'", line)


class ScriptTests(unittest.TestCase):
    def test_install_script_is_root_checked_registration_only(self):
        text = render_install_script(standing(), SRC)
        self.assertIn("id -u", text)
        self.assertIn("--enable", text)
        self.assertIn("NOT enabled", text)
        self.assertIn("useradd", text)
        enable_at = text.index("--enable\"")
        self.assertLess(text.index("daemon-reload"), enable_at)

    def test_uninstall_script_keeps_the_data_root(self):
        text = render_uninstall_script(standing())
        self.assertIn("disable", text)
        self.assertIn("NOT deleted", text)
        self.assertIn(DEFAULT_DATA_ROOT, text)
        self.assertNotIn("rm -rf", text)

    def test_shipped_scripts_carry_the_same_law(self):
        install = (DEPLOY / "install.sh").read_text()
        self.assertIn("--enable", install)
        self.assertIn("NOT", install)
        # The S-412 addition: a shipped uninstall road, the
        # parity defect this slice found and fixed.
        uninstall = (DEPLOY / "uninstall.sh").read_text()
        self.assertIn("disable --now", uninstall)
        self.assertIn("NOT", uninstall)
        self.assertIn("data root kept", uninstall)
        self.assertNotIn("rm -rf", uninstall)
        for name in ALL_UNITS:
            self.assertIn(name, uninstall)
        ini = (DEPLOY / "samverk.ini.example").read_text()
        self.assertIn("data_root = /var/lib/samverk", ini)


class WalkAndDocsTests(unittest.TestCase):
    def test_walk_steps_complete_and_unique(self):
        names = [s["name"] for s in INSTALL_WALK_STEPS]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(names), 8)
        for s in INSTALL_WALK_STEPS:
            for key in ("title", "action", "failure",
                        "failure_words", "remedy"):
                self.assertTrue(s[key], (s["name"], key))

    def test_walk_shares_the_other_citizens_step_names(self):
        names = [s["name"] for s in INSTALL_WALK_STEPS]
        for shared in ("root_shell", "python_runtime",
                       "package_installed", "data_root_and_config",
                       "first_admin_walk", "service_user_rights"):
            self.assertIn(shared, names)

    def test_guide_carries_every_step_failure_and_honest_words(self):
        doc = (ROOT / "docs" / "LINUX_SERVICE.md").read_text()
        for s in INSTALL_WALK_STEPS:
            self.assertIn(s["name"], doc)
            self.assertIn(s["failure"], doc)
        self.assertIn("NOT PROVEN", doc)
        self.assertIn("No Docker", doc)
        self.assertIn("systemd", doc)
        for cap in CAPABILITIES:
            self.assertIn(cap, doc)

    def test_no_migration_no_taxonomy_event_pins_stand(self):
        import samverk.db as db
        from samverk.taxonomy import AUDIT_EVENTS
        self.assertEqual(len(db.MIGRATIONS), 140)
        self.assertEqual(len(AUDIT_EVENTS), 142)


if __name__ == "__main__":
    unittest.main()
