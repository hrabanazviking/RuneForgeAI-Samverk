"""S-335 acceptance battery: the Volmarr census fixture.

Acceptance (roadmap S-335): the 54-originals inventory is
imported as mirror definitions; uncertain-classified repos
are NOT auto-mirrored (his word governs each).

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.census_fixture import (
    ACTION_DEFINE, ACTION_HOLD, ACTION_SKIP, BUCKET_EXCLUDE,
    BUCKET_INCLUDE, BUCKET_UNCERTAIN, CLASS_PRIVATE, CLASS_PUBLIC,
    CLASS_UNCERTAIN, DEFINED, HELD, CensusEntry, CensusFixtureError,
    CensusFixtureService, census_source, decide_census_entry,
    parse_classification, render_census_fixture_page)
from samverk.db import schema_version
from samverk.pull_mirrors import PullMirrorService
from samverk.repositories import RepositoryStore


def entry(name, private=False, note=""):
    return {"name": name, "private": private, "fork": False,
            "size_kb": 1, "updated": "2026-10-27", "branch": "main",
            "parent": "", "note": note}


def small_classification():
    return parse_classification(__import__("json").dumps({
        "include": [entry("alpha"), entry("beta", private=True),
                    entry("gamma")],
        "uncertain": [entry("maybe-one", note="fork; parent gone"),
                      entry("maybe-two")],
        "exclude": [entry("someone-elses-fork"), entry("other-fork")]}))


def full_classification():
    include = ([entry(f"pub-{i:02d}") for i in range(43)]
               + [entry(f"priv-{i:02d}", private=True) for i in range(11)])
    uncertain = [entry(f"unc-{i:02d}") for i in range(17)]
    exclude = [entry(f"exc-{i:02d}") for i in range(84)]
    return parse_classification(__import__("json").dumps(
        {"include": include, "uncertain": uncertain, "exclude": exclude}))


class CensusFixtureTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        root = Path(self._td.name)
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

    # -- pins ---------------------------------------------------
    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 139)
        self.assertEqual(db.MIGRATIONS[-1][0], 138)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 138)

    # -- parsing --------------------------------------------------
    def test_parse_real_shape(self):
        parsed = small_classification()
        self.assertEqual(len(parsed[BUCKET_INCLUDE]), 3)
        self.assertEqual(len(parsed[BUCKET_UNCERTAIN]), 2)
        self.assertEqual(len(parsed[BUCKET_EXCLUDE]), 2)
        self.assertTrue(parsed[BUCKET_INCLUDE][1].private)

    def test_parse_refuses_bad_shapes(self):
        for bad in ("not json", "[]", '{"include": {}}',
                    '{"include": [42]}', '{"include": [{"private": true}]}',
                    '{"include": [{"name": "x", "private": "yes"}]}'):
            with self.assertRaises(CensusFixtureError):
                parse_classification(bad)

    def test_parse_missing_buckets_are_empty(self):
        parsed = parse_classification('{"include": []}')
        self.assertEqual(parsed[BUCKET_UNCERTAIN], [])
        self.assertEqual(parsed[BUCKET_EXCLUDE], [])

    # -- pure decisions --------------------------------------------
    def test_decisions(self):
        public = decide_census_entry(BUCKET_INCLUDE, CensusEntry("a"))
        self.assertEqual((public.action, public.classification),
                         (ACTION_DEFINE, CLASS_PUBLIC))
        private = decide_census_entry(
            BUCKET_INCLUDE, CensusEntry("b", private=True))
        self.assertEqual((private.action, private.classification),
                         (ACTION_DEFINE, CLASS_PRIVATE))
        held = decide_census_entry(BUCKET_UNCERTAIN, CensusEntry("c"))
        self.assertEqual((held.action, held.classification),
                         (ACTION_HOLD, CLASS_UNCERTAIN))
        skipped = decide_census_entry(BUCKET_EXCLUDE, CensusEntry("d"))
        self.assertEqual(skipped.action, ACTION_SKIP)

    # -- import ------------------------------------------------------
    def test_import_defines_include_as_pending_mirrors(self):
        report = self.census.import_classification(
            self.owner.id, "volmarr", small_classification(),
            github_owner="hrabanazviking")
        self.assertEqual((report.defined, report.held,
                          report.skipped_excluded), (3, 2, 2))
        self.assertEqual(report.refused, [])
        mirror = self.pull.pull_mirror_for("volmarr", "alpha")
        self.assertIsNotNone(mirror)
        self.assertFalse(mirror.ready)  # a definition, not a sync
        self.assertEqual(mirror.source,
                         "https://github.com/hrabanazviking/alpha.git")
        beta = self.repos.get_repository("volmarr", "beta")
        self.assertEqual(beta.visibility, "private")
        alpha = self.repos.get_repository("volmarr", "alpha")
        self.assertEqual(alpha.visibility, "public")

    def test_uncertain_are_held_never_mirrored(self):
        self.census.import_classification(
            self.owner.id, "volmarr", small_classification(),
            github_owner="hrabanazviking")
        for name in ("maybe-one", "maybe-two"):
            self.assertIsNone(self.repos.get_repository("volmarr", name))
            self.assertIsNone(self.pull.pull_mirror_for("volmarr", name))
            record = self.census.record_for("volmarr", name)
            self.assertEqual(record.state, HELD)
            self.assertIsNone(record.repo_id)
        held = self.census.held_entries()
        self.assertEqual([r.name for r in held], ["maybe-one", "maybe-two"])
        self.assertEqual(held[0].note, "fork; parent gone")

    def test_excluded_leave_no_trace_but_the_count(self):
        report = self.census.import_classification(
            self.owner.id, "volmarr", small_classification(),
            github_owner="hrabanazviking")
        self.assertEqual(report.skipped_excluded, 2)
        self.assertIsNone(
            self.census.record_for("volmarr", "someone-elses-fork"))
        self.assertIsNone(
            self.repos.get_repository("volmarr", "someone-elses-fork"))

    def test_full_fixture_counts(self):
        report = self.census.import_classification(
            self.owner.id, "volmarr", full_classification(),
            github_owner="hrabanazviking")
        self.assertEqual((report.defined, report.held,
                          report.skipped_excluded), (54, 17, 84))
        self.assertEqual(report.refused, [])
        self.assertEqual(self.census.summary(), {DEFINED: 54, HELD: 17})

    def test_reimport_is_idempotent(self):
        first = self.census.import_classification(
            self.owner.id, "volmarr", small_classification(),
            github_owner="hrabanazviking")
        second = self.census.import_classification(
            self.owner.id, "volmarr", small_classification(),
            github_owner="hrabanazviking")
        self.assertEqual((first.defined, first.held), (3, 2))
        self.assertEqual((second.defined, second.held), (0, 0))
        self.assertEqual((second.already_defined, second.already_held), (3, 2))
        self.assertEqual(len(self.census.entries()), 5)

    def test_conflicting_classification_is_refused(self):
        parsed = parse_classification(__import__("json").dumps({
            "include": [entry("clash")], "uncertain": [entry("clash")],
            "exclude": []}))
        report = self.census.import_classification(
            self.owner.id, "volmarr", parsed, github_owner="hrabanazviking")
        self.assertEqual(report.defined, 1)
        self.assertEqual(len(report.refused), 1)
        self.assertEqual(report.refused[0][0], "clash")

    # -- the owner's word ---------------------------------------------
    def test_release_held_defines_exactly_one(self):
        self.census.import_classification(
            self.owner.id, "volmarr", small_classification(),
            github_owner="hrabanazviking")
        released = self.census.release_held(
            self.owner.id, "volmarr", "maybe-one",
            github_owner="hrabanazviking")
        self.assertEqual(released.state, DEFINED)
        self.assertIsNotNone(released.repo_id)
        mirror = self.pull.pull_mirror_for("volmarr", "maybe-one")
        self.assertIsNotNone(mirror)
        self.assertFalse(mirror.ready)
        repo = self.repos.get_repository("volmarr", "maybe-one")
        self.assertEqual(repo.visibility, "private")
        self.assertEqual([r.name for r in self.census.held_entries()],
                         ["maybe-two"])

    def test_release_refuses_defined_and_unknown(self):
        self.census.import_classification(
            self.owner.id, "volmarr", small_classification(),
            github_owner="hrabanazviking")
        with self.assertRaises(CensusFixtureError):
            self.census.release_held(self.owner.id, "volmarr", "alpha",
                                     github_owner="hrabanazviking")
        with self.assertRaises(CensusFixtureError):
            self.census.release_held(self.owner.id, "volmarr", "nope",
                                     github_owner="hrabanazviking")

    # -- source law ------------------------------------------------------
    def test_source_carries_no_credential(self):
        self.assertEqual(census_source("hrabanazviking", "alpha"),
                         "https://github.com/hrabanazviking/alpha.git")
        for bad_owner in ("user:secret@evil", "a/b", "", "a b"):
            with self.assertRaises(CensusFixtureError):
                census_source(bad_owner, "alpha")
        with self.assertRaises(CensusFixtureError):
            census_source("owner", "x@y")

    # -- page --------------------------------------------------------------
    def test_page_states_states_and_escapes(self):
        self.census.import_classification(
            self.owner.id, "volmarr", small_classification(),
            github_owner="hrabanazviking")
        page = render_census_fixture_page(self.census.entries())
        self.assertIn("3 mirror definitions; 2 held", page)
        self.assertIn("maybe-one", page)
        evil = parse_classification(__import__("json").dumps({
            "include": [], "exclude": [],
            "uncertain": [entry("esc", note="<script>x</script>")]}))
        self.census.import_classification(
            self.owner.id, "volmarr", evil, github_owner="hrabanazviking")
        page = render_census_fixture_page(self.census.entries())
        self.assertNotIn("<script>x</script>", page)
        self.assertIn("&lt;script&gt;", page)


if __name__ == "__main__":
    unittest.main()
