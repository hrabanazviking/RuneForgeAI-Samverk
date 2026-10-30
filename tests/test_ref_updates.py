"""S-053 acceptance battery: atomic ref updates.

Acceptance (roadmap S-053): branch create/delete/rename
through `update-ref` with lock discipline; the
concurrent-push race test — many writers CAS the same ref
from the same expected value, exactly one wins.

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk import db
from samverk.accounts import AccountStore
from samverk.refs import RefError, RefStore
from samverk.repositories import RepositoryStore

GIT_ENV = {
    "GIT_AUTHOR_NAME": "A U Thor", "GIT_AUTHOR_EMAIL": "a@example.com",
    "GIT_COMMITTER_NAME": "A U Thor", "GIT_COMMITTER_EMAIL": "a@example.com",
}


def git(repo: Path, *args: str, input_bytes: bytes | None = None) -> str:
    env = dict(os.environ); env.update(GIT_ENV)
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         input=input_bytes, capture_output=True, env=env)
    if out.returncode != 0:
        raise AssertionError(out.stderr.decode())
    return out.stdout.decode().strip()


class RefUpdateTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.data_root = Path(self._td.name)
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.store = RepositoryStore(self.conn, self.data_root, self.accounts)
        self.store.create_repository(self.owner.id, "volmarr", "samverk")
        self.path = self.store.path_for("volmarr", "samverk")
        self.refs = RefStore(self.path)
        blob = git(self.path, "hash-object", "-w", "--stdin", input_bytes=b"x\n")
        tree = git(self.path, "mktree",
                   input_bytes=f"100644 blob {blob}\tx.txt\n".encode())
        self.c1 = git(self.path, "commit-tree", tree, input_bytes=b"one\n")
        self.c2 = git(self.path, "commit-tree", tree, "-p", self.c1,
                      input_bytes=b"two\n")
        git(self.path, "update-ref", "refs/heads/main", self.c1)

    def test_create_cas_delete_cycle(self):
        self.refs.create_branch("topic", self.c1)
        self.assertEqual(self.refs.resolve("refs/heads/topic"), self.c1)
        with self.assertRaises(RefError):
            self.refs.create_branch("topic", self.c2)  # already exists
        # CAS with the right old value moves; with a stale one refuses.
        self.refs.update_ref("refs/heads/topic", self.c2, expected_old=self.c1)
        with self.assertRaises(RefError) as caught:
            self.refs.update_ref("refs/heads/topic", self.c1, expected_old=self.c1)
        self.assertEqual(caught.exception.reason, "stale_ref")
        self.assertEqual(self.refs.resolve("refs/heads/topic"), self.c2)
        self.refs.delete_branch("topic", expected_old=self.c2)
        self.assertIsNone(self.refs.resolve("refs/heads/topic"))

    def test_rename_preserves_the_commit(self):
        renamed = self.refs.rename_branch("main", "trunk")
        self.assertEqual(renamed.oid, self.c1)
        self.assertIsNone(self.refs.resolve("refs/heads/main"))
        self.assertEqual(self.refs.resolve("refs/heads/trunk"), self.c1)
        with self.assertRaises(RefError):
            self.refs.rename_branch("trunk", "trunk")

    def test_concurrent_cas_exactly_one_writer_wins(self):
        # Ten candidate successor commits, one starting value.
        candidates = []
        parent = self.c1
        for i in range(10):
            nxt = git(self.path, "commit-tree", self._tree(), "-p", parent,
                      input_bytes=f"race {i}\n".encode())
            candidates.append(nxt)
            parent = nxt  # chain not required; distinct commits suffice
        wins, losses = [], []

        def attempt(oid):
            try:
                self.refs.update_ref(
                    "refs/heads/main", oid, expected_old=self.c1)
                wins.append(oid)
            except RefError:
                losses.append(oid)

        threads = [threading.Thread(target=attempt, args=(c,)) for c in candidates]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(wins), 1, f"winners: {wins}")
        self.assertEqual(len(losses), 9)
        self.assertEqual(self.refs.resolve("refs/heads/main"), wins[0])

    def _tree(self):
        blob = git(self.path, "hash-object", "-w", "--stdin", input_bytes=b"x\n")
        return git(self.path, "mktree",
                   input_bytes=f"100644 blob {blob}\tx.txt\n".encode())


if __name__ == "__main__":
    unittest.main()
