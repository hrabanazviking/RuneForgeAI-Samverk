"""S-337 acceptance battery: private originals.

Acceptance (roadmap S-337): with a read-scoped GitHub
credential in place, the private originals mirror too,
landing as *private* mirrors always.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import json, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.census_fixture import CensusFixtureService, parse_classification
from samverk.db import schema_version
from samverk.mirror_credentials import MirrorCredentialService
from samverk.private_originals import (
    ACTION_ALLOW, ACTION_REFUSE, PHASE_PRIVATE, PrivateOriginalsService,
    decide_credential, landing_is_private, plan_private_originals,
    render_private_originals_page)
from samverk.pull_mirrors import PullMirrorService
from samverk.repositories import RepositoryStore
from samverk.secrets import Secrets


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


def make_source(base: Path, name: str) -> Path:
    src = base / name
    subprocess.run(["git", "init", "--bare", "-b", "main", str(src)],
                   check=True, capture_output=True)
    blob = git(src, "hash-object", "-w", "--stdin", input_bytes=b"hi\n")
    tree = git(src, "mktree",
               input_bytes=f"100644 blob {blob}\tx.txt\n".encode())
    commit = git(src, "commit-tree", tree, input_bytes=b"first\n")
    git(src, "update-ref", "refs/heads/main", commit)
    return src


def census_entry(name, private=False):
    return {"name": name, "private": private, "fork": False,
            "parent": "", "note": ""}


class PrivateOriginalsTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        root = Path(self._td.name)
        self.outside = root / "outside"; self.outside.mkdir()
        self.data_root = root / "instance"; self.data_root.mkdir()
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.data_root, self.accounts)
        self.audit = AuditLog(self.conn)
        self.census = CensusFixtureService(
            self.conn, self.data_root, self.accounts, self.repos, self.audit)
        self.pull = PullMirrorService(
            self.conn, self.data_root, self.accounts, self.repos)
        self.creds = MirrorCredentialService(
            self.conn, self.data_root, self.accounts, self.repos, self.audit)
        self.private = PrivateOriginalsService(
            self.conn, self.data_root, self.accounts, self.repos, self.audit)
        self.secrets = Secrets({"GITHUB_READ_TOKEN": "test-token-value"})

    def define(self, name: str, source: Path, private: bool = True,
               bucket: str = "include"):
        parsed = parse_classification(json.dumps(
            {bucket: [census_entry(name, private=private)]}))
        self.census.import_classification(
            self.owner.id, "volmarr", parsed, github_owner="hrabanazviking")
        repo = self.repos.get_repository("volmarr", name)
        if repo is not None:
            with self.conn:
                self.conn.execute(
                    "UPDATE repo_mirrors SET source = ?, source_kind = 'local'"
                    " WHERE repo_id = ?", (str(source), repo.id))
        return repo

    def name_credential(self, name: str):
        self.creds.set_credential(
            self.owner.id, "volmarr", name, "GITHUB_READ_TOKEN")

    # -- pins ------------------------------------------------------
    def test_schema_and_taxonomy_pins_unchanged(self):
        # S-337 reuses the standing run log and seams: no
        # migration, no new audit event, on purpose.
        self.assertEqual(schema_version(self.conn), 139)
        self.assertEqual(db.MIGRATIONS[-1][0], 139)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 138)

    # -- pure credential gate ----------------------------------------
    def test_gate_refuses_missing_credential(self):
        verdict = decide_credential(False, "read")
        self.assertEqual(verdict.action, ACTION_REFUSE)
        self.assertIn("no credential", verdict.reason)

    def test_gate_refuses_undeclared_scope(self):
        verdict = decide_credential(True, "")
        self.assertEqual(verdict.action, ACTION_REFUSE)
        self.assertIn("not declared", verdict.reason)

    def test_gate_refuses_write_scope(self):
        verdict = decide_credential(True, "contents:write")
        self.assertEqual(verdict.action, ACTION_REFUSE)
        self.assertIn("not read-only", verdict.reason)

    def test_gate_refuses_read_word_beside_write_word(self):
        verdict = decide_credential(True, "read contents:write")
        self.assertEqual(verdict.action, ACTION_REFUSE)

    def test_gate_refuses_unknown_scope_word(self):
        verdict = decide_credential(True, "everything")
        self.assertEqual(verdict.action, ACTION_REFUSE)

    def test_gate_allows_read_scoped(self):
        for scope in ("read", "read-only", "contents:read",
                      "metadata:read contents:read"):
            self.assertEqual(
                decide_credential(True, scope).action, ACTION_ALLOW, scope)

    # -- pure landing + plan ------------------------------------------
    def test_landing_is_private_only_for_private(self):
        self.assertTrue(landing_is_private("private"))
        self.assertFalse(landing_is_private("public"))
        self.assertFalse(landing_is_private("internal"))
        self.assertFalse(landing_is_private(None))

    def test_plan_takes_private_counts_public_and_held(self):
        src = make_source(self.outside, "plan-src")
        self.define("priv-a", src, private=True)
        self.define("pub-a", src, private=False)
        self.define("held-a", src, private=True, bucket="uncertain")
        plan = plan_private_originals(self.census.entries())
        self.assertEqual([e.name for e in plan.entries], ["priv-a"])
        self.assertEqual(plan.skipped_public, 1)
        self.assertEqual(plan.skipped_held, 1)

    # -- the gate in action --------------------------------------------
    def test_run_without_credential_refuses_and_syncs_nothing(self):
        src = make_source(self.outside, "gate-src")
        self.define("priv-gate", src)
        report = self.private.run_private_originals(
            "volmarr", secrets=self.secrets, declared_scope="read")
        self.assertEqual(len(report.runs), 1)
        self.assertEqual(report.runs[0].state, "failed")
        self.assertIn("credential gate refused", report.runs[0].detail)
        self.assertEqual(report.runs[0].phase, PHASE_PRIVATE)
        self.assertFalse(self.pull.is_ready("volmarr", "priv-gate"))
        self.assertEqual(
            len(self.private.runs_for("volmarr/priv-gate")), 1)

    def test_run_with_write_scope_refuses_and_syncs_nothing(self):
        src = make_source(self.outside, "write-src")
        self.define("priv-write", src)
        self.name_credential("priv-write")
        report = self.private.run_private_originals(
            "volmarr", secrets=self.secrets,
            declared_scope="contents:write")
        self.assertEqual(report.runs[0].state, "failed")
        self.assertIn("not read-only", report.runs[0].detail)
        self.assertFalse(self.pull.is_ready("volmarr", "priv-write"))

    def test_run_with_unloaded_secret_refuses(self):
        src = make_source(self.outside, "unloaded-src")
        self.define("priv-unloaded", src)
        self.name_credential("priv-unloaded")
        report = self.private.run_private_originals(
            "volmarr", secrets=Secrets({}), declared_scope="read")
        self.assertEqual(report.runs[0].state, "failed")
        self.assertIn("credential gate refused", report.runs[0].detail)
        self.assertFalse(self.pull.is_ready("volmarr", "priv-unloaded"))

    # -- the happy road --------------------------------------------------
    def test_private_original_mirrors_and_verifies(self):
        src = make_source(self.outside, "happy-src")
        self.define("priv-happy", src)
        self.name_credential("priv-happy")
        report = self.private.run_private_originals(
            "volmarr", secrets=self.secrets, declared_scope="read")
        self.assertEqual(report.verified_count, 1)
        self.assertEqual(report.runs[0].refs_matched, 1)
        self.assertTrue(self.pull.is_ready("volmarr", "priv-happy"))
        repo = self.repos.get_repository("volmarr", "priv-happy")
        self.assertEqual(repo.visibility, "private")

    def test_drifted_visibility_is_repaired_before_sync(self):
        src = make_source(self.outside, "drift-src")
        repo = self.define("priv-drift", src)
        self.repos.update_metadata(
            self.owner.id, "volmarr", "priv-drift", visibility="public")
        self.assertEqual(
            self.repos.get_repository("volmarr", "priv-drift").visibility,
            "public")
        self.name_credential("priv-drift")
        report = self.private.run_private_originals(
            "volmarr", secrets=self.secrets,
            declared_scope="contents:read")
        self.assertEqual(report.verified_count, 1)
        self.assertIn("landing repaired", report.runs[0].detail)
        self.assertEqual(
            self.repos.get_repository("volmarr", "priv-drift").visibility,
            "private")

    def test_public_and_held_entries_are_never_touched(self):
        src = make_source(self.outside, "scope-src")
        self.define("pub-only", src, private=False)
        self.define("held-only", src, private=True, bucket="uncertain")
        report = self.private.run_private_originals(
            "volmarr", secrets=self.secrets, declared_scope="read")
        self.assertEqual(report.runs, [])
        self.assertEqual(report.skipped_public, 1)
        self.assertEqual(report.skipped_held, 1)
        self.assertFalse(self.pull.is_ready("volmarr", "pub-only"))

    def test_token_never_stands_in_a_recorded_detail(self):
        src = make_source(self.outside, "scrub-src")
        self.define("priv-scrub", src)
        self.name_credential("priv-scrub")
        report = self.private.run_private_originals(
            "volmarr", secrets=self.secrets, declared_scope="read")
        for run in report.runs:
            self.assertNotIn("test-token-value", run.detail)

    # -- page --------------------------------------------------------------
    def test_page_states_verdicts_in_words(self):
        src = make_source(self.outside, "page-src")
        self.define("priv-page", src)
        self.name_credential("priv-page")
        report = self.private.run_private_originals(
            "volmarr", secrets=self.secrets, declared_scope="read")
        page = render_private_originals_page(report)
        self.assertIn("Private originals mirroring", page)
        self.assertIn("priv-page", page)
        self.assertIn("verified", page)


if __name__ == "__main__":
    unittest.main()
