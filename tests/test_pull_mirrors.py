"""S-329 acceptance battery: pull mirrors.

Acceptance (roadmap S-329): create a repo as a mirror of any git
URL; first sync completes before the repo advertises itself as
ready.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import os, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.pull_mirrors import (
    FAILED, PENDING, READY, PullMirrorError, PullMirrorService,
    sanitize_git_url)
from samverk.refs import RefStore
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


def make_source(base: Path, name: str = "src.git") -> tuple[Path, str]:
    src = base / name
    subprocess.run(["git", "init", "--bare", "-b", "main", str(src)],
                   check=True, capture_output=True)
    blob = git(src, "hash-object", "-w", "--stdin", input_bytes=b"hi\n")
    tree = git(src, "mktree", input_bytes=f"100644 blob {blob}\tx.txt\n".encode())
    commit = git(src, "commit-tree", tree, input_bytes=b"first\n")
    git(src, "update-ref", "refs/heads/main", commit)
    return src, commit


class PullMirrorTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        root = Path(self._td.name)
        outside = root / "outside"; outside.mkdir()
        self.src, self.commit = make_source(outside)
        self.data_root = root / "instance"; self.data_root.mkdir()
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.other = self.accounts.register("yrsa", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.data_root, self.accounts)
        self.pull = PullMirrorService(self.conn, self.data_root,
                                      self.accounts, self.repos)

    # -- the readiness law -------------------------------------------
    def test_create_runs_first_sync_before_advertising_ready(self):
        mirror = self.pull.create_pull_mirror(
            self.owner.id, "volmarr", "mir", self.src)
        self.assertEqual(mirror.state, READY)
        self.assertTrue(mirror.ready)
        path = self.repos.path_for("volmarr", "mir")
        self.assertEqual(RefStore(path).resolve("refs/heads/main"), self.commit)
        self.assertTrue(self.pull.is_ready("volmarr", "mir"))

    def test_pending_mirror_does_not_advertise_ready(self):
        mirror = self.pull.begin_pull_mirror(
            self.owner.id, "volmarr", "mir", self.src)
        self.assertEqual(mirror.state, PENDING)
        self.assertFalse(mirror.ready)
        self.assertFalse(self.pull.is_ready("volmarr", "mir"))
        advert = self.pull.advertisement("volmarr", "mir")
        self.assertIsNotNone(advert)
        self.assertFalse(advert.ready)
        self.assertIn("waiting for its first sync", advert.headline)
        # The repo exists and is listed -- it is the readiness
        # claim that is withheld, not the repository itself.
        self.assertIsNotNone(self.repos.get_repository("volmarr", "mir"))
        done = self.pull.complete_first_sync("volmarr", "mir")
        self.assertEqual(done.state, READY)
        self.assertTrue(self.pull.is_ready("volmarr", "mir"))

    def test_failed_first_sync_never_looks_ready(self):
        empty = self.data_root.parent / "outside" / "empty.git"
        subprocess.run(["git", "init", "--bare", "-b", "main", str(empty)],
                       check=True, capture_output=True)
        # An existing but unreachable-after-creation source: begin
        # against the real source, then break the source, then sync.
        mirror = self.pull.begin_pull_mirror(
            self.owner.id, "volmarr", "mir", self.src)
        self.assertFalse(mirror.ready)
        gone = self.data_root.parent / "outside" / "gone.git"
        self.src.rename(gone)
        result = self.pull.complete_first_sync("volmarr", "mir")
        self.assertEqual(result.state, FAILED)
        after = self.pull.pull_mirror_for("volmarr", "mir")
        self.assertEqual(after.state, FAILED)
        self.assertFalse(after.ready)
        self.assertTrue(after.last_detail)
        # The repository survives its failed first sync, and a
        # later sync (source restored) can still bring it ready.
        gone.rename(self.src)
        retry = self.pull.sync_pull_mirror("volmarr", "mir")
        self.assertEqual(retry.state, READY)
        self.assertTrue(self.pull.is_ready("volmarr", "mir"))

    def test_create_with_unreachable_source_is_failed_not_ready(self):
        # file:// source that exists at begin time is required, so
        # use a git:// URL on a port nothing serves: creation
        # succeeds as a record, first sync fails, never ready.
        mirror = self.pull.create_pull_mirror(
            self.owner.id, "volmarr", "netmir",
            "git://127.0.0.1:1/src.git")
        self.assertEqual(mirror.state, FAILED)
        self.assertFalse(mirror.ready)
        self.assertFalse(self.pull.is_ready("volmarr", "netmir"))

    # -- source shapes -------------------------------------------------
    def test_file_url_source_syncs_like_a_local_source(self):
        mirror = self.pull.create_pull_mirror(
            self.owner.id, "volmarr", "mir", f"file://{self.src}")
        self.assertEqual(mirror.source_kind, "local")
        self.assertEqual(mirror.state, READY)
        path = self.repos.path_for("volmarr", "mir")
        self.assertEqual(RefStore(path).resolve("refs/heads/main"), self.commit)

    def test_remote_url_is_stored_verbatim_when_clean(self):
        stored, kind, stripped = sanitize_git_url(
            "https://example.com/volmarr/repo.git")
        self.assertEqual(stored, "https://example.com/volmarr/repo.git")
        self.assertEqual(kind, "url")
        self.assertFalse(stripped)

    def test_credentials_inside_a_url_are_stripped_never_stored(self):
        secret = "s3cr3t-token-value"
        stored, kind, stripped = sanitize_git_url(
            f"https://volmarr:{secret}@example.com/volmarr/repo.git")
        self.assertTrue(stripped)
        self.assertEqual(stored, "https://example.com/volmarr/repo.git")
        self.assertNotIn(secret, stored)
        self.assertNotIn("volmarr:", stored)
        mirror = self.pull.begin_pull_mirror(
            self.owner.id, "volmarr", "mir",
            f"https://volmarr:{secret}@127.0.0.1:1/repo.git")
        self.assertTrue(mirror.credential_stripped)
        self.assertNotIn(secret, mirror.source)
        row = self.conn.execute(
            "SELECT source FROM repo_mirrors WHERE repo_id = ?",
            (mirror.repo_id,)).fetchone()
        self.assertNotIn(secret, row[0])

    def test_invalid_sources_are_refused_in_plain_words(self):
        bad = ["", "  ", "-https://example.com/x.git",
               "ext::sh -c true", "git@github.com:volmarr/repo.git",
               "relative/path.git", "ftp://example.com/repo.git",
               "https://example.com/repo.git#frag",
               "https:///no-host.git", "file:///no/such/dir.git",
               "file://otherhost/tmp/x.git"]
        for source in bad:
            with self.assertRaises(PullMirrorError, msg=source):
                sanitize_git_url(source)
        with self.assertRaises(PullMirrorError) as ctx:
            self.pull.begin_pull_mirror(
                self.owner.id, "volmarr", "mir", "ext::sh -c true")
        self.assertEqual(ctx.exception.reason, "source_invalid")
        self.assertIsNone(self.repos.get_repository("volmarr", "mir"))

    # -- bookkeeping ---------------------------------------------------
    def test_schema_and_taxonomy_are_unmoved(self):
        # S-329 itself moved neither; S-330's migration 133
        # (repo_mirrors.credential_name) has since landed, so
        # the schema pin stands at 133 -- taxonomy unmoved.
        from samverk import taxonomy
        self.assertEqual(db.schema_version(self.conn), 138)
        self.assertEqual(db.MIGRATIONS[-1][0], 138)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 138)

    def test_non_mirror_repo_has_no_advertisement(self):
        self.repos.create_repository(self.owner.id, "volmarr", "plain")
        self.assertIsNone(self.pull.pull_mirror_for("volmarr", "plain"))
        self.assertIsNone(self.pull.advertisement("volmarr", "plain"))
        self.assertFalse(self.pull.is_ready("volmarr", "plain"))
        with self.assertRaises(PullMirrorError):
            self.pull.sync_pull_mirror("volmarr", "plain")

    def test_only_the_owner_can_begin_a_pull_mirror(self):
        with self.assertRaises(PullMirrorError):
            self.pull.begin_pull_mirror(
                self.other.id, "volmarr", "mir", self.src)
        self.assertIsNone(self.repos.get_repository("volmarr", "mir"))

    def test_list_pull_mirrors_shows_states_honestly(self):
        self.pull.create_pull_mirror(self.owner.id, "volmarr", "one", self.src)
        self.pull.begin_pull_mirror(self.owner.id, "volmarr", "two", self.src)
        listed = {m.full_name: m.state
                  for m in self.pull.list_pull_mirrors("volmarr")}
        self.assertEqual(listed, {"volmarr/one": READY,
                                  "volmarr/two": PENDING})


if __name__ == "__main__":
    unittest.main()
