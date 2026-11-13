"""S-286 acceptance battery: Discussion polls --
the published refusal.

Acceptance (roadmap S-286): Polls (if in) --
discussion polls with honest counts and close
dates; otherwise recorded as refused with
reasons. S-282 verdicted polls DEFERRED, so the
refusal is what stands here.

The centre is samverk/discussion_polls.py: a
poll is named whole on its discussion thread,
the four operations are judged for real first --
the thread through S-283's own door, the rungs
through S-190's engine on the owning repository
(create / vote / results at read, close at the
thread's author or the maintain rung) -- private
is indistinguishable from missing even in the
refusal, and only a permitted, well-formed
request meets S-282's deferral, delegated to the
verdict's own decision so the slices cannot
drift. The seam invariants are S-282's own
tuple, imported not forked. The audit proves the
refusal against the live instance and the
battery plants a poll-shaped table to prove the
audit would catch one. The refusal writes and
audits nothing, proven by row and audit counts.

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
from samverk.discussion_polls import (
    DEFERRAL_REASONS, OPERATIONS, SEAM_INVARIANTS,
    DiscussionPolls, DiscussionPollsAudit, PollError, PollRef,
    audit_discussion_polls, decide_close, decide_create,
    decide_results, decide_vote, get_operation,
    render_discussion_polls_page, validate_choice,
    validate_close_date, validate_options, validate_question)
from samverk.discussions import DiscussionStore
from samverk.discussions_verdict import (
    MUST_NOT_BREAK as VERDICT_INVARIANTS, get_feature)
from samverk.repositories import RepositoryStore

ROOT = Path(__file__).resolve().parent.parent
PW = "correct horse battery"
T0 = 1_700_000_000
FUTURE = T0 + 7 * 24 * 3600


class Clock:
    def __init__(self, now=T0):
        self.now = now
    def __call__(self):
        return self.now


EXPECTED_OPERATIONS = (
    ("create", "read"), ("vote", "read"),
    ("results", "read"), ("close", "maintain"))


class DiscussionPollsTests(unittest.TestCase):
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
        self.reader = self.accounts.register("yrsa", PW)
        self.fellow = self.accounts.register("tess", PW)
        self.stranger = self.accounts.register("mallory", PW)
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts,
            audit=self.audit_log, time_fn=self.clock)
        self.board = DiscussionStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit_log, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        self.cat = self.board.create_category(
            self.owner, "volmarr", "pub", "Questions", "question")
        self.thread = self.board.create_thread(
            self.reader, "volmarr", "pub", self.cat.id,
            "How do tides work?", "Asking for a friend.")
        self.priv_cat = self.board.create_category(
            self.owner, "volmarr", "priv", "Questions", "question")
        self.priv_thread = self.board.create_thread(
            self.owner, "volmarr", "priv", self.priv_cat.id,
            "A private question", "For the house only.")
        self.polls = DiscussionPolls(
            self.conn, self.repos, self.accounts, self.board,
            audit=self.audit_log, time_fn=self.clock)

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(PollError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    def _create(self, actor, repo="pub", number=None, **kw):
        args = dict(question="Tea or mead?",
                    options=["Tea", "Mead"], closes_at=FUTURE)
        args.update(kw)
        return self.polls.create_poll(
            actor, "volmarr", repo,
            self.thread.number if number is None else number, **args)

    # pins
    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 127)
        self.assertEqual(db.MIGRATIONS[-1][0], 127)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 135)
        families = {}
        for event in taxonomy.AUDIT_EVENTS:
            families[event.split(".")[0]] = (
                families.get(event.split(".")[0], 0) + 1)
        self.assertEqual(
            families, {"auth": 33, "repo": 89, "admin": 13})
        self.assertFalse(any(
            "poll" in e for e in taxonomy.AUDIT_EVENTS))

    # the verdict this refusal stands on
    def test_polls_feature_is_deferred_with_reasons(self):
        feature = get_feature("polls")
        self.assertEqual(feature.judgement, "deferred")
        self.assertIs(DEFERRAL_REASONS, feature)
        self.assertIn("account scope", feature.village_need)
        self.assertIn("fraud-resistant", feature.village_need)

    def test_seam_invariants_are_the_verdicts_own(self):
        self.assertIs(SEAM_INVARIANTS, VERDICT_INVARIANTS)
        self.assertEqual(len(SEAM_INVARIANTS), 8)

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
            self._reason(get_operation, "recount"),
            "poll_action_invalid")

    def test_poll_ref_names_its_thread(self):
        ref = PollRef(
            owner="Volmarr", repo="Anvil", thread_number=7,
            question="Tea or mead?", options=("Tea", "Mead"),
            closes_at=FUTURE)
        self.assertEqual(ref.thread_ref, "Volmarr/Anvil#7")
        self.assertEqual(ref.coordinate, "poll:Volmarr/Anvil#7:2 options")

    # shape doors: judged first, storing nothing
    def test_validate_question(self):
        self.assertEqual(validate_question("  Tea or mead? "), "Tea or mead?")
        for bad in ("", "   ", None, 7, "x" * 201, "bad\x01question"):
            self.assertEqual(
                self._reason(validate_question, bad),
                "poll_question_invalid", repr(bad))

    def test_validate_options(self):
        self.assertEqual(
            validate_options([" Tea ", "Mead"]), ("Tea", "Mead"))
        self.assertEqual(
            validate_options(("A", "B", "C")), ("A", "B", "C"))
        for bad in (None, "Tea", [], ["Only"], ["A"] * 7,
                    ["Tea", "tea"], ["Tea", " "], ["Tea", None],
                    ["Tea", "x" * 81]):
            self.assertEqual(
                self._reason(validate_options, bad),
                "poll_options_invalid", repr(bad))

    def test_validate_close_date(self):
        self.assertEqual(validate_close_date(FUTURE, T0), FUTURE)
        for bad in (T0, T0 - 1, None, True, "tomorrow", 1.5):
            self.assertEqual(
                self._reason(validate_close_date, bad, T0),
                "poll_close_invalid", repr(bad))

    def test_validate_choice(self):
        self.assertEqual(validate_choice(0), 0)
        self.assertEqual(validate_choice(3), 3)
        for bad in (-1, None, True, "0", 0.5):
            self.assertEqual(
                self._reason(validate_choice, bad),
                "poll_choice_invalid", repr(bad))

    # the pure decision matrix
    def test_decide_create_vote_results_matrix(self):
        for decide in (decide_create, decide_vote, decide_results):
            self.assertEqual(
                decide(False, "admin"), "discussion_not_found")
            self.assertEqual(
                decide(True, None), "discussion_not_found")
            self.assertEqual(
                decide(True, "read"), "discussions_deferred")
            self.assertEqual(
                decide(True, "admin"), "discussions_deferred")

    def test_decide_close_matrix(self):
        self.assertEqual(
            decide_close(False, "admin", is_author=True),
            "discussion_not_found")
        self.assertEqual(
            decide_close(True, None, is_author=False),
            "discussion_not_found")
        self.assertEqual(
            decide_close(True, "read", is_author=False),
            "permission_denied")
        self.assertEqual(
            decide_close(True, "write", is_author=False),
            "permission_denied")
        self.assertEqual(
            decide_close(True, "read", is_author=True),
            "discussions_deferred")
        self.assertEqual(
            decide_close(True, "maintain", is_author=False),
            "discussions_deferred")
        self.assertEqual(
            decide_close(True, "admin", is_author=False),
            "discussions_deferred")

    # create through the face: permissions before verdict
    def test_create_permitted_reader_meets_the_deferral(self):
        self.assertEqual(
            self._reason(self._create, self.reader),
            "discussions_deferred")
        self.assertEqual(
            self._reason(self._create, self.owner),
            "discussions_deferred")
        # Any reader of the public thread passes the door.
        self.assertEqual(
            self._reason(self._create, self.stranger),
            "discussions_deferred")
        # The owner of the private thread meets it too.
        self.assertEqual(
            self._reason(
                self._create, self.owner, repo="priv",
                number=self.priv_thread.number),
            "discussions_deferred")

    def test_create_private_is_indistinguishable_from_missing(self):
        stranger_private = self._reason(
            self._create, self.stranger, repo="priv",
            number=self.priv_thread.number)
        stranger_missing = self._reason(
            self._create, self.stranger, repo="pub", number=999)
        owner_missing_repo = self._reason(
            self._create, self.owner, repo="ghost",
            number=self.thread.number)
        self.assertEqual(stranger_private, "discussion_not_found")
        self.assertEqual(stranger_private, stranger_missing)
        self.assertEqual(stranger_missing, owner_missing_repo)
        anon_private = self._reason(
            self.polls.results, None, "volmarr", "priv",
            self.priv_thread.number)
        self.assertEqual(anon_private, "discussion_not_found")

    def test_create_anonymous_and_shape_doors(self):
        self.assertEqual(
            self._reason(self._create, None), "authentication_required")
        # Shape is judged before any thread is read: even a
        # stranger to a private thread meets the shape refusal.
        self.assertEqual(
            self._reason(
                self._create, self.stranger, repo="priv",
                number=self.priv_thread.number, question=""),
            "poll_question_invalid")
        self.assertEqual(
            self._reason(self._create, self.owner, options=["Only"]),
            "poll_options_invalid")
        self.assertEqual(
            self._reason(self._create, self.owner, closes_at=T0),
            "poll_close_invalid")
        # A shapeless thread reference answers at the board's door.
        self.assertEqual(
            self._reason(self._create, self.owner, number="one"),
            "discussion_not_found")
        self.assertEqual(
            self._reason(self._create, self.owner, number=0),
            "discussion_not_found")

    # vote and results
    def test_vote_and_results_meet_the_deferral(self):
        self.assertEqual(
            self._reason(
                self.polls.vote, self.fellow, "volmarr", "pub",
                self.thread.number, 1),
            "discussions_deferred")
        self.assertEqual(
            self._reason(
                self.polls.vote, None, "volmarr", "pub",
                self.thread.number, 0),
            "authentication_required")
        self.assertEqual(
            self._reason(
                self.polls.vote, self.fellow, "volmarr", "pub",
                self.thread.number, -1),
            "poll_choice_invalid")
        self.assertEqual(
            self._reason(
                self.polls.results, self.stranger, "volmarr", "pub",
                self.thread.number),
            "discussions_deferred")
        # Anonymous reads a public thread to the same verdict.
        self.assertEqual(
            self._reason(
                self.polls.results, None, "volmarr", "pub",
                self.thread.number),
            "discussions_deferred")
        self.assertEqual(
            self._reason(
                self.polls.vote, self.stranger, "volmarr", "priv",
                self.priv_thread.number, 0),
            "discussion_not_found")

    # close: the curation hands
    def test_close_curation_door(self):
        # The thread's author may close: meets the deferral.
        self.assertEqual(
            self._reason(
                self.polls.close_poll, self.reader, "volmarr", "pub",
                self.thread.number),
            "discussions_deferred")
        # A maintainer/admin (the owner) may close: the deferral.
        self.assertEqual(
            self._reason(
                self.polls.close_poll, self.owner, "volmarr", "pub",
                self.thread.number),
            "discussions_deferred")
        # A fellow reader holds neither hand: permission first.
        self.assertEqual(
            self._reason(
                self.polls.close_poll, self.fellow, "volmarr", "pub",
                self.thread.number),
            "permission_denied")
        self.assertEqual(
            self._reason(
                self.polls.close_poll, None, "volmarr", "pub",
                self.thread.number),
            "authentication_required")
        # A stranger to the private thread: missing, not permission.
        self.assertEqual(
            self._reason(
                self.polls.close_poll, self.stranger, "volmarr", "priv",
                self.priv_thread.number),
            "discussion_not_found")

    # the refusal writes and audits nothing
    def test_refusal_writes_nothing(self):
        tables = ("users", "repositories", "audit_log",
                  "discussion_categories", "discussion_threads",
                  "discussion_replies", "discussion_events")
        before = {
            t: self.conn.execute(
                f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
            for t in tables}
        calls = (
            lambda: self._create(self.reader),
            lambda: self.polls.vote(
                self.fellow, "volmarr", "pub", self.thread.number, 0),
            lambda: self.polls.results(
                self.stranger, "volmarr", "pub", self.thread.number),
            lambda: self.polls.close_poll(
                self.owner, "volmarr", "pub", self.thread.number),
            lambda: self._create(self.stranger, repo="priv",
                                 number=self.priv_thread.number),
            lambda: self.polls.close_poll(
                self.fellow, "volmarr", "pub", self.thread.number))
        for call in calls:
            with self.assertRaises(PollError):
                call()
        audit_discussion_polls(self.conn)
        render_discussion_polls_page()
        after = {
            t: self.conn.execute(
                f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
            for t in tables}
        self.assertEqual(before, after)

    # the audit: refusal proven, planting caught
    def test_audit_is_refused_cleanly(self):
        audit = audit_discussion_polls(self.conn)
        self.assertTrue(audit.refused_cleanly, audit)
        self.assertEqual(audit.verdict_feature, "polls")
        self.assertEqual(audit.feature_judgement, "deferred")
        self.assertTrue(audit.verdict_audit_clean)
        self.assertEqual(audit.offending_tables, ())
        self.assertEqual(audit.offending_columns, ())
        self.assertEqual(audit.offending_events, ())
        self.assertEqual(audit.verdict_offending_tables, ())
        self.assertEqual(audit.events_scanned, 135)
        self.assertEqual(audit.operations_defined, 4)
        self.assertEqual(audit.seam_invariants, 8)
        self.assertGreater(audit.tables_scanned, 50)
        self.assertGreater(audit.columns_scanned, 400)

    def test_audit_catches_a_planted_poll_table(self):
        with self.conn:
            self.conn.execute(
                "CREATE TABLE discussion_polls (id INTEGER,"
                " poll_question TEXT)")
        audit = audit_discussion_polls(self.conn)
        self.assertFalse(audit.refused_cleanly)
        self.assertIn("discussion_polls", audit.offending_tables)
        self.assertIn(
            "discussion_polls.poll_question", audit.offending_columns)
        # S-282's verdict audit catches it too: a poll surface
        # is a discussion-shaped name beyond the sanctioned build.
        self.assertIn(
            "discussion_polls", audit.verdict_offending_tables)

    def test_audit_catches_a_planted_poll_column(self):
        with self.conn:
            self.conn.execute(
                "CREATE TABLE notes (id INTEGER, poll_id INTEGER)")
        audit = audit_discussion_polls(self.conn)
        self.assertFalse(audit.refused_cleanly)
        self.assertIn("notes.poll_id", audit.offending_columns)

    # the S-282 must-not-break invariants still hold
    def test_s282_invariants_still_hold(self):
        audit = audit_discussion_polls(self.conn)
        self.assertTrue(audit.verdict_audit_clean, audit)
        for invariant in SEAM_INVARIANTS:
            self.assertTrue(invariant.statement.strip(), invariant.id)
        joined = " ".join(i.id for i in SEAM_INVARIANTS)
        for token in ("permissions-follow-the-repository",
                      "private-is-missing-everywhere"):
            self.assertIn(token, joined)

    # the page: the published refusal, in words
    def test_page_says_no_polls_plainly(self):
        page = render_discussion_polls_page(
            audit_discussion_polls(self.conn))
        self.assertIn("Discussion polls -- no polls (S-286)", page)
        self.assertIn("no discussion polls", page)
        self.assertIn("A poll belongs to its thread", page)
        self.assertIn("Checked, not just claimed", page)
        self.assertIn("discussions_deferred", page)
        for operation in OPERATIONS:
            self.assertIn(operation.title, page)
            self.assertIn(operation.id, page)
        for invariant in SEAM_INVARIANTS:
            self.assertIn(invariant.title, page)
        self.assertIn("S-403", page)
        self.assertIn("docs/DISCUSSION_POLLS.md", page)

    def test_page_without_audit_states_no_check(self):
        page = render_discussion_polls_page()
        self.assertNotIn("Checked, not just claimed", page)
        self.assertNotIn("not clean", page)

    def test_page_reports_a_planted_defect_honestly(self):
        with self.conn:
            self.conn.execute(
                "CREATE TABLE discussion_polls (id INTEGER)")
        page = render_discussion_polls_page(
            audit_discussion_polls(self.conn))
        self.assertIn("not clean", page)
        self.assertIn("discussion_polls", page)
        self.assertIn("defect against S-286", page)

    def test_page_escapes_every_value(self):
        audit = DiscussionPollsAudit(
            verdict_feature="polls", feature_judgement="deferred",
            verdict_audit_clean=True, tables_scanned=1,
            columns_scanned=1, events_scanned=1,
            verdict_offending_tables=(), verdict_offending_columns=(),
            verdict_offending_events=(),
            offending_tables=("<b>polls</b>",),
            offending_columns=(), offending_events=(),
            operations_defined=4, seam_invariants=8)
        page = render_discussion_polls_page(audit)
        self.assertNotIn("<b>polls</b>", page)
        self.assertIn("&lt;b&gt;polls", page)

    # the docs say it too
    def test_docs_record_the_refusal_and_seam(self):
        doc = (ROOT / "docs" / "DISCUSSION_POLLS.md").read_text(
            encoding="utf-8")
        self.assertIn("S-286", doc)
        self.assertIn("S-282", doc)
        self.assertIn("no discussion polls", doc.lower())
        for operation in OPERATIONS:
            self.assertIn(operation.id, doc, operation.id)
            self.assertIn(operation.minimum_role, doc, operation.id)
        for invariant in SEAM_INVARIANTS:
            self.assertIn(invariant.id, doc, invariant.id)

    def test_verdict_docs_record_s286_progress(self):
        doc = (ROOT / "docs" / "DISCUSSIONS_VERDICT.md").read_text(
            encoding="utf-8")
        self.assertIn("S-286", doc)
        self.assertIn("discussion_polls", doc)

    def test_taxonomy_docs_record_s286(self):
        doc = (ROOT / "docs" / "AUDIT_TAXONOMY.md").read_text(
            encoding="utf-8")
        self.assertIn("S-286", doc)
        self.assertIn("discussion_polls", doc)


if __name__ == "__main__":
    unittest.main()
