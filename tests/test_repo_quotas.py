"""S-068 acceptance battery: repository quotas.

Acceptance (roadmap S-068): size quota enforced at receive
time with a clear refusal message.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import os, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.repo_quotas import QuotaError, QuotaService
from samverk.repositories import RepositoryStore

def git(repo: Path, *args: str, input_bytes: bytes | None = None) -> str:
    env = dict(os.environ)
    env.update({"GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@e.c",
                "GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": "a@e.c"})
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         input=input_bytes, capture_output=True, env=env)
    if out.returncode != 0:
        raise AssertionError(out.stderr.decode())
    return out.stdout.decode().strip()

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
        self.repos.create_repository(self.owner.id, "volmarr", "proj",
                                     visibility="private")
        self.path = self.repos.path_for("volmarr", "proj")
        blob = git(self.path, "hash-object", "-w", "--stdin",
                   input_bytes=b"x" * 1000)
        tree = git(self.path, "mktree",
                   input_bytes=f"100644 blob {blob}\tx.txt\n".encode())
        commit = git(self.path, "commit-tree", tree, input_bytes=b"first\n")
        git(self.path, "update-ref", "refs/heads/main", commit)
        self.quotas = QuotaService(self.conn, self.data_root,
                                   self.accounts, self.repos)
        self.usage = self.quotas.usage_bytes("volmarr", "proj")
        self.assertGreater(self.usage, 1000)

    def test_no_quota_means_unlimited(self):
        self.assertIsNone(self.quotas.effective_quota("volmarr", "proj"))
        decision = self.quotas.check_receive("volmarr", "proj", 10**12)
        self.assertTrue(decision.allowed)
        self.assertIsNone(decision.quota_bytes)
        self.assertEqual(
            self.quotas.enforce_receive("volmarr", "proj", 10**12), decision)

    def test_quota_enforced_at_receive_with_a_clear_message(self):
        quota = self.usage + 100
        self.quotas.set_repo_quota(self.owner.id, "volmarr", "proj", quota)
        fits = self.quotas.check_receive("volmarr", "proj", 100)
        self.assertTrue(fits.allowed)
        over = self.quotas.check_receive("volmarr", "proj", 101)
        self.assertFalse(over.allowed)
        self.assertIn("Repository quota exceeded for volmarr/proj",
                      over.message)
        self.assertIn(str(quota), over.message)       # the limit, in numbers
        self.assertIn(str(self.usage), over.message)  # what it holds now
        self.assertIn("101", over.message)            # what the push adds
        with self.assertRaises(QuotaError) as caught:
            self.quotas.enforce_receive("volmarr", "proj", 101)
        self.assertEqual(caught.exception.reason, "quota_exceeded")
        self.assertEqual(str(caught.exception), over.message)

    def test_setting_and_clearing_is_owner_or_admin_only(self):
        with self.assertRaises(QuotaError) as caught:
            self.quotas.set_repo_quota(self.other.id, "volmarr", "proj", 100)
        self.assertEqual(caught.exception.reason, "permission_denied")
        self.assertEqual(
            self.quotas.set_repo_quota(self.admin.id, "volmarr", "proj", 5000),
            5000)
        self.assertIsNone(
            self.quotas.set_repo_quota(self.owner.id, "volmarr", "proj", None))
        self.assertIsNone(self.quotas.effective_quota("volmarr", "proj"))

    def test_instance_default_applies_and_per_repo_quota_wins(self):
        with self.assertRaises(QuotaError):
            self.quotas.set_default_quota(self.owner.id, 10**6)
        self.assertEqual(
            self.quotas.set_default_quota(self.admin.id, self.usage + 10),
            self.usage + 10)
        self.assertTrue(self.quotas.check_receive("volmarr", "proj", 10).allowed)
        self.assertFalse(self.quotas.check_receive("volmarr", "proj", 11).allowed)
        self.quotas.set_repo_quota(self.owner.id, "volmarr", "proj",
                                   self.usage + 1000)
        self.assertTrue(self.quotas.check_receive("volmarr", "proj", 500).allowed)
        self.quotas.set_default_quota(self.admin.id, None)
        self.assertEqual(self.quotas.effective_quota("volmarr", "proj"),
                         self.usage + 1000)

    def test_validation(self):
        for bad in (-1, 1.5, "100", True):
            with self.assertRaises(QuotaError, msg=repr(bad)):
                self.quotas.set_repo_quota(self.owner.id, "volmarr", "proj", bad)
        with self.assertRaises(QuotaError):
            self.quotas.check_receive("volmarr", "proj", -5)
        with self.assertRaises(QuotaError) as caught:
            self.quotas.check_receive("volmarr", "ghost", 1)
        self.assertEqual(caught.exception.reason, "no_such_repo")

if __name__ == "__main__":
    unittest.main()
