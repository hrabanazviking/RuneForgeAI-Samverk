"""S-350 acceptance battery: first-admin creation.

Acceptance (roadmap S-350): a CLI command creates the first
admin; the admin's first sign-in lands on a home that shows
the next three things to do (token creation, repo creation,
mirror setup — each reachable and labelled in plain words).
"""
from __future__ import annotations
import io, os, subprocess, sys, tempfile, time, unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.access_tokens import AccessTokenStore
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.cli import main as cli_main
from samverk.db import schema_version
from samverk.fine_grained_tokens import FineTokenStore
from samverk.first_admin import (
    FirstAdminError, FirstAdminHome, FirstAdminService,
    decide_first_admin, decide_next_steps, render_first_admin_home)
from samverk.login import LoginService
from samverk.mirrors import MirrorService
from samverk.repositories import RepositoryStore
from samverk.sessions import SessionStore

PASSWORD = "correct horse battery staple"

class FirstAdminTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        root = Path(self._td.name)
        self.data_root = root / "instance"; self.data_root.mkdir()
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        self.service = FirstAdminService(self.conn, self.accounts, audit=self.audit)

    # -- pure judgements ------------------------------------
    def test_pure_first_means_first(self):
        self.assertIsNone(decide_first_admin(False))
        self.assertEqual(decide_first_admin(True), "admin_exists")

    def test_pure_next_steps_exactly_three_in_order(self):
        steps = decide_next_steps(has_token=False, has_repository=False,
                                  has_mirror=False, first_repo_path=None)
        self.assertEqual([s.key for s in steps], ["token", "repository", "mirror"])
        self.assertEqual(steps[0].label, "Create a personal access token")
        self.assertEqual(steps[1].label, "Create a repository")
        self.assertEqual(steps[2].label, "Set up a mirror")
        self.assertEqual(steps[0].href, "/settings/tokens")
        self.assertEqual(steps[1].href, "/api/v1/repos")
        self.assertEqual(steps[2].href, "/api/v1/repos")
        self.assertTrue(all(s.state_word == "To do" for s in steps))

    def test_pure_next_steps_done_and_mirror_repo_door(self):
        steps = decide_next_steps(has_token=True, has_repository=True,
                                  has_mirror=False,
                                  first_repo_path="/volmarr/first")
        self.assertEqual(steps[0].state_word, "Done")
        self.assertEqual(steps[1].state_word, "Done")
        self.assertEqual(steps[2].href, "/volmarr/first")
        self.assertEqual(steps[2].state_word, "To do")

    # -- creation --------------------------------------------
    def test_creates_active_admin_who_can_sign_in(self):
        user = self.service.create_first_admin("volmarr", PASSWORD, "v@example.org")
        self.assertTrue(user.is_admin)
        self.assertEqual(user.status, "active")
        login = LoginService(self.conn, self.accounts,
                             SessionStore(self.conn), audit=self.audit)
        token = login.login("volmarr", PASSWORD)
        self.assertEqual(login.authenticate_session(token), user.id)

    def test_second_first_admin_refused(self):
        self.service.create_first_admin("volmarr", PASSWORD)
        with self.assertRaises(FirstAdminError) as ctx:
            self.service.create_first_admin("othername", PASSWORD)
        self.assertEqual(ctx.exception.reason, "admin_exists")
        self.assertIsNone(self.accounts.get_by_username("othername"))

    def test_refused_when_admin_already_stands_from_elsewhere(self):
        ordinary = self.accounts.register("someone", "a long enough password")
        with self.conn:
            self.conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (ordinary.id,))
        with self.assertRaises(FirstAdminError) as ctx:
            self.service.create_first_admin("volmarr", PASSWORD)
        self.assertEqual(ctx.exception.reason, "admin_exists")

    def test_ordinary_accounts_do_not_block_the_first_admin(self):
        self.accounts.register("someone", "a long enough password")
        user = self.service.create_first_admin("volmarr", PASSWORD)
        self.assertTrue(user.is_admin)

    def test_account_law_applies_whole(self):
        for name, pw, reason in (
            ("admin", PASSWORD, "username_reserved"),
            ("ab", PASSWORD, "username_too_short"),
            ("volmarr", "short", "password_too_short"),
            ("volmarr", "password123", "password_too_common"),
        ):
            with self.assertRaises(FirstAdminError) as ctx:
                self.service.create_first_admin(name, pw)
            self.assertEqual(ctx.exception.reason, reason, (name, pw))
        self.accounts.register("takenname", "a long enough password")
        with self.assertRaises(FirstAdminError) as ctx:
            self.service.create_first_admin("TakenName", PASSWORD)
        self.assertEqual(ctx.exception.reason, "username_taken")

    def test_password_never_stored_or_audited_in_plaintext(self):
        self.service.create_first_admin("volmarr", PASSWORD)
        raw = (self.data_root / "samverk.db").read_bytes()
        self.assertNotIn(PASSWORD.encode(), raw)
        rows = self.conn.execute(
            "SELECT detail FROM audit_log WHERE action = 'admin.user.create'"
        ).fetchall()
        self.assertTrue(rows)
        for row in rows:
            self.assertNotIn(PASSWORD, row["detail"] or "")
        ok = [r for r in self.conn.execute(
            "SELECT outcome FROM audit_log WHERE action = 'admin.user.create'").fetchall()]
        self.assertIn("success", [r["outcome"] for r in ok])

    # -- the first sign-in home -------------------------------
    def _home(self):
        classic = AccessTokenStore(self.conn, self.accounts, audit=self.audit)
        fine = FineTokenStore(self.conn, self.accounts, audit=self.audit)
        repos = RepositoryStore(self.conn, self.data_root, self.accounts, audit=self.audit)
        mirrors = MirrorService(self.conn, self.data_root, self.accounts, repos, audit=self.audit)
        return FirstAdminHome(self.accounts, classic, fine, repos, mirrors), classic, repos, mirrors

    def test_home_shows_three_todo_steps_then_done_as_they_land(self):
        admin = self.service.create_first_admin("volmarr", PASSWORD)
        home, classic, repos, mirrors = self._home()
        steps = home.steps_for(admin.id)
        self.assertEqual([s.key for s in steps], ["token", "repository", "mirror"])
        self.assertTrue(all(not s.done for s in steps))
        page = render_first_admin_home(admin.username, steps)
        for label in ("Create a personal access token", "Create a repository",
                      "Set up a mirror"):
            self.assertIn(label, page)
        self.assertIn('href="/settings/tokens"', page)
        self.assertIn('href="/api/v1/repos"', page)
        self.assertIn("(To do)", page)
        classic.create_token(admin.id, "cli", {"repo:read"},
                             int(time.time()) + 3600)
        steps = home.steps_for(admin.id)
        self.assertTrue(steps[0].done)
        self.assertFalse(steps[1].done)
        repos.create_repository(admin.id, "volmarr", "first")
        steps = home.steps_for(admin.id)
        self.assertTrue(steps[1].done)
        self.assertEqual(steps[2].href, "/volmarr/first")
        src = Path(self._td.name) / "src.git"
        subprocess.run(["git", "init", "--bare", "-b", "main", str(src)],
                       check=True, capture_output=True)
        mirrors.create_mirror(admin.id, "volmarr", "copy", src)
        steps = home.steps_for(admin.id)
        self.assertTrue(all(s.done for s in steps))
        page = render_first_admin_home(admin.username, steps)
        self.assertIn("(Done)", page)
        self.assertNotIn("(To do)", page)

    def test_home_escapes_username(self):
        steps = decide_next_steps(has_token=False, has_repository=False,
                                  has_mirror=False, first_repo_path=None)
        page = render_first_admin_home("<script>x</script>", steps)
        self.assertNotIn("<script>x</script>", page)
        self.assertIn("&lt;script&gt;", page)

    def test_home_unknown_user_refused(self):
        home, *_ = self._home()
        with self.assertRaises(FirstAdminError):
            home.steps_for(99999)

    # -- the CLI door ------------------------------------------
    def test_cli_creates_first_admin_and_refuses_second(self):
        env = {"SAMVERK_DATA_ROOT": str(self.data_root),
               "SAMVERK_CONFIG": str(Path(self._td.name) / "none.ini"),
               "FA_PW": PASSWORD}
        with mock.patch.dict(os.environ, env):
            out = io.StringIO()
            with redirect_stdout(out):
                rc = cli_main(["admin", "create-first-admin", "--username",
                               "volmarr", "--password-env", "FA_PW"])
            self.assertEqual(rc, 0)
            self.assertIn("first admin created: volmarr", out.getvalue())
            self.assertNotIn(PASSWORD, out.getvalue())
            err = io.StringIO()
            with redirect_stderr(err):
                rc = cli_main(["admin", "create-first-admin", "--username",
                               "secondone", "--password-env", "FA_PW"])
            self.assertEqual(rc, 1)
            self.assertIn("An admin already exists", err.getvalue())
        user = self.accounts.get_by_username("volmarr")
        self.assertIsNotNone(user)
        self.assertTrue(user.is_admin)

    def test_cli_missing_password_env_refused(self):
        env = {"SAMVERK_DATA_ROOT": str(self.data_root),
               "SAMVERK_CONFIG": str(Path(self._td.name) / "none.ini")}
        with mock.patch.dict(os.environ, env):
            err = io.StringIO()
            with redirect_stderr(err):
                rc = cli_main(["admin", "create-first-admin", "--username",
                               "volmarr", "--password-env", "NO_SUCH_VAR_XYZ"])
            self.assertEqual(rc, 1)
            self.assertIsNone(self.accounts.get_by_username("volmarr"))

    # -- pins ---------------------------------------------------
    def test_no_migration_no_new_taxonomy_event(self):
        self.assertEqual(schema_version(self.conn), 139)
        self.assertEqual(db.MIGRATIONS[-1][0], 139)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 138)
        self.assertIn("admin.user.create", taxonomy.AUDIT_EVENTS)

if __name__ == "__main__":
    unittest.main()
