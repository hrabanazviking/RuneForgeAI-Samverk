"""S-292 acceptance battery: push protection.

Acceptance (roadmap S-292): Push protection --
receive-pack refuses pushes containing detected
secrets (at the S-089 gate), naming the file and
pattern class, never echoing the secret.

The refusal lives in samverk/push_protection.py as
an S-089 `secret_scan`-stage plug-in over S-291's
introduced-history walk: for every ref update, the
commits reachable from the new oid and not from the
old oid nor any prior ref tip, oldest first; every
introduced blob version judged once per oid, at its
oldest introducing commit per (path, blob). Any
finding refuses with a sentence naming the file,
the pattern class and the line; a walk cut by the
commit or blob cap refuses naming the cap (a capped
scan is never a clean bill); binary and oversize
blobs are skipped and counted without refusing.
Findings carry path, commit, blob, detector, pattern
class, line, column, a redacted preview and a
fingerprint -- never the secret, on any surface
(decision, dict, page, reason, finding repr).

The detector seam is lazy, as in S-289/S-290/S-291:
no detector module is imported at load; S-291's
combined judgement is preferred when present, the
two layers are probed directly otherwise, and with
no layer and no injected scanner the check raises
`detector_unavailable`, which the gate's fail-closed
law turns into a refusal. This battery drives the
standing injected-scanner seam plus an in-memory
history, guards each real-layer case on the layer's
presence, and proves the gate wiring end to end.

No migration (no push-protection tables; the schema
is whatever the standing migrations say) and no new
taxonomy event -- 133 stand (33 auth / 87 repo /
13 admin); a refusal is a gate veto, unwitnessed.

Counted with: python3 -m unittest tests.test_push_protection
"""
from __future__ import annotations
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.hooks import RefUpdate
from samverk.push_protection import (
    GitHistory, ProtectionFinding, PushProtection,
    PushProtectionError, RawFinding, decide,
    generic_layer_available, pattern_class_for,
    pattern_layer_available, refusal_reason,
    render_push_protection_page, scan_text)
from samverk.receive_gate import ReceiveGate
from samverk.repositories import RepositoryStore
from samverk.taxonomy import AUDIT_EVENTS

PW = "correct horse battery"
ZERO = "0" * 40
SECRET = "hunter2-is-the-planted-secret"


def oid(n: int) -> str:
    return f"{n:040x}"


def fake_scanner(text: str):
    """The injected seam: one finding per SECRET line."""
    out = []
    for i, line in enumerate(text.splitlines(), start=1):
        if SECRET in line:
            out.append(RawFinding(
                source="injected", detector_id="planted_secret",
                line=i, column=line.index(SECRET) + 1,
                redacted="planted...[redacted]",
                fingerprint=hashlib.sha256(
                    SECRET.encode()).hexdigest()))
    return out


class FakeHistory:
    """In-memory history, S-291's shape: commits oid
    -> (parents, tree); commit_tree returns the
    commit oid itself as its tree key."""

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


class PushProtectionTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", PW)
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts)
        self.repo = self.repos.create_repository(
            self.owner.id, "volmarr", "forge")
        self.protection = PushProtection(
            self.repos, scanner=fake_scanner)
        self.hist = FakeHistory()

    # -- helpers ------------------------------------------------------

    def check(self, updates, **kw):
        kw.setdefault("history", self.hist)
        return self.protection.check_push(
            "volmarr", "forge", updates, **kw)

    def chain(self, n=3, secret_at=None, path="app.py"):
        commits = []
        parent = ()
        files = {}
        for i in range(n):
            body = (f"line one\n{SECRET}\n" if i == secret_at
                    else f"clean line {i}\n")
            files = {**files, path: body.encode()}
            c = self.hist.add_commit(parents=parent, files=files)
            commits.append(c)
            parent = (c,)
        return commits

    # -- the push door --------------------------------------------------

    def test_clean_push_is_allowed(self):
        commits = self.chain(2)
        d = self.check([RefUpdate("refs/heads/main", ZERO, commits[-1])])
        self.assertTrue(d.allowed)
        self.assertEqual(d.findings, ())
        self.assertEqual(d.reason, "")
        self.assertEqual(d.commits_scanned, 2)
        self.assertEqual(d.partial_reason, "")

    def test_secret_at_tip_refuses_naming_file_and_class(self):
        commits = self.chain(2, secret_at=1)
        d = self.check([RefUpdate("refs/heads/main", ZERO, commits[-1])])
        self.assertFalse(d.allowed)
        self.assertEqual(len(d.findings), 1)
        f = d.findings[0]
        self.assertEqual(f.path, "app.py")
        self.assertEqual(f.detector_id, "planted_secret")
        self.assertEqual(f.pattern_class, "planted_secret")
        self.assertEqual(f.line, 2)
        self.assertEqual(f.commit_oid, commits[1])
        self.assertIn("app.py", d.reason)
        self.assertIn("planted_secret", d.reason)
        self.assertIn("remove it and push again", d.reason)

    def test_secret_never_echoed_on_any_surface(self):
        commits = self.chain(1, secret_at=0)
        d = self.check([RefUpdate("refs/heads/main", ZERO, commits[-1])])
        surfaces = (d.reason + str(d.to_dict()) + repr(d.findings)
                    + render_push_protection_page(d))
        self.assertNotIn(SECRET, surfaces)
        self.assertNotIn(SECRET, str(d.findings[0].to_dict()))

    def test_secret_buried_three_commits_deep_refuses(self):
        commits = self.chain(4, secret_at=0)
        d = self.check([RefUpdate("refs/heads/main", ZERO, commits[-1])])
        self.assertFalse(d.allowed)
        self.assertEqual(d.findings[0].commit_oid, commits[0])

    def test_history_already_held_is_not_rejudged(self):
        commits = self.chain(2, secret_at=0)
        d = self.check([RefUpdate(
            "refs/heads/main", commits[0], commits[1])])
        self.assertTrue(d.allowed)
        self.assertEqual(d.commits_scanned, 1)

    def test_prior_tips_exclude_their_history(self):
        commits = self.chain(2, secret_at=0)
        d = self.check(
            [RefUpdate("refs/heads/topic", ZERO, commits[1])],
            prior_tips=(commits[0],))
        self.assertTrue(d.allowed)

    def test_deletion_introduces_nothing(self):
        commits = self.chain(1, secret_at=0)
        d = self.check([RefUpdate("refs/heads/main", commits[0], ZERO)])
        self.assertTrue(d.allowed)
        self.assertEqual(d.commits_scanned, 0)

    def test_force_push_rewrite_with_secret_refuses(self):
        base = self.chain(1)
        rewritten = self.hist.add_commit(
            parents=(), files={"app.py": f"{SECRET}\n".encode()})
        d = self.check([RefUpdate(
            "refs/heads/main", base[0], rewritten)])
        self.assertFalse(d.allowed)

    def test_same_blob_at_two_paths_refuses_at_both(self):
        blob = self.hist.add_blob(f"{SECRET}\n".encode())
        tree = {"a.py": ("100644", blob), "b.py": ("100644", blob)}
        c = self.hist.add_commit_tree((), tree)
        d = self.check([RefUpdate("refs/heads/main", ZERO, c)])
        self.assertFalse(d.allowed)
        self.assertEqual({f.path for f in d.findings}, {"a.py", "b.py"})
        self.assertIn("and 1 more detected secret", d.reason)

    def test_binary_blob_is_skipped_not_judged(self):
        c = self.hist.add_commit(
            files={"bin.dat": b"\x00\x01" + SECRET.encode()})
        d = self.check([RefUpdate("refs/heads/main", ZERO, c)])
        self.assertTrue(d.allowed)
        self.assertEqual(d.blobs_skipped, 1)
        self.assertEqual(d.blobs_scanned, 0)

    def test_oversize_blob_is_skipped_and_counted(self):
        protection = PushProtection(
            self.repos, scanner=fake_scanner, max_blob_bytes=8)
        c = self.hist.add_commit(
            files={"big.py": f"{SECRET} plus padding\n".encode()})
        d = protection.check_push(
            "volmarr", "forge",
            [RefUpdate("refs/heads/main", ZERO, c)], history=self.hist)
        self.assertTrue(d.allowed)
        self.assertEqual(d.blobs_skipped, 1)

    def test_commit_cap_refuses_fail_closed(self):
        protection = PushProtection(
            self.repos, scanner=fake_scanner, max_commits=1)
        commits = self.chain(3)
        d = protection.check_push(
            "volmarr", "forge",
            [RefUpdate("refs/heads/main", ZERO, commits[-1])],
            history=self.hist)
        self.assertFalse(d.allowed)
        self.assertEqual(d.partial_reason, "commit_cap")
        self.assertIn("cannot be proven", d.reason)

    def test_blob_cap_refuses_fail_closed(self):
        protection = PushProtection(
            self.repos, scanner=fake_scanner, max_blobs=1)
        c = self.hist.add_commit(files={
            "a.py": b"clean a\n", "b.py": b"clean b\n"})
        d = protection.check_push(
            "volmarr", "forge",
            [RefUpdate("refs/heads/main", ZERO, c)], history=self.hist)
        self.assertFalse(d.allowed)
        self.assertEqual(d.partial_reason, "blob_cap")

    # -- named errors ---------------------------------------------------

    def test_empty_updates_are_refused_by_name(self):
        with self.assertRaises(PushProtectionError) as cm:
            self.check([])
        self.assertEqual(cm.exception.reason, "updates_empty")

    def test_malformed_oid_is_refused_by_name(self):
        with self.assertRaises(PushProtectionError) as cm:
            self.check([RefUpdate("refs/heads/main", ZERO, "nope")])
        self.assertEqual(cm.exception.reason, "update_invalid")

    def test_unmoving_ref_is_refused_by_name(self):
        commits = self.chain(1)
        with self.assertRaises(PushProtectionError) as cm:
            self.check([RefUpdate(
                "refs/heads/main", commits[0], commits[0])])
        self.assertEqual(cm.exception.reason, "update_invalid")

    def test_missing_repository_is_named(self):
        commits = self.chain(1)
        with self.assertRaises(PushProtectionError) as cm:
            self.protection.check_push(
                "volmarr", "ghost",
                [RefUpdate("refs/heads/main", ZERO, commits[0])],
                history=self.hist)
        self.assertEqual(cm.exception.reason, "repo_not_found")

    def test_history_unavailable_is_named(self):
        bare = PushProtection(scanner=fake_scanner)
        commits = self.chain(1)
        with self.assertRaises(PushProtectionError) as cm:
            bare.check_push(
                "volmarr", "forge",
                [RefUpdate("refs/heads/main", ZERO, commits[0])])
        self.assertEqual(cm.exception.reason, "history_unavailable")

    def test_no_detector_layer_fails_closed_by_name(self):
        if pattern_layer_available() or generic_layer_available():
            self.skipTest("a detector layer is present on this base")
        bare = PushProtection(self.repos)
        commits = self.chain(1)
        with self.assertRaises(PushProtectionError) as cm:
            bare.check_push(
                "volmarr", "forge",
                [RefUpdate("refs/heads/main", ZERO, commits[0])],
                history=self.hist)
        self.assertEqual(cm.exception.reason, "detector_unavailable")

    # -- the text door and the pure faces ---------------------------------

    def test_check_texts_refuses_and_allows(self):
        dirty = self.protection.check_texts(
            [("keys.py", f"token = {SECRET}\n")])
        self.assertFalse(dirty.allowed)
        self.assertEqual(dirty.findings[0].path, "keys.py")
        self.assertEqual(dirty.findings[0].commit_oid, "")
        clean = self.protection.check_texts([("a.py", "x = 1\n")])
        self.assertTrue(clean.allowed)
        self.assertEqual(clean.blobs_scanned, 1)

    def test_decide_is_pure_and_complete(self):
        f = ProtectionFinding(
            path="a.py", commit_oid="", blob_oid="",
            source="injected", detector_id="planted_secret",
            pattern_class="planted_secret", line=1, column=1,
            redacted="planted...[redacted]", fingerprint="ab" * 32)
        self.assertFalse(decide([f]).allowed)
        self.assertTrue(decide([]).allowed)
        capped = decide([], partial_reason="commit_cap")
        self.assertFalse(capped.allowed)
        self.assertIn("cannot be proven", capped.reason)

    def test_refusal_reason_counts_the_rest(self):
        def mk(path):
            return ProtectionFinding(
                path=path, commit_oid="", blob_oid="",
                source="injected", detector_id="planted_secret",
                pattern_class="planted_secret", line=3, column=1,
                redacted="planted...[redacted]",
                fingerprint="cd" * 32)
        reason = refusal_reason([mk("a.py"), mk("a.py"), mk("b.py")])
        self.assertIn("a.py", reason)
        self.assertIn("2 more detected secrets in 2 files", reason)
        self.assertNotIn(SECRET, reason)

    def test_pattern_class_names(self):
        self.assertEqual(
            pattern_class_for("generic_entropy", "generic"),
            "generic high-entropy secret")
        self.assertEqual(
            pattern_class_for("planted_secret", "injected"),
            "planted_secret")

    def test_scan_text_with_injected_scanner(self):
        found, p_ok, g_ok = scan_text(
            f"{SECRET}\n", scanner=fake_scanner)
        self.assertEqual(len(found), 1)
        self.assertFalse(p_ok)
        self.assertFalse(g_ok)

    # -- standing invariants ----------------------------------------------

    def test_taxonomy_unchanged_and_no_tables(self):
        # S-292 added no event and no table of its own.
        # On the banked line the taxonomy stands at 134
        # (S-293's bypass event) and the one table of
        # this shape is S-293's bypass alert table.
        self.assertEqual(len(AUDIT_EVENTS), 135)
        rows = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name LIKE '%push_protection%'").fetchall()
        self.assertEqual([r[0] for r in rows],
                         ["push_protection_bypasses"])

    def test_page_face_names_file_and_class_only(self):
        commits = self.chain(1, secret_at=0)
        d = self.check([RefUpdate("refs/heads/main", ZERO, commits[-1])])
        page = render_push_protection_page(d)
        self.assertIn("app.py", page)
        self.assertIn("planted_secret", page)
        self.assertNotIn(SECRET, page)
        clean = self.protection.check_texts([("a.py", "ok\n")])
        self.assertIn("Push allowed", render_push_protection_page(clean))


class GateWiringTests(unittest.TestCase):
    """The S-089 door itself: plug-in order, veto
    shape, and the fail-closed error law."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", PW)
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts)
        self.repos.create_repository(
            self.owner.id, "volmarr", "forge")
        self.protection = PushProtection(
            self.repos, scanner=fake_scanner)
        self.hist = FakeHistory()

    def gate(self, protection=None):
        gate = ReceiveGate()
        gate.register_secret_scanner(
            "push-protection",
            (protection or self.protection).receive_gate_plugin())
        return gate

    def check(self, gate, updates, **kw):
        kw.setdefault("payload", {"history": self.hist})
        return gate.check(
            owner="volmarr", repo="forge", actor="volmarr",
            transport="local", updates=updates, **kw)

    def chain(self, secret=False):
        body = f"{SECRET}\n" if secret else "clean\n"
        return self.hist.add_commit(files={"app.py": body.encode()})

    def test_gate_allows_a_clean_push(self):
        c = self.chain()
        result = self.check(
            self.gate(), (RefUpdate("refs/heads/main", ZERO, c),))
        self.assertTrue(result.allowed)
        stage = [o for o in result.outcomes
                 if o.stage == "secret_scan"]
        self.assertEqual(stage[0].status, "allowed")

    def test_gate_vetoes_a_dirty_push_at_secret_scan(self):
        c = self.chain(secret=True)
        result = self.check(
            self.gate(), (RefUpdate("refs/heads/main", ZERO, c),))
        self.assertFalse(result.allowed)
        self.assertEqual(result.refused_stage, "secret_scan")
        self.assertEqual(result.refused_by, "push-protection")
        self.assertIn("app.py", result.reason)
        self.assertIn("planted_secret", result.reason)
        self.assertNotIn(SECRET, result.reason)

    def test_gate_decision_is_kept_for_callers(self):
        c = self.chain(secret=True)
        result = self.check(
            self.gate(), (RefUpdate("refs/heads/main", ZERO, c),))
        self.assertFalse(result.allowed)
        decision = self.protection.last_decision
        self.assertIsNotNone(decision)
        self.assertEqual(decision.findings[0].path, "app.py")

    def test_gate_with_no_updates_cannot_judge_and_allows(self):
        result = self.check(self.gate(), ())
        self.assertTrue(result.allowed)

    def test_protection_stage_refusal_runs_before_the_scanner(self):
        calls = []
        def scanner_spy(text):
            calls.append(text)
            return fake_scanner(text)
        protection = PushProtection(self.repos, scanner=scanner_spy)
        gate = ReceiveGate()
        gate.register_protection(
            "protected-main", lambda ctx: "refs/heads/main is protected")
        gate.register_secret_scanner(
            "push-protection", protection.receive_gate_plugin())
        c = self.chain(secret=True)
        result = self.check(
            gate, (RefUpdate("refs/heads/main", ZERO, c),))
        self.assertFalse(result.allowed)
        self.assertEqual(result.refused_stage, "protection")
        self.assertEqual(calls, [])

    def test_missing_detector_fails_closed_at_the_gate(self):
        if pattern_layer_available() or generic_layer_available():
            self.skipTest("a detector layer is present on this base")
        gate = self.gate(PushProtection(self.repos))
        c = self.chain()
        result = self.check(
            gate, (RefUpdate("refs/heads/main", ZERO, c),))
        self.assertFalse(result.allowed)
        self.assertEqual(result.refused_stage, "secret_scan")


class RealLayerTests(unittest.TestCase):
    """Guarded on the layers' presence: on a base
    carrying S-289 (and S-291's combined judgement)
    a synthetic published-shape token refuses with
    its real pattern class."""

    def setUp(self):
        if not pattern_layer_available():
            self.skipTest("S-289 pattern layer not on this base")
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", PW)
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts)
        self.repos.create_repository(
            self.owner.id, "volmarr", "forge")

    def test_published_shape_token_refuses_with_real_class(self):
        token = "ghp_" + "A" * 36
        protection = PushProtection(self.repos)
        d = protection.check_texts([("keys.py", f"t = '{token}'\n")])
        self.assertFalse(d.allowed)
        self.assertTrue(d.pattern_available)
        self.assertIn("GitHub", d.findings[0].pattern_class)
        self.assertIn("GitHub", d.reason)
        self.assertNotIn(token, d.reason)
        self.assertNotIn(token, str(d.to_dict()))


if __name__ == "__main__":
    unittest.main()
