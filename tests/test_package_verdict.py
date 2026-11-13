"""S-264 acceptance battery: Package registry verdict.

Acceptance (roadmap S-264): Package registry
verdict -- research file 26 concludes which
ecosystems, if any, Samverk hosts: decided by
village need, recorded with reasons.

The verdict here is DEFER: no ecosystem is
hosted now, Python is the named first candidate,
generic archives are already served by releases,
Go modules by the git transports, and OCI
containers are refused outright. The centre is
the audit: the deferral is checked against the
live instance -- no table, column or audit event
carries a package registry -- and the battery
plants a registry-shaped table to prove the
audit would catch one.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.db import schema_version
from samverk.package_verdict import (
    ECOSYSTEMS, MUST_NOT_BREAK, REASONS,
    REOPEN_CONDITIONS, VERDICT, PackageVerdictAudit,
    PackageVerdictError, audit_package_verdict,
    attempt_registry_action, decide_registry_request,
    get_ecosystem, get_invariant, get_reason,
    render_package_verdict_page)

ROOT = Path(__file__).resolve().parent.parent

EXPECTED_REASON_IDS = (
    "no-measured-village-need",
    "releases-already-serve-distribution",
    "each-ecosystem-is-its-own-surface",
    "trust-machinery-not-yet-standing",
    "village-scale-simplicity")
EXPECTED_ECOSYSTEM_IDS = (
    "python", "generic-archives", "javascript",
    "oci-containers", "go-modules")
EXPECTED_JUDGEMENTS = {
    "python": "deferred-first-candidate",
    "generic-archives": "served-by-releases",
    "javascript": "deferred",
    "oci-containers": "refused",
    "go-modules": "served-by-git"}
EXPECTED_INVARIANT_IDS = (
    "namespace-follows-permissions",
    "versions-are-immutable",
    "private-is-missing-on-fetch",
    "digest-is-not-identity",
    "quarantine-before-visible",
    "deletion-leaves-a-tombstone",
    "export-or-it-does-not-ship",
    "publish-and-fetch-are-witnessed")


class PackageVerdictTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.conn = db.init_db(
            Path(self._td.name) / "samverk.db")
        self.addCleanup(self.conn.close)

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(PackageVerdictError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    # pins
    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 126)
        self.assertEqual(db.MIGRATIONS[-1][0], 126)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 135)
        families = {}
        for event in taxonomy.AUDIT_EVENTS:
            families[event.split(".")[0]] = (
                families.get(event.split(".")[0], 0) + 1)
        self.assertEqual(
            families, {"auth": 33, "repo": 89, "admin": 13})
        self.assertFalse(any(
            "package" in e or "registry" in e
            for e in taxonomy.AUDIT_EVENTS))

    # the verdict and its reasons
    def test_verdict_is_deferred(self):
        self.assertEqual(VERDICT, "deferred")

    def test_reason_ids_exact_and_each_reason_substantive(self):
        self.assertEqual(
            tuple(r.id for r in REASONS), EXPECTED_REASON_IDS)
        for reason in REASONS:
            self.assertTrue(reason.title.strip(), reason.id)
            self.assertGreater(len(reason.detail), 200, reason.id)
            self.assertIs(get_reason(reason.id), reason)

    def test_get_reason_unknown_refused(self):
        self.assertEqual(
            self._reason(get_reason, "build-now"), "reason_unknown")
        self.assertEqual(
            self._reason(get_reason, None), "reason_unknown")

    # research 26's candidate ecosystems
    def test_ecosystem_ids_exact_and_judged(self):
        self.assertEqual(
            tuple(e.id for e in ECOSYSTEMS), EXPECTED_ECOSYSTEM_IDS)
        for ecosystem in ECOSYSTEMS:
            self.assertIs(get_ecosystem(ecosystem.id), ecosystem)
            self.assertEqual(
                ecosystem.judgement,
                EXPECTED_JUDGEMENTS[ecosystem.id], ecosystem.id)
            self.assertTrue(ecosystem.hosting_means.strip(), ecosystem.id)
            self.assertTrue(ecosystem.village_need.strip(), ecosystem.id)
            self.assertTrue(ecosystem.served_by.strip(), ecosystem.id)
        self.assertEqual(
            self._reason(get_ecosystem, "maven-central"),
            "ecosystem_unknown")

    def test_python_is_the_first_candidate(self):
        ecosystem = get_ecosystem("python")
        self.assertEqual(
            ecosystem.judgement, "deferred-first-candidate")
        joined = " ".join(REOPEN_CONDITIONS)
        self.assertIn("Python first", joined)

    def test_oci_is_the_one_refusal(self):
        refused = [e.id for e in ECOSYSTEMS
                   if e.judgement == "refused"]
        self.assertEqual(refused, ["oci-containers"])
        ecosystem = get_ecosystem("oci-containers")
        self.assertIn("no Docker", ecosystem.village_need)

    # the must-not-break invariants
    def test_invariant_ids_exact(self):
        self.assertEqual(
            tuple(i.id for i in MUST_NOT_BREAK),
            EXPECTED_INVARIANT_IDS)
        for invariant in MUST_NOT_BREAK:
            self.assertIs(
                get_invariant(invariant.id), invariant)
            self.assertGreater(
                len(invariant.statement), 150, invariant.id)
            self.assertTrue(invariant.ground.strip(), invariant.id)
        self.assertEqual(
            self._reason(get_invariant, "anything-goes"),
            "invariant_unknown")

    def test_reopen_conditions_name_the_successor(self):
        self.assertEqual(len(REOPEN_CONDITIONS), 4)
        joined = " ".join(REOPEN_CONDITIONS)
        self.assertIn("S-403", joined)
        self.assertIn("S-268", joined)
        self.assertIn("release assets cannot serve", joined)

    # the pure per-ecosystem answers
    def test_decide_registry_request_pure(self):
        self.assertEqual(
            decide_registry_request("python"), "registry_deferred")
        self.assertEqual(
            decide_registry_request("javascript"), "registry_deferred")
        self.assertEqual(
            decide_registry_request("oci-containers"),
            "registry_refused")
        self.assertEqual(
            decide_registry_request("generic-archives"),
            "registry_served_by_releases")
        self.assertEqual(
            decide_registry_request("go-modules"),
            "registry_served_by_git")
        self.assertEqual(
            decide_registry_request("maven-central"),
            "registry_ecosystem_unknown")
        self.assertEqual(
            decide_registry_request(""), "registry_request_invalid")
        self.assertEqual(
            decide_registry_request("   "), "registry_request_invalid")
        self.assertEqual(
            decide_registry_request(None), "registry_request_invalid")

    def test_every_registry_action_answered(self):
        self.assertEqual(
            self._reason(attempt_registry_action, "python"),
            "registry_deferred")
        self.assertEqual(
            self._reason(attempt_registry_action, "oci-containers"),
            "registry_refused")
        self.assertEqual(
            self._reason(attempt_registry_action, "generic-archives"),
            "registry_served_by_releases")
        self.assertEqual(
            self._reason(attempt_registry_action, "go-modules"),
            "registry_served_by_git")
        self.assertEqual(
            self._reason(attempt_registry_action, "maven-central"),
            "registry_ecosystem_unknown")
        self.assertEqual(
            self._reason(attempt_registry_action, ""),
            "registry_request_invalid")

    def test_refusal_writes_nothing(self):
        before = {
            t: self.conn.execute(
                f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
            for t in ("users", "audit_log")}
        self._reason(attempt_registry_action, "python")
        audit_package_verdict(self.conn)
        render_package_verdict_page()
        after = {
            t: self.conn.execute(
                f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
            for t in ("users", "audit_log")}
        self.assertEqual(before, after)

    # the audit: deferral proven, planting caught
    def test_audit_is_deferred_cleanly(self):
        audit = audit_package_verdict(self.conn)
        self.assertTrue(audit.deferred_cleanly, audit)
        self.assertEqual(audit.verdict, "deferred")
        self.assertEqual(audit.offending_tables, ())
        self.assertEqual(audit.offending_columns, ())
        self.assertEqual(audit.offending_events, ())
        self.assertEqual(audit.events_scanned, 135)
        self.assertGreater(audit.tables_scanned, 50)
        self.assertGreater(audit.columns_scanned, 400)

    def test_audit_catches_a_planted_registry_table(self):
        with self.conn:
            self.conn.execute(
                "CREATE TABLE package_registry (id INTEGER,"
                " package_name TEXT)")
        audit = audit_package_verdict(self.conn)
        self.assertFalse(audit.deferred_cleanly)
        self.assertIn("package_registry", audit.offending_tables)
        self.assertIn(
            "package_registry.package_name",
            audit.offending_columns)

    # the page
    def test_page_says_deferred_plainly(self):
        page = render_package_verdict_page(
            audit_package_verdict(self.conn))
        self.assertIn("Package registry -- deferred (S-264)", page)
        self.assertIn("deferred", page)
        self.assertIn("no package registry", page)
        self.assertIn("Checked, not just claimed", page)
        for reason in REASONS:
            self.assertIn(reason.title, page)
        for ecosystem in ECOSYSTEMS:
            self.assertIn(ecosystem.title, page)
        for invariant in MUST_NOT_BREAK:
            self.assertIn(invariant.title, page)
        self.assertIn("S-403", page)
        self.assertIn("docs/PACKAGE_VERDICT.md", page)

    def test_page_without_audit_states_no_verdict(self):
        page = render_package_verdict_page()
        self.assertNotIn("Checked, not just claimed", page)
        self.assertNotIn("not clean", page)

    def test_page_reports_a_planted_defect_honestly(self):
        with self.conn:
            self.conn.execute(
                "CREATE TABLE package_registry (id INTEGER)")
        page = render_package_verdict_page(
            audit_package_verdict(self.conn))
        self.assertIn("not clean", page)
        self.assertIn("package_registry", page)
        self.assertIn("defect against S-264", page)

    def test_page_escapes_every_value(self):
        audit = PackageVerdictAudit(
            verdict="deferred",
            tables_scanned=1, columns_scanned=1,
            events_scanned=1,
            offending_tables=("<b>registry</b>",),
            offending_columns=(), offending_events=())
        page = render_package_verdict_page(audit)
        self.assertNotIn("<b>registry</b>", page)
        self.assertIn("&lt;b&gt;registry", page)

    # the docs say it too
    def test_docs_record_the_verdict_and_invariants(self):
        doc = (ROOT / "docs" / "PACKAGE_VERDICT.md").read_text(
            encoding="utf-8")
        self.assertIn("deferred", doc.lower())
        self.assertIn("S-264", doc)
        self.assertIn("research file 26", doc)
        self.assertIn("S-265", doc)
        for invariant in MUST_NOT_BREAK:
            self.assertIn(invariant.id, doc, invariant.id)
        for reason in REASONS:
            self.assertIn(reason.id, doc, reason.id)
        for ecosystem in ECOSYSTEMS:
            self.assertIn(ecosystem.id, doc, ecosystem.id)


if __name__ == "__main__":
    unittest.main()
