"""S-268 acceptance battery: storage accounting.

Acceptance (roadmap S-268): storage accounting --
releases and artifacts join S-058's size
accounting and S-068-style quotas.

The centre is samverk/storage_accounting.py:
StorageAccounting joins S-058's walked categories
(measure_path, never re-walked) with the standing
release_assets (S-259, migration 102) and
ci_artifacts (S-266, migration 105) rows -- bytes
counted once per content-addressed file at each
store's own disk grouping -- and judges uploads
against S-068's one effective quota on the joined
total, as a decision object first and an exception
second. Shown to owners and admins only (S-058's
law). No migration (schema 105 stands); no new
taxonomy event (133 stand).

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import base64, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.access_tokens import AccessTokenStore
from samverk.accounts import AccountStore
from samverk.api_checks import StatusChecksAPI
from samverk.audit import AuditLog
from samverk.ci_artifacts import CIArtifactsAPI
from samverk.db import schema_version
from samverk.issues import IssueStore
from samverk.release_assets import ReleaseAssetStore
from samverk.releases import ReleaseStore
from samverk.repo_quotas import QuotaService
from samverk.repo_size import RepoSizeAccounting
from samverk.repositories import RepositoryStore
from samverk.storage_accounting import (
    StorageAccounting, StorageError, StorageReport, decide_storage,
    render_storage_page, storage_to_dict, storage_words)
from test_repo_home import run_git

PW = "correct horse battery"
OID = "a" * 40
T0 = 1_700_000_000
ZIP = b"PK\x03\x04" + b"\x00" * 40
TEXT = b"anvil release notes\nsecond line\n"


class Clock:
    def __init__(self, now=T0):
        self.now = now
    def __call__(self):
        return self.now


def basic(username, credential):
    raw = base64.b64encode(f"{username}:{credential}".encode())
    return "Basic " + raw.decode("ascii")


class StorageAccountingTests(unittest.TestCase):
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
        self.other = self.accounts.register("yrsa", PW)
        self.admin = self.accounts.register("adminuser", PW)
        with self.conn:
            self.conn.execute(
                "UPDATE users SET is_admin = 1 WHERE id = ?",
                (self.admin.id,))
        self.admin = self.accounts.get_by_id(self.admin.id)
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        self.sizes = RepoSizeAccounting(
            self.conn, self.root, self.accounts, self.repos)
        self.quotas = QuotaService(
            self.conn, self.root, self.accounts, self.repos,
            audit=self.audit, time_fn=self.clock)
        self.storage = StorageAccounting(
            self.conn, self.root, self.accounts, self.repos,
            self.quotas)
        # A release with assets (S-257 + S-259).
        self.releases = ReleaseStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.assets = ReleaseAssetStore(
            self.conn, self.repos, self.releases, self.root,
            self.accounts, audit=self.audit, time_fn=self.clock)
        bare = self.repos.path_for("volmarr", "pub")
        work = self.root / "work"; work.mkdir()
        run_git(work, "init", "-b", "main")
        (work / "app.py").write_text("print('hi')\n")
        run_git(work, "add", "-A")
        run_git(work, "commit", "-m", "first")
        run_git(work, "push", str(bare), "main")
        run_git(work, "tag", "v1.0")
        run_git(work, "push", str(bare), "v1.0")
        self.releases.create_release(
            self.owner, "volmarr", "pub", "v1.0", "Anvil 1.0")
        self._asset(TEXT, "notes.txt")
        self._asset(TEXT, "notes-copy.txt")
        self._asset(ZIP, "build.zip")
        # CI artifacts (S-266): two rows, one digest.
        classic = AccessTokenStore(
            self.conn, self.accounts, audit=self.audit,
            time_fn=self.clock)
        _, self.owner_write = classic.create_token(
            self.owner.id, "write token", {"repo:write"},
            self.clock.now + 3600)
        self.issues = IssueStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.checks_api = StatusChecksAPI(
            self.conn, self.accounts, self.repos, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.owner_basic = basic("volmarr", PW)
        self.checks_api.post_check_run(
            self.owner_basic, "volmarr", "pub",
            {"oid": OID, "name": "ci/build", "status": "completed",
             "conclusion": "success"})
        self.api = CIArtifactsAPI(
            self.conn, self.accounts, self.repos, self.issues,
            self.root, audit=self.audit, time_fn=self.clock)
        self._artifact(ZIP, "build.zip")
        self._artifact(ZIP, "build-copy.zip")

    # -- helpers -------------------------------------------------
    def _asset(self, data, name, tag="v1.0"):
        chunks = [data[i:i + 8] for i in range(0, len(data), 8)]
        session = self.assets.begin_upload(
            self.owner, "volmarr", "pub", tag, name)
        for idx, chunk in enumerate(chunks):
            self.assets.upload_chunk(
                self.owner, session.id, idx, chunk)
        return self.assets.complete_upload(self.owner, session.id)

    def _artifact(self, data, name, **over):
        payload = {"oid": OID, "check_run": "ci/build", "name": name}
        payload.update(over)
        session = self.api.begin_upload(
            self.owner_basic, "volmarr", "pub", payload)
        chunks = [data[i:i + 8] for i in range(0, len(data), 8)]
        for idx, chunk in enumerate(chunks):
            self.api.upload_chunk(
                self.owner_basic, "volmarr", "pub",
                session["id"], idx, chunk)
        return self.api.complete_upload(
            self.owner_basic, "volmarr", "pub", session["id"])

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(StorageError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    def _report(self, repo="pub"):
        return self.storage.report_for(
            self.owner.id, "volmarr", repo)

    # -- pins ------------------------------------------------------
    def test_pins_schema_105_taxonomy_133(self):
        self.assertEqual(schema_version(self.conn), 118)
        self.assertEqual(db.MIGRATIONS[-1][0], 118)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 134)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 88)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)

    # -- the joined account -----------------------------------------
    def test_categories_sum_to_the_joined_total(self):
        report = self._report()
        walked = self.sizes.size_for(self.owner.id, "volmarr", "pub")
        self.assertEqual(report.git_objects_bytes,
                         walked.git_objects_bytes)
        self.assertEqual(report.lfs_bytes, walked.lfs_bytes)
        self.assertEqual(report.other_bytes, walked.other_bytes)
        self.assertEqual(report.repo_bytes, walked.total_bytes)
        self.assertEqual(
            report.total_bytes,
            report.repo_bytes + report.release_assets_bytes
            + report.artifacts_bytes)
        self.assertEqual(report.uploads_bytes,
                         report.release_assets_bytes
                         + report.artifacts_bytes)
        self.assertGreater(report.total_bytes, report.repo_bytes)

    def test_release_assets_counted_once_per_shared_file(self):
        report = self._report()
        # Three rows: TEXT twice (one shared file in the
        # release) and ZIP once.
        self.assertEqual(report.release_asset_count, 3)
        self.assertEqual(report.release_asset_files, 2)
        self.assertEqual(report.release_assets_bytes,
                         len(TEXT) + len(ZIP))

    def test_artifacts_counted_once_per_shared_digest(self):
        report = self._report()
        # Two rows naming one digest in one repository.
        self.assertEqual(report.artifact_count, 2)
        self.assertEqual(report.artifact_files, 1)
        self.assertEqual(report.artifacts_bytes, len(ZIP))

    def test_same_asset_bytes_in_a_second_release_count_again(self):
        bare = self.repos.path_for("volmarr", "pub")
        work = self.root / "work"
        (work / "app.py").write_text("print('ho')\n")
        run_git(work, "add", "-A")
        run_git(work, "commit", "-m", "second")
        run_git(work, "push", str(bare), "main")
        run_git(work, "tag", "v1.1")
        run_git(work, "push", str(bare), "v1.1")
        self.releases.create_release(
            self.owner, "volmarr", "pub", "v1.1", "Anvil 1.1")
        before = self._report()
        self._asset(TEXT, "notes.txt", tag="v1.1")
        after = self._report()
        # A second release holds a second file on disk,
        # so the joined account grows by the bytes again.
        self.assertEqual(
            after.release_assets_bytes - before.release_assets_bytes,
            len(TEXT))
        self.assertEqual(after.release_asset_files,
                         before.release_asset_files + 1)

    def test_empty_repository_reports_zero_uploads(self):
        report = self._report("priv")
        self.assertEqual(report.release_assets_bytes, 0)
        self.assertEqual(report.release_asset_count, 0)
        self.assertEqual(report.artifacts_bytes, 0)
        self.assertEqual(report.artifact_count, 0)
        self.assertEqual(report.total_bytes, report.repo_bytes)

    def test_expired_artifact_still_counts_until_swept(self):
        self._artifact(TEXT, "report.txt", retention_days=7)
        report = self._report()
        self.assertEqual(report.artifact_count, 3)
        self.assertEqual(report.artifacts_bytes,
                         len(ZIP) + len(TEXT))

    def test_deleted_asset_stops_counting(self):
        before = self._report()
        asset = self.assets.list_assets(
            self.owner, "volmarr", "pub", "v1.0")[0]
        self.assets.delete_asset(
            self.owner, "volmarr", "pub", "v1.0", asset.name)
        after = self._report()
        self.assertEqual(after.release_asset_count,
                         before.release_asset_count - 1)

    # -- visibility ---------------------------------------------------
    def test_shown_to_owner_and_admin_only(self):
        self.assertEqual(
            self.storage.report_for(
                self.admin.id, "volmarr", "pub").full_name,
            "volmarr/pub")
        self.assertEqual(
            self._reason(self.storage.report_for,
                         self.other.id, "volmarr", "pub"),
            "permission_denied")
        self.assertEqual(
            self._reason(self.storage.report_for,
                         self.other.id, "volmarr", "priv"),
            "permission_denied")

    def test_missing_repo_and_user_are_named(self):
        self.assertEqual(
            self._reason(self.storage.report_for,
                         self.owner.id, "volmarr", "ghost"),
            "no_such_repo")
        self.assertEqual(
            self._reason(self.storage.report_for,
                         99999, "volmarr", "pub"),
            "no_such_user")

    def test_reports_for_owner_lists_every_repo(self):
        reports = self.storage.reports_for_owner(
            self.owner.id, "volmarr")
        self.assertEqual([r.full_name for r in reports],
                         ["volmarr/priv", "volmarr/pub"])

    # -- quota gate -----------------------------------------------------
    def test_no_quota_means_unlimited(self):
        report = self._report()
        self.assertIsNone(report.quota_bytes)
        self.assertIsNone(report.headroom_bytes)
        self.assertFalse(report.over_quota)
        decision = self.storage.check_upload(
            "volmarr", "pub", "artifact", 10**12)
        self.assertTrue(decision.allowed)
        self.assertIsNone(decision.quota_bytes)
        self.assertEqual(decision.usage_bytes, report.total_bytes)
        enforced = self.storage.enforce_upload(
            "volmarr", "pub", "release", 10**12)
        self.assertTrue(enforced.allowed)
        self.assertEqual(enforced.store, "release")
        self.assertEqual(enforced.usage_bytes, report.total_bytes)

    def test_quota_judged_on_the_joined_total(self):
        report = self._report()
        # A quota S-068's receive gate alone would pass a
        # push against (it sees only the bare repo), but
        # the joined total already fills it.
        quota = report.repo_bytes + report.uploads_bytes
        self.quotas.set_repo_quota(
            self.owner.id, "volmarr", "pub", quota)
        self.assertTrue(
            self.quotas.check_receive("volmarr", "pub", 1).allowed)
        decision = self.storage.check_upload(
            "volmarr", "pub", "artifact", 1)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.usage_bytes, report.total_bytes)
        self.assertIn("Storage quota exceeded for volmarr/pub",
                      decision.message)
        self.assertIn(str(report.total_bytes), decision.message)
        fits = self.storage.check_upload(
            "volmarr", "pub", "artifact", 0)
        self.assertTrue(fits.allowed)
        self.assertEqual(
            self._reason(self.storage.enforce_upload,
                         "volmarr", "pub", "artifact", 1),
            "quota_exceeded")

    def test_headroom_and_over_quota_are_honest(self):
        report = self._report()
        self.quotas.set_repo_quota(
            self.owner.id, "volmarr", "pub",
            report.total_bytes + 50)
        roomy = self._report()
        self.assertEqual(roomy.headroom_bytes, 50)
        self.assertFalse(roomy.over_quota)
        self.quotas.set_repo_quota(
            self.owner.id, "volmarr", "pub", report.total_bytes - 1)
        tight = self._report()
        self.assertEqual(tight.headroom_bytes, 0)
        self.assertTrue(tight.over_quota)
        self.assertIn("over its", render_storage_page(tight))

    def test_instance_default_quota_applies(self):
        self.quotas.set_default_quota(self.admin.id, 10**9)
        report = self._report()
        self.assertEqual(report.quota_bytes, 10**9)
        self.quotas.set_default_quota(self.admin.id, None)
        self.assertIsNone(self._report().quota_bytes)

    def test_upload_gate_validates_its_inputs(self):
        self.assertEqual(
            self._reason(self.storage.check_upload,
                         "volmarr", "pub", "bogus", 1),
            "store_invalid")
        self.assertEqual(
            self._reason(self.storage.check_upload,
                         "volmarr", "pub", "artifact", -1),
            "incoming_invalid")
        self.assertEqual(
            self._reason(self.storage.check_upload,
                         "volmarr", "pub", "artifact", True),
            "incoming_invalid")
        self.assertEqual(
            self._reason(self.storage.check_upload,
                         "volmarr", "ghost", "artifact", 1),
            "no_such_repo")

    # -- pure law ---------------------------------------------------
    def test_decide_storage_boundaries(self):
        at = decide_storage("o/r", "release", 90, 100, 10)
        self.assertTrue(at.allowed)
        over = decide_storage("o/r", "release", 90, 100, 11)
        self.assertFalse(over.allowed)
        self.assertIn("holds 90 bytes of its 100-byte quota",
                      over.message)
        free = decide_storage("o/r", "artifact", 90, None, 10**12)
        self.assertTrue(free.allowed)
        self.assertIsNone(free.quota_bytes)

    # -- faces ---------------------------------------------------------
    def test_dict_and_words_carry_the_whole_account(self):
        report = self._report()
        data = storage_to_dict(report)
        self.assertEqual(data["full_name"], "volmarr/pub")
        self.assertEqual(data["total_bytes"], report.total_bytes)
        self.assertEqual(data["release_asset_count"], 3)
        self.assertEqual(data["artifact_files"], 1)
        words = storage_words(report)
        self.assertIn("volmarr/pub", words)
        self.assertIn("release assets", words)
        self.assertIn("CI artifacts", words)

    def test_rendered_page_is_escaped_and_states_in_text(self):
        report = StorageReport(
            full_name="o/<b>r</b>", git_objects_bytes=1,
            lfs_bytes=2, other_bytes=3, release_assets_bytes=4,
            release_asset_count=1, release_asset_files=1,
            artifacts_bytes=5, artifact_count=1, artifact_files=1,
            quota_bytes=None)
        page = render_storage_page(report)
        self.assertIn("o/&lt;b&gt;r&lt;/b&gt;", page)
        self.assertNotIn("<b>r</b>", page)
        self.assertIn("Release assets: 4 bytes", page)
        self.assertIn("CI artifacts: 5 bytes", page)
        self.assertIn("Total: 15 bytes", page)
        self.assertIn("no quota", page)


if __name__ == "__main__":
    unittest.main()
