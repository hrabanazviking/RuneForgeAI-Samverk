"""S-340 acceptance battery: LFS mirror.

Acceptance (roadmap S-340): LFS objects (S-060) sync
with their repos; a mirror without its LFS objects
reports itself incomplete.
"""
from __future__ import annotations
import subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.db import schema_version
from samverk.lfs_mirror import (
    PHASE_LFS, LFSMirrorError, LFSMirrorService, judge_completeness,
    plan_lfs_sync, render_lfs_completeness_page, render_lfs_mirror_page)
from samverk.lfs_store import LFSPointer, LFSStore, make_pointer, oid_for
from samverk.mirrors import MirrorService
from samverk.repositories import RepositoryStore

DATA = b"large-binary-payload" * 10
OID = oid_for(DATA)
DATA2 = b"second-payload" * 7
OID2 = oid_for(DATA2)

def git(repo: Path, *args: str, input_bytes: bytes | None = None) -> str:
    import os
    env = dict(os.environ)
    env.update({"GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@e.c",
                "GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": "a@e.c"})
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         input=input_bytes, capture_output=True, env=env)
    if out.returncode != 0:
        raise AssertionError(out.stderr.decode())
    return out.stdout.decode().strip()

def make_source(base: Path, pointers: list[tuple[str, str, int]],
                name: str = "src.git") -> Path:
    src = base / name
    subprocess.run(["git", "init", "--bare", "-b", "main", str(src)],
                   check=True, capture_output=True)
    lines = []
    for fname, oid, size in pointers:
        blob = git(src, "hash-object", "-w", "--stdin",
                   input_bytes=make_pointer(oid, size))
        lines.append(f"100644 blob {blob}\t{fname}\n")
    tree = git(src, "mktree", input_bytes="".join(lines).encode())
    commit = git(src, "commit-tree", tree, input_bytes=b"first\n")
    git(src, "update-ref", "refs/heads/main", commit)
    return src

class LFSMirrorTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        root = Path(self._td.name)
        self.outside = root / "outside"; self.outside.mkdir()
        self.data_root = root / "instance"; self.data_root.mkdir()
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.data_root, self.accounts)
        self.mirrors = MirrorService(self.conn, self.data_root,
                                     self.accounts, self.repos)
        self.lfs = LFSMirrorService(self.conn, self.data_root,
                                    self.accounts, self.repos)

    def make_mirror(self, pointers, store_oids=(), name="mir"):
        src = make_source(self.outside, pointers,
                          name=f"src-{name}.git")
        store = LFSStore(src)
        payloads = {OID: DATA, OID2: DATA2}
        for oid in store_oids:
            store.put(oid, payloads[oid], expected_size=len(payloads[oid]))
        self.mirrors.create_mirror(self.owner.id, "volmarr", name, src)
        self.assertEqual(self.mirrors.sync_mirror("volmarr", name).status, "ok")
        return src

    # -- pins ------------------------------------------------------
    def test_schema_and_taxonomy_pins_unchanged(self):
        self.assertEqual(schema_version(self.conn), 139)
        self.assertEqual(db.MIGRATIONS[-1][0], 139)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 138)

    # -- pure judgements --------------------------------------------
    def test_judge_complete_when_all_present(self):
        v = judge_completeness("o/r", [LFSPointer(OID, len(DATA))], [OID])
        self.assertTrue(v.complete); self.assertTrue(v.healthy)
        self.assertEqual(v.state, "complete")

    def test_judge_missing_is_incomplete_and_named(self):
        v = judge_completeness("o/r", [LFSPointer(OID, len(DATA))], [])
        self.assertFalse(v.complete); self.assertFalse(v.healthy)
        self.assertEqual(v.missing, (OID,))
        self.assertEqual(v.missing_bytes, len(DATA))
        self.assertIn("incomplete", v.headline)

    def test_judge_corrupt_counts_as_not_usable(self):
        v = judge_completeness("o/r", [LFSPointer(OID, len(DATA))],
                               [OID], [OID])
        self.assertFalse(v.complete)
        self.assertEqual(v.corrupt, (OID,)); self.assertEqual(v.present, ())

    def test_judge_dedupes_pointers_by_oid(self):
        p = LFSPointer(OID, len(DATA))
        v = judge_completeness("o/r", [p, p], [OID])
        self.assertEqual(v.expected, 1)

    def test_judge_no_pointers_needs_no_objects(self):
        v = judge_completeness("o/r", [], [])
        self.assertTrue(v.complete); self.assertEqual(v.state, "no_lfs")

    def test_plan_is_missing_plus_corrupt(self):
        ps = [LFSPointer(OID, len(DATA)), LFSPointer(OID2, len(DATA2))]
        self.assertEqual(plan_lfs_sync(ps, [OID]), (OID2,))
        self.assertEqual(plan_lfs_sync(ps, [OID, OID2], [OID]), (OID,))
        self.assertEqual(plan_lfs_sync(ps, [OID, OID2]), ())

    # -- completeness over real repos ---------------------------------
    def test_mirror_without_objects_reports_incomplete(self):
        self.make_mirror([("big.bin", OID, len(DATA))], store_oids=(OID,))
        v = self.lfs.completeness_for("volmarr", "mir")
        self.assertFalse(v.complete); self.assertFalse(v.healthy)
        self.assertEqual(v.missing, (OID,))
        self.assertIn("incomplete", v.headline)
        page = render_lfs_completeness_page(v)
        self.assertIn("incomplete", page); self.assertIn("Healthy: no", page)
        self.assertIn(OID, page)

    def test_honest_status_not_healthy_despite_green_git_sync(self):
        self.make_mirror([("big.bin", OID, len(DATA))], store_oids=(OID,))
        status = self.lfs.honest_status("volmarr", "mir")
        self.assertTrue(status.sync_healthy)
        self.assertFalse(status.healthy)
        self.assertIn("not healthy", status.headline)

    def test_sync_lfs_copies_objects_and_completes(self):
        self.make_mirror([("big.bin", OID, len(DATA)),
                          ("two.bin", OID2, len(DATA2))],
                         store_oids=(OID, OID2))
        report = self.lfs.sync_lfs("volmarr", "mir")
        self.assertEqual(report.copied, 2)
        self.assertTrue(report.complete)
        store = LFSStore(self.repos.path_for("volmarr", "mir"))
        self.assertEqual(store.read(OID), DATA)
        self.assertEqual(store.read(OID2), DATA2)
        self.assertTrue(self.lfs.honest_status("volmarr", "mir").healthy)
        runs = self.lfs.runs_for("volmarr/mir")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].phase, PHASE_LFS)
        self.assertEqual(runs[0].state, "verified")
        self.assertEqual(runs[0].refs_matched, 2)
        page = render_lfs_mirror_page(report)
        self.assertIn("Healthy: yes", page)

    def test_sync_lfs_second_run_copies_nothing(self):
        self.make_mirror([("big.bin", OID, len(DATA))], store_oids=(OID,))
        self.lfs.sync_lfs("volmarr", "mir")
        self.assertEqual(self.lfs.sync_lfs("volmarr", "mir").copied, 0)

    def test_source_missing_object_stays_missing_and_is_named(self):
        self.make_mirror([("big.bin", OID, len(DATA))], store_oids=())
        report = self.lfs.sync_lfs("volmarr", "mir")
        self.assertEqual(report.copied, 0)
        self.assertFalse(report.complete)
        self.assertEqual(report.source_missing, (OID,))
        self.assertEqual(report.after.missing, (OID,))
        self.assertIn("does not hold", report.detail)
        runs = self.lfs.runs_for("volmarr/mir")
        self.assertEqual(runs[-1].state, "failed")
        self.assertEqual(runs[-1].refs_missing, 1)

    def test_corrupt_object_is_incomplete_and_repaired_by_sync(self):
        self.make_mirror([("big.bin", OID, len(DATA))], store_oids=(OID,))
        path = self.repos.path_for("volmarr", "mir")
        store = LFSStore(path)
        store.put(OID, DATA, expected_size=len(DATA))
        store.path_for(OID).write_bytes(b"rotted-bytes")
        v = self.lfs.completeness_for("volmarr", "mir")
        self.assertEqual(v.corrupt, (OID,))
        self.assertFalse(v.complete)
        report = self.lfs.sync_lfs("volmarr", "mir")
        self.assertTrue(report.complete)
        self.assertEqual(store.read(OID), DATA)

    def test_mirror_with_no_lfs_pointers_is_not_incomplete(self):
        src = self.outside / "plain.git"
        subprocess.run(["git", "init", "--bare", "-b", "main", str(src)],
                       check=True, capture_output=True)
        blob = git(src, "hash-object", "-w", "--stdin", input_bytes=b"hi\n")
        tree = git(src, "mktree",
                   input_bytes=f"100644 blob {blob}\tx.txt\n".encode())
        commit = git(src, "commit-tree", tree, input_bytes=b"first\n")
        git(src, "update-ref", "refs/heads/main", commit)
        self.mirrors.create_mirror(self.owner.id, "volmarr", "plainmir", src)
        self.assertEqual(
            self.mirrors.sync_mirror("volmarr", "plainmir").status, "ok")
        v = self.lfs.completeness_for("volmarr", "plainmir")
        self.assertEqual(v.state, "no_lfs"); self.assertTrue(v.complete)
        report = self.lfs.sync_lfs("volmarr", "plainmir")
        self.assertEqual(report.copied, 0); self.assertTrue(report.complete)
        self.assertEqual(report.run.state, "verified")

    def test_sync_lfs_refuses_non_mirror(self):
        self.repos.create_repository(self.owner.id, "volmarr", "plain")
        with self.assertRaises(LFSMirrorError) as ctx:
            self.lfs.sync_lfs("volmarr", "plain")
        self.assertEqual(ctx.exception.reason, "not_a_mirror")

    def test_completeness_unknown_repo_refused(self):
        with self.assertRaises(LFSMirrorError) as ctx:
            self.lfs.completeness_for("volmarr", "nope")
        self.assertEqual(ctx.exception.reason, "no_such_repo")

    def test_url_source_sync_is_recorded_failed_in_plain_words(self):
        self.repos.create_repository(self.owner.id, "volmarr", "netmir")
        path = self.repos.path_for("volmarr", "netmir")
        blob = git(path, "hash-object", "-w", "--stdin",
                   input_bytes=make_pointer(OID, len(DATA)))
        tree = git(path, "mktree",
                   input_bytes=f"100644 blob {blob}\tbig.bin\n".encode())
        commit = git(path, "commit-tree", tree, input_bytes=b"first\n")
        git(path, "update-ref", "refs/heads/main", commit)
        self.mirrors.attach_mirror(self.owner.id, "volmarr", "netmir",
                                   "https://example.com/src.git")
        report = self.lfs.sync_lfs("volmarr", "netmir")
        self.assertFalse(report.complete)
        self.assertIn("remote URL", report.detail)
        self.assertEqual(self.lfs.runs_for("volmarr/netmir")[-1].state,
                         "failed")

if __name__ == "__main__":
    unittest.main()
