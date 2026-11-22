"""S-323 acceptance battery: workflow artifacts.

Acceptance (roadmap S-323): Artifacts --
workflow artifacts via S-266, listed on the run
page.

The centre is samverk/workflow_artifacts.py:
`WorkflowArtifactsStore` gathers one workflow
run's artifacts from S-266's `ci_artifacts`
rows by way of the run's S-321 job checks
(``<workflow> / <job>`` check runs standing on
the run's commit), grouped by job in check-run
order, read through S-054's `can_read` (a
stranger to a private repository gets the
uniform `repository_not_found`), with expired
artifacts listed and marked by S-266's own
`is_expired` law. The fixtures seed the S-246
check-run rows and S-266 artifact rows the
listing reads -- S-266's own battery proves the
upload road that writes them; this battery
proves the gathering. No migration (the tables
are S-246's and S-266's; schema stays 131);
taxonomy unmoved at 135 (33 auth / 89 repo /
13 admin); no audit row is written by any face.

Counted with: python3 -m unittest
tests.test_workflow_artifacts
"""
from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.check_reporting import check_name_for
from samverk.ci_artifacts import is_expired
from samverk.db import schema_version
from samverk.issues import IssueStore
from samverk.repositories import RepositoryStore
from samverk.workflow_artifacts import (
    JobArtifacts, RunArtifacts, WorkflowArtifactsError,
    WorkflowArtifactsStore, audit_workflow_artifacts,
    is_run_check_name, job_artifacts_to_dict,
    job_for_check_name, render_run_artifacts_page,
    run_artifact_to_dict, run_artifacts_to_dict,
    run_check_prefix, validate_run_address)

PW = "correct horse battery"
T0 = 1_700_000_000
DAY = 86400
OID = "a" * 40
OID2 = "b" * 40


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


def _reason(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except WorkflowArtifactsError as exc:
        return exc.reason
    raise AssertionError("expected WorkflowArtifactsError")


class PureLawTests(unittest.TestCase):
    def test_prefix_is_s321s_separator(self):
        self.assertEqual(run_check_prefix("CI"), "CI / ")
        self.assertEqual(run_check_prefix(" CI "), "CI / ")
        self.assertEqual(
            check_name_for("CI", "build"), "CI / build")

    def test_job_extraction(self):
        self.assertEqual(
            job_for_check_name("CI", "CI / build"), "build")
        self.assertEqual(
            job_for_check_name("CI", "CI / test-2"), "test-2")
        self.assertTrue(is_run_check_name("CI", "CI / build"))

    def test_job_extraction_refusals(self):
        for name in ("CI", "CI /", "CI / ", "CI/build",
                     "Docs / build", "CI2 / build", "",
                     "CI /  build", None, 7):
            self.assertIsNone(job_for_check_name("CI", name))
            self.assertFalse(is_run_check_name("CI", name))

    def test_workflow_must_be_named(self):
        for bad in ("", "  ", None, 7):
            self.assertEqual(
                _reason(run_check_prefix, bad),
                "run_workflow_invalid")
            self.assertEqual(
                _reason(validate_run_address, bad, OID),
                "run_workflow_invalid")

    def test_oid_must_be_named(self):
        for bad in ("", "  ", None, 7):
            self.assertEqual(
                _reason(validate_run_address, "CI", bad),
                "run_oid_invalid")
        self.assertEqual(
            validate_run_address(" CI ", f" {OID} "),
            ("CI", OID))

    def test_expiry_law_is_s266s(self):
        self.assertFalse(is_expired(None, T0 + 10 ** 9))
        self.assertFalse(is_expired(T0 + 10, T0 + 9))
        self.assertTrue(is_expired(T0 + 10, T0 + 10))


class World(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, time_fn=self.clock)
        self.owner = self.accounts.register("volmarr", PW)
        self.stranger = self.accounts.register("mallory", PW)
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts)
        self.issues = IssueStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.store = WorkflowArtifactsStore(
            self.conn, self.repos, time_fn=self.clock)
        self.pub = self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.priv = self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")

    # -- seeding: the rows S-246 / S-266 stand ----

    def _check_run(self, repo, name, oid=OID, poster="samverk-ci"):
        cur = self.conn.execute(
            "INSERT INTO check_runs (repo_id, head_oid, name,"
            " status, conclusion, poster, target_url,"
            " description, created_at, updated_at)"
            " VALUES (?, ?, ?, 'completed', 'success', ?, '',"
            " '', ?, ?)",
            (repo.id, oid, name, poster, T0, T0))
        self.conn.commit()
        return int(cur.lastrowid)

    def _artifact(self, repo, check_run_id, name, oid=OID,
                  check_run="CI / build", size=100,
                  retention_days=90, created_at=T0,
                  poster="volmarr"):
        expires = (None if retention_days == 0
                   else created_at + retention_days * DAY)
        digest = hashlib.sha256(name.encode()).hexdigest()
        cur = self.conn.execute(
            "INSERT INTO ci_artifacts (repo_id, check_run_id,"
            " head_oid, check_run, name, size, sha256,"
            " content_type, download_count, retention_days,"
            " expires_at, uploader_id, poster, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 'application/zip',"
            " 0, ?, ?, ?, ?, ?)",
            (repo.id, check_run_id, oid, check_run, name, size,
             digest, retention_days, expires, self.owner.id,
             poster, created_at))
        self.conn.commit()
        return int(cur.lastrowid)

    def _seed_run(self, repo=None, oid=OID):
        """One CI run on one commit: build + test jobs,
        an external poster's check, and artifacts."""
        repo = repo or self.pub
        build = self._check_run(repo, "CI / build", oid)
        test = self._check_run(repo, "CI / test", oid)
        docs = self._check_run(repo, "Docs / build", oid)
        plain = self._check_run(repo, "external-scan", oid)
        self._artifact(repo, build, "app.zip", oid, size=300)
        self._artifact(repo, build, "build.log.txt", oid,
                       size=50)
        self._artifact(repo, test, "report.html", oid,
                       check_run="CI / test", size=120)
        self._artifact(repo, docs, "docs.zip", oid,
                       check_run="Docs / build", size=999)
        self._artifact(repo, plain, "scan.json", oid,
                       check_run="external-scan", size=888)
        return build, test

    def _list(self, viewer="owner", repo="pub",
              workflow="CI", oid=OID):
        viewer = {"owner": self.owner,
                  "stranger": self.stranger,
                  "anon": None}[viewer]
        return self.store.list_run_artifacts(
            viewer, "volmarr", repo, workflow, oid)

    # -- the gathering --------------------------------

    def test_run_listing_gathers_by_job(self):
        self._seed_run()
        listing = self._list()
        self.assertEqual(listing.full_name, "volmarr/pub")
        self.assertEqual(listing.workflow, "CI")
        self.assertEqual(listing.oid, OID)
        self.assertEqual(
            [g.job_id for g in listing.groups],
            ["build", "test"])
        self.assertEqual(
            [a.artifact.name for a in listing.groups[0].artifacts],
            ["app.zip", "build.log.txt"])
        self.assertEqual(
            [a.artifact.name for a in listing.groups[1].artifacts],
            ["report.html"])
        self.assertEqual(listing.total_count, 3)
        self.assertEqual(listing.total_bytes, 470)
        self.assertEqual(listing.expired_count, 0)
        self.assertIn("3 artifacts (470 bytes) across 2 jobs",
                      listing.words)

    def test_other_workflows_and_posters_excluded(self):
        self._seed_run()
        names = [a.artifact.name for a in self._list().artifacts]
        self.assertNotIn("docs.zip", names)
        self.assertNotIn("scan.json", names)
        docs = self._list(workflow="Docs")
        self.assertEqual(
            [a.artifact.name for a in docs.artifacts],
            ["docs.zip"])

    def test_other_commit_excluded(self):
        self._seed_run()
        self._seed_run(oid=OID2)
        listing = self._list(oid=OID2)
        self.assertEqual(listing.total_count, 3)
        self.assertEqual(listing.oid, OID2)
        self.assertEqual(self._list(oid="c" * 40).total_count, 0)

    def test_job_without_artifacts_answers_no_group(self):
        build = self._check_run(self.pub, "CI / build")
        self._check_run(self.pub, "CI / lint")
        self._artifact(self.pub, build, "app.zip")
        listing = self._list()
        self.assertEqual([g.job_id for g in listing.groups],
                         ["build"])

    def test_empty_run_lists_honestly_empty(self):
        listing = self._list()
        self.assertEqual(listing.groups, ())
        self.assertEqual(listing.total_count, 0)
        self.assertEqual(listing.total_bytes, 0)
        self.assertIn("produced no artifacts", listing.words)

    def test_job_narrowing(self):
        self._seed_run()
        one = self.store.list_job_artifacts(
            self.owner, "volmarr", "pub", "CI", OID, "test")
        self.assertEqual([g.job_id for g in one.groups], ["test"])
        self.assertEqual(one.total_count, 1)
        none = self.store.list_job_artifacts(
            self.owner, "volmarr", "pub", "CI", OID, "lint")
        self.assertEqual(none.total_count, 0)
        self.assertEqual(
            _reason(self.store.list_job_artifacts,
                    self.owner, "volmarr", "pub", "CI", OID, " "),
            "run_job_invalid")

    # -- expiry standing ------------------------------

    def test_expired_artifacts_listed_and_marked(self):
        build = self._check_run(self.pub, "CI / build")
        self._artifact(self.pub, build, "old.zip", size=10,
                       retention_days=7)
        self._artifact(self.pub, build, "kept.zip", size=20,
                       retention_days=0)
        fresh = self._list()
        self.assertEqual(fresh.expired_count, 0)
        self.clock.now = T0 + 7 * DAY
        listing = self._list()
        self.assertEqual(listing.total_count, 2)
        self.assertEqual(listing.expired_count, 1)
        by_name = {a.artifact.name: a for a in listing.artifacts}
        self.assertTrue(by_name["old.zip"].expired)
        self.assertFalse(by_name["kept.zip"].expired)
        self.assertIn("expired", by_name["old.zip"].words)
        data = run_artifacts_to_dict(listing)
        self.assertEqual(data["expired_count"], 1)
        self.assertTrue(data["artifacts"][0]["expired"])

    def test_swept_artifact_vanishes_from_listing(self):
        build = self._check_run(self.pub, "CI / build")
        gone = self._artifact(self.pub, build, "old.zip",
                              retention_days=7)
        self._artifact(self.pub, build, "kept.zip",
                       retention_days=0)
        with self.conn:
            self.conn.execute(
                "DELETE FROM ci_artifacts WHERE id = ?", (gone,))
        listing = self._list()
        self.assertEqual(
            [a.artifact.name for a in listing.artifacts],
            ["kept.zip"])

    # -- permission ------------------------------------

    def test_private_run_hidden_from_stranger(self):
        self._seed_run(repo=self.priv)
        mine = self._list(repo="priv")
        self.assertEqual(mine.total_count, 3)
        for viewer in ("stranger", "anon"):
            self.assertEqual(
                _reason(self._list, viewer, "priv"),
                "repository_not_found")
        self.assertEqual(
            _reason(self.store.list_job_artifacts,
                    self.stranger, "volmarr", "priv",
                    "CI", OID, "build"),
            "repository_not_found")

    def test_public_run_reads_anonymously(self):
        self._seed_run()
        self.assertEqual(self._list(viewer="anon").total_count, 3)
        self.assertEqual(
            self._list(viewer="stranger").total_count, 3)

    def test_missing_repository_uniform(self):
        self.assertEqual(
            _reason(self._list, "owner", "ghost"),
            "repository_not_found")

    def test_address_validates_before_repository(self):
        self.assertEqual(
            _reason(self.store.list_run_artifacts,
                    self.owner, "volmarr", "ghost", " ", OID),
            "run_workflow_invalid")
        self.assertEqual(
            _reason(self.store.list_run_artifacts,
                    self.owner, "volmarr", "ghost", "CI", ""),
            "run_oid_invalid")

    def test_listing_writes_no_audit_row(self):
        self._seed_run()
        before = self.conn.execute(
            "SELECT COUNT(*) c FROM audit_log").fetchone()["c"]
        self._list()
        after = self.conn.execute(
            "SELECT COUNT(*) c FROM audit_log").fetchone()["c"]
        self.assertEqual(before, after)

    # -- shapes -----------------------------------------

    def test_dict_shapes(self):
        self._seed_run()
        listing = self._list()
        data = run_artifacts_to_dict(listing)
        self.assertEqual(data["repository"], "volmarr/pub")
        self.assertEqual(data["workflow"], "CI")
        self.assertEqual(data["total_count"], 3)
        self.assertEqual(data["total_bytes"], 470)
        self.assertEqual(len(data["jobs"]), 2)
        first = data["artifacts"][0]
        self.assertEqual(first["name"], "app.zip")
        self.assertEqual(first["job_id"], "build")
        self.assertEqual(first["check_run"], "CI / build")
        self.assertEqual(first["size"], 300)
        self.assertFalse(first["expired"])
        self.assertEqual(first["retention_days"], 90)
        self.assertEqual(first["expires_at"], T0 + 90 * DAY)
        group = job_artifacts_to_dict(listing.groups[0])
        self.assertEqual(group["total_bytes"], 350)
        one = run_artifact_to_dict(listing.artifacts[0])
        self.assertEqual(one["sha256"],
                         hashlib.sha256(b"app.zip").hexdigest())

    # -- render -----------------------------------------

    def test_render_escapes_and_speaks(self):
        build = self._check_run(self.pub, "CI / build")
        self._artifact(self.pub, build, "<b>x</b>.zip")
        page = render_run_artifacts_page(listing=self._list())
        self.assertIn("<h1>Workflow run artifacts</h1>", page)
        self.assertIn("&lt;b&gt;x&lt;/b&gt;.zip", page)
        self.assertNotIn("<b>x</b>.zip", page)
        self.assertIn("produced 1 artifacts", page)
        bare = render_run_artifacts_page()
        self.assertIn("S-266", bare)

    # -- audit + pins ------------------------------------

    def test_audit_stands_cleanly(self):
        self._seed_run()
        audit = audit_workflow_artifacts(self.conn)
        self.assertTrue(audit.names_ok)
        self.assertTrue(audit.schema_ok)
        self.assertEqual(audit.schema_version, 138)
        self.assertTrue(audit.events_ok)
        self.assertTrue(audit.tables_ok)
        self.assertEqual(audit.rows_scanned, 5)
        self.assertEqual(audit.problems, ())
        self.assertTrue(audit.stands_cleanly)
        page = render_run_artifacts_page(audit=audit)
        self.assertIn("stands cleanly", page)

    def test_audit_names_broken_ties(self):
        build = self._check_run(self.pub, "CI / build")
        self._artifact(self.pub, build, "app.zip")
        with self.conn:
            self.conn.execute(
                "UPDATE ci_artifacts SET check_run = 'CI / test'")
        audit = audit_workflow_artifacts(self.conn)
        self.assertFalse(audit.stands_cleanly)
        self.assertEqual(len(audit.problems), 1)
        self.assertIn("check name", audit.problems[0])

    def test_pins_schema_131_taxonomy_135(self):
        self.assertEqual(schema_version(self.conn), 140)
        self.assertEqual(db.MIGRATIONS[-1][0], 140)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 142)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 92)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        tables = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("ci_artifacts", tables)
        self.assertIn("check_runs", tables)


if __name__ == "__main__":
    unittest.main()
