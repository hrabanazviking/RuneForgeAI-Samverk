"""S-077 acceptance battery: smart HTTP advertisement.

Acceptance (roadmap S-077): `GET /info/refs?service=git-upload-pack`
gated by read permission *before* any ref byte is built; private
repos answer anonymous callers as if absent.

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
from samverk.git_http import SmartHttpService, TransportError, pkt_line
from samverk.repositories import RepositoryStore

GIT_ENV = {
    "GIT_AUTHOR_NAME": "A U Thor", "GIT_AUTHOR_EMAIL": "a@example.com",
    "GIT_COMMITTER_NAME": "A U Thor", "GIT_COMMITTER_EMAIL": "a@example.com",
}


def git(repo: Path, *args: str, input_bytes: bytes | None = None) -> str:
    env = dict(os.environ); env.update(GIT_ENV)
    out = subprocess.run(
        ["git", f"--git-dir={repo}", *args], input=input_bytes,
        capture_output=True, env=env)
    if out.returncode != 0:
        raise AssertionError(out.stderr.decode())
    return out.stdout.decode().strip()


def seed_commit(store: RepositoryStore, owner: str, name: str) -> str:
    path = store.path_for(owner, name)
    blob = git(path, "hash-object", "-w", "--stdin", input_bytes=b"hello\n")
    tree = git(path, "mktree",
               input_bytes=f"100644 blob {blob}\thello.txt\n".encode())
    commit = git(path, "commit-tree", tree, input_bytes=b"first\n")
    git(path, "update-ref", "refs/heads/main", commit)
    return commit


def parse_pkt_lines(body: bytes) -> list[bytes]:
    lines = []
    pos = 0
    while pos < len(body):
        size = int(body[pos:pos + 4], 16)
        if size == 0:
            lines.append(b"")
            pos += 4
            continue
        lines.append(body[pos + 4:pos + size])
        pos += size
    return lines


class AdvertisementTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.data_root = Path(self._td.name)
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.other = self.accounts.register("yrsa", "correct horse battery")
        self.store = RepositoryStore(self.conn, self.data_root, self.accounts)
        self.service = SmartHttpService(
            self.conn, self.data_root, self.accounts, self.store)
        self.store.create_repository(
            self.owner.id, "volmarr", "open", visibility="public")
        self.open_commit = seed_commit(self.store, "volmarr", "open")
        self.store.create_repository(
            self.owner.id, "volmarr", "secret", visibility="private")
        self.secret_commit = seed_commit(self.store, "volmarr", "secret")

    def test_public_repo_advertises_anonymously_in_protocol_shape(self):
        resp = self.service.advertise(None, "volmarr", "open")
        self.assertEqual(
            resp.content_type,
            "application/x-git-upload-pack-advertisement")
        lines = parse_pkt_lines(resp.body)
        self.assertEqual(lines[0], b"# service=git-upload-pack\n")
        self.assertEqual(lines[1], b"")  # flush after the service line
        # The HEAD line's capabilities also *mention* the branch
        # (symref-target:), so match the ref line itself exactly:
        # "<oid> refs/heads/main" up to the capability NUL.
        ref_lines = [ln for ln in lines
                     if ln.split(b"\x00")[0].rstrip(b"\n")
                     .endswith(b" refs/heads/main")]
        self.assertEqual(len(ref_lines), 1)
        self.assertTrue(ref_lines[0].startswith(self.open_commit.encode()))
        self.assertEqual(lines[-1], b"")  # advertisement ends in flush

    def test_private_repo_is_absent_for_anonymous_and_strangers(self):
        for viewer in (None, self.other):
            with self.assertRaises(TransportError) as caught:
                self.service.advertise(viewer, "volmarr", "secret")
            self.assertEqual(caught.exception.reason, "repo_not_found")
        resp = self.service.advertise(self.owner, "volmarr", "secret")
        self.assertIn(b"refs/heads/main", resp.body)
        self.assertIn(self.secret_commit.encode(), resp.body)

    def test_missing_repo_answers_identically_to_private(self):
        for viewer in (None, self.owner):
            with self.assertRaises(TransportError) as caught:
                self.service.advertise(viewer, "volmarr", "nosuch")
            self.assertEqual(caught.exception.reason, "repo_not_found")

    def test_gate_runs_before_any_ref_byte_is_built(self):
        # Damage the private repo on disk: a gate that ran git
        # first would fail with advertise_failed (or worse, leak);
        # the permission gate must answer repo_not_found without
        # ever spawning the pack program.
        head = self.store.path_for("volmarr", "secret") / "HEAD"
        head.write_text("ref: refs/heads/gone\n")
        objects = self.store.path_for("volmarr", "secret") / "objects"
        for child in objects.iterdir():
            if child.is_dir() and child.name not in ("info", "pack"):
                for f in child.iterdir():
                    f.write_bytes(b"corrupt")
        with self.assertRaises(TransportError) as caught:
            self.service.advertise(None, "volmarr", "secret")
        self.assertEqual(caught.exception.reason, "repo_not_found")

    def test_unknown_services_are_refused_by_name(self):
        for bad in ("git-upload-archive", "dumb", "", None):
            with self.assertRaises(TransportError) as caught:
                self.service.advertise(None, "volmarr", "open", bad)
            self.assertEqual(caught.exception.reason, "service_invalid")

    def test_empty_public_repo_advertises_capabilities_and_no_refs(self):
        self.store.create_repository(
            self.owner.id, "volmarr", "fresh", visibility="public")
        resp = self.service.advertise(None, "volmarr", "fresh")
        self.assertIn(b"capabilities^{}", resp.body)
        self.assertNotIn(b"refs/heads/", resp.body)

    def test_pkt_line_helper_measures_itself(self):
        self.assertEqual(pkt_line(b"abc"), b"0007abc")
        self.assertEqual(pkt_line(b""), b"0004")


if __name__ == "__main__":
    unittest.main()
