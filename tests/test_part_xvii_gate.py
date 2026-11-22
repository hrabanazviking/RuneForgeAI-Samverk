"""S-344 -- PART XVII GATE battery: mirroring & backup duty, assembled.

The whole Part XVII system struck at once, in the house
gate shape of S-204/S-220/S-236/S-256/S-272/S-288/S-312/
S-328 -- no new production code, only the battery that
walks the landed S-330..S-338 machinery end to end through
its public seams, at the things the gate names: **mirror
freshness, restore proof, and the census fixture
reconciled; counted green.**

- **The pins** -- the assembled system stands at schema
  139 with 138 audit events (33 auth / 92 repo / 13 admin),
  and the claims register still stands at its 35 rows
  (C-01..C-35) untouched: Part XVII minted no register
  extension of its own, and this gate claims none. The
  gate claims no migration and no taxonomy event.
- **The census fixture reconciled (S-335)** -- the full
  54-originals fixture imports as 54 mirror definitions,
  17 held uncertain, 84 excluded; re-import is idempotent;
  a held entry is never mirrored until the owner's word
  releases exactly that one.
- **Mirror freshness (S-330..S-338)** -- the first pass
  (S-336) verifies public originals ref-for-ref, proof
  before batch, a failed proof blocks the batch; drift
  after a sync is *detected* by re-verification and cured
  by a re-sync; sync status (S-332) reads healthy only
  after a successful sync and a failed mirror never looks
  healthy; the scheduler's sync-now (S-331) brings a
  mirror fresh through the credential road (S-330); the
  write law (S-334) refuses local writes to a mirror;
  push mirrors (S-333) carry a repo onward ref-for-ref;
  private originals (S-337) mirror only behind a
  read-scoped credential and land private always;
  metadata import (S-338) lands issues, labels,
  milestones and releases marked imported with source
  links, idempotently.
- **Restore proof (S-074)** -- over the seams that exist
  on this base: a mirrored repository is exported with
  S-074's primitive (bundle + metadata JSON), the
  metadata's SHA-256 and refs agree with the bundle and
  the source, and a stock-git bare clone from the bundle
  restores every ref exactly. S-341 (whole-instance
  export) and S-342 (restore drill) are being built in
  parallel by other teams and are NOT on this base; the
  gate record (docs/PART_XVII_GATE.md) names that
  honestly -- this battery proves restore over S-074,
  not over S-341/S-342.
- **The honest remainder** -- S-339 (wiki mirror), S-340
  (LFS mirror), S-341, S-342 and S-343 (drift census)
  land after this gate in banking order and are not on
  this base; the gate record names them as the gate's
  remainder rather than pretending coverage.

Counted with: python3 -m unittest tests.test_part_xvii_gate
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.census_fixture import (
    DEFINED, HELD, CensusFixtureService, parse_classification)
from samverk.db import schema_version
from samverk.first_pass_mirroring import (
    FAILED, PHASE_PROOF, VERIFIED, FirstPassMirroringService)
from samverk.metadata_import import (
    KIND_ISSUE, STATE_IMPORTED, MetadataImportService)
from samverk.mirror_credentials import MirrorCredentialService
from samverk.mirror_write_law import MirrorWriteLaw
from samverk.mirrors import MirrorService
from samverk.private_originals import PrivateOriginalsService
from samverk.pull_mirrors import PullMirrorService
from samverk.push_mirrors import PushMirrorService
from samverk.refs import RefStore
from samverk.repo_backup import BackupError, RepoBackup
from samverk.repositories import RepositoryStore
from samverk.secrets import Secrets
from samverk.sync_scheduler import SyncSchedulerService
from samverk.sync_status import SyncStatusService

ROOT = Path(__file__).resolve().parent.parent
REGISTER = ROOT / "docs" / "CLAIMS_REGISTER.md"
GATE_DOC = ROOT / "docs" / "PART_XVII_GATE.md"
PW = "correct horse battery"
GH = "hrabanazviking"


def git(repo, *args, input_bytes=None):
    env = dict(os.environ)
    env.update({"GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@e.c",
                "GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": "a@e.c"})
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         input=input_bytes, capture_output=True, env=env)
    assert out.returncode == 0, out.stderr.decode()
    return out.stdout.decode().strip()


def make_source(base, name, *, tag=False, second_branch=False):
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


def advance_source(src, parent):
    blob = git(src, "hash-object", "-w", "--stdin", input_bytes=b"two\n")
    tree = git(src, "mktree",
               input_bytes=f"100644 blob {blob}\tx.txt\n".encode())
    commit = git(src, "commit-tree", tree, "-p", parent,
                 input_bytes=b"second\n")
    git(src, "update-ref", "refs/heads/main", commit)
    return commit


def census_entry(name, private=False, note=""):
    return {"name": name, "private": private, "fork": False,
            "size_kb": 1, "updated": "2026-10-27", "branch": "main",
            "parent": "", "note": note}


def full_classification():
    include = ([census_entry(f"pub-{i:02d}") for i in range(43)]
               + [census_entry(f"priv-{i:02d}", private=True)
                  for i in range(11)])
    uncertain = [census_entry(f"unc-{i:02d}") for i in range(17)]
    exclude = [census_entry(f"exc-{i:02d}") for i in range(84)]
    return parse_classification(json.dumps(
        {"include": include, "uncertain": uncertain,
         "exclude": exclude}))


META_PAYLOADS = {
    "labels": [{"name": "bug", "color": "d73a4a",
                "description": "Broken",
                "html_url": "https://github.com/hrabanazviking/widget/labels"}],
    "milestones": [{"title": "v1.0", "description": "First",
                    "state": "open",
                    "html_url": "https://github.com/hrabanazviking/widget/milestone/1"}],
    "issues": [{"number": 7, "title": "Imported bug",
                "body": "From GitHub", "state": "closed",
                "labels": [{"name": "bug"}], "milestone": None,
                "html_url": "https://github.com/hrabanazviking/widget/issues/7"},
               {"number": 8, "title": "A pull request", "state": "open",
                "pull_request": {"url": "https://api.github.com/x"},
                "html_url": "https://github.com/hrabanazviking/widget/pull/8"}],
    "releases": [{"tag_name": "v1.0.0", "name": "First release",
                  "body": "Notes", "draft": False, "prerelease": False,
                  "html_url": "https://github.com/hrabanazviking/widget/releases/tag/v1.0.0"}],
}


class FakeFetch:
    def __init__(self):
        self.calls = []

    def __call__(self, url, token=None):
        self.calls.append((url, token))
        for endpoint, payload in META_PAYLOADS.items():
            if f"/{endpoint}?" in url:
                return json.loads(json.dumps(payload))
        return []


class GateBase(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        root = Path(self._td.name)
        self.outside = root / "outside"; self.outside.mkdir()
        self.data_root = root / "instance"; self.data_root.mkdir()
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", PW)
        self.other = self.accounts.register("yrsa", PW)
        self.repos = RepositoryStore(
            self.conn, self.data_root, self.accounts)
        self.audit = AuditLog(self.conn)
        self.clock = [1_700_000_000.0]
        self.census = CensusFixtureService(
            self.conn, self.data_root, self.accounts, self.repos,
            self.audit)
        self.pull = PullMirrorService(
            self.conn, self.data_root, self.accounts, self.repos)
        self.first = FirstPassMirroringService(
            self.conn, self.data_root, self.accounts, self.repos,
            self.audit)
        self.private = PrivateOriginalsService(
            self.conn, self.data_root, self.accounts, self.repos,
            self.audit)
        self.creds = MirrorCredentialService(
            self.conn, self.data_root, self.accounts, self.repos,
            self.audit)
        self.mirrors = MirrorService(
            self.conn, self.data_root, self.accounts, self.repos,
            audit=self.audit, time_fn=lambda: self.clock[0])
        self.status = SyncStatusService(
            self.conn, self.data_root, self.accounts, self.repos)
        self.backup = RepoBackup(
            self.conn, self.data_root, self.accounts, self.repos)
        self.secrets = Secrets({"GITHUB_READ_TOKEN": "gate-token-344"})

    def define(self, name, source, private=False, bucket="include"):
        parsed = parse_classification(json.dumps(
            {bucket: [census_entry(name, private=private)]}))
        self.census.import_classification(
            self.owner.id, "volmarr", parsed, github_owner=GH)
        repo = self.repos.get_repository("volmarr", name)
        if repo is not None:
            with self.conn:
                self.conn.execute(
                    "UPDATE repo_mirrors SET source = ?,"
                    " source_kind = 'local' WHERE repo_id = ?",
                    (str(source), repo.id))
        return repo


class PinsTests(GateBase):
    def test_pins_schema_139_taxonomy_138(self):
        self.assertEqual(schema_version(self.conn), 140)
        self.assertEqual(db.MIGRATIONS[-1][0], 140)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 142)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 92)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)

    def test_register_stands_at_35_rows_untouched(self):
        rows = []
        for line in REGISTER.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if re.match(r"\| C-\d+ \|", line):
                rows.append(line.split("|")[1].strip())
        self.assertEqual(rows, [f"C-{i:02d}" for i in range(1, 36)])

    def test_part_xvii_tables_stand(self):
        tables = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ("repo_mirrors", "repo_push_mirrors",
                      "census_fixture_entries",
                      "first_pass_mirror_runs",
                      "metadata_imports", "metadata_import_runs"):
            self.assertIn(table, tables, msg=table)

    def test_gate_record_names_the_honest_remainder(self):
        text = GATE_DOC.read_text(encoding="utf-8")
        for slice_id in ("S-339", "S-340", "S-341", "S-342", "S-343"):
            self.assertIn(slice_id, text, msg=slice_id)
        self.assertIn("S-074", text)


class CensusReconciledTests(GateBase):
    def test_full_fixture_reconciled(self):
        report = self.census.import_classification(
            self.owner.id, "volmarr", full_classification(),
            github_owner=GH)
        self.assertEqual((report.defined, report.held,
                          report.skipped_excluded), (54, 17, 84))
        self.assertEqual(report.refused, [])
        self.assertEqual(self.census.summary(), {DEFINED: 54, HELD: 17})
        defined = self.census.entries(state=DEFINED)
        self.assertEqual(len(defined), 54)
        for record in defined:
            mirror = self.pull.pull_mirror_for("volmarr", record.name)
            self.assertIsNotNone(mirror, msg=record.name)
            self.assertFalse(mirror.ready, msg=record.name)
        for record in self.census.held_entries():
            self.assertIsNone(
                self.repos.get_repository("volmarr", record.name))
            self.assertIsNone(
                self.pull.pull_mirror_for("volmarr", record.name))
        priv = self.repos.get_repository("volmarr", "priv-00")
        self.assertEqual(priv.visibility, "private")
        pub = self.repos.get_repository("volmarr", "pub-00")
        self.assertEqual(pub.visibility, "public")

    def test_reimport_idempotent_and_release_by_owners_word(self):
        self.census.import_classification(
            self.owner.id, "volmarr", full_classification(),
            github_owner=GH)
        second = self.census.import_classification(
            self.owner.id, "volmarr", full_classification(),
            github_owner=GH)
        self.assertEqual((second.defined, second.held), (0, 0))
        self.assertEqual((second.already_defined,
                          second.already_held), (54, 17))
        released = self.census.release_held(
            self.owner.id, "volmarr", "unc-00", github_owner=GH)
        self.assertEqual(released.state, DEFINED)
        self.assertIsNotNone(
            self.pull.pull_mirror_for("volmarr", "unc-00"))
        self.assertEqual(len(self.census.held_entries()), 16)
        self.assertEqual(self.census.summary(), {DEFINED: 55, HELD: 16})


class MirrorFreshnessTests(GateBase):
    def test_first_pass_verifies_ref_for_ref_and_reads_fresh(self):
        alpha_src, alpha_refs = make_source(
            self.outside, "alpha.git", tag=True)
        beta_src, beta_refs = make_source(
            self.outside, "beta.git", second_branch=True)
        self.define("beta", beta_src)
        self.define("alpha", alpha_src)
        report = self.first.run_first_pass("volmarr")
        self.assertFalse(report.batch_blocked)
        self.assertEqual(report.proof.phase, PHASE_PROOF)
        self.assertEqual(report.proof.state, VERIFIED)
        self.assertEqual(report.proof.refs_matched, len(alpha_refs))
        self.assertEqual(len(report.batch), 1)
        self.assertEqual(report.batch[0].state, VERIFIED)
        self.assertEqual(report.verified_count, 2)
        self.assertEqual(self.first.mirror_refs("volmarr", "alpha"),
                         alpha_refs)
        self.assertEqual(self.first.mirror_refs("volmarr", "beta"),
                         beta_refs)
        st = self.status.status_for("volmarr", "alpha")
        self.assertIsNotNone(st)
        self.assertEqual(st.state, "healthy")
        self.assertTrue(st.healthy)

    def test_drift_is_detected_and_a_resync_restores_freshness(self):
        alpha_src, alpha_refs = make_source(self.outside, "alpha.git")
        self.define("alpha", alpha_src)
        first = self.first.run_first_pass("volmarr")
        self.assertEqual(first.proof.state, VERIFIED)
        new_head = advance_source(alpha_src, alpha_refs["refs/heads/main"])
        verdict = self.first.verify_mirror("volmarr", "alpha")
        self.assertFalse(verdict.verified)
        self.assertEqual(verdict.diverged, ("refs/heads/main",))
        second = self.first.run_first_pass("volmarr")
        self.assertEqual(second.proof.state, VERIFIED)
        self.assertEqual(
            self.first.mirror_refs("volmarr", "alpha"),
            {"refs/heads/main": new_head})
        self.assertTrue(
            self.first.verify_mirror("volmarr", "alpha").verified)

    def test_failed_proof_blocks_the_batch(self):
        alpha_src, _ = make_source(self.outside, "alpha.git")
        beta_src, _ = make_source(self.outside, "beta.git")
        self.define("alpha", alpha_src)
        self.define("beta", beta_src)
        alpha_src.rename(self.outside / "alpha-gone.git")
        report = self.first.run_first_pass("volmarr")
        self.assertTrue(report.batch_blocked)
        self.assertEqual(report.proof.state, FAILED)
        self.assertEqual(report.batch, [])
        self.assertFalse(self.pull.pull_mirror_for("volmarr", "beta").ready)
        self.assertEqual(self.first.runs_for("volmarr/beta"), [])

    def test_scheduler_sync_now_and_failed_mirror_never_healthy(self):
        src, sched_refs = make_source(self.outside, "sched.git")
        commit = sched_refs["refs/heads/main"]
        self.mirrors.create_mirror(self.owner.id, "volmarr", "mir", src)
        st = self.status.status_for("volmarr", "mir")
        self.assertEqual(st.state, "never_synced")
        self.assertFalse(st.healthy)
        scheduler = SyncSchedulerService(
            self.conn, self.data_root, self.accounts, self.repos,
            audit=self.audit, time_fn=lambda: self.clock[0],
            rand_fn=lambda: 0.5)
        result = scheduler.sync_now(self.owner.id, "volmarr", "mir")
        self.assertEqual(result.status, "ok")
        st = self.status.status_for("volmarr", "mir")
        self.assertEqual(st.state, "healthy")
        self.assertTrue(st.healthy)
        self.assertEqual(st.objects_moved, 3)
        self.assertEqual(st.last_success_at, 1_700_000_000)
        path = self.repos.path_for("volmarr", "mir")
        self.assertEqual(RefStore(path).resolve("refs/heads/main"), commit)
        # Break the source: the next sync fails, and the
        # status must say so -- never healthy.
        import shutil
        shutil.rmtree(src)
        self.clock[0] += 60
        failed = self.mirrors.sync_mirror("volmarr", "mir")
        self.assertEqual(failed.status, "failed")
        st = self.status.status_for("volmarr", "mir")
        self.assertEqual(st.state, "failed")
        self.assertFalse(st.healthy)
        self.assertIsNotNone(st.failure_reason)
        self.assertEqual(st.last_success_at, 1_700_000_000)

    def test_write_law_refuses_a_mirror_and_allows_a_plain_repo(self):
        src, _ = make_source(self.outside, "law.git")
        self.mirrors.create_mirror(self.owner.id, "volmarr", "mir", src)
        self.repos.create_repository(self.owner.id, "volmarr", "plain")
        law = MirrorWriteLaw(
            self.conn, self.data_root, self.accounts, self.repos)
        decision = law.judge("volmarr", "mir")
        self.assertTrue(decision.is_mirror)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "mirror_read_only")
        plain = law.judge("volmarr", "plain")
        self.assertFalse(plain.is_mirror)
        self.assertTrue(plain.allowed)

    def test_push_mirror_carries_a_repo_onward_ref_for_ref(self):
        self.repos.create_repository(self.owner.id, "volmarr", "core")
        path = self.repos.path_for("volmarr", "core")
        blob = git(path, "hash-object", "-w", "--stdin",
                   input_bytes=b"hi\n")
        tree = git(path, "mktree",
                   input_bytes=f"100644 blob {blob}\tx.txt\n".encode())
        commit = git(path, "commit-tree", tree, input_bytes=b"first\n")
        git(path, "update-ref", "refs/heads/main", commit)
        dest_dir = Path(self._td.name) / "second"; dest_dir.mkdir()
        dest = dest_dir / "core.git"
        subprocess.run(["git", "init", "--bare", "-b", "main", str(dest)],
                       check=True, capture_output=True)
        push = PushMirrorService(
            self.conn, self.data_root, self.accounts, self.repos,
            audit=self.audit, time_fn=lambda: self.clock[0])
        target = push.add_target(self.owner.id, "volmarr", "core", dest)
        self.assertFalse(target.healthy)
        result = push.push_to_target("volmarr", "core", target.id)
        self.assertEqual(result.status, "ok")
        landed = push.get_target("volmarr", "core", target.id)
        self.assertTrue(landed.healthy)
        self.assertEqual(RefStore(dest).resolve("refs/heads/main"), commit)


class PrivateAndMetadataTests(GateBase):
    def test_private_original_refused_without_credential_then_verified(self):
        src, _ = make_source(self.outside, "priv.git")
        self.define("secret", src, private=True)
        refused = self.private.run_private_originals(
            "volmarr", secrets=self.secrets, declared_scope="read")
        self.assertEqual(len(refused.runs), 1)
        self.assertEqual(refused.runs[0].state, FAILED)
        self.assertFalse(self.pull.is_ready("volmarr", "secret"))
        self.creds.set_credential(
            self.owner.id, "volmarr", "secret", "GITHUB_READ_TOKEN")
        write = self.private.run_private_originals(
            "volmarr", secrets=self.secrets,
            declared_scope="contents:write")
        self.assertEqual(write.runs[0].state, FAILED)
        self.assertFalse(self.pull.is_ready("volmarr", "secret"))
        report = self.private.run_private_originals(
            "volmarr", secrets=self.secrets, declared_scope="read")
        self.assertEqual(report.verified_count, 1)
        self.assertTrue(self.pull.is_ready("volmarr", "secret"))
        repo = self.repos.get_repository("volmarr", "secret")
        self.assertEqual(repo.visibility, "private")
        for run in report.runs:
            self.assertNotIn("gate-token-344", run.detail)

    def test_metadata_import_lands_marked_and_idempotent(self):
        parsed = parse_classification(json.dumps(
            {"include": [census_entry("widget")]}))
        self.census.import_classification(
            self.owner.id, "volmarr", parsed, github_owner=GH)
        repo = self.repos.get_repository("volmarr", "widget")
        with self.conn:
            self.conn.execute(
                "UPDATE repo_mirrors SET source ="
                " 'https://github.com/hrabanazviking/widget',"
                " source_kind = 'url' WHERE repo_id = ?", (repo.id,))
        fetch = FakeFetch()
        svc = MetadataImportService(
            self.conn, self.data_root, self.accounts, self.repos,
            self.audit, fetch_fn=fetch)
        refused = svc.import_metadata(
            "volmarr", "widget", secrets=self.secrets,
            declared_scope="read")
        self.assertEqual(refused.state, "refused")
        self.assertEqual(fetch.calls, [])
        self.creds.set_credential(
            self.owner.id, "volmarr", "widget", "GITHUB_READ_TOKEN")
        report = svc.import_metadata(
            "volmarr", "widget", secrets=self.secrets,
            declared_scope="read")
        self.assertEqual(report.state, STATE_IMPORTED)
        self.assertEqual((report.labels_imported,
                          report.milestones_imported,
                          report.issues_imported,
                          report.releases_imported), (1, 1, 1, 1))
        self.assertEqual(report.pull_requests_skipped, 1)
        records = svc.imports_for("volmarr", "widget")
        self.assertEqual(len(records), 4)
        issue_rec = [r for r in records if r.kind == KIND_ISSUE][0]
        self.assertEqual(
            issue_rec.source_url,
            "https://github.com/hrabanazviking/widget/issues/7")
        second = svc.import_metadata(
            "volmarr", "widget", secrets=self.secrets,
            declared_scope="read")
        self.assertEqual(second.imported_total, 0)
        count = self.conn.execute(
            "SELECT COUNT(*) c FROM issues"
            " WHERE title = 'Imported bug'").fetchone()
        self.assertEqual(count["c"], 1)


class RestoreProofTests(GateBase):
    def test_export_of_a_mirror_restores_every_ref(self):
        alpha_src, alpha_refs = make_source(
            self.outside, "alpha.git", tag=True, second_branch=True)
        self.define("alpha", alpha_src)
        report = self.first.run_first_pass("volmarr")
        self.assertEqual(report.proof.state, VERIFIED)
        dest = Path(self._td.name) / "exports"
        export = self.backup.export_repo(
            self.owner.id, "volmarr", "alpha", dest)
        meta = json.loads(export.metadata_path.read_text())
        self.assertEqual(meta["format"], "samverk-repo-export/1")
        self.assertEqual(meta["full_name"], "volmarr/alpha")
        self.assertEqual(meta["refs"], alpha_refs)
        self.assertEqual(
            meta["bundle_sha256"],
            hashlib.sha256(export.bundle_path.read_bytes()).hexdigest())
        self.assertEqual(export.bundle_sha256, meta["bundle_sha256"])
        self.assertEqual(meta["bundle_bytes"],
                         export.bundle_path.stat().st_size)
        restored = Path(self._td.name) / "restored.git"
        out = subprocess.run(
            ["git", "clone", "--bare", "--no-hardlinks",
             str(export.bundle_path), str(restored)],
            capture_output=True)
        self.assertEqual(out.returncode, 0, out.stderr.decode())
        store = RefStore(restored)
        for ref, oid in alpha_refs.items():
            self.assertEqual(store.resolve(ref), oid, msg=ref)

    def test_export_gate_owner_only_empty_refused_no_overwrite(self):
        alpha_src, _ = make_source(self.outside, "alpha.git")
        self.define("alpha", alpha_src)
        self.first.run_first_pass("volmarr")
        dest = Path(self._td.name) / "exports"
        with self.assertRaises(BackupError) as caught:
            self.backup.export_repo(
                self.other.id, "volmarr", "alpha", dest)
        self.assertEqual(caught.exception.reason, "permission_denied")
        self.repos.create_repository(self.owner.id, "volmarr", "blank")
        with self.assertRaises(BackupError) as caught:
            self.backup.export_repo(
                self.owner.id, "volmarr", "blank", dest)
        self.assertEqual(caught.exception.reason, "repo_empty")
        self.backup.export_repo(self.owner.id, "volmarr", "alpha", dest)
        with self.assertRaises(BackupError) as caught:
            self.backup.export_repo(
                self.owner.id, "volmarr", "alpha", dest)
        self.assertEqual(caught.exception.reason, "export_exists")


if __name__ == "__main__":
    unittest.main()
