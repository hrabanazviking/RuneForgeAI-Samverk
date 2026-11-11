"""S-265 acceptance battery: Registry core --
the published refusal.

Acceptance (roadmap S-265): Registry core (if
verdicted in) -- namespaced package publish/fetch
with repo-linked permissions; if verdicted out,
this slice is the published refusal with the seam
documented. S-264 verdicted DEFER/out, so the
refusal is what stands here.

The centre is samverk/registry_core.py: the
namespace is a linked repository, the four
operations are judged at S-054's rungs for real
(publish write, fetch/list read, delete admin)
before S-264's per-ecosystem verdict is spoken,
private is indistinguishable from missing even in
the refusal, and the seam invariants are S-264's
own tuple, imported not forked. The audit proves
the refusal against the live instance and the
battery plants a registry-shaped table to prove
the audit would catch one.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.package_verdict import MUST_NOT_BREAK as VERDICT_INVARIANTS
from samverk.registry_core import (
    OPERATIONS, SEAM_INVARIANTS, PackageRef, RegistryCore,
    RegistryCoreAudit, RegistryCoreError, audit_registry_core,
    decide_delete, decide_fetch, decide_list, decide_publish,
    get_operation, render_registry_core_page, validate_name,
    validate_namespace, validate_version)
from samverk.repositories import RepositoryStore

ROOT = Path(__file__).resolve().parent.parent
PW = "correct horse battery"
T0 = 1_700_000_000


class Clock:
    def __init__(self, now=T0):
        self.now = now
    def __call__(self):
        return self.now


EXPECTED_OPERATIONS = (
    ("publish", "write"), ("fetch", "read"),
    ("list", "read"), ("delete", "admin"))


class RegistryCoreTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.clock = Clock()
        self.audit_log = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(
            self.conn, audit=self.audit_log, time_fn=self.clock)
        self.owner = self.accounts.register("volmarr", PW)
        self.other = self.accounts.register("yrsa", PW)
        self.stranger = self.accounts.register("mallory", PW)
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts,
            audit=self.audit_log, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        self.core = RegistryCore(self.repos)

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(RegistryCoreError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    # pins
    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 112)
        self.assertEqual(db.MIGRATIONS[-1][0], 112)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 133)
        families = {}
        for event in taxonomy.AUDIT_EVENTS:
            families[event.split(".")[0]] = (
                families.get(event.split(".")[0], 0) + 1)
        self.assertEqual(
            families, {"auth": 33, "repo": 87, "admin": 13})
        self.assertFalse(any(
            "package" in e or "registry" in e
            for e in taxonomy.AUDIT_EVENTS))

    # the operations catalogue
    def test_operations_exact_and_each_substantive(self):
        self.assertEqual(
            tuple((op.id, op.minimum_role) for op in OPERATIONS),
            EXPECTED_OPERATIONS)
        for operation in OPERATIONS:
            self.assertIs(get_operation(operation.id), operation)
            self.assertTrue(operation.title.strip(), operation.id)
            self.assertGreater(
                len(operation.would_do), 60, operation.id)
        self.assertEqual(
            self._reason(get_operation, "teleport"),
            "registry_action_invalid")

    def test_package_ref_names_the_namespace(self):
        ref = PackageRef(
            ecosystem="python", owner="Volmarr", repo="Anvil",
            name="anvil-kit", version="1.2.0")
        self.assertEqual(ref.namespace, "Volmarr/Anvil")
        self.assertEqual(
            ref.coordinate, "python:Volmarr/Anvil/anvil-kit@1.2.0")

    # the seam is the verdict's own, not a fork
    def test_seam_invariants_are_the_verdicts_own(self):
        self.assertIs(SEAM_INVARIANTS, VERDICT_INVARIANTS)
        self.assertEqual(len(SEAM_INVARIANTS), 8)

    # shape doors: judged first, storing nothing
    def test_validate_name(self):
        self.assertEqual(validate_name("anvil-kit"), "anvil-kit")
        self.assertEqual(validate_name("a.b_c-1"), "a.b_c-1")
        for bad in ("", "Anvil", "-anvil", ".anvil", "anvil.",
                    "anvil-", "an..vil", "an/vil", "an vil",
                    None, 7, "x" * 101):
            self.assertEqual(
                self._reason(validate_name, bad),
                "package_name_invalid", repr(bad))

    def test_validate_version(self):
        self.assertEqual(validate_version("1.2.0"), "1.2.0")
        self.assertEqual(validate_version("2.0rc1+local"), "2.0rc1+local")
        for bad in ("", "..", "1..2", "1/2", "/1.2", " 1.2",
                    None, 1.2, "v" * 65):
            self.assertEqual(
                self._reason(validate_version, bad),
                "package_version_invalid", repr(bad))

    def test_validate_namespace(self):
        self.assertEqual(
            validate_namespace("volmarr", "pub"), ("volmarr", "pub"))
        for bad_owner, bad_repo in (
                ("", "pub"), ("volmarr", ""), (None, "pub"),
                ("vol marr", "pub"), ("volmarr", "a/b")):
            self.assertEqual(
                self._reason(validate_namespace, bad_owner, bad_repo),
                "namespace_invalid", (bad_owner, bad_repo))

    # the pure decision matrix
    def test_decide_publish_matrix(self):
        self.assertEqual(
            decide_publish("python", False, "admin"), "repo_not_found")
        self.assertEqual(
            decide_publish("python", True, None), "repo_not_found")
        self.assertEqual(
            decide_publish("python", True, "read"), "permission_denied")
        self.assertEqual(
            decide_publish("python", True, "write"), "registry_deferred")
        self.assertEqual(
            decide_publish("python", True, "admin"), "registry_deferred")
        self.assertEqual(
            decide_publish("oci-containers", True, "write"),
            "registry_refused")
        self.assertEqual(
            decide_publish("generic-archives", True, "write"),
            "registry_served_by_releases")
        self.assertEqual(
            decide_publish("go-modules", True, "admin"),
            "registry_served_by_git")

    def test_decide_fetch_and_list_matrix(self):
        for decide in (decide_fetch, decide_list):
            self.assertEqual(
                decide("python", False, "read"), "package_not_found")
            self.assertEqual(
                decide("python", True, None), "package_not_found")
            self.assertEqual(
                decide("python", True, "read"), "registry_deferred")
            self.assertEqual(
                decide("javascript", True, "read"), "registry_deferred")
            self.assertEqual(
                decide("oci-containers", True, "read"),
                "registry_refused")

    def test_decide_delete_matrix(self):
        self.assertEqual(
            decide_delete("python", False, "admin"), "repo_not_found")
        self.assertEqual(
            decide_delete("python", True, None), "repo_not_found")
        self.assertEqual(
            decide_delete("python", True, "read"), "permission_denied")
        self.assertEqual(
            decide_delete("python", True, "write"), "permission_denied")
        self.assertEqual(
            decide_delete("python", True, "admin"), "registry_deferred")

    # publish through the core: permissions before verdict
    def test_publish_owner_meets_the_verdict(self):
        self.assertEqual(
            self._reason(
                self.core.publish, self.owner, "python",
                "volmarr", "pub", "anvil-kit", "1.0"),
            "registry_deferred")
        self.assertEqual(
            self._reason(
                self.core.publish, self.owner, "oci-containers",
                "volmarr", "pub", "anvil-kit", "1.0"),
            "registry_refused")
        self.assertEqual(
            self._reason(
                self.core.publish, self.owner, "generic-archives",
                "volmarr", "priv", "anvil-kit", "1.0"),
            "registry_served_by_releases")

    def test_publish_permission_door(self):
        # A reader of a public repo may not write: permission first.
        self.assertEqual(
            self._reason(
                self.core.publish, self.other, "python",
                "volmarr", "pub", "anvil-kit", "1.0"),
            "permission_denied")
        # A granted write collaborator passes the door to the verdict.
        self.assertEqual(
            self._reason(
                self.core.publish, self.other, "python",
                "volmarr", "priv", "anvil-kit", "1.0",
                collaborator_role="write"),
            "registry_deferred")
        # A stranger to a private repo, and a missing repo, are one.
        self.assertEqual(
            self._reason(
                self.core.publish, self.stranger, "python",
                "volmarr", "priv", "anvil-kit", "1.0"),
            "repo_not_found")
        self.assertEqual(
            self._reason(
                self.core.publish, self.owner, "python",
                "volmarr", "ghost", "anvil-kit", "1.0"),
            "repo_not_found")
        # Anonymous publish is refused before any repository is read.
        self.assertEqual(
            self._reason(
                self.core.publish, None, "python",
                "volmarr", "pub", "anvil-kit", "1.0"),
            "authentication_required")

    def test_publish_shape_refused_before_permissions(self):
        # Even a stranger meets the shape refusal first: the door
        # judges the request's shape before any repository is read.
        self.assertEqual(
            self._reason(
                self.core.publish, self.stranger, "python",
                "volmarr", "priv", "Bad Name", "1.0"),
            "package_name_invalid")
        self.assertEqual(
            self._reason(
                self.core.publish, self.owner, "maven-central",
                "volmarr", "pub", "anvil-kit", "1.0"),
            "registry_ecosystem_unknown")
        self.assertEqual(
            self._reason(
                self.core.publish, self.owner, "",
                "volmarr", "pub", "anvil-kit", "1.0"),
            "registry_request_invalid")
        self.assertEqual(
            self._reason(
                self.core.publish, self.owner, "python",
                "volmarr", "a/b", "anvil-kit", "1.0"),
            "namespace_invalid")
        self.assertEqual(
            self._reason(
                self.core.publish, self.owner, "python",
                "volmarr", "pub", "anvil-kit", "1/0"),
            "package_version_invalid")

    # fetch/list: private is missing, even in the refusal
    def test_fetch_private_is_indistinguishable_from_missing(self):
        stranger_private = self._reason(
            self.core.fetch, self.stranger, "python",
            "volmarr", "priv", "anvil-kit", "1.0")
        stranger_missing = self._reason(
            self.core.fetch, self.stranger, "python",
            "volmarr", "ghost", "anvil-kit", "1.0")
        owner_missing_package = self._reason(
            self.core.fetch, self.owner, "python",
            "volmarr", "ghost2", "anvil-kit", "1.0")
        self.assertEqual(stranger_private, "package_not_found")
        self.assertEqual(stranger_private, stranger_missing)
        self.assertEqual(stranger_missing, owner_missing_package)
        anon_private = self._reason(
            self.core.fetch, None, "python",
            "volmarr", "priv", "anvil-kit", "1.0")
        self.assertEqual(anon_private, "package_not_found")

    def test_fetch_reader_meets_the_verdict(self):
        self.assertEqual(
            self._reason(
                self.core.fetch, self.stranger, "python",
                "volmarr", "pub", "anvil-kit", "1.0"),
            "registry_deferred")
        # Anonymous reads a public namespace to the same verdict.
        self.assertEqual(
            self._reason(
                self.core.fetch, None, "go-modules",
                "volmarr", "pub", "anvil-kit", "1.0"),
            "registry_served_by_git")
        # The owner of a private namespace meets the verdict too.
        self.assertEqual(
            self._reason(
                self.core.fetch, self.owner, "python",
                "volmarr", "priv", "anvil-kit", "1.0"),
            "registry_deferred")
        self.assertEqual(
            self._reason(
                self.core.list_versions, self.other, "python",
                "volmarr", "pub", "anvil-kit"),
            "registry_deferred")
        self.assertEqual(
            self._reason(
                self.core.list_versions, self.stranger, "python",
                "volmarr", "priv", "anvil-kit"),
            "package_not_found")

    # delete: the admin rung
    def test_delete_admin_door(self):
        self.assertEqual(
            self._reason(
                self.core.delete, self.owner, "python",
                "volmarr", "priv", "anvil-kit", "1.0"),
            "registry_deferred")
        self.assertEqual(
            self._reason(
                self.core.delete, self.other, "python",
                "volmarr", "pub", "anvil-kit", "1.0",
                collaborator_role="write"),
            "permission_denied")
        self.assertEqual(
            self._reason(
                self.core.delete, self.other, "python",
                "volmarr", "pub", "anvil-kit", "1.0",
                collaborator_role="admin"),
            "registry_deferred")
        self.assertEqual(
            self._reason(
                self.core.delete, None, "python",
                "volmarr", "pub", "anvil-kit", "1.0"),
            "authentication_required")

    # the refusal writes and audits nothing
    def test_refusal_writes_nothing(self):
        tables = ("users", "repositories", "audit_log")
        before = {
            t: self.conn.execute(
                f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
            for t in tables}
        for fn, args in (
                (self.core.publish,
                 (self.owner, "python", "volmarr", "pub",
                  "anvil-kit", "1.0")),
                (self.core.fetch,
                 (self.stranger, "python", "volmarr", "pub",
                  "anvil-kit", "1.0")),
                (self.core.list_versions,
                 (self.owner, "python", "volmarr", "priv", "anvil-kit")),
                (self.core.delete,
                 (self.owner, "python", "volmarr", "pub",
                  "anvil-kit", "1.0"))):
            with self.assertRaises(RegistryCoreError):
                fn(*args)
        audit_registry_core(self.conn)
        render_registry_core_page()
        after = {
            t: self.conn.execute(
                f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
            for t in tables}
        self.assertEqual(before, after)

    # the audit: refusal proven, planting caught
    def test_audit_is_refused_cleanly(self):
        audit = audit_registry_core(self.conn)
        self.assertTrue(audit.refused_cleanly, audit)
        self.assertEqual(audit.verdict, "deferred")
        self.assertTrue(audit.verdict_deferred_cleanly)
        self.assertTrue(audit.contract_ratified)
        self.assertEqual(audit.registry_contract_resources, ())
        self.assertEqual(audit.offending_tables, ())
        self.assertEqual(audit.offending_columns, ())
        self.assertEqual(audit.offending_events, ())
        self.assertEqual(audit.events_scanned, 133)
        self.assertEqual(audit.operations_defined, 4)
        self.assertEqual(audit.seam_invariants, 8)
        self.assertGreater(audit.tables_scanned, 50)
        self.assertGreater(audit.contract_resources_checked, 30)

    def test_audit_catches_a_planted_registry_table(self):
        with self.conn:
            self.conn.execute(
                "CREATE TABLE registry_packages (id INTEGER,"
                " package_name TEXT)")
        audit = audit_registry_core(self.conn)
        self.assertFalse(audit.refused_cleanly)
        self.assertIn("registry_packages", audit.offending_tables)
        self.assertIn(
            "registry_packages.package_name", audit.offending_columns)

    # the page: the published refusal, in words
    def test_page_says_no_registry_plainly(self):
        page = render_registry_core_page(
            audit_registry_core(self.conn))
        self.assertIn("Registry core -- no registry (S-265)", page)
        self.assertIn("no package registry", page)
        self.assertIn("The namespace is a repository", page)
        self.assertIn("Checked, not just claimed", page)
        for operation in OPERATIONS:
            self.assertIn(operation.title, page)
            self.assertIn(operation.id, page)
        for invariant in SEAM_INVARIANTS:
            self.assertIn(invariant.title, page)
        self.assertIn("registry_deferred", page)
        self.assertIn("registry_refused", page)
        self.assertIn("S-403", page)
        self.assertIn("docs/REGISTRY_CORE.md", page)

    def test_page_without_audit_states_no_check(self):
        page = render_registry_core_page()
        self.assertNotIn("Checked, not just claimed", page)
        self.assertNotIn("not clean", page)

    def test_page_reports_a_planted_defect_honestly(self):
        with self.conn:
            self.conn.execute(
                "CREATE TABLE registry_packages (id INTEGER)")
        page = render_registry_core_page(
            audit_registry_core(self.conn))
        self.assertIn("not clean", page)
        self.assertIn("registry_packages", page)
        self.assertIn("defect against S-265", page)

    def test_page_escapes_every_value(self):
        audit = RegistryCoreAudit(
            verdict="deferred", verdict_deferred_cleanly=False,
            contract_ratified=True, contract_resources_checked=1,
            registry_contract_resources=("<b>packages</b>",),
            tables_scanned=1, columns_scanned=1, events_scanned=1,
            offending_tables=(), offending_columns=(),
            offending_events=(), operations_defined=4,
            seam_invariants=8)
        page = render_registry_core_page(audit)
        self.assertNotIn("<b>packages</b>", page)
        self.assertIn("&lt;b&gt;packages", page)

    # the docs say it too
    def test_docs_record_the_refusal_and_seam(self):
        doc = (ROOT / "docs" / "REGISTRY_CORE.md").read_text(
            encoding="utf-8")
        self.assertIn("S-265", doc)
        self.assertIn("S-264", doc)
        self.assertIn("no package registry", doc.lower())
        for operation in OPERATIONS:
            self.assertIn(operation.id, doc, operation.id)
            self.assertIn(operation.minimum_role, doc, operation.id)
        for invariant in SEAM_INVARIANTS:
            self.assertIn(invariant.id, doc, invariant.id)


if __name__ == "__main__":
    unittest.main()
