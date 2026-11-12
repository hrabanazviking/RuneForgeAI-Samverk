"""S-291 acceptance battery: scan on push.

Acceptance (roadmap S-291): Scan on push -- every
accepted push scanned across its full introduced
history; findings create alerts (S-294).

The scan lives in samverk/push_scanning.py over
migration 115's push_scans / push_scan_updates /
secret_alerts tables (schema 114 -> 115). Every
introduced commit is walked oldest first (reachable
from the new oid, not from the old oid nor any prior
ref tip; deletions introduce nothing; force-push
rewrites are new oids and are scanned), every blob
version a commit introduces is judged once per oid,
and each finding stands as one open alert carrying
commit, path, detector, line, a redacted preview
and a fingerprint -- never the secret. A scan is
exactly-once per (repository, exact ref updates):
a rescan returns the standing scan and creates no
second alert. Caps (commits / blobs / blob bytes)
and binary skips are counted on the record, and a
capped scan stands partial naming its cap.

The detector seam is lazy: S-289's patterns and
S-290's generic judgement judge when present and
are recorded absent when not -- this battery passes
on a base with neither, either, or both, guarding
each real-layer case on the layer's presence, and
drives the rest through an injected scanner (the
standing seam) plus an in-memory history, with one
real-git case proving the ObjectReader road.

No new taxonomy event -- 133 stand (33 auth /
87 repo / 13 admin); scanning is unwitnessed.

Counted with: python3 -m unittest tests.test_push_scanning
"""
from __future__ import annotations
import hashlib
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.hooks import RefUpdate
from samverk.push_scanning import (
    GitHistory, PushScanError, PushScanStore, ScanFinding,
    generic_layer_available, introduced_blobs, introduced_commits,
    pattern_layer_available, push_key_for, render_push_scan_page,
    render_secret_alerts_page, scan_blob_text)
from samverk.repositories import RepositoryStore
from samverk.taxonomy import AUDIT_EVENTS

PW = "correct horse battery"
T0 = 1_700_000_000
ZERO = "0" * 40
SECRET = "hunter2-is-the-planted-secret"


def oid(n: int) -> str:
    return f"{n:040x}"


def fake_scanner(text: str):
    """The injected seam: one finding per SECRET line."""
    out = []
    for i, line in enumerate(text.splitlines(), start=1):
        if SECRET in line:
            out.append(ScanFinding(
                source="injected", detector_id="planted_secret",
                line=i, column=line.index(SECRET) + 1,
                redacted="planted…[redacted]",
                fingerprint=hashlib.sha256(
                    SECRET.encode()).hexdigest()))
    return out


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


class FakeHistory:
    """In-memory history: commits oid -> (parents, tree),
    trees are dicts path -> (mode, blob_oid), blobs oid ->
    bytes. commit_tree returns the commit oid itself as
    its tree key (one tree per commit in this fake)."""

    def __init__(self):
        self.parents: dict = {}
        self.trees: dict = {}
        self.blobs: dict = {}
        self._next = 1000

    def add_blob(self, data: bytes) -> str:
        self._next += 1
        b = oid(self._next)
        self.blobs[b] = data
        return b

    def add_commit(self, parents=(), files=None) -> str:
        """files: path -> bytes (a fresh blob each call)."""
        self._next += 1
        c = oid(self._next)
        tree = {}
        for path, data in (files or {}).items():
            tree[path] = ("100644", self.add_blob(data))
        self.parents[c] = tuple(parents)
        self.trees[c] = tree
        return c

    def add_commit_tree(self, parents, tree) -> str:
        self._next += 1
        c = oid(self._next)
        self.parents[c] = tuple(parents)
        self.trees[c] = dict(tree)
        return c

    def commit_parents(self, o):
        return self.parents[o]

    def commit_tree(self, o):
        return o

    def flatten_tree(self, t):
        return dict(self.trees[t])

    def read_blob(self, o):
        return self.blobs[o]


class PushScanningTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.clock = Clock()
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(
            self.conn, audit=self.audit, time_fn=self.clock)
        self.owner = self.accounts.register("volmarr", PW)
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.repo = self.repos.create_repository(
            self.owner.id, "volmarr", "forge")
        self.scans = PushScanStore(
            self.conn, self.repos, time_fn=self.clock)
        self.hist = FakeHistory()

    # -- helpers -----------------------------------------------------

    def push(self, updates, prior_tips=(), scanner=fake_scanner,
             **kw):
        return self.scans.scan_push(
            "volmarr", "forge", updates=updates,
            history=self.hist, prior_tips=prior_tips,
            scanner=scanner, **kw)

    def clean_chain(self, n=2, secret_at=None):
        """A linear chain; returns commit oids oldest first.
        secret_at: index whose file carries the secret."""
        commits = []
        parent = ()
        for i in range(n):
            body = f"line one\n{SECRET}\n" if i == secret_at \
                else f"ordinary content {i}\n"
            c = self.hist.add_commit(
                parents=parent, files={"app.py": body.encode()})
            commits.append(c)
            parent = (c,)
        return commits

    # -- schema / taxonomy pins ---------------------------------------

    def test_schema_stands_at_116(self):
        self.assertEqual(schema_version(self.conn), 116)
        self.assertEqual(db.MIGRATIONS[-1][0], 116)

    def test_taxonomy_still_133(self):
        self.assertEqual(len(AUDIT_EVENTS), 133)

    # -- the full-history law ------------------------------------------

    def test_secret_buried_in_history_is_found(self):
        c1, c2, c3 = self.clean_chain(3, secret_at=0)
        scan = self.push([RefUpdate("refs/heads/main", ZERO, c3)])
        self.assertEqual(scan.status, "complete")
        self.assertEqual(scan.commits_scanned, 3)
        self.assertEqual(scan.alerts_created, 1)
        alerts = self.scans.alerts_for_scan(scan.id)
        self.assertEqual(alerts[0].commit_oid, c1)
        self.assertEqual(alerts[0].path, "app.py")
        self.assertEqual(alerts[0].state, "open")
        self.assertEqual(alerts[0].detector_id, "planted_secret")

    def test_tip_only_secret_is_found(self):
        commits = self.clean_chain(2, secret_at=1)
        scan = self.push(
            [RefUpdate("refs/heads/main", ZERO, commits[-1])])
        self.assertEqual(scan.alerts_created, 1)

    def test_old_history_is_not_rescanned(self):
        c1, c2 = self.clean_chain(2, secret_at=0)
        first = self.push([RefUpdate("refs/heads/main", ZERO, c1)])
        self.assertEqual(first.alerts_created, 1)
        c3 = self.hist.add_commit(
            parents=(c2,), files={"app.py": b"clean\n"})
        # chain is c1 -> c2 -> c3; push c1..c3 introduces c2, c3
        scan = self.push([RefUpdate("refs/heads/main", c1, c3)])
        self.assertEqual(scan.commits_scanned, 2)
        self.assertEqual(scan.alerts_created, 0)
        self.assertEqual(
            self.scans.count_alerts("volmarr", "forge"), 1)

    def test_creation_excludes_prior_ref_history(self):
        c1, c2 = self.clean_chain(2, secret_at=0)
        scan = self.push(
            [RefUpdate("refs/heads/topic", ZERO, c2)],
            prior_tips=(c2,))
        self.assertEqual(scan.commits_scanned, 0)
        self.assertEqual(scan.alerts_created, 0)

    def test_deletion_introduces_nothing(self):
        c1, = self.clean_chain(1, secret_at=0)
        scan = self.push([RefUpdate("refs/heads/main", c1, ZERO)])
        self.assertEqual(scan.commits_scanned, 0)
        self.assertEqual(scan.alerts_created, 0)
        self.assertEqual(scan.status, "complete")

    def test_force_push_rewrite_is_scanned(self):
        c1, c2 = self.clean_chain(2, secret_at=None)
        self.push([RefUpdate("refs/heads/main", ZERO, c2)])
        # rewritten line: a fresh root carrying the secret
        r1 = self.hist.add_commit(
            parents=(), files={"app.py": f"{SECRET}\n".encode()})
        scan = self.push([RefUpdate("refs/heads/main", c2, r1)])
        self.assertEqual(scan.commits_scanned, 1)
        self.assertEqual(scan.alerts_created, 1)

    def test_multi_ref_push_dedupes_commits(self):
        c1, c2 = self.clean_chain(2, secret_at=0)
        scan = self.push([
            RefUpdate("refs/heads/main", ZERO, c2),
            RefUpdate("refs/heads/topic", ZERO, c2),
        ])
        self.assertEqual(scan.commits_scanned, 2)
        self.assertEqual(scan.alerts_created, 1)
        self.assertEqual(len(scan.updates), 2)

    def test_introduced_commits_oldest_first(self):
        c1, c2, c3 = self.clean_chain(3)
        got = introduced_commits(
            self.hist, [RefUpdate("refs/heads/main", ZERO, c3)])
        self.assertEqual(got, [c1, c2, c3])

    def test_merge_second_parent_line_is_scanned(self):
        base = self.hist.add_commit(
            parents=(), files={"a.txt": b"base\n"})
        side_blob = self.hist.add_blob(f"{SECRET}\n".encode())
        side_tree = {"a.txt": ("100644",
                               self.hist.add_blob(b"base\n")),
                     "s.txt": ("100644", side_blob)}
        # rebuild base tree identity for a.txt is not needed:
        # side commit introduces s.txt (and its own a.txt blob)
        side = self.hist.add_commit_tree((base,), side_tree)
        main = self.hist.add_commit(
            parents=(base,), files={"m.txt": b"main\n"})
        merge_tree = dict(self.hist.trees[main])
        merge_tree.update(side_tree)
        merge = self.hist.add_commit_tree((main, side), merge_tree)
        scan = self.push([RefUpdate("refs/heads/main", ZERO, merge)])
        self.assertEqual(scan.commits_scanned, 4)
        self.assertEqual(scan.alerts_created, 1)
        alerts = self.scans.alerts_for_scan(scan.id)
        self.assertEqual(alerts[0].commit_oid, side)

    # -- blob law --------------------------------------------------------

    def test_same_blob_two_paths_judged_once_alerted_twice(self):
        blob = self.hist.add_blob(f"{SECRET}\n".encode())
        tree = {"x.py": ("100644", blob), "y.py": ("100644", blob)}
        c = self.hist.add_commit_tree((), tree)
        scan = self.push([RefUpdate("refs/heads/main", ZERO, c)])
        self.assertEqual(scan.blobs_scanned, 1)
        self.assertEqual(scan.alerts_created, 2)
        paths = {a.path for a in self.scans.alerts_for_scan(scan.id)}
        self.assertEqual(paths, {"x.py", "y.py"})

    def test_inherited_blob_not_rescanned_at_child(self):
        blob = self.hist.add_blob(f"{SECRET}\n".encode())
        c1 = self.hist.add_commit_tree(
            (), {"x.py": ("100644", blob)})
        c2 = self.hist.add_commit_tree(
            (c1,), {"x.py": ("100644", blob),
                    "z.py": ("100644", self.hist.add_blob(b"z\n"))})
        scan = self.push([RefUpdate("refs/heads/main", ZERO, c2)])
        self.assertEqual(scan.alerts_created, 1)
        self.assertEqual(
            self.scans.alerts_for_scan(scan.id)[0].commit_oid, c1)

    def test_binary_blob_is_skipped_and_counted(self):
        blob = self.hist.add_blob(b"\x00\x01\x02" + SECRET.encode())
        c = self.hist.add_commit_tree((), {"bin.dat": ("100644", blob)})
        scan = self.push([RefUpdate("refs/heads/main", ZERO, c)])
        self.assertEqual(scan.blobs_skipped, 1)
        self.assertEqual(scan.alerts_created, 0)

    def test_oversize_blob_is_skipped_and_counted(self):
        import samverk.push_scanning as ps
        blob = self.hist.add_blob(b"a" * (ps.MAX_BLOB_BYTES + 1))
        c = self.hist.add_commit_tree((), {"big.txt": ("100644", blob)})
        scan = self.push([RefUpdate("refs/heads/main", ZERO, c)])
        self.assertEqual(scan.blobs_skipped, 1)
        self.assertEqual(scan.alerts_created, 0)

    def test_gitlink_is_never_scanned(self):
        c = self.hist.add_commit_tree(
            (), {"sub": ("160000", oid(4242))})
        scan = self.push([RefUpdate("refs/heads/main", ZERO, c)])
        self.assertEqual(scan.blobs_scanned, 0)
        self.assertEqual(scan.alerts_created, 0)

    def test_symlink_blob_is_scanned_as_text(self):
        blob = self.hist.add_blob(f"{SECRET}\n".encode())
        c = self.hist.add_commit_tree(
            (), {"link": ("120000", blob)})
        scan = self.push([RefUpdate("refs/heads/main", ZERO, c)])
        self.assertEqual(scan.alerts_created, 1)

    def test_introduced_blobs_names_only_new_versions(self):
        c1, c2 = self.clean_chain(2)
        self.assertEqual(len(introduced_blobs(self.hist, c1)), 1)
        got = introduced_blobs(self.hist, c2)
        self.assertEqual([g[0] for g in got], ["app.py"])

    # -- exactly once ------------------------------------------------------

    def test_rescan_returns_standing_scan_no_new_alerts(self):
        c1, = self.clean_chain(1, secret_at=0)
        upd = [RefUpdate("refs/heads/main", ZERO, c1)]
        first = self.push(upd)
        second = self.push(upd)
        self.assertEqual(first.id, second.id)
        self.assertEqual(second.alerts_created, 1)
        self.assertEqual(self.scans.count_scans("volmarr", "forge"), 1)
        self.assertEqual(
            self.scans.count_alerts("volmarr", "forge"), 1)

    def test_push_key_is_stable_and_update_sensitive(self):
        a = [RefUpdate("refs/heads/main", ZERO, oid(7))]
        b = [RefUpdate("refs/heads/main", ZERO, oid(8))]
        self.assertEqual(push_key_for(a), push_key_for(list(a)))
        self.assertNotEqual(push_key_for(a), push_key_for(b))

    # -- refusals ------------------------------------------------------------

    def test_missing_repo_is_named(self):
        with self.assertRaises(PushScanError) as ctx:
            self.scans.scan_push(
                "volmarr", "nope", updates=[
                    RefUpdate("refs/heads/main", ZERO, oid(1))],
                history=self.hist, scanner=fake_scanner)
        self.assertEqual(ctx.exception.reason, "repo_not_found")

    def test_empty_updates_refused(self):
        with self.assertRaises(PushScanError) as ctx:
            self.push([])
        self.assertEqual(ctx.exception.reason, "updates_empty")

    def test_still_ref_update_refused(self):
        with self.assertRaises(PushScanError) as ctx:
            self.push([RefUpdate("refs/heads/main", oid(3), oid(3))])
        self.assertEqual(ctx.exception.reason, "update_invalid")

    def test_bad_transport_refused(self):
        c1, = self.clean_chain(1)
        with self.assertRaises(PushScanError) as ctx:
            self.push([RefUpdate("refs/heads/main", ZERO, c1)],
                      transport="carrier-pigeon")
        self.assertEqual(ctx.exception.reason, "transport_invalid")

    # -- the seam -------------------------------------------------------------

    def test_layer_flags_match_reality(self):
        self.assertEqual(
            pattern_layer_available(),
            importlib.util.find_spec("samverk.secret_scanning")
            is not None)
        self.assertEqual(
            generic_layer_available(),
            importlib.util.find_spec(
                "samverk.generic_secret_detection") is not None)

    def test_scan_records_which_layers_judged(self):
        c1, = self.clean_chain(1)
        scan = self.push(
            [RefUpdate("refs/heads/main", ZERO, c1)], scanner=None)
        self.assertEqual(scan.pattern_available,
                         pattern_layer_available())
        self.assertEqual(scan.generic_available,
                         generic_layer_available())
        self.assertEqual(scan.status, "complete")

    def test_clean_push_creates_no_alerts_any_scanner(self):
        c1, c2 = self.clean_chain(2)
        scan = self.push(
            [RefUpdate("refs/heads/main", ZERO, c2)], scanner=None)
        self.assertEqual(scan.alerts_created, 0)
        self.assertEqual(
            self.scans.count_alerts("volmarr", "forge"), 0)

    @unittest.skipUnless(pattern_layer_available(),
                         "S-289 pattern layer absent on this base")
    def test_pattern_layer_finds_published_shape(self):
        token = "ghp_" + "A" * 36
        c = self.hist.add_commit(
            parents=(), files={"k.txt": f"key = {token}\n".encode()})
        scan = self.push(
            [RefUpdate("refs/heads/main", ZERO, c)], scanner=None)
        self.assertEqual(scan.alerts_created, 1)
        alert = self.scans.alerts_for_scan(scan.id)[0]
        self.assertEqual(alert.source, "pattern")
        self.assertEqual(alert.detector_id, "github_pat_classic")
        self.assertNotIn(token, alert.redacted)

    @unittest.skipUnless(generic_layer_available(),
                         "S-290 generic layer absent on this base")
    def test_generic_layer_finds_unshaped_secret(self):
        value = "Kx9Qm2Zv8Lp4Rt7Wn3Hs6Yd1Fj5Bc0"
        text = f"api_key = \"{value}\"\n"
        findings, p_ok, g_ok = scan_blob_text(text)
        self.assertTrue(g_ok)
        self.assertTrue(any(f.source == "generic" for f in findings))

    # -- redaction law ---------------------------------------------------------

    def test_secret_never_stored_or_rendered(self):
        c1, = self.clean_chain(1, secret_at=0)
        scan = self.push([RefUpdate("refs/heads/main", ZERO, c1)])
        alert = self.scans.alerts_for_scan(scan.id)[0]
        for surface in (str(alert.to_dict()), str(scan.to_dict()),
                        render_push_scan_page(
                            scan, self.scans.alerts_for_scan(scan.id)),
                        render_secret_alerts_page([alert])):
            self.assertNotIn(SECRET, surface)
        row = self.conn.execute(
            "SELECT * FROM secret_alerts").fetchone()
        self.assertNotIn(SECRET, str(dict(row)))

    def test_render_pages_state_facts_in_words(self):
        c1, = self.clean_chain(1, secret_at=0)
        scan = self.push([RefUpdate("refs/heads/main", ZERO, c1)])
        page = render_push_scan_page(
            scan, self.scans.alerts_for_scan(scan.id))
        self.assertIn("full introduced history", page)
        self.assertIn("open", page)
        alerts_page = render_secret_alerts_page(
            self.scans.list_alerts("volmarr", "forge"))
        self.assertIn("app.py", alerts_page)

    # -- reads -------------------------------------------------------------------

    def test_list_and_count_reads(self):
        c1, = self.clean_chain(1, secret_at=0)
        self.push([RefUpdate("refs/heads/main", ZERO, c1)])
        self.assertEqual(self.scans.count_scans("volmarr", "forge"), 1)
        self.assertEqual(
            len(self.scans.list_scans("volmarr", "forge")), 1)
        self.assertEqual(
            self.scans.count_alerts("volmarr", "forge",
                                    state="open"), 1)
        self.assertEqual(
            self.scans.count_alerts("volmarr", "forge",
                                    state="resolved"), 0)
        self.assertEqual(
            len(self.scans.list_alerts("volmarr", "forge",
                                       state="open")), 1)
        with self.assertRaises(PushScanError) as ctx:
            self.scans.list_alerts("volmarr", "forge", state="bogus")
        self.assertEqual(ctx.exception.reason, "state_invalid")

    def test_scan_is_unwitnessed(self):
        before = self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
        c1, = self.clean_chain(1, secret_at=0)
        self.push([RefUpdate("refs/heads/main", ZERO, c1)])
        after = self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
        self.assertEqual(before, after)

    # -- caps -----------------------------------------------------------------------

    def test_commit_cap_marks_partial(self):
        import samverk.push_scanning as ps
        old = ps.MAX_COMMITS_PER_SCAN
        ps.MAX_COMMITS_PER_SCAN = 2
        try:
            commits = self.clean_chain(4)
            scan = self.push([RefUpdate(
                "refs/heads/main", ZERO, commits[-1])])
        finally:
            ps.MAX_COMMITS_PER_SCAN = old
        self.assertEqual(scan.status, "partial")
        self.assertEqual(scan.partial_reason, "commit_cap")
        self.assertEqual(scan.commits_scanned, 2)

    # -- the real-git road -------------------------------------------------------------

    @unittest.skipUnless(subprocess.run(
        ["git", "--version"], capture_output=True).returncode == 0,
        "git not available")
    def test_real_git_history_road(self):
        bare = self.repos.path_for("volmarr", "forge")
        work = Path(self._td.name) / "work"
        env = {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "T",
               "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin"}

        def git(*args, cwd):
            r = subprocess.run(["git", *args], cwd=cwd, env=env,
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)

        git("clone", str(bare), str(work), cwd=self.root)
        (work / "app.py").write_text(f"{SECRET}\n")
        git("add", ".", cwd=work)
        git("commit", "-m", "one", cwd=work)
        (work / "app.py").write_text("clean now\n")
        git("add", ".", cwd=work)
        git("commit", "-m", "two", cwd=work)
        git("push", "origin", "HEAD:refs/heads/main", cwd=work)
        tip = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=work, env=env,
            capture_output=True, text=True).stdout.strip()
        history = GitHistory(bare)
        scan = self.scans.scan_push(
            "volmarr", "forge",
            updates=[RefUpdate("refs/heads/main", ZERO, tip)],
            history=history, scanner=fake_scanner)
        self.assertEqual(scan.commits_scanned, 2)
        self.assertEqual(scan.alerts_created, 1)
        alert = self.scans.alerts_for_scan(scan.id)[0]
        self.assertNotEqual(alert.commit_oid, tip)


if __name__ == "__main__":
    unittest.main()
