"""S-298 acceptance battery: advisory data.

Acceptance (roadmap S-298): Advisory data -- a
bundled, dated snapshot of public vulnerability
data; its age is displayed wherever alerts are
shown.

The snapshot lives in samverk/advisory_snapshot.json
and the seam in samverk/advisory_data.py, on banked
base 617b5b6 (296/416; S-297 banks ahead of this
slice in roadmap order). parse_snapshot is a pure
validator: missing / malformed / future snapshot
dates, unknown formats, malformed or empty advisory
lists, unknown ecosystems or severities and
duplicate ids are each refused by name, and a fixed
version is a string or honestly None (*fix unknown*).
AdvisoryStore loads the bundled snapshot offline --
no migration of its own (schema 122 stands on the banked line), no database, no
network -- and answers per-package lookups under
each ecosystem's own name equivalence. Age is whole
days from the snapshot date; past thirty days is
*stale*, said on every render surface; no usable
snapshot is *age unknown*, never *fresh*. No new
taxonomy event -- 134 stand (33 auth / 88 repo /
13 admin); the battery proves the audit log does
not move.

Counted with: python3 -m unittest tests.test_advisory_data
"""
from __future__ import annotations
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.advisory_data import (
    ADVISORY_DUPLICATE, ADVISORY_INVALID, ADVISORY_NOT_FOUND,
    ECOSYSTEMS, FRESHNESS_CURRENT, FRESHNESS_STALE,
    FRESHNESS_UNKNOWN, SEVERITIES, SNAPSHOT_DATE_IN_FUTURE,
    SNAPSHOT_DATE_INVALID, SNAPSHOT_DATE_MISSING, SNAPSHOT_EMPTY,
    SNAPSHOT_FORMAT_UNKNOWN, SNAPSHOT_MALFORMED,
    SNAPSHOT_NOT_FOUND, STALE_AFTER_DAYS, AdvisoryError,
    AdvisoryStore, age_words, freshness_for, normalise_package,
    parse_snapshot, render_advisories_page, render_advisory_banner,
    render_package_page)
from samverk.audit import AuditLog
from samverk.db import schema_version

TODAY = date(2026, 11, 12)


def snap_dict(**over):
    data = {
        "snapshot_format": 1,
        "source": "test source",
        "snapshot_date": "2026-11-10",
        "advisories": [{
            "id": "CVE-0000-0001", "ecosystem": "python",
            "package": "Example_Pkg", "severity": "moderate",
            "affected": "<1.0", "fixed_version": "1.0",
            "summary": "a test advisory",
            "published": "2026-01-01", "references": [],
        }],
    }
    data.update(over)
    return data


class BundledSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.store = AdvisoryStore.bundled(now=TODAY)

    def test_bundled_snapshot_loads_and_is_dated(self):
        snap = self.store.snapshot
        self.assertEqual(snap.snapshot_date, TODAY)
        self.assertTrue(snap.source)
        self.assertGreaterEqual(len(snap.advisories), 8)

    def test_bundled_covers_all_four_ecosystems(self):
        counts = self.store.counts()
        self.assertEqual(set(counts["by_ecosystem"]), ECOSYSTEMS)
        self.assertEqual(counts["total"],
                         len(self.store.all_advisories()))

    def test_bundled_rows_are_well_formed(self):
        for adv in self.store.all_advisories():
            self.assertIn(adv.ecosystem, ECOSYSTEMS)
            self.assertIn(adv.severity, SEVERITIES)
            self.assertTrue(adv.affected)
            self.assertTrue(adv.summary)

    def test_fix_unknown_is_honest_none(self):
        unknown = [a for a in self.store.all_advisories()
                   if a.fixed_version is None]
        self.assertTrue(unknown)
        for adv in unknown:
            self.assertEqual(adv.fixed_words, "fix unknown")
            self.assertIsNone(adv.to_dict()["fixed_version"])

    def test_get_and_missing(self):
        adv = self.store.all_advisories()[0]
        self.assertEqual(self.store.get(adv.id).id, adv.id)
        with self.assertRaises(AdvisoryError) as ctx:
            self.store.get("CVE-9999-9999")
        self.assertEqual(ctx.exception.reason, ADVISORY_NOT_FOUND)


class AgeLawTests(unittest.TestCase):
    def setUp(self):
        self.store = AdvisoryStore.bundled(now=TODAY)

    def test_age_zero_on_snapshot_day(self):
        info = self.store.snapshot_info(TODAY)
        self.assertEqual(info.age_days, 0)
        self.assertEqual(info.freshness, FRESHNESS_CURRENT)
        self.assertIn("taken today", info.age_words)

    def test_age_counts_whole_days(self):
        info = self.store.snapshot_info(date(2026, 11, 15))
        self.assertEqual(info.age_days, 3)
        self.assertIn("3 days old", info.age_words)
        one = self.store.snapshot_info(date(2026, 11, 13))
        self.assertIn("1 day old", one.age_words)

    def test_stale_boundary_is_honest(self):
        edge = self.store.snapshot_info(
            TODAY + timedelta(days=STALE_AFTER_DAYS))
        self.assertEqual(edge.freshness, FRESHNESS_CURRENT)
        past = self.store.snapshot_info(
            TODAY + timedelta(days=STALE_AFTER_DAYS + 1))
        self.assertEqual(past.freshness, FRESHNESS_STALE)
        self.assertIn("stale", past.age_words)

    def test_no_snapshot_age_is_unknown_never_fresh(self):
        self.assertEqual(freshness_for(None, TODAY),
                         FRESHNESS_UNKNOWN)
        self.assertEqual(age_words(None, TODAY),
                         "advisory snapshot age unknown")

    def test_epoch_now_accepted(self):
        info = self.store.snapshot_info(1794528000)  # 2026-11-13 UTC
        self.assertEqual(info.age_days, 1)


class ParseLawTests(unittest.TestCase):
    def test_roundtrip(self):
        snap = parse_snapshot(json.dumps(snap_dict()), now=TODAY)
        self.assertEqual(snap.snapshot_date, date(2026, 11, 10))
        self.assertEqual(snap.advisories[0].package, "Example_Pkg")
        self.assertEqual(snap.age_days(TODAY), 2)

    def test_missing_date_refused(self):
        data = snap_dict()
        del data["snapshot_date"]
        with self.assertRaises(AdvisoryError) as ctx:
            parse_snapshot(data, now=TODAY)
        self.assertEqual(ctx.exception.reason, SNAPSHOT_DATE_MISSING)

    def test_malformed_date_refused(self):
        with self.assertRaises(AdvisoryError) as ctx:
            parse_snapshot(snap_dict(snapshot_date="12 Nov 2026"),
                           now=TODAY)
        self.assertEqual(ctx.exception.reason, SNAPSHOT_DATE_INVALID)

    def test_future_date_refused_never_fresh(self):
        with self.assertRaises(AdvisoryError) as ctx:
            parse_snapshot(snap_dict(snapshot_date="2026-12-01"),
                           now=TODAY)
        self.assertEqual(ctx.exception.reason,
                         SNAPSHOT_DATE_IN_FUTURE)

    def test_malformed_json_and_format_refused(self):
        with self.assertRaises(AdvisoryError) as ctx:
            parse_snapshot("{not json", now=TODAY)
        self.assertEqual(ctx.exception.reason, SNAPSHOT_MALFORMED)
        with self.assertRaises(AdvisoryError) as ctx:
            parse_snapshot(snap_dict(snapshot_format=99), now=TODAY)
        self.assertEqual(ctx.exception.reason,
                         SNAPSHOT_FORMAT_UNKNOWN)

    def test_empty_snapshot_refused(self):
        with self.assertRaises(AdvisoryError) as ctx:
            parse_snapshot(snap_dict(advisories=[]), now=TODAY)
        self.assertEqual(ctx.exception.reason, SNAPSHOT_EMPTY)

    def test_duplicate_ids_refused(self):
        row = snap_dict()["advisories"][0]
        with self.assertRaises(AdvisoryError) as ctx:
            parse_snapshot(snap_dict(advisories=[row, dict(row)]),
                           now=TODAY)
        self.assertEqual(ctx.exception.reason, ADVISORY_DUPLICATE)

    def test_unknown_ecosystem_and_severity_refused(self):
        row = dict(snap_dict()["advisories"][0], ecosystem="maven")
        with self.assertRaises(AdvisoryError) as ctx:
            parse_snapshot(snap_dict(advisories=[row]), now=TODAY)
        self.assertEqual(ctx.exception.reason, ADVISORY_INVALID)
        row = dict(snap_dict()["advisories"][0], severity="severe")
        with self.assertRaises(AdvisoryError) as ctx:
            parse_snapshot(snap_dict(advisories=[row]), now=TODAY)
        self.assertEqual(ctx.exception.reason, ADVISORY_INVALID)

    def test_missing_file_named(self):
        with self.assertRaises(AdvisoryError) as ctx:
            AdvisoryStore.from_path("/nonexistent/snap.json",
                                    now=TODAY)
        self.assertEqual(ctx.exception.reason, SNAPSHOT_NOT_FOUND)


class LookupTests(unittest.TestCase):
    def setUp(self):
        self.store = AdvisoryStore.bundled(now=TODAY)

    def test_python_names_follow_pep503(self):
        self.assertEqual(normalise_package("python", "Example_Pkg"),
                         "example-pkg")
        found = self.store.for_package("python", "pyyaml")
        self.assertTrue(found)
        self.assertTrue(all(a.package == "PyYAML" for a in found))
        self.assertEqual(self.store.for_package("python", "PyYAML"),
                         found)

    def test_case_folded_and_exact_ecosystems(self):
        self.assertTrue(self.store.for_package("npm", "LODASH"))
        self.assertTrue(self.store.for_package(
            "go", "golang.org/x/text"))
        self.assertEqual(self.store.for_package(
            "go", "Golang.org/x/text"), ())

    def test_unknown_ecosystem_lookup_refused(self):
        with self.assertRaises(AdvisoryError) as ctx:
            self.store.for_package("maven", "log4j")
        self.assertEqual(ctx.exception.reason, ADVISORY_INVALID)

    def test_absent_package_is_empty_not_error(self):
        self.assertEqual(
            self.store.for_package("python", "no-such-package"), ())


class RenderLawTests(unittest.TestCase):
    def setUp(self):
        self.store = AdvisoryStore.bundled(now=TODAY)

    def test_banner_states_date_and_age(self):
        banner = render_advisory_banner(
            self.store.snapshot_info(date(2026, 11, 15)))
        self.assertIn("2026-11-12", banner)
        self.assertIn("3 days old", banner)
        self.assertIn('data-freshness="current"', banner)

    def test_banner_shows_stale_honestly(self):
        banner = render_advisory_banner(
            self.store.snapshot_info(date(2027, 6, 1)))
        self.assertIn("stale", banner)
        self.assertIn('data-freshness="stale"', banner)

    def test_pages_carry_the_age(self):
        page = render_advisories_page(self.store, date(2026, 12, 1))
        self.assertIn("2026-11-12", page)
        self.assertIn("days old", page)
        pkg = render_package_page(self.store, "python", "PyYAML",
                                  date(2026, 12, 1))
        self.assertIn("2026-11-12", pkg)
        self.assertIn("CVE-2020-14343", pkg)
        empty = render_package_page(self.store, "python",
                                    "no-such-package", TODAY)
        self.assertIn("2026-11-12", empty)
        self.assertIn("No advisories", empty)

    def test_render_escapes_snapshot_fields(self):
        evil = snap_dict(source="<script>alert(1)</script>")
        store = AdvisoryStore.from_text(evil, now=TODAY)
        page = render_advisories_page(store, TODAY)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)


class InvariantTests(unittest.TestCase):
    def test_no_migration_schema_122_stands(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.init_db(Path(td) / "t.db")
            try:
                self.assertEqual(schema_version(conn), 127)
            finally:
                conn.close()

    def test_no_new_taxonomy_event(self):
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 135)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 89)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)

    def test_loading_writes_nothing_and_audits_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.init_db(Path(td) / "t.db")
            try:
                accounts = AccountStore(conn)
                acct = accounts.register("aud", "password-12345")
                log = AuditLog(conn)
                before = conn.execute(
                    "SELECT COUNT(*) FROM audit_log").fetchone()[0]
                store = AdvisoryStore.bundled(now=TODAY)
                store.for_package("python", "PyYAML")
                render_advisories_page(store, TODAY)
                after = conn.execute(
                    "SELECT COUNT(*) FROM audit_log").fetchone()[0]
                self.assertEqual(before, after)
                self.assertIsNotNone(acct)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
