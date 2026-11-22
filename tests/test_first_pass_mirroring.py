"""S-336 acceptance battery: the first-pass mirroring run.

Acceptance (roadmap S-336): the public originals are mirrored
and verified ref-for-ref against GitHub -- proof-first: one
small repo verified before the batch.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.census_fixture import CensusFixtureService, parse_classification
from samverk.db import schema_version
from samverk.first_pass_mirroring import (
    ACTION_BLOCK_BATCH, ACTION_RUN_BATCH, FAILED, PHASE_BATCH,
    PHASE_PROOF, VERIFIED, FirstPassError, FirstPassMirroringService,
    compare_ref_maps, decide_batch, parse_ls_remote, plan_first_pass,
    render_first_pass_page)
from samverk.proc import run_git_ls_remote_refs
from samverk.pull_mirrors import PullMirrorService
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


def make_source(base: Path, name: str, *, tag: bool = False,
                second_branch: bool = False) -> tuple[Path, dict[str, str]]:
    src = base / name
    subprocess.run(["git", "init", "--bare", "-b", "main", str(src)],
                   check=True, capture_output=True)
    blob = git(src, "hash-object", "-w", "--stdin", input_bytes=b"hi\n")
    tree = git(src, "mktree",
               input_bytes=f"100644 blob {blob}\tx.txt\n".encode())
    commit = git(src, "commit-tree", tree, input_bytes=b"first\n")
    git(src, "update-ref", "refs/heads/main", commit)
    refs = {"refs/heads/main": commit}
    if second_branch:
        git(src, "update-ref", "refs/heads/dev", commit)
        refs["refs/heads/dev"] = commit
    if tag:
        tag_obj = git(src, "mktag", input_bytes=(
            f"object {commit}\ntype commit\ntag v1\n"
            f"tagger A <a@e.c> 0 +0000\n\nrelease\n").encode())
        git(src, "update-ref", "refs/tags/v1", tag_obj)
        refs["refs/tags/v1"] = tag_obj
    return src, refs


def census_entry(name, private=False):
    return {"name": name, "private": private, "fork": False,
            "parent": "", "note": ""}


class FirstPassTests(unittest.TestCase):
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
        self.first = FirstPassMirroringService(
            self.conn, self.data_root, self.accounts, self.repos, self.audit)

    def define(self, name: str, source: Path, private: bool = False):
        """Define one mirror through the census road (S-335),
        then point its record at the local source the test
        built -- the census builds GitHub URLs, and this
        battery verifies against on-disk originals."""
        parsed = parse_classification(json.dumps(
            {"include": [census_entry(name, private=private)]}))
        self.census.import_classification(
            self.owner.id, "volmarr", parsed, github_owner="hrabanazviking")
        repo = self.repos.get_repository("volmarr", name)
        with self.conn:
            self.conn.execute(
                "UPDATE repo_mirrors SET source = ?, source_kind = 'local'"
                " WHERE repo_id = ?", (str(source), repo.id))

    # -- pins ------------------------------------------------------
    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 139)
        self.assertEqual(db.MIGRATIONS[-1][0], 139)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 138)

    # -- pure ref judgement ------------------------------------------
    def test_compare_exact_maps_verify(self):
        refs = {"refs/heads/main": "a" * 40, "refs/tags/v1": "b" * 40}
        verdict = compare_ref_maps(refs, dict(refs))
        self.assertTrue(verdict.verified)
        self.assertEqual(verdict.matched, 2)
        self.assertIn("verified ref-for-ref", verdict.headline)

    def test_compare_names_missing_extra_and_diverged(self):
        source = {"refs/heads/main": "a" * 40, "refs/heads/dev": "c" * 40,
                  "refs/tags/v1": "b" * 40}
        mirror = {"refs/heads/main": "d" * 40, "refs/tags/v1": "b" * 40,
                  "refs/heads/stale": "e" * 40}
        verdict = compare_ref_maps(source, mirror)
        self.assertFalse(verdict.verified)
        self.assertEqual(verdict.missing, ("refs/heads/dev",))
        self.assertEqual(verdict.extra, ("refs/heads/stale",))
        self.assertEqual(verdict.diverged, ("refs/heads/main",))
        self.assertEqual(verdict.matched, 1)

    def test_compare_empty_source_never_verifies(self):
        verdict = compare_ref_maps({}, {})
        self.assertFalse(verdict.verified)
        self.assertIn("no refs", verdict.headline)

    def test_compare_ignores_refs_outside_mirror_scope(self):
        source = {"refs/heads/main": "a" * 40, "refs/pull/1/head": "f" * 40}
        mirror = {"refs/heads/main": "a" * 40}
        self.assertTrue(compare_ref_maps(source, mirror).verified)

    def test_parse_ls_remote_drops_peeled_and_out_of_scope(self):
        text = ("a" * 40 + "\trefs/heads/main\n"
                + "b" * 40 + "\trefs/tags/v1\n"
                + "c" * 40 + "\trefs/tags/v1^{}\n"
                + "d" * 40 + "\tHEAD\n")
        self.assertEqual(parse_ls_remote(text),
                         {"refs/heads/main": "a" * 40,
                          "refs/tags/v1": "b" * 40})

    def test_parse_ls_remote_refuses_malformed_lines(self):
        with self.assertRaises(FirstPassError):
            parse_ls_remote("not-a-ref-line\n")

    # -- pure planning and the gate -----------------------------------
    def test_plan_picks_first_public_as_proof_and_counts_skips(self):
        self.define("beta", make_source(self.outside, "beta.git")[0])
        self.define("alpha", make_source(self.outside, "alpha.git")[0])
        self.define("secret", make_source(self.outside, "secret.git")[0],
                    private=True)
        plan = plan_first_pass(self.census.entries())
        self.assertEqual(plan.proof.name, "alpha")
        self.assertEqual([r.name for r in plan.batch], ["beta"])
        self.assertEqual(plan.skipped_private, 1)
        self.assertEqual(plan.skipped_held, 0)

    def test_gate_opens_only_behind_a_verified_proof(self):
        self.assertEqual(decide_batch(VERIFIED).action, ACTION_RUN_BATCH)
        self.assertEqual(decide_batch(FAILED).action, ACTION_BLOCK_BATCH)

    # -- the seam ------------------------------------------------------
    def test_ls_remote_seam_reads_a_local_source(self):
        src, refs = make_source(self.outside, "src.git", tag=True,
                                second_branch=True)
        result = run_git_ls_remote_refs(src, timeout=30.0)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            parse_ls_remote(result.stdout.decode()), refs)

    # -- the run ---------------------------------------------------------
    def test_first_pass_proof_then_batch_all_verified(self):
        alpha_src, alpha_refs = make_source(self.outside, "alpha.git",
                                            tag=True)
        beta_src, beta_refs = make_source(self.outside, "beta.git",
                                          second_branch=True)
        self.define("beta", beta_src)
        self.define("alpha", alpha_src)
        report = self.first.run_first_pass("volmarr")
        self.assertFalse(report.batch_blocked)
        self.assertIsNotNone(report.proof)
        self.assertEqual(report.proof.phase, PHASE_PROOF)
        self.assertEqual(report.proof.full_name, "volmarr/alpha")
        self.assertEqual(report.proof.state, VERIFIED)
        self.assertEqual(report.proof.refs_matched, len(alpha_refs))
        self.assertEqual(len(report.batch), 1)
        self.assertEqual(report.batch[0].phase, PHASE_BATCH)
        self.assertEqual(report.batch[0].state, VERIFIED)
        self.assertEqual(report.batch[0].refs_matched, len(beta_refs))
        self.assertEqual(report.verified_count, 2)
        self.assertTrue(self.pull.is_ready("volmarr", "alpha"))
        self.assertEqual(self.first.mirror_refs("volmarr", "alpha"),
                         alpha_refs)
        stored = self.first.latest_run("volmarr/beta")
        self.assertEqual(stored.state, VERIFIED)

    def test_failed_proof_blocks_the_batch(self):
        alpha_src, _ = make_source(self.outside, "alpha.git")
        beta_src, _ = make_source(self.outside, "beta.git")
        self.define("alpha", alpha_src)
        self.define("beta", beta_src)
        alpha_src.rename(self.outside / "alpha-gone.git")
        report = self.first.run_first_pass("volmarr")
        self.assertTrue(report.batch_blocked)
        self.assertEqual(report.proof.state, FAILED)
        self.assertIn("sync failed", report.proof.detail)
        self.assertEqual(report.batch, [])
        # The batch repo was never synced: still pending, never ready.
        beta = self.pull.pull_mirror_for("volmarr", "beta")
        self.assertFalse(beta.ready)
        self.assertEqual(self.first.runs_for("volmarr/beta"), [])
        self.assertIn("batch was not started", report.headline)

    def test_diverged_mirror_fails_verification_after_sync(self):
        alpha_src, _ = make_source(self.outside, "alpha.git")
        self.define("alpha", alpha_src)
        first = self.first.run_first_pass("volmarr")
        self.assertEqual(first.proof.state, VERIFIED)
        # The source moves after the mirror synced; a fresh
        # verification (no sync) must now refuse to verify.
        blob = git(alpha_src, "hash-object", "-w", "--stdin",
                   input_bytes=b"new\n")
        tree = git(alpha_src, "mktree",
                   input_bytes=f"100644 blob {blob}\ty.txt\n".encode())
        commit = git(alpha_src, "commit-tree", tree,
                     input_bytes=b"second\n")
        git(alpha_src, "update-ref", "refs/heads/main", commit)
        verdict = self.first.verify_mirror("volmarr", "alpha")
        self.assertFalse(verdict.verified)
        self.assertEqual(verdict.diverged, ("refs/heads/main",))

    def test_private_and_held_entries_are_never_touched(self):
        pub_src, _ = make_source(self.outside, "pub.git")
        self.define("pub", pub_src)
        self.define("secret", make_source(self.outside, "s.git")[0],
                    private=True)
        parsed = parse_classification(json.dumps(
            {"uncertain": [census_entry("maybe")]}))
        self.census.import_classification(
            self.owner.id, "volmarr", parsed, github_owner="hrabanazviking")
        report = self.first.run_first_pass("volmarr")
        self.assertEqual(report.skipped_private, 1)
        self.assertEqual(report.skipped_held, 1)
        secret = self.pull.pull_mirror_for("volmarr", "secret")
        self.assertFalse(secret.ready)
        self.assertEqual(self.first.runs_for("volmarr/secret"), [])
        self.assertIsNone(self.repos.get_repository("volmarr", "maybe"))

    def test_empty_pass_is_stated_not_faked(self):
        report = self.first.run_first_pass("volmarr")
        self.assertIsNone(report.proof)
        self.assertIn("no public originals", report.headline)

    def test_run_one_refuses_a_non_mirror(self):
        self.repos.create_repository(self.owner.id, "volmarr", "plain")
        with self.assertRaises(FirstPassError):
            self.first.run_one("volmarr", "plain", PHASE_PROOF)

    def test_page_states_the_gate_and_the_verdicts(self):
        alpha_src, _ = make_source(self.outside, "alpha.git")
        self.define("alpha", alpha_src)
        report = self.first.run_first_pass("volmarr")
        page = render_first_pass_page(report)
        self.assertIn("volmarr/alpha", page)
        self.assertIn("verified", page)


if __name__ == "__main__":
    unittest.main()
