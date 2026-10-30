"""S-063 acceptance battery: archive downloads.

Acceptance (roadmap S-063): zip and tar.gz of any ref via
`git archive`, streamed, counted; checksum-stable for a
fixed ref.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import hashlib, io, os, subprocess, sys, tarfile, tempfile, unittest, zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.archives import ArchiveError, ArchiveService
from samverk.repositories import RepositoryStore

GIT_ENV = {
    "GIT_AUTHOR_NAME": "A U Thor", "GIT_AUTHOR_EMAIL": "a@example.com",
    "GIT_COMMITTER_NAME": "A U Thor", "GIT_COMMITTER_EMAIL": "a@example.com",
    "GIT_AUTHOR_DATE": "2020-01-01T00:00:00Z",
    "GIT_COMMITTER_DATE": "2020-01-01T00:00:00Z",
}

def git(repo: Path, *args: str, input_bytes: bytes | None = None) -> str:
    env = dict(os.environ); env.update(GIT_ENV)
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         input=input_bytes, capture_output=True, env=env)
    if out.returncode != 0:
        raise AssertionError(out.stderr.decode())
    return out.stdout.decode().strip()

def commit_file(repo: Path, name: str, data: bytes, msg: str,
                parent: str | None = None) -> str:
    blob = git(repo, "hash-object", "-w", "--stdin", input_bytes=data)
    tree = git(repo, "mktree", input_bytes=f"100644 blob {blob}\t{name}\n".encode())
    args = ["commit-tree", tree]
    if parent:
        args += ["-p", parent]
    return git(repo, *args, input_bytes=msg.encode())

class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.data_root = Path(self._td.name)
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.stranger = self.accounts.register("yrsa", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.data_root, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "arch",
                                     visibility="private")
        self.path = self.repos.path_for("volmarr", "arch")
        self.c1 = commit_file(self.path, "hello.txt", b"hello samverk\n", "first\n")
        git(self.path, "update-ref", "refs/heads/main", self.c1)
        git(self.path, "update-ref", "refs/tags/v1", self.c1)
        self.archives = ArchiveService(self.conn, self.data_root,
                                       self.accounts, self.repos)

    def test_zip_of_fixed_ref_is_checksum_stable_and_counted(self):
        s1, data1 = self.archives.download_bytes(self.owner, "volmarr", "arch", "main", "zip")
        s2, data2 = self.archives.download_bytes(self.owner, "volmarr", "arch", "main", "zip")
        self.assertEqual(data1, data2)
        self.assertEqual(s1.sha256, s2.sha256)
        self.assertEqual(s1.sha256, hashlib.sha256(data1).hexdigest())
        self.assertEqual(s1.bytes_counted, len(data1))
        self.assertTrue(s1.completed)
        self.assertEqual(s1.filename, "arch-main.zip")
        self.assertEqual(s1.content_type, "application/zip")
        self.assertEqual(s1.oid, self.c1)
        with zipfile.ZipFile(io.BytesIO(data1)) as zf:
            names = zf.namelist()
            self.assertIn("arch-main/hello.txt", names)
            self.assertEqual(zf.read("arch-main/hello.txt"), b"hello samverk\n")

    def test_tar_gz_of_tag_is_checksum_stable_and_readable(self):
        s1, data1 = self.archives.download_bytes(self.owner, "volmarr", "arch", "v1", "tar.gz")
        s2, data2 = self.archives.download_bytes(self.owner, "volmarr", "arch", "refs/tags/v1", "tar.gz")
        self.assertEqual(s1.sha256, s2.sha256)
        self.assertEqual(s1.filename, "arch-v1.tar.gz")
        self.assertEqual(s1.content_type, "application/gzip")
        with tarfile.open(fileobj=io.BytesIO(data1), mode="r:gz") as tf:
            member = tf.getmember("arch-v1/hello.txt")
            self.assertEqual(tf.extractfile(member).read(), b"hello samverk\n")

    def test_streaming_yields_chunks_and_write_to_counts(self):
        payload = b"".join(hashlib.sha256(f"block-{i}".encode()).digest() for i in range(10000))
        big = commit_file(self.path, "big.bin", payload, "big\n", parent=self.c1)
        git(self.path, "update-ref", "refs/heads/main", big)
        stream = self.archives.open_archive(self.owner, "volmarr", "arch", "main", "zip")
        chunks = list(stream)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(isinstance(c, bytes) and c for c in chunks))
        self.assertEqual(sum(len(c) for c in chunks), stream.bytes_counted)
        out = io.BytesIO()
        stream2 = self.archives.open_archive(self.owner, "volmarr", "arch", "main", "zip")
        written = stream2.write_to(out)
        self.assertEqual(written, stream2.bytes_counted)
        self.assertEqual(out.getvalue(), b"".join(chunks))

    def test_permission_gate_private_hidden_public_open(self):
        for viewer in (self.stranger, None):
            with self.assertRaises(ArchiveError) as caught:
                self.archives.open_archive(viewer, "volmarr", "arch", "main", "zip")
            self.assertEqual(caught.exception.reason, "repo_not_found")
        with self.assertRaises(ArchiveError) as caught:
            self.archives.open_archive(self.owner, "volmarr", "ghost", "main", "zip")
        self.assertEqual(caught.exception.reason, "repo_not_found")
        self.repos.update_metadata(self.owner.id, "volmarr", "arch", visibility="public")
        stream, data = self.archives.download_bytes(None, "volmarr", "arch", "main", "zip")
        self.assertGreater(len(data), 0)
        self.assertTrue(stream.completed)

    def test_unknown_ref_bad_format_and_flag_refusals(self):
        with self.assertRaises(ArchiveError) as caught:
            self.archives.open_archive(self.owner, "volmarr", "arch", "nope", "zip")
        self.assertEqual(caught.exception.reason, "ref_not_found")
        with self.assertRaises(ArchiveError) as caught:
            self.archives.open_archive(self.owner, "volmarr", "arch", "main", "rar")
        self.assertEqual(caught.exception.reason, "format_invalid")
        for bad in ("--upload-pack=touch /tmp/pwn", "-c", "../main"):
            with self.assertRaises(ArchiveError):
                self.archives.open_archive(self.owner, "volmarr", "arch", bad, "zip")
        self.assertFalse(Path("/tmp/pwn").exists())

    def test_different_ref_different_checksum(self):
        _, data_main = self.archives.download_bytes(self.owner, "volmarr", "arch", "main", "zip")
        c2 = commit_file(self.path, "hello.txt", b"changed\n", "second\n", parent=self.c1)
        git(self.path, "update-ref", "refs/heads/next", c2)
        s_next, _ = self.archives.download_bytes(self.owner, "volmarr", "arch", "next", "zip")
        s_main, _ = self.archives.download_bytes(self.owner, "volmarr", "arch", "main", "zip")
        self.assertNotEqual(s_next.sha256, s_main.sha256)
        self.assertEqual(s_main.sha256, hashlib.sha256(data_main).hexdigest())

if __name__ == "__main__":
    unittest.main()
