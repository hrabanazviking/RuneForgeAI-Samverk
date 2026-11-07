"""S-182 acceptance battery: tag protection.

Acceptance (roadmap S-182): tag name patterns
protected from deletion and force-move; release
tags get the strongest default.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.hooks import RefUpdate
from samverk.issues import IssueStore
from samverk.protection_push_shape import CREATION, DELETION, FAST_FORWARD, FORCE, NO_OP, UNPROVEN
from samverk.protection_rules import ProtectionSettings
from samverk.protection_rulesets import RulesetStore, evaluate_layered
from samverk.protection_tags import (
    PROTECTED_TAG_REFUSED, TagProtectionStore, TagRefusedError,
    decide_tag_update, is_release_tag, render_tag_decision, tag_from_ref)
from samverk.receive_gate import GateContext, GateVeto
from samverk.repositories import RepositoryStore

ZERO = "0" * 40

def git(repo, *args, input_bytes=None):
    env = {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": "/usr/bin:/bin"}
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         capture_output=True, input=input_bytes, env=env)
    assert out.returncode == 0, out.stderr.decode()
    return out.stdout.decode().strip()

def make_commit(repo, parents, files, message):
    lines = []
    for name in sorted(files):
        blob = git(repo, "hash-object", "-w", "--stdin", input_bytes=files[name].encode())
        lines.append(f"100644 blob {blob}\t{name}\n")
    tree = git(repo, "mktree", input_bytes="".join(lines).encode())
    headers = [f"tree {tree}"]
    for p in parents:
        headers.append(f"parent {p}")
    headers.append("author T <t@t> 1700000000 +0000")
    headers.append("committer T <t@t> 1700000000 +0000")
    raw = ("\n".join(headers) + f"\n\n{message}\n").encode()
    return git(repo, "hash-object", "-t", "commit", "-w", "--stdin", input_bytes=raw)

BASE_FILES = {"a.txt": "alpha\n"}
HEAD_FILES = {"a.txt": "beta\n"}
SIDE_FILES = {"a.txt": "alpha\n", "b.txt": "side\n"}

class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now

class TagProtectionTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, time_fn=self.clock)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.reader = self.accounts.register("yrsa", "correct horse battery")
        self.conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (self.owner.id,))
        self.conn.commit()
        self.admin = self.accounts.get_by_id(self.owner.id)
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.issues = IssueStore(self.conn, self.repos, self.accounts, audit=self.audit, time_fn=self.clock)
        self.rulesets = RulesetStore(self.conn, self.repos, self.accounts, audit=self.audit, time_fn=self.clock)
        self.gate = TagProtectionStore(self.conn, self.repos, self.accounts, self.issues, audit=self.audit, time_fn=self.clock, rulesets=self.rulesets)
        self.repos.create_repository(self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(self.owner.id, "volmarr", "priv", visibility="private")
        self.path = self.repos.path_for("volmarr", "pub")
        self.base_oid = make_commit(self.path, [], BASE_FILES, "base")
        git(self.path, "update-ref", "refs/heads/main", self.base_oid)
        self.ff_oid = make_commit(self.path, [self.base_oid], HEAD_FILES, "ff")
        self.div_oid = make_commit(self.path, [self.base_oid], SIDE_FILES, "div")

    def _ruleset(self, name="Tags", tags=("stable-*",), **settings):
        return self.rulesets.create_ruleset(
            self.admin, name, target="tag",
            repo_patterns=["volmarr/*"], tag_patterns=list(tags),
            settings=ProtectionSettings(**settings) if settings else ProtectionSettings())

    # release detection
    def test_release_detection(self):
        for t in ("v1", "v1.2", "v1.2.3", "v2.0.0-rc1", "1.2.3", "release-2026", "release/2026-11", "RELEASE-1"):
            self.assertTrue(is_release_tag(t), t)
        for t in ("nightly", "stable-1", "vnext", "version1", "edge", ""):
            self.assertFalse(is_release_tag(t), t)

    def test_tag_from_ref(self):
        self.assertEqual(tag_from_ref("refs/tags/v1"), "v1")
        self.assertIsNone(tag_from_ref("refs/heads/main"))
        self.assertIsNone(tag_from_ref("HEAD"))
        self.assertIsNone(tag_from_ref(None))

    # pure decisions via layered evaluation (no rulesets)
    def test_pure_release_deletion_blocked(self):
        ev = evaluate_layered([], [], "volmarr/pub", "tag", "v1.2.3")
        d = decide_tag_update(ev, "v1.2.3", self.base_oid, ZERO)
        self.assertEqual(d.shape, DELETION)
        self.assertFalse(d.satisfied)
        self.assertTrue(d.blocks_deletion)

    def test_pure_release_force_blocked(self):
        ev = evaluate_layered([], [], "volmarr/pub", "tag", "v1")
        d = decide_tag_update(ev, "v1", self.base_oid, self.div_oid, ancestor=False)
        self.assertEqual(d.shape, FORCE)
        self.assertFalse(d.satisfied)

    def test_pure_release_creation_and_ff_pass(self):
        ev = evaluate_layered([], [], "volmarr/pub", "tag", "v1")
        self.assertTrue(decide_tag_update(ev, "v1", ZERO, self.base_oid).satisfied)
        self.assertTrue(decide_tag_update(ev, "v1", self.base_oid, self.ff_oid, ancestor=True).satisfied)
        self.assertTrue(decide_tag_update(ev, "v1", self.base_oid, self.base_oid).satisfied)

    def test_pure_release_unproven_blocked(self):
        ev = evaluate_layered([], [], "volmarr/pub", "tag", "v1")
        d = decide_tag_update(ev, "v1", self.base_oid, self.div_oid, ancestor=None)
        self.assertEqual(d.shape, UNPROVEN)
        self.assertFalse(d.satisfied)

    def test_pure_unprotected_tag_passes_all(self):
        ev = evaluate_layered([], [], "volmarr/pub", "tag", "nightly")
        self.assertTrue(decide_tag_update(ev, "nightly", self.base_oid, ZERO).satisfied)
        self.assertTrue(decide_tag_update(ev, "nightly", self.base_oid, self.div_oid, ancestor=False).satisfied)

    # store: ruleset-protected tag
    def test_store_ruleset_deletion_blocked(self):
        self._ruleset()
        d = self.gate.check_tag_update(self.owner, "volmarr", "pub", "stable-1", self.base_oid, ZERO)
        self.assertFalse(d.satisfied)
        with self.assertRaises(TagRefusedError) as cm:
            self.gate.enforce_tag_update(self.owner, "volmarr", "pub", "stable-1", self.base_oid, ZERO)
        self.assertEqual(cm.exception.reason, PROTECTED_TAG_REFUSED)

    def test_store_ruleset_force_blocked_real_git(self):
        self._ruleset()
        d = self.gate.check_tag_update(self.owner, "volmarr", "pub", "stable-1", self.ff_oid, self.div_oid)
        self.assertEqual(d.shape, FORCE)
        self.assertFalse(d.satisfied)

    def test_store_ruleset_ff_passes_real_git(self):
        self._ruleset()
        d = self.gate.check_tag_update(self.owner, "volmarr", "pub", "stable-1", self.base_oid, self.ff_oid)
        self.assertTrue(d.satisfied)

    def test_store_ruleset_blocks_off_passes(self):
        self._ruleset(block_force_pushes=False, block_branch_deletion=False)
        d = self.gate.check_tag_update(self.owner, "volmarr", "pub", "stable-1", self.base_oid, ZERO)
        self.assertTrue(d.satisfied)

    def test_store_release_blocked_without_ruleset(self):
        d = self.gate.check_tag_update(self.owner, "volmarr", "pub", "v9.9.9", self.base_oid, ZERO)
        self.assertFalse(d.satisfied)
        self.assertIn("release tag", d.words)

    def test_store_release_force_blocked_despite_ruleset_off(self):
        # A tag ruleset for v* with blocks off does not loosen release default.
        self.rulesets.create_ruleset(self.admin, "Vee", target="tag", repo_patterns=["volmarr/*"], tag_patterns=["v*"], settings=ProtectionSettings(block_force_pushes=False, block_branch_deletion=False))
        d = self.gate.check_tag_update(self.owner, "volmarr", "pub", "v1.0.0", self.base_oid, ZERO)
        self.assertFalse(d.satisfied)

    def test_store_unprotected_passes(self):
        d = self.gate.check_tag_update(self.owner, "volmarr", "pub", "nightly", self.base_oid, ZERO)
        self.assertTrue(d.satisfied)

    def test_store_private_stranger_repo_not_found(self):
        with self.assertRaises(Exception) as cm:
            self.gate.check_tag_update(self.reader, "volmarr", "priv", "v1", self.base_oid, ZERO)
        self.assertEqual(getattr(cm.exception, "reason", ""), "repo_not_found")

    def test_check_push_skips_branches(self):
        self._ruleset()
        updates = [RefUpdate(ref="refs/heads/main", old_oid=self.base_oid, new_oid=ZERO),
                   RefUpdate(ref="refs/tags/stable-1", old_oid=self.base_oid, new_oid=ZERO)]
        ds = self.gate.check_push(self.owner, "volmarr", "pub", updates)
        self.assertEqual(len(ds), 1)
        self.assertEqual(ds[0].tag, "stable-1")
        with self.assertRaises(TagRefusedError):
            self.gate.enforce_push(self.owner, "volmarr", "pub", updates)

    def test_receive_gate_plugin_vetoes(self):
        self._ruleset()
        plugin = self.gate.receive_gate_plugin()
        ctx = GateContext(repo="volmarr/pub", owner="volmarr", repo_name="pub", actor="volmarr", updates=(RefUpdate(ref="refs/tags/stable-1", old_oid=self.base_oid, new_oid=ZERO),))
        with self.assertRaises(GateVeto):
            plugin(ctx)
        ctx2 = GateContext(repo="volmarr/pub", owner="volmarr", repo_name="pub", actor="volmarr", updates=(RefUpdate(ref="refs/tags/nightly", old_oid=self.base_oid, new_oid=ZERO),))
        self.assertIsNone(plugin(ctx2))

    def test_render_escapes_and_words(self):
        ev = evaluate_layered([], [], "volmarr/pub", "tag", "v1")
        d = decide_tag_update(ev, "v1", self.base_oid, ZERO)
        html = render_tag_decision(d)
        self.assertIn("Tag protection gate", html)
        self.assertIn("not satisfied", html)

    def test_no_migration_no_taxonomy(self):
        self.assertEqual(schema_version(self.conn), 78)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 122)

if __name__ == "__main__":
    unittest.main()
