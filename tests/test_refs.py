"""S-052 acceptance battery: ref listing and resolution.

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
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


class RefListingTests(unittest.TestCase):
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
        git(self.path, "update-ref", "refs/heads/main", self.c2)
        git(self.path, "update-ref", "refs/heads/topic", self.c1)
        git(self.path, "update-ref", "refs/tags/v1", self.c1)
        # Annotated tag: peeled id must come through.
        self.tag_obj = git(self.path, "mktag", input_bytes=(
            f"object {self.c2}\ntype commit\ntag v2\n"
            "tagger A U Thor <a@example.com> 1700000000 +0000\n\nrelease\n").encode())

        git(self.path, "update-ref", "refs/tags/v2", self.tag_obj)

    def test_listing_branches_tags_and_peeling(self):
        branches = {r.short: r.oid for r in self.refs.list_branches()}
        self.assertEqual(branches, {"main": self.c2, "topic": self.c1})
        tags = {r.short: r for r in self.refs.list_tags()}
        self.assertEqual(tags["v1"].oid, self.c1)
        self.assertEqual(tags["v2"].oid, self.tag_obj)
        self.assertEqual(tags["v2"].peeled_oid, self.c2)
        self.assertTrue(all(r.name.startswith("refs/") for r in self.refs.list_refs()))

    def test_resolution_and_head(self):
        self.assertEqual(self.refs.resolve("refs/heads/main"), self.c2)
        self.assertEqual(self.refs.resolve("HEAD"), self.c2)
        self.assertEqual(self.refs.head_ref(), "refs/heads/main")
        self.assertEqual(self.refs.head_oid(), self.c2)
        self.assertIsNone(self.refs.resolve("refs/heads/nope"))
        with self.assertRaises(RefError):
            self.refs.resolve("--upload-pack=touch /tmp/pwn")

    def test_empty_repo_lists_nothing_but_head_points_at_default(self):
        self.store.create_repository(self.owner.id, "volmarr", "empty")
        empty = RefStore(self.store.path_for("volmarr", "empty"))
        self.assertEqual(empty.list_refs(), [])
        self.assertEqual(empty.head_ref(), "refs/heads/main")
        self.assertIsNone(empty.head_oid())


if __name__ == "__main__":
    unittest.main()
