"""S-267 acceptance battery: artifact expiry.

Acceptance (roadmap S-267): artifact expiry --
retention windows enforced by the off-path job;
expired artifacts vanish from UI and disk
together (S-071 reconciles).

The centre is samverk/artifact_expiry.py:
ArtifactExpiryJob over the rows and bytes S-266's
CIArtifactsAPI lands (migration 105). The sweep
judges with S-266's own is_expired, deletes an
expired artifact's row and its content-addressed
bytes in the same run (shared bytes kept while a
live row names them, missing bytes counted
honestly), and S-071's ConsistencyChecker
reconciles the artifact store: a standing expired
row, a row whose bytes are gone, and bytes no row
names are each drift. No migration (schema 105
stands); no new taxonomy event (133 stand).

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
from samverk.artifact_expiry import (
    ArtifactExpiryJob, artifact_bytes_path, main,
    render_artifact_expiry_page)
from samverk.audit import AuditLog
from samverk.ci_artifacts import CIArtifactsAPI, CIArtifactsError
from samverk.consistency import ConsistencyChecker
from samverk.db import schema_version
from samverk.issues import IssueStore
from samverk.repositories import RepositoryStore

PW = "correct horse battery"
OID = "a" * 40
T0 = 1_700_000_000
DAY = 86400
ZIP = b"PK\x03\x04" + b"\x00" * 40
TEXT = b"test report: all green\n"


class Clock:
    def __init__(self, now=T0):
        self.now = now
    def __call__(self):
        return self.now


def basic(username, credential):
    raw = base64.b64encode(f"{username}:{credential}".encode())
    return "Basic " + raw.decode("ascii")


def make_world(root: Path) -> SimpleNamespace:
    conn = db.init_db(root / "samverk.db")
    clock = Clock()
    audit = AuditLog(conn, time_fn=clock)
    accounts = AccountStore(conn, audit=audit, time_fn=clock)
    owner = accounts.register("volmarr", PW)
    accounts.register("yrsa", PW)
    repos = RepositoryStore(conn, root, accounts, audit=audit)
    issues = IssueStore(conn, repos, accounts, audit=audit, time_fn=clock)
    repos.create_repository(owner.id, "volmarr", "pub", visibility="public")
    classic = AccessTokenStore(conn, accounts, audit=audit, time_fn=clock)
    expiry = clock.now + 3600
    _, owner_write = classic.create_token(owner.id, "write token", {"repo:write"}, expiry)
    checks_api = StatusChecksAPI(conn, accounts, repos, issues, audit=audit, time_fn=clock)
    api = CIArtifactsAPI(conn, accounts, repos, issues, root, audit=audit, time_fn=clock)
    job = ArtifactExpiryJob(conn, root, time_fn=clock)
    checker = ConsistencyChecker(conn, root, repos, time_fn=clock)
    return SimpleNamespace(
        conn=conn, clock=clock, audit=audit, accounts=accounts,
        owner=owner, repos=repos, issues=issues,
        owner_write=owner_write, checks_api=checks_api, api=api,
        job=job, checker=checker, root=root)


class ArtifactExpiryTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.w = make_world(Path(self._td.name))
        self.addCleanup(self.w.conn.close)
        self.owner_basic = basic("volmarr", PW)
        self.w.checks_api.post_check_run(
            self.owner_basic, "volmarr", "pub",
            {"oid": OID, "name": "ci/build", "status": "completed",
             "conclusion": "success"})
        self.w.checks_api.post_check_run(
            self.owner_basic, "volmarr", "pub",
            {"oid": OID, "name": "ci/test", "status": "completed",
             "conclusion": "success"})

    def _upload(self, data=ZIP, name="build.zip", run="ci/build", **over):
        payload = {"oid": OID, "check_run": run, "name": name}
        payload.update(over)
        session = self.w.api.begin_upload(
            self.owner_basic, "volmarr", "pub", payload)
        chunks = [data[i:i + 8] for i in range(0, len(data), 8)]
        for idx, chunk in enumerate(chunks):
            self.w.api.upload_chunk(
                self.owner_basic, "volmarr", "pub",
                session["id"], idx, chunk)
        return self.w.api.complete_upload(
            self.owner_basic, "volmarr", "pub", session["id"])

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(CIArtifactsError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    def _path(self, artifact):
        repo_id = int(self.w.conn.execute(
            "SELECT id FROM repositories WHERE name = 'pub'"
        ).fetchone()[0])
        return artifact_bytes_path(
            self.w.root, repo_id, artifact["sha256"],
            artifact["content_type"])

    def _audit_count(self):
        return int(self.w.conn.execute(
            "SELECT COUNT(*) c FROM audit_log").fetchone()["c"])

    # -- pins ------------------------------------------------------
    def test_pins_schema_105_taxonomy_133(self):
        self.assertEqual(schema_version(self.w.conn), 121)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 134)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 88)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)

    # -- the sweep ---------------------------------------------------
    def test_expired_artifact_vanishes_from_ui_and_disk_together(self):
        artifact = self._upload(retention_days=7)
        path = self._path(artifact)
        self.assertTrue(path.is_file())
        self.w.clock.now = T0 + 7 * DAY
        run = self.w.job.sweep()
        self.assertEqual(
            (run.expired, run.rows_removed, run.bytes_removed,
             run.bytes_kept_shared, run.bytes_missing),
            (1, 1, 1, 0, 0))
        self.assertFalse(path.exists())
        listing = self.w.api.list_artifacts(
            self.owner_basic, "volmarr", "pub")
        self.assertEqual(listing["total"], 0)
        self.assertEqual(self._reason(
            self.w.api.get_artifact, self.owner_basic,
            "volmarr", "pub", artifact["id"]), "artifact_not_found")
        self.assertEqual(self._reason(
            self.w.api.download_artifact, self.owner_basic,
            "volmarr", "pub", artifact["id"]), "artifact_not_found")

    def test_before_the_stamp_nothing_is_swept_at_it_all_is(self):
        artifact = self._upload(retention_days=7)
        self.w.clock.now = T0 + 7 * DAY - 1
        run = self.w.job.sweep()
        self.assertEqual(run.rows_removed, 0)
        self.assertTrue(self._path(artifact).is_file())
        self.w.clock.now = T0 + 7 * DAY
        run = self.w.job.sweep()
        self.assertEqual(run.rows_removed, 1)

    def test_keep_forever_is_never_swept(self):
        artifact = self._upload(retention_days=0)
        self.assertIsNone(artifact["expires_at"])
        self.w.clock.now = T0 + 3650 * DAY
        run = self.w.job.sweep()
        self.assertEqual((run.expired, run.rows_removed), (0, 0))
        self.assertTrue(self._path(artifact).is_file())
        got = self.w.api.download_artifact(
            self.owner_basic, "volmarr", "pub", artifact["id"])
        self.assertEqual(got.read_all(), ZIP)

    def test_unexpired_artefact_survives_among_expired(self):
        self._upload(retention_days=7)
        live = self._upload(
            data=TEXT, name="report.txt", run="ci/test",
            retention_days=365)
        self.w.clock.now = T0 + 30 * DAY
        run = self.w.job.sweep()
        self.assertEqual(run.rows_removed, 1)
        listing = self.w.api.list_artifacts(
            self.owner_basic, "volmarr", "pub")
        self.assertEqual(
            [a["name"] for a in listing["artifacts"]], ["report.txt"])
        got = self.w.api.download_artifact(
            self.owner_basic, "volmarr", "pub", live["id"])
        self.assertEqual(got.read_all(), TEXT)

    def test_shared_bytes_are_kept_for_the_live_row(self):
        self._upload(retention_days=7)
        live = self._upload(name="copy.zip", run="ci/test", retention_days=0)
        self.w.clock.now = T0 + 7 * DAY
        run = self.w.job.sweep()
        self.assertEqual(
            (run.rows_removed, run.bytes_removed,
             run.bytes_kept_shared), (1, 0, 1))
        self.assertTrue(self._path(live).is_file())
        got = self.w.api.download_artifact(
            self.owner_basic, "volmarr", "pub", live["id"])
        self.assertEqual(got.read_all(), ZIP)

    def test_missing_bytes_are_counted_never_hidden(self):
        artifact = self._upload(retention_days=7)
        self._path(artifact).unlink()
        self.w.clock.now = T0 + 7 * DAY
        run = self.w.job.sweep()
        self.assertEqual(
            (run.rows_removed, run.bytes_removed, run.bytes_missing),
            (1, 0, 1))

    def test_sweep_is_idempotent(self):
        self._upload(retention_days=7)
        self.w.clock.now = T0 + 7 * DAY
        first = self.w.job.sweep()
        second = self.w.job.sweep()
        self.assertEqual(first.rows_removed, 1)
        self.assertEqual(
            (second.expired, second.rows_removed,
             second.bytes_removed), (0, 0, 0))
        self.assertIn("0 expired", second.words)

    def test_expired_rows_is_a_pure_read(self):
        self._upload(retention_days=7)
        self.w.clock.now = T0 + 7 * DAY
        rows = self.w.job.expired_rows()
        self.assertEqual(len(rows), 1)
        listing = self.w.api.list_artifacts(
            self.owner_basic, "volmarr", "pub")
        self.assertEqual(listing["total"], 1)
        self.assertTrue(listing["artifacts"][0]["expired"])

    def test_expired_refuses_expired_before_sweep_not_found_after(self):
        artifact = self._upload(retention_days=7)
        self.w.clock.now = T0 + 7 * DAY
        self.assertEqual(self._reason(
            self.w.api.download_artifact, self.owner_basic,
            "volmarr", "pub", artifact["id"]), "artifact_expired")
        self.w.job.sweep()
        self.assertEqual(self._reason(
            self.w.api.download_artifact, self.owner_basic,
            "volmarr", "pub", artifact["id"]), "artifact_not_found")

    def test_sweep_witnesses_nothing(self):
        self._upload(retention_days=7)
        before = self._audit_count()
        self.w.clock.now = T0 + 7 * DAY
        self.w.job.sweep()
        self.assertEqual(self._audit_count(), before)

    # -- S-071 reconciles ---------------------------------------------
    def test_checker_names_expired_standing_and_sweep_clears_it(self):
        self._upload(retention_days=7)
        self.w.clock.now = T0 + 7 * DAY
        report = self.w.checker.check()
        self.assertEqual(report.artifacts_checked, 1)
        self.assertEqual(
            len(report.by_kind("artifact_expired_standing")), 1)
        self.w.job.sweep()
        report = self.w.checker.check()
        self.assertEqual(report.by_kind("artifact_expired_standing"), [])
        self.assertEqual(report.artifacts_checked, 0)

    def test_checker_names_missing_bytes_and_orphan_bytes(self):
        artifact = self._upload(retention_days=0)
        self._path(artifact).unlink()
        orphan = self._path(artifact).parent / ("f" * 64 + ".zip")
        orphan.write_bytes(b"orphan")
        report = self.w.checker.check()
        self.assertEqual(
            len(report.by_kind("artifact_bytes_missing")), 1)
        self.assertEqual(
            len(report.by_kind("artifact_bytes_orphan")), 1)
        # the sweep is not the orphan's executioner: unexpired
        # row stands, orphan bytes stand, both still reported
        run = self.w.job.sweep()
        self.assertEqual(run.rows_removed, 0)
        self.assertTrue(orphan.is_file())

    def test_checker_is_clean_over_live_artifacts(self):
        self._upload(retention_days=90)
        report = self.w.checker.check()
        self.assertEqual(report.artifacts_checked, 1)
        self.assertEqual(report.by_kind("artifact_expired_standing"), [])
        self.assertEqual(report.by_kind("artifact_bytes_missing"), [])
        self.assertEqual(report.by_kind("artifact_bytes_orphan"), [])

    # -- the job's faces ------------------------------------------------
    def test_main_usage_and_words(self):
        self.assertEqual(main([]), 2)
        self.assertEqual(main(["only-one"]), 2)
        artifact = self._upload(retention_days=7)
        self.assertIn("1 expired", self.w.job.sweep(
            now=T0 + 7 * DAY).words)
        self.assertFalse(self._path(artifact).exists())

    def test_render_page_states_the_law(self):
        page = render_artifact_expiry_page()
        self.assertIn("Artifact expiry", page)
        self.assertIn("S-071", page)
        self.assertIn("keep forever", page)


if __name__ == "__main__":
    unittest.main()
