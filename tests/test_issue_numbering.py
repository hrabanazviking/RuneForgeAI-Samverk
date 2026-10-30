"""S-121 acceptance battery: issue model and numbering.

Acceptance (roadmap S-121): per-repo sequential numbers
shared with PRs (the GitHub habit users rely on: `#n` is
unambiguous in a repo).

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, threading, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.issues import IssueError, IssueStore
from samverk.repositories import RepositoryStore

class IssueNumberingTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.db_path = self.root / "samverk.db"
        self.conn = db.init_db(self.db_path); self.addCleanup(self.conn.close)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.other = self.accounts.register("yrsa", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.issues = IssueStore(self.conn, self.repos, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "alpha")
        self.repos.create_repository(self.owner.id, "volmarr", "beta")
        self.repos.create_repository(self.other.id, "yrsa", "alpha")

    def test_numbers_are_sequential_per_repo(self):
        got = [self.issues.claim_number("volmarr", "alpha", "issue",
                                        self.owner.id).number
               for _ in range(3)]
        self.assertEqual(got, [1, 2, 3])
        self.assertEqual(self.issues.last_number("volmarr", "alpha"), 3)

    def test_sequences_are_independent_across_repos(self):
        self.issues.claim_number("volmarr", "alpha", "issue", self.owner.id)
        self.issues.claim_number("volmarr", "alpha", "issue", self.owner.id)
        first_beta = self.issues.claim_number(
            "volmarr", "beta", "issue", self.owner.id)
        first_yrsa = self.issues.claim_number(
            "yrsa", "alpha", "issue", self.other.id)
        self.assertEqual(first_beta.number, 1)
        self.assertEqual(first_yrsa.number, 1)

    def test_sequence_is_shared_between_issues_and_prs(self):
        a = self.issues.claim_number("volmarr", "alpha", "issue", self.owner.id)
        b = self.issues.claim_number(
            "volmarr", "alpha", "pull_request", self.owner.id)
        c = self.issues.claim_number("volmarr", "alpha", "issue", self.owner.id)
        self.assertEqual((a.number, b.number, c.number), (1, 2, 3))
        self.assertEqual(
            self.issues.resolve_number("volmarr", "alpha", 1).kind, "issue")
        self.assertEqual(
            self.issues.resolve_number("volmarr", "alpha", 2).kind,
            "pull_request")
        self.assertEqual(
            self.issues.resolve_number("volmarr", "alpha", 3).kind, "issue")
        self.assertIsNone(self.issues.resolve_number("volmarr", "alpha", 4))
        self.assertTrue(self.issues.exists("volmarr", "alpha", 2))
        self.assertFalse(self.issues.exists("volmarr", "beta", 1))

    def test_numbers_are_never_reused(self):
        item = self.issues.claim_number(
            "volmarr", "alpha", "issue", self.owner.id)
        with self.conn:
            self.conn.execute("DELETE FROM issues WHERE id = ?", (item.row_id,))
        nxt = self.issues.claim_number(
            "volmarr", "alpha", "issue", self.owner.id)
        self.assertEqual(nxt.number, 2)

    def test_invalid_claims_refuse_and_spend_nothing(self):
        for kind, author, owner, repo, reason in (
                ("wiki", self.owner.id, "volmarr", "alpha", "kind_invalid"),
                ("issue", 99999, "volmarr", "alpha", "no_such_user"),
                ("issue", self.owner.id, "volmarr", "missing", "repo_not_found")):
            with self.assertRaises(IssueError) as caught:
                self.issues.claim_number(owner, repo, kind, author)
            self.assertEqual(caught.exception.reason, reason)
        self.assertEqual(self.issues.last_number("volmarr", "alpha"), 0)
        self.assertFalse(self.issues.exists("volmarr", "alpha", 1))

    def test_concurrent_claims_on_separate_connections_are_unique(self):
        results, errors = [], []
        def claim():
            try:
                conn = db.init_db(self.db_path)
                try:
                    store = IssueStore(
                        conn, RepositoryStore(conn, self.root, AccountStore(conn)),
                        AccountStore(conn))
                    results.append(store.claim_number(
                        "volmarr", "alpha", "issue", self.owner.id).number)
                finally:
                    conn.close()
            except Exception as exc:  # collected, asserted below
                errors.append(exc)
        threads = [threading.Thread(target=claim) for _ in range(20)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(errors, [])
        self.assertEqual(sorted(results), list(range(1, 21)))

if __name__ == "__main__":
    unittest.main()
