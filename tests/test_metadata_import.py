"""S-338 acceptance battery: metadata import.

Acceptance (roadmap S-338): issues, labels, milestones,
and releases imported from GitHub's API into the mirror
(where the owner's credential allows), marked as
imported with source links.
"""
from __future__ import annotations
import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.census_fixture import CensusFixtureService, parse_classification
from samverk.db import schema_version
from samverk.issues import IssueStore
from samverk.metadata_import import (
    KIND_ISSUE, STATE_FAILED, STATE_IMPORTED, STATE_REFUSED,
    MetadataImportError, MetadataImportService, is_pull_request,
    normalise_issue, normalise_label, normalise_milestone,
    normalise_release, parse_github_source, render_metadata_import_page)
from samverk.mirror_credentials import MirrorCredentialService
from samverk.secrets import Secrets

PAYLOADS = {
    "labels": [
        {"name": "bug", "color": "d73a4a", "description": "Something isn't working", "url": "https://api.github.com/x", "html_url": "https://github.com/hrabanazviking/widget/labels"},
        {"name": "imported-only", "color": "0e8a16", "description": "From GitHub", "html_url": "https://github.com/hrabanazviking/widget/labels"},
        {"color": "ffffff"},
    ],
    "milestones": [
        {"title": "v1.0", "description": "First", "state": "open", "due_on": "2027-01-15T00:00:00Z", "html_url": "https://github.com/hrabanazviking/widget/milestone/1"},
    ],
    "issues": [
        {"number": 7, "title": "Imported bug", "body": "From GitHub", "state": "closed", "state_reason": "completed", "labels": [{"name": "imported-only"}], "milestone": {"title": "v1.0"}, "html_url": "https://github.com/hrabanazviking/widget/issues/7"},
        {"number": 8, "title": "A pull request", "state": "open", "pull_request": {"url": "https://api.github.com/x"}, "html_url": "https://github.com/hrabanazviking/widget/pull/8"},
        {"number": 9, "title": "Open one", "state": "open", "labels": [], "milestone": None},
    ],
    "releases": [
        {"tag_name": "v1.0.0", "name": "First release", "body": "Notes", "draft": False, "prerelease": True, "target_commitish": "main", "html_url": "https://github.com/hrabanazviking/widget/releases/tag/v1.0.0"},
        {"name": "No tag here"},
    ],
}


class FakeFetch:
    def __init__(self, payloads=None):
        self.payloads = PAYLOADS if payloads is None else payloads
        self.calls = []
    def __call__(self, url, token=None):
        self.calls.append((url, token))
        for endpoint, payload in self.payloads.items():
            if f"/{endpoint}?" in url:
                return json.loads(json.dumps(payload))
        return []


class MetadataImportTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        root = Path(self._td.name)
        self.data_root = root / "instance"; self.data_root.mkdir()
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        from samverk.repositories import RepositoryStore
        self.repos = RepositoryStore(self.conn, self.data_root, self.accounts)
        self.audit = AuditLog(self.conn)
        self.census = CensusFixtureService(self.conn, self.data_root, self.accounts, self.repos, self.audit)
        self.creds = MirrorCredentialService(self.conn, self.data_root, self.accounts, self.repos, self.audit)
        self.fetch = FakeFetch()
        self.svc = MetadataImportService(self.conn, self.data_root, self.accounts, self.repos, self.audit, fetch_fn=self.fetch)
        self.secrets = Secrets({"GITHUB_READ_TOKEN": "test-token-value"})
        parsed = parse_classification(json.dumps({"include": [{"name": "widget", "private": False, "fork": False, "parent": "", "note": ""}]}))
        self.census.import_classification(self.owner.id, "volmarr", parsed, github_owner="hrabanazviking")
        repo = self.repos.get_repository("volmarr", "widget")
        with self.conn:
            self.conn.execute("UPDATE repo_mirrors SET source = 'https://github.com/hrabanazviking/widget', source_kind = 'url' WHERE repo_id = ?", (repo.id,))

    def credential(self):
        self.creds.set_credential(self.owner.id, "volmarr", "widget", "GITHUB_READ_TOKEN")

    def run_import(self, scope="read", secrets=None):
        return self.svc.import_metadata("volmarr", "widget", secrets=self.secrets if secrets is None else secrets, declared_scope=scope)

    # -- pins ------------------------------------------------------
    def test_schema_and_taxonomy_pins(self):
        # S-338 adds migration 139 (provenance + runs) and
        # no new audit event: taxonomy stands at 138.
        self.assertEqual(schema_version(self.conn), 139)
        self.assertEqual(db.MIGRATIONS[-1][0], 139)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 138)

    # -- pure source parsing ----------------------------------------
    def test_parse_github_source_variants(self):
        self.assertEqual(parse_github_source("https://github.com/a/b"), ("a", "b"))
        self.assertEqual(parse_github_source("https://github.com/a/b.git"), ("a", "b"))
        self.assertEqual(parse_github_source("https://github.com/a/b/"), ("a", "b"))
        self.assertIsNone(parse_github_source("https://example.com/a/b"))
        self.assertIsNone(parse_github_source("/tmp/local"))
        self.assertIsNone(parse_github_source("git@github.com:a/b.git"))
        self.assertIsNone(parse_github_source(None))

    # -- pure normalisers --------------------------------------------
    def test_normalise_label_colour_and_name_law(self):
        lab = normalise_label({"name": "bug", "color": "D73A4A", "description": "x"})
        self.assertEqual(lab.colour, "#d73a4a")
        with self.assertRaises(MetadataImportError):
            normalise_label({"color": "ffffff"})

    def test_normalise_milestone_due_date(self):
        ms = normalise_milestone({"title": "v1", "state": "open", "due_on": "2027-01-15T00:00:00Z"})
        self.assertEqual(ms.due_on, "2027-01-15")
        with self.assertRaises(Exception):
            normalise_milestone({"title": "v1", "due_on": "2027-02-30T00:00:00Z"})

    def test_normalise_issue_and_pr_marker(self):
        self.assertTrue(is_pull_request({"pull_request": {}}))
        self.assertFalse(is_pull_request({"number": 1}))
        issue = normalise_issue({"number": 3, "title": "T", "state": "closed", "labels": [{"name": "bug"}], "milestone": {"title": "v1"}})
        self.assertEqual(issue.state_reason, "completed")
        self.assertEqual(issue.label_names, ("bug",))
        with self.assertRaises(MetadataImportError):
            normalise_issue({"title": "no number"})

    def test_normalise_release_requires_tag(self):
        rel = normalise_release({"tag_name": "v1", "name": "", "draft": True})
        self.assertEqual(rel.title, "v1")
        self.assertTrue(rel.draft)
        with self.assertRaises(MetadataImportError):
            normalise_release({"name": "no tag"})

    # -- credential gate -----------------------------------------------
    def test_gate_refuses_without_credential_and_records(self):
        report = self.run_import()
        self.assertEqual(report.state, STATE_REFUSED)
        self.assertIn("no credential", report.detail)
        self.assertEqual(self.fetch.calls, [])
        runs = self.svc.runs_for("volmarr/widget")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].state, STATE_REFUSED)

    def test_gate_refuses_write_scope_before_fetch(self):
        self.credential()
        report = self.run_import(scope="contents:write")
        self.assertEqual(report.state, STATE_REFUSED)
        self.assertEqual(self.fetch.calls, [])

    def test_gate_refuses_undeclared_scope(self):
        self.credential()
        report = self.run_import(scope="")
        self.assertEqual(report.state, STATE_REFUSED)
        self.assertEqual(self.fetch.calls, [])

    def test_gate_refuses_unloaded_secret(self):
        self.credential()
        report = self.svc.import_metadata("volmarr", "widget", secrets=Secrets({}), declared_scope="read")
        self.assertEqual(report.state, STATE_REFUSED)
        self.assertIn("not loaded", report.detail)
        self.assertEqual(self.fetch.calls, [])

    def test_not_a_mirror_raises(self):
        with self.assertRaises(MetadataImportError):
            self.svc.import_metadata("volmarr", "nope", secrets=self.secrets, declared_scope="read")

    # -- the import ------------------------------------------------------
    def test_import_lands_all_kinds_marked_with_links(self):
        self.credential()
        report = self.run_import()
        self.assertEqual(report.state, STATE_IMPORTED)
        self.assertEqual(report.labels_imported, 2)
        self.assertEqual(report.milestones_imported, 1)
        self.assertEqual(report.issues_imported, 2)
        self.assertEqual(report.releases_imported, 1)
        self.assertEqual(report.pull_requests_skipped, 1)
        self.assertEqual(report.invalid_items, 2)
        self.assertTrue(self.fetch.calls)
        self.assertTrue(all(tok == "test-token-value" for _, tok in self.fetch.calls))
        records = self.svc.imports_for("volmarr", "widget")
        self.assertEqual(len(records), 6)
        issue_rec = [r for r in records if r.kind == KIND_ISSUE and r.source_key == "7"][0]
        self.assertEqual(issue_rec.source_url, "https://github.com/hrabanazviking/widget/issues/7")
        row = self.conn.execute("SELECT * FROM issues WHERE repo_id = (SELECT id FROM repositories WHERE name='widget') AND number = 7").fetchone()
        self.assertEqual(row["title"], "Imported bug")
        self.assertEqual(row["state"], "closed")
        lab = self.conn.execute("SELECT colour FROM labels WHERE name = 'imported-only'").fetchone()
        self.assertEqual(lab["colour"], "#0e8a16")
        link = self.conn.execute("SELECT COUNT(*) c FROM issue_labels WHERE issue_id = ?", (row["id"],)).fetchone()
        self.assertEqual(link["c"], 1)
        self.assertIsNotNone(row["milestone_id"])
        rel = self.conn.execute("SELECT * FROM releases WHERE tag = 'v1.0.0'").fetchone()
        self.assertEqual(rel["prerelease"], 1)

    def test_import_is_idempotent(self):
        self.credential()
        self.run_import()
        second = self.run_import()
        self.assertEqual(second.imported_total, 0)
        self.assertEqual(second.issues_skipped, 2)
        count = self.conn.execute("SELECT COUNT(*) c FROM issues WHERE title = 'Imported bug'").fetchone()
        self.assertEqual(count["c"], 1)

    def test_preserved_number_advances_counter(self):
        self.credential()
        self.run_import()
        store = IssueStore(self.conn, self.repos, self.accounts, self.audit)
        claimed = store.claim_number("volmarr", "widget", "issue", self.owner.id)
        self.assertGreater(claimed.number, 9)

    def test_non_github_source_fails_recorded(self):
        self.credential()
        repo = self.repos.get_repository("volmarr", "widget")
        with self.conn:
            self.conn.execute("UPDATE repo_mirrors SET source = 'https://example.com/a/b', source_kind = 'url' WHERE repo_id = ?", (repo.id,))
        report = self.run_import()
        self.assertEqual(report.state, STATE_FAILED)
        self.assertEqual(self.fetch.calls, [])
        self.assertEqual(self.svc.runs_for("volmarr/widget")[-1].state, STATE_FAILED)

    def test_fetch_failure_recorded(self):
        self.credential()
        def boom(url, token=None):
            raise RuntimeError("network down")
        svc = MetadataImportService(self.conn, self.data_root, self.accounts, self.repos, self.audit, fetch_fn=boom)
        report = svc.import_metadata("volmarr", "widget", secrets=self.secrets, declared_scope="read")
        self.assertEqual(report.state, STATE_FAILED)
        self.assertIn("network down", report.detail)

    def test_page_marks_imported_with_source_links(self):
        self.credential()
        report = self.run_import()
        page = render_metadata_import_page(report)
        self.assertIn("imported from", page)
        self.assertIn("https://github.com/hrabanazviking/widget/issues/7", page)
        self.assertIn("2 labels", page)


if __name__ == "__main__":
    unittest.main()
