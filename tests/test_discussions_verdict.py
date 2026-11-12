"""S-282 acceptance battery: Discussions verdict.

Acceptance (roadmap S-282): Discussions verdict
-- research file 30 concludes build/defer/refuse
for a village-scale forge, with reasons recorded.

The verdict here is BUILD the core: categories
and threads, answer marking and conversion are
verdicted in (S-283..S-285), polls and rich
badges are deferred (S-286 takes the verdicted-
out road). The centre is the audit: the build
queue is checked against the live instance -- no
table, column or audit event carries a
discussion before its building slice -- and the
battery plants a discussion-shaped table to
prove the audit would catch one.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.db import schema_version
from samverk.discussions_verdict import (
    BUILD_CONDITIONS, FEATURES, MUST_NOT_BREAK, REASONS,
    VERDICT, DiscussionsVerdictAudit,
    DiscussionsVerdictError, audit_discussions_verdict,
    attempt_discussion_action, decide_discussion_request,
    get_feature, get_invariant, get_reason,
    render_discussions_verdict_page)

ROOT = Path(__file__).resolve().parent.parent

EXPECTED_REASON_IDS = (
    "discussions-are-not-issues",
    "the-machinery-already-stands",
    "village-need-is-knowledge-exchange",
    "risks-are-named-and-bounded",
    "scope-can-be-cut-honestly")
EXPECTED_FEATURE_IDS = (
    "categories-and-threads", "answer-marking",
    "issue-discussion-conversion", "polls",
    "rich-badges")
EXPECTED_JUDGEMENTS = {
    "categories-and-threads": "build",
    "answer-marking": "build",
    "issue-discussion-conversion": "build",
    "polls": "deferred",
    "rich-badges": "deferred"}
EXPECTED_INVARIANT_IDS = (
    "permissions-follow-the-repository",
    "private-is-missing-everywhere",
    "answer-mark-is-an-event",
    "conversion-is-exactly-once-and-never-silent",
    "one-timeline-holds-the-conversation",
    "categories-carry-explicit-states-and-powers",
    "subscriptions-share-notifications-with-own-controls",
    "composer-and-search-stay-accessible")


class DiscussionsVerdictTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.conn = db.init_db(
            Path(self._td.name) / "samverk.db")
        self.addCleanup(self.conn.close)

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(DiscussionsVerdictError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    # pins
    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 121)
        self.assertEqual(db.MIGRATIONS[-1][0], 121)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 134)
        families = {}
        for event in taxonomy.AUDIT_EVENTS:
            families[event.split(".")[0]] = (
                families.get(event.split(".")[0], 0) + 1)
        self.assertEqual(
            families, {"auth": 33, "repo": 88, "admin": 13})
        self.assertFalse(any(
            "discussion" in e for e in taxonomy.AUDIT_EVENTS))

    # the verdict and its reasons
    def test_verdict_is_build(self):
        self.assertEqual(VERDICT, "build")

    def test_reason_ids_exact_and_each_reason_substantive(self):
        self.assertEqual(
            tuple(r.id for r in REASONS), EXPECTED_REASON_IDS)
        for reason in REASONS:
            self.assertTrue(reason.title.strip(), reason.id)
            self.assertGreater(len(reason.detail), 200, reason.id)
            self.assertIs(get_reason(reason.id), reason)

    def test_get_reason_unknown_refused(self):
        self.assertEqual(
            self._reason(get_reason, "defer-everything"),
            "reason_unknown")
        self.assertEqual(
            self._reason(get_reason, None), "reason_unknown")

    # research 30's pieces, judged one by one
    def test_feature_ids_exact_and_judged(self):
        self.assertEqual(
            tuple(f.id for f in FEATURES), EXPECTED_FEATURE_IDS)
        for feature in FEATURES:
            self.assertIs(get_feature(feature.id), feature)
            self.assertEqual(
                feature.judgement,
                EXPECTED_JUDGEMENTS[feature.id], feature.id)
            self.assertTrue(feature.building_means.strip(), feature.id)
            self.assertTrue(feature.village_need.strip(), feature.id)
            self.assertTrue(feature.served_by.strip(), feature.id)
        self.assertEqual(
            self._reason(get_feature, "live-chat"),
            "feature_unknown")

    def test_core_is_in_and_only_polls_and_badges_defer(self):
        built = [f.id for f in FEATURES if f.judgement == "build"]
        deferred = [f.id for f in FEATURES
                    if f.judgement == "deferred"]
        self.assertEqual(built, [
            "categories-and-threads", "answer-marking",
            "issue-discussion-conversion"])
        self.assertEqual(deferred, ["polls", "rich-badges"])
        polls = get_feature("polls")
        self.assertIn("account scope", polls.village_need)

    def test_build_conditions_name_the_following_slices(self):
        self.assertEqual(len(BUILD_CONDITIONS), 4)
        joined = " ".join(BUILD_CONDITIONS)
        for token in ("S-283", "S-284", "S-285", "S-286", "S-403"):
            self.assertIn(token, joined)

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

    # the pure per-feature answers
    def test_decide_discussion_request_pure(self):
        self.assertEqual(
            decide_discussion_request("categories-and-threads"),
            "discussions_build_queued")
        self.assertEqual(
            decide_discussion_request("answer-marking"),
            "discussions_build_queued")
        self.assertEqual(
            decide_discussion_request("issue-discussion-conversion"),
            "discussions_build_queued")
        self.assertEqual(
            decide_discussion_request("polls"),
            "discussions_deferred")
        self.assertEqual(
            decide_discussion_request("rich-badges"),
            "discussions_deferred")
        self.assertEqual(
            decide_discussion_request("live-chat"),
            "discussions_feature_unknown")
        self.assertEqual(
            decide_discussion_request(""),
            "discussions_request_invalid")
        self.assertEqual(
            decide_discussion_request("   "),
            "discussions_request_invalid")
        self.assertEqual(
            decide_discussion_request(None),
            "discussions_request_invalid")

    def test_every_discussion_action_answered(self):
        self.assertEqual(
            self._reason(attempt_discussion_action,
                         "categories-and-threads"),
            "discussions_build_queued")
        self.assertEqual(
            self._reason(attempt_discussion_action, "polls"),
            "discussions_deferred")
        self.assertEqual(
            self._reason(attempt_discussion_action, "live-chat"),
            "discussions_feature_unknown")
        self.assertEqual(
            self._reason(attempt_discussion_action, ""),
            "discussions_request_invalid")

    def test_refusal_writes_nothing(self):
        before = {
            t: self.conn.execute(
                f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
            for t in ("users", "audit_log")}
        self._reason(attempt_discussion_action, "polls")
        audit_discussions_verdict(self.conn)
        render_discussions_verdict_page()
        after = {
            t: self.conn.execute(
                f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
            for t in ("users", "audit_log")}
        self.assertEqual(before, after)

    # the audit: queue proven, planting caught
    def test_audit_is_build_queued_cleanly(self):
        audit = audit_discussions_verdict(self.conn)
        self.assertTrue(audit.build_queued_cleanly, audit)
        self.assertEqual(audit.verdict, "build")
        self.assertEqual(audit.offending_tables, ())
        self.assertEqual(audit.offending_columns, ())
        self.assertEqual(audit.offending_events, ())
        self.assertEqual(audit.events_scanned, 134)
        self.assertGreater(audit.tables_scanned, 50)
        self.assertGreater(audit.columns_scanned, 400)

    def test_audit_catches_a_planted_discussion_table(self):
        with self.conn:
            self.conn.execute(
                "CREATE TABLE discussions (id INTEGER,"
                " discussion_title TEXT)")
        audit = audit_discussions_verdict(self.conn)
        self.assertFalse(audit.build_queued_cleanly)
        self.assertIn("discussions", audit.offending_tables)
        self.assertIn(
            "discussions.discussion_title",
            audit.offending_columns)

    # the page
    def test_page_says_build_plainly(self):
        page = render_discussions_verdict_page(
            audit_discussions_verdict(self.conn))
        self.assertIn("Discussions -- build (S-282)", page)
        self.assertIn("build", page)
        self.assertIn("deferred", page)
        self.assertIn("Checked, not just claimed", page)
        for reason in REASONS:
            self.assertIn(reason.title, page)
        for feature in FEATURES:
            self.assertIn(feature.title, page)
        for invariant in MUST_NOT_BREAK:
            self.assertIn(invariant.title, page)
        self.assertIn("S-403", page)
        self.assertIn("docs/DISCUSSIONS_VERDICT.md", page)

    def test_page_without_audit_states_no_check(self):
        page = render_discussions_verdict_page()
        self.assertNotIn("Checked, not just claimed", page)
        self.assertNotIn("not clean", page)

    def test_page_reports_a_planted_defect_honestly(self):
        with self.conn:
            self.conn.execute(
                "CREATE TABLE discussions (id INTEGER)")
        page = render_discussions_verdict_page(
            audit_discussions_verdict(self.conn))
        self.assertIn("not clean", page)
        self.assertIn("discussions", page)
        self.assertIn("defect against S-282", page)

    def test_page_escapes_every_value(self):
        audit = DiscussionsVerdictAudit(
            verdict="build",
            tables_scanned=1, columns_scanned=1,
            events_scanned=1,
            offending_tables=("<b>discussions</b>",),
            offending_columns=(), offending_events=())
        page = render_discussions_verdict_page(audit)
        self.assertNotIn("<b>discussions</b>", page)
        self.assertIn("&lt;b&gt;discussions", page)

    # the docs say it too
    def test_docs_record_the_verdict_and_invariants(self):
        doc = (ROOT / "docs" / "DISCUSSIONS_VERDICT.md").read_text(
            encoding="utf-8")
        self.assertIn("build", doc.lower())
        self.assertIn("deferred", doc.lower())
        self.assertIn("S-282", doc)
        self.assertIn("research file 30", doc)
        self.assertIn("S-283", doc)
        self.assertIn("S-286", doc)
        for invariant in MUST_NOT_BREAK:
            self.assertIn(invariant.id, doc, invariant.id)
        for reason in REASONS:
            self.assertIn(reason.id, doc, reason.id)
        for feature in FEATURES:
            self.assertIn(feature.id, doc, feature.id)


if __name__ == "__main__":
    unittest.main()
