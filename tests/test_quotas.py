"""S-354 acceptance battery: quotas.

Acceptance (roadmap S-354): per-user and per-repo
storage quotas enforced at S-068's point, visible to
owners before they bite.

Counted with: python3 -m unittest tests.test_quotas
"""
from __future__ import annotations
import os, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.quotas import (QuotaOverviewService, overview_words,
                            render_quotas_page)
from samverk.receive_gate import ReceiveGate
from samverk.repo_quotas import QuotaError, QuotaService
from samverk.repositories import RepositoryStore
from samverk.taxonomy import AUDIT_EVENTS

def git(repo: Path, *args: str, input_bytes: bytes | None = None) -> str:
    env = dict(os.environ)
    env.update({"GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@e.c",
                "GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": "a@e.c"})
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         input=input_bytes, capture_output=True, env=env)
    if out.returncode != 0:
        raise AssertionError(out.stderr.decode())
    return out.stdout.decode().strip()

def seed_repo(repos, owner_id, owner, name, payload: bytes):
    repos.create_repository(owner_id, owner, name, visibility="private")
    path = repos.path_for(owner, name)
    blob = git(path, "hash-object", "-w", "--stdin", input_bytes=payload)
    tree = git(path, "mktree",
               input_bytes=f"100644 blob {blob}\tx.txt\n".encode())
    commit = git(path, "commit-tree", tree, input_bytes=b"first\n")
    git(path, "update-ref", "refs/heads/main", commit)
    return path

class QuotaTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.data_root = Path(self._td.name)
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.other = self.accounts.register("yrsa", "correct horse battery")
        self.admin = self.accounts.register("adminx", "correct horse battery")
        with self.conn:
            self.conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?",
                              (self.admin.id,))
        self.repos = RepositoryStore(self.conn, self.data_root, self.accounts)
        seed_repo(self.repos, self.owner.id, "volmarr", "proj", b"x" * 1000)
        seed_repo(self.repos, self.owner.id, "volmarr", "side", b"y" * 2000)
        self.audit = AuditLog(self.conn)
        self.quotas = QuotaService(self.conn, self.data_root,
                                   self.accounts, self.repos,
                                   audit=self.audit)
        self.u_proj = self.quotas.usage_bytes("volmarr", "proj")
        self.u_side = self.quotas.usage_bytes("volmarr", "side")
        self.u_total = self.quotas.user_usage_bytes("volmarr")
        self.assertEqual(self.u_total, self.u_proj + self.u_side)
        self.overview = QuotaOverviewService(
            self.conn, self.data_root, self.accounts, self.repos,
            quotas=self.quotas)

    # -- per-repo level still enforced at the one point ------
    def test_repo_quota_refused_at_receive_point(self):
        self.quotas.set_repo_quota(self.owner.id, "volmarr", "proj",
                                   self.u_proj + 10)
        decision = self.quotas.check_receive("volmarr", "proj", 11)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.blocked_by, "repository")
        self.assertIn("Repository quota exceeded for volmarr/proj",
                      decision.message)
        with self.assertRaises(QuotaError) as caught:
            self.quotas.enforce_receive("volmarr", "proj", 11)
        self.assertEqual(caught.exception.reason, "quota_exceeded")

    def test_receive_gate_refuses_on_user_quota(self):
        gate = ReceiveGate(quota_service=self.quotas)
        self.quotas.set_user_quota(self.admin.id, "volmarr", self.u_total + 5)
        result = gate.check(owner="volmarr", repo="proj", incoming_bytes=6)
        self.assertFalse(result.allowed)
        self.assertEqual(result.refused_stage, "quota")
        self.assertIn("User quota exceeded for volmarr", result.reason)
        ok = gate.check(owner="volmarr", repo="proj", incoming_bytes=5)
        self.assertTrue(ok.allowed)

    # -- per-user level ---------------------------------------
    def test_user_quota_aggregates_across_repos(self):
        # Neither repo has a repo quota; the user limit alone bites,
        # and it counts BOTH repositories' bytes.
        self.quotas.set_user_quota(self.admin.id, "volmarr",
                                   self.u_total + 100)
        fits = self.quotas.check_receive("volmarr", "side", 100)
        self.assertTrue(fits.allowed)
        self.assertEqual(fits.user_usage_bytes, self.u_total)
        over = self.quotas.check_receive("volmarr", "side", 101)
        self.assertFalse(over.allowed)
        self.assertEqual(over.blocked_by, "user")
        self.assertIn("User quota exceeded for volmarr", over.message)
        self.assertIn(str(self.u_total), over.message)          # aggregate held
        self.assertIn(str(self.u_total + 100), over.message)    # the limit
        self.assertIn("101", over.message)                      # the push
        with self.assertRaises(QuotaError) as caught:
            self.quotas.enforce_receive("volmarr", "proj", 101)
        self.assertEqual(str(caught.exception), over.message.replace(
            "volmarr/side", "volmarr/proj"))

    def test_raising_user_quota_lets_same_push_through(self):
        self.quotas.set_user_quota(self.admin.id, "volmarr", self.u_total)
        self.assertFalse(
            self.quotas.check_receive("volmarr", "proj", 1).allowed)
        self.quotas.set_user_quota(self.admin.id, "volmarr",
                                   self.u_total + 1000)
        self.assertTrue(
            self.quotas.check_receive("volmarr", "proj", 1).allowed)

    def test_user_default_applies_and_per_user_wins(self):
        self.quotas.set_default_user_quota(self.admin.id, self.u_total + 10)
        self.assertEqual(self.quotas.effective_user_quota("volmarr"),
                         self.u_total + 10)
        self.assertTrue(self.quotas.check_receive("volmarr", "proj", 10).allowed)
        self.assertFalse(self.quotas.check_receive("volmarr", "proj", 11).allowed)
        self.quotas.set_user_quota(self.admin.id, "volmarr",
                                   self.u_total + 5000)
        self.assertTrue(self.quotas.check_receive("volmarr", "proj", 500).allowed)
        self.quotas.set_user_quota(self.admin.id, "volmarr", None)
        self.assertEqual(self.quotas.effective_user_quota("volmarr"),
                         self.u_total + 10)

    def test_no_user_quota_means_unlimited(self):
        self.assertIsNone(self.quotas.effective_user_quota("volmarr"))
        decision = self.quotas.check_receive("volmarr", "proj", 10**12)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.blocked_by, "none")

    # -- who may set ------------------------------------------
    def test_user_quota_is_admin_only_and_audited(self):
        for actor in (self.owner.id, self.other.id):
            with self.assertRaises(QuotaError) as caught:
                self.quotas.set_user_quota(actor, "volmarr", 1000)
            self.assertEqual(caught.exception.reason, "permission_denied")
        self.assertEqual(
            self.quotas.set_user_quota(self.admin.id, "volmarr", 4242), 4242)
        rows = self.conn.execute(
            "SELECT action, target_kind, target_id, detail FROM audit_log"
            " WHERE action = 'admin.settings.change'").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["target_kind"], "user")
        self.assertEqual(rows[0]["target_id"], "volmarr")
        self.assertIn("user_quota_bytes", rows[0]["detail"])
        self.assertIn("4242", rows[0]["detail"])

    def test_user_quota_validation(self):
        for bad in (-1, 1.5, "100", True):
            with self.assertRaises(QuotaError, msg=repr(bad)):
                self.quotas.set_user_quota(self.admin.id, "volmarr", bad)
        with self.assertRaises(QuotaError) as caught:
            self.quotas.set_user_quota(self.admin.id, "ghost", 100)
        self.assertEqual(caught.exception.reason, "no_such_user")
        with self.assertRaises(QuotaError):
            self.quotas.set_default_user_quota(self.owner.id, 100)

    # -- visible before it bites -------------------------------
    def test_overview_states_usage_vs_limit_in_words(self):
        self.quotas.set_repo_quota(self.owner.id, "volmarr", "proj",
                                   self.u_proj + 50)
        self.quotas.set_user_quota(self.admin.id, "volmarr",
                                   self.u_total + 500)
        overview = self.overview.overview_for(self.owner.id, "volmarr")
        self.assertEqual(overview.user_usage_bytes, self.u_total)
        self.assertEqual(overview.user_quota_bytes, self.u_total + 500)
        self.assertEqual(overview.user_headroom_bytes, 500)
        self.assertFalse(overview.user_over_quota)
        words = overview_words(overview)
        self.assertIn(f"hold {self.u_total} of {self.u_total + 500} bytes",
                      words)
        self.assertIn("500 bytes remain", words)
        self.assertIn(f"volmarr/proj holds {self.u_proj} of "
                      f"{self.u_proj + 50} bytes", words)
        self.assertIn("volmarr/side", words)
        self.assertIn("no repository quota", words)
        page = render_quotas_page(overview)
        self.assertIn("<h1>Storage quotas: volmarr</h1>", page)
        self.assertIn(overview_words(overview), page)

    def test_overview_is_owner_or_admin_only(self):
        with self.assertRaises(QuotaError) as caught:
            self.overview.overview_for(self.other.id, "volmarr")
        self.assertEqual(caught.exception.reason, "permission_denied")
        self.assertEqual(
            self.overview.overview_for(self.admin.id, "volmarr").owner,
            "volmarr")

    def test_overview_names_an_already_passed_limit(self):
        self.quotas.set_user_quota(self.admin.id, "volmarr", self.u_total - 1)
        overview = self.overview.overview_for(self.owner.id, "volmarr")
        self.assertTrue(overview.user_over_quota)
        self.assertIn("over their", overview_words(overview))
        self.assertIn("new pushes will be refused", overview_words(overview))

    # -- pins ---------------------------------------------------
    def test_no_migration_no_new_taxonomy_event(self):
        self.assertEqual(db.schema_version(self.conn), 140)
        self.assertEqual(db.MIGRATIONS[-1][0], 140)
        self.assertEqual(len(AUDIT_EVENTS), 142)

if __name__ == "__main__":
    unittest.main()
