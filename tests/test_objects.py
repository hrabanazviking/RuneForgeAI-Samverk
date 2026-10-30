"""S-051 acceptance battery: object reading.

Acceptance (roadmap S-051): blob/tree/commit reads via
`cat-file` batch process; a large-object-count repo reads
stay within the latency budget (proven here at 2,000 objects
in a single batch, with a generous ceiling that a
spawn-per-object implementation would blow past).

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk import db
from samverk.accounts import AccountStore
from samverk.objects import ObjectError, ObjectReader
from samverk.repositories import RepositoryStore

GIT_ENV = {
    "GIT_AUTHOR_NAME": "A U Thor", "GIT_AUTHOR_EMAIL": "a@example.com",
    "GIT_COMMITTER_NAME": "A U Thor", "GIT_COMMITTER_EMAIL": "a@example.com",
}


def git(repo: Path, *args: str, input_bytes: bytes | None = None) -> str:
    import os
    env = dict(os.environ); env.update(GIT_ENV)
    out = subprocess.run(
        ["git", f"--git-dir={repo}", *args], input=input_bytes,
        capture_output=True, env=env)
    if out.returncode != 0:
        raise AssertionError(out.stderr.decode())
    return out.stdout.decode().strip()


class ObjectReadingTests(unittest.TestCase):
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
        self.reader = ObjectReader(self.path)
        # Fixture history built with git plumbing directly.
        self.blob_oid = git(self.path, "hash-object", "-w", "--stdin",
                            input_bytes=b"hello samverk\n")
        tree_input = f"100644 blob {self.blob_oid}\thello.txt\n".encode()
        self.tree_oid = git(self.path, "mktree", input_bytes=tree_input)
        self.commit_oid = git(
            self.path, "commit-tree", self.tree_oid, input_bytes=b"first\n")
        self.commit2_oid = git(
            self.path, "commit-tree", self.tree_oid, "-p", self.commit_oid,
            input_bytes=b"second\n")

    def test_blob_tree_commit_reads(self):
        self.assertEqual(self.reader.read_blob(self.blob_oid), b"hello samverk\n")
        entries = self.reader.read_tree(self.tree_oid)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].name, "hello.txt")
        self.assertEqual(entries[0].oid, self.blob_oid)
        self.assertEqual(entries[0].type, "blob")
        commit = self.reader.read_commit(self.commit_oid)
        self.assertEqual(commit.tree, self.tree_oid)
        self.assertEqual(commit.parents, ())
        self.assertIn("first", commit.message)
        commit2 = self.reader.read_commit(self.commit2_oid)
        self.assertEqual(commit2.parents, (self.commit_oid,))

    def test_missing_and_invalid_objects_are_named_refusals(self):
        with self.assertRaises(ObjectError) as caught:
            self.reader.read_object("0" * 40)
        self.assertEqual(caught.exception.reason, "object_not_found")
        with self.assertRaises(ObjectError):
            self.reader.read_object("--upload-pack=touch /tmp/pwn")
        with self.assertRaises(ObjectError):
            self.reader.read_blob(self.tree_oid)  # wrong type

    def test_batch_read_of_many_objects_stays_fast(self):
        # 2,000 distinct blobs written through a single git call.
        with tempfile.TemporaryDirectory() as td:
            files = []
            for i in range(2000):
                f = Path(td) / f"b{i}"
                f.write_bytes(f"payload-{i}\n".encode())
                files.append(str(f))
            out = subprocess.run(
                ["git", f"--git-dir={self.path}", "hash-object", "-w", *files],
                capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            oids = out.stdout.split()
        self.assertEqual(len(oids), 2000)
        start = time.time()
        objects = self.reader.read_objects(oids)
        elapsed = time.time() - start
        self.assertEqual(len(objects), 2000)
        self.assertEqual(objects[123].data, b"payload-123\n")
        self.assertLess(elapsed, 5.0,
                        f"batch read took {elapsed:.2f}s — spawn-per-object?")


if __name__ == "__main__":
    unittest.main()
