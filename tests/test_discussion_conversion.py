"""S-285 acceptance battery: issue <-> discussion conversion.

Acceptance (roadmap S-285): Issue <-> discussion
conversion (if in) -- converts with a forwarding
note both ways, never silently. S-282 verdicted
conversion IN, S-283 built the board, and S-284's
answer marking recorded that a converted question
keeps its thread, mark and timeline as the linked
origin. This battery proves the build in
samverk/discussion_conversion.py
(DiscussionConversionStore over migration 114's
discussion_conversions) under the verdict's
conversion invariant:

- both ways through the standing doors, in the
  same repository: the counterpart carries the
  source's title, body and author; the converter
  is recorded on the link, never substituted;
- a forwarding note both ways, never silently:
  a converted_to_issue / converted_from_issue
  event on the thread's one timeline, and a
  forwarding comment in the issue's conversation,
  each written in the conversion's transaction;
- the origin is preserved: the source keeps its
  state, content and number; a converted question
  keeps its replies, its accepted-answer mark and
  its timeline whole;
- exactly once: a second conversion of the same
  object -- from either seat -- is refused
  already_converted naming the first link, and
  migration 114's UNIQUE constraints are the
  concurrency backstop;
- judged by S-190: the author, a writer and a
  maintainer may convert; a reader, a stranger
  and the anonymous are refused; the new thread
  is opened under its category's declared create
  rung; private answers not_found exactly as
  missing, on the act and on both link reads.

Storage is migration 114's discussion_conversions
table (schema 113 -> 114), sanctioned in S-282's
verdict audit as S-283's tables were. No new
taxonomy event -- 133 stand (33 auth / 87 repo /
13 admin); conversion writes no audit row, proven
by an audit-count snapshot across both directions.
"""
from __future__ import annotations
import sqlite3, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.discussion_conversion import (
    Conversion, ConversionError, DiscussionConversionStore,
    ForwardingNote, can_convert, conversion_to_dict,
    render_conversion_banner, render_forwarding_note)
from samverk.discussions import DiscussionStore, describe_timeline_entry
from samverk.discussions_verdict import audit_discussions_verdict
from samverk.issue_comments import IssueCommentStore
from samverk.issues import IssueStore
from samverk.outside_collaborators import OutsideCollaboratorStore
from samverk.repositories import RepositoryStore

PW = "correct horse battery"
T0 = 1_700_000_000


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


class ConversionTests(unittest.TestCase):
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
        self.asker = self.accounts.register("tess", PW)
        self.answerer = self.accounts.register("yrsa", PW)
        self.stranger = self.accounts.register("mallory", PW)
        self.maintainer = self.accounts.register("mai", PW)
        self.writer = self.accounts.register("wri", PW)
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.issues = IssueStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.comments = IssueCommentStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.board = DiscussionStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.convert = DiscussionConversionStore(
            self.conn, self.repos, self.accounts, self.issues,
            self.board, audit=self.audit, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        pub = self.repos.get_repository("volmarr", "pub")
        assert pub is not None
        collabs = OutsideCollaboratorStore(
            self.conn, self.accounts, self.audit,
            time_fn=self.clock)
        collabs.grant(self.owner.id, pub.id, "mai", "maintain")
        collabs.grant(self.owner.id, pub.id, "wri", "write")
        self.questions = self.board.create_category(
            self.owner, "volmarr", "pub", "Questions", "question")
        self.announce = self.board.create_category(
            self.owner, "volmarr", "pub", "News", "announcement")
        self.open_cat = self.board.create_category(
            self.owner, "volmarr", "pub", "General", "discussion")
        self.priv_questions = self.board.create_category(
            self.owner, "volmarr", "priv", "Questions", "question")

    # -- helpers -------------------------------------------

    def _reason(self, fn, *a, **k):
        with self.assertRaises(ConversionError) as ctx:
            fn(*a, **k)
        return ctx.exception.reason

    def _issue(self, title="Harbour ice report", repo="pub",
               actor=None, body="The ice is late this year."):
        return self.issues.create_issue(
            actor or self.asker, "volmarr", repo, title, body)

    def _question(self, title="How do tides work?", repo="pub",
                  cat=None, actor=None):
        return self.board.create_thread(
            actor or self.asker, "volmarr", repo,
            (cat or self.questions).id, title, "Asking the village.")

    def _audit_count(self):
        return int(self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"])

    def _counts(self):
        out = {}
        for table in ("issues", "discussion_threads",
                      "discussion_conversions", "issue_comments",
                      "discussion_events"):
            out[table] = int(self.conn.execute(
                f"SELECT COUNT(*) AS n FROM {table}"
            ).fetchone()["n"])
        return out

    def _events(self, thread, repo="pub", viewer=None):
        return [e.event for e in self.board.timeline(
            viewer or self.asker, "volmarr", repo, thread.number)
            if e.event is not None]

    # -- schema / taxonomy / verdict seam -------------------

    def test_schema_taxonomy_and_verdict_stand(self):
        self.assertEqual(schema_version(self.conn), 126)
        self.assertEqual(db.MIGRATIONS[-1][0], 126)
        self.assertEqual(db.migrate(self.conn), 126)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 135)
        families = {}
        for event in taxonomy.AUDIT_EVENTS:
            families[event.split(".")[0]] = (
                families.get(event.split(".")[0], 0) + 1)
        self.assertEqual(
            families, {"auth": 33, "repo": 89, "admin": 13})
        audit = audit_discussions_verdict(self.conn)
        self.assertTrue(audit.build_queued_cleanly, audit)
        self.assertEqual(audit.offending_tables, ())
        tables = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("discussion_conversions", tables)

    def test_unique_constraints_are_the_backstop(self):
        issue = self._issue()
        link = self.convert.convert_issue_to_discussion(
            self.asker, "volmarr", "pub", issue.number,
            self.questions.id)
        with self.assertRaises(sqlite3.IntegrityError):
            with self.conn:
                self.conn.execute(
                    "INSERT INTO discussion_conversions"
                    " (repo_id, issue_id, issue_number,"
                    " discussion_id, discussion_number, direction,"
                    " converted_by, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (link.repo_id, link.issue_id, link.issue_number,
                     999999, 99, "issue_to_discussion",
                     self.asker.id, T0))
        with self.assertRaises(sqlite3.IntegrityError):
            with self.conn:
                self.conn.execute(
                    "INSERT INTO discussion_conversions"
                    " (repo_id, issue_id, issue_number,"
                    " discussion_id, discussion_number, direction,"
                    " converted_by, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (link.repo_id, 999999, 99,
                     link.discussion_id, link.discussion_number,
                     "discussion_to_issue", self.asker.id, T0))

    # -- the pure judgement ----------------------------------

    def test_can_convert_pure_matrix(self):
        self.assertTrue(can_convert(is_author=True, role="read"))
        self.assertTrue(can_convert(is_author=True, role=None))
        self.assertTrue(can_convert(is_author=False, role="write"))
        self.assertTrue(can_convert(is_author=False, role="maintain"))
        self.assertTrue(can_convert(is_author=False, role="admin"))
        self.assertFalse(can_convert(is_author=False, role="triage"))
        self.assertFalse(can_convert(is_author=False, role="read"))
        self.assertFalse(can_convert(is_author=False, role=None))

    # -- issue -> discussion -----------------------------------

    def test_issue_to_discussion_happy(self):
        issue = self._issue()
        link = self.convert.convert_issue_to_discussion(
            self.maintainer, "volmarr", "pub", issue.number,
            self.questions.id)
        self.assertEqual(link.direction, "issue_to_discussion")
        self.assertEqual(link.issue_number, issue.number)
        self.assertEqual(link.discussion_number, 1)
        self.assertEqual(link.converted_by, self.maintainer.id)
        self.assertEqual(link.created_at, T0)
        self.assertEqual(link.source_kind, "issue")
        self.assertEqual(link.target_kind, "discussion")
        self.assertEqual(
            link.words,
            "This issue was converted to discussion #1")
        thread = self.board.get_thread(
            self.asker, "volmarr", "pub", link.discussion_number)
        self.assertEqual(thread.id, link.discussion_id)
        self.assertEqual(thread.title, issue.title)
        self.assertEqual(thread.body, issue.body)
        # The author is preserved; the converter is not
        # substituted as the voice.
        self.assertEqual(thread.author_id, self.asker.id)
        self.assertEqual(thread.state, "open")
        as_dict = conversion_to_dict(link)
        self.assertEqual(as_dict["issue_number"], issue.number)
        self.assertEqual(as_dict["discussion_number"], 1)

    def test_issue_to_discussion_link_reads_both_ways(self):
        issue = self._issue()
        link = self.convert.convert_issue_to_discussion(
            self.asker, "volmarr", "pub", issue.number,
            self.open_cat.id)
        by_issue = self.convert.conversion_for_issue(
            self.stranger, "volmarr", "pub", issue.number)
        by_thread = self.convert.conversion_for_discussion(
            self.stranger, "volmarr", "pub", link.discussion_number)
        self.assertEqual(by_issue, link)
        self.assertEqual(by_thread, link)
        note_on_issue = self.convert.forwarding_note_for_issue(
            self.asker, "volmarr", "pub", issue.number)
        note_on_thread = self.convert.forwarding_note_for_discussion(
            self.asker, "volmarr", "pub", link.discussion_number)
        self.assertEqual(
            note_on_issue.words,
            "This issue was converted to discussion #1")
        self.assertEqual(
            note_on_thread.words,
            "This discussion was converted from issue #1")
        self.assertEqual(note_on_issue.converted_by, self.asker.id)
        self.assertIn(
            "This issue was converted to discussion #1",
            render_forwarding_note(note_on_issue))

    def test_issue_to_discussion_notes_never_silent(self):
        issue = self._issue()
        link = self.convert.convert_issue_to_discussion(
            self.asker, "volmarr", "pub", issue.number,
            self.questions.id)
        comments = self.comments.list_comments(
            self.asker, "volmarr", "pub", issue.number)
        self.assertEqual(len(comments), 1)
        self.assertEqual(comments[0].author_id, self.asker.id)
        self.assertIn(
            "converted to discussion #1", comments[0].body)
        self.assertIn("linked origin", comments[0].body)
        thread = self.board.get_thread(
            self.asker, "volmarr", "pub", link.discussion_number)
        events = self._events(thread)
        self.assertEqual([e.kind for e in events],
                         ["converted_from_issue"])
        self.assertEqual(events[0].actor_id, self.asker.id)
        self.assertEqual(events[0].detail, "issue #1")
        entry = [e for e in self.board.timeline(
            self.asker, "volmarr", "pub", thread.number)
            if e.event is not None][0]
        words = describe_timeline_entry(
            entry, {self.asker.id: "tess"})
        self.assertEqual(
            words, "tess converted this discussion from issue #1")

    def test_issue_keeps_state_and_content_after_conversion(self):
        issue = self._issue()
        before = self.issues.get_issue(
            self.asker, "volmarr", "pub", issue.number)
        self.convert.convert_issue_to_discussion(
            self.asker, "volmarr", "pub", issue.number,
            self.questions.id)
        after = self.issues.get_issue(
            self.asker, "volmarr", "pub", issue.number)
        self.assertEqual(after.state, "open")
        self.assertEqual(after.title, before.title)
        self.assertEqual(after.body, before.body)
        self.assertEqual(after.version, before.version)
        self.assertEqual(after.number, before.number)

    # -- discussion -> issue -----------------------------------

    def test_discussion_to_issue_happy(self):
        thread = self._question()
        link = self.convert.convert_discussion_to_issue(
            self.asker, "volmarr", "pub", thread.number)
        self.assertEqual(link.direction, "discussion_to_issue")
        self.assertEqual(link.discussion_number, thread.number)
        self.assertEqual(link.issue_number, 1)
        self.assertEqual(link.converted_by, self.asker.id)
        issue = self.issues.get_issue(
            self.asker, "volmarr", "pub", link.issue_number)
        self.assertEqual(issue.id, link.issue_id)
        self.assertEqual(issue.title, thread.title)
        self.assertEqual(issue.body, thread.body)
        self.assertEqual(issue.author_id, self.asker.id)
        self.assertEqual(issue.state, "open")
        note = self.convert.forwarding_note_for_discussion(
            self.asker, "volmarr", "pub", thread.number)
        self.assertEqual(
            note.words, "This discussion was converted to issue #1")
        back = self.convert.forwarding_note_for_issue(
            self.asker, "volmarr", "pub", link.issue_number)
        self.assertEqual(
            back.words, "This issue was converted from discussion #1")

    def test_converted_question_keeps_mark_thread_and_timeline(self):
        thread = self._question()
        reply = self.board.add_reply(
            self.answerer, "volmarr", "pub", thread.number,
            "Use the moon.")
        self.board.mark_answer(
            self.asker, "volmarr", "pub", thread.number, reply.id)
        before_kinds = [e.kind for e in self._events(thread)]
        link = self.convert.convert_discussion_to_issue(
            self.maintainer, "volmarr", "pub", thread.number)
        after = self.board.get_thread(
            self.asker, "volmarr", "pub", thread.number)
        self.assertTrue(after.is_answered)
        self.assertEqual(after.accepted_reply_id, reply.id)
        self.assertEqual(after.accepted_by, self.asker.id)
        found = self.board.accepted_answer(
            self.asker, "volmarr", "pub", thread.number)
        self.assertEqual(found.id, reply.id)
        self.assertEqual(found.body, "Use the moon.")
        replies = self.board.list_replies(
            self.asker, "volmarr", "pub", thread.number)
        self.assertEqual([r.id for r in replies], [reply.id])
        kinds = [e.kind for e in self._events(thread)]
        self.assertEqual(kinds, before_kinds + ["converted_to_issue"])
        events = self._events(thread)
        self.assertEqual(events[-1].detail, f"issue #{link.issue_number}")
        entry = [e for e in self.board.timeline(
            self.asker, "volmarr", "pub", thread.number)
            if e.event is not None
            and e.event.kind == "converted_to_issue"][0]
        words = describe_timeline_entry(
            entry, {self.maintainer.id: "mai"})
        self.assertEqual(
            words,
            f"mai converted this discussion to issue "
            f"#{link.issue_number}")
        # The new issue's author is the asker, not the
        # maintainer who converted it.
        issue = self.issues.get_issue(
            self.asker, "volmarr", "pub", link.issue_number)
        self.assertEqual(issue.author_id, self.asker.id)

    def test_discussion_to_issue_note_comment_on_new_issue(self):
        thread = self._question()
        link = self.convert.convert_discussion_to_issue(
            self.asker, "volmarr", "pub", thread.number)
        comments = self.comments.list_comments(
            self.asker, "volmarr", "pub", link.issue_number)
        self.assertEqual(len(comments), 1)
        self.assertEqual(comments[0].author_id, self.asker.id)
        self.assertIn(
            f"converted from discussion #{thread.number}",
            comments[0].body)
        self.assertIn("linked origin", comments[0].body)

    def test_numbers_come_from_the_standing_sequences(self):
        first = self._issue(title="First report")
        second = self._issue(title="Second report")
        self.assertEqual((first.number, second.number), (1, 2))
        link = self.convert.convert_issue_to_discussion(
            self.asker, "volmarr", "pub", first.number,
            self.questions.id)
        self.assertEqual(link.discussion_number, 1)
        other = self._question(title="A fresh question?")
        self.assertEqual(other.number, 2)
        back = self.convert.convert_discussion_to_issue(
            self.asker, "volmarr", "pub", other.number)
        self.assertEqual(back.issue_number, 3)

    # -- exactly once -------------------------------------------

    def test_second_conversion_of_issue_refused_naming_first(self):
        issue = self._issue()
        self.convert.convert_issue_to_discussion(
            self.asker, "volmarr", "pub", issue.number,
            self.questions.id)
        with self.assertRaises(ConversionError) as ctx:
            self.convert.convert_issue_to_discussion(
                self.maintainer, "volmarr", "pub", issue.number,
                self.open_cat.id)
        self.assertEqual(ctx.exception.reason, "already_converted")
        self.assertIn("discussion #1", str(ctx.exception))

    def test_second_conversion_of_discussion_refused_naming_first(self):
        thread = self._question()
        self.convert.convert_discussion_to_issue(
            self.asker, "volmarr", "pub", thread.number)
        with self.assertRaises(ConversionError) as ctx:
            self.convert.convert_discussion_to_issue(
                self.maintainer, "volmarr", "pub", thread.number)
        self.assertEqual(ctx.exception.reason, "already_converted")
        self.assertIn("issue #1", str(ctx.exception))

    def test_converted_result_cannot_convert_again(self):
        thread = self._question()
        link = self.convert.convert_discussion_to_issue(
            self.asker, "volmarr", "pub", thread.number)
        self.assertEqual(self._reason(
            self.convert.convert_issue_to_discussion,
            self.asker, "volmarr", "pub", link.issue_number,
            self.questions.id), "already_converted")
        issue = self._issue(title="Another report")
        link2 = self.convert.convert_issue_to_discussion(
            self.asker, "volmarr", "pub", issue.number,
            self.questions.id)
        self.assertEqual(self._reason(
            self.convert.convert_discussion_to_issue,
            self.asker, "volmarr", "pub", link2.discussion_number),
            "already_converted")

    def test_refused_conversion_creates_nothing(self):
        issue = self._issue()
        before = self._counts()
        self.assertEqual(self._reason(
            self.convert.convert_issue_to_discussion,
            self.stranger, "volmarr", "pub", issue.number,
            self.questions.id), "permission_denied")
        self.assertEqual(self._reason(
            self.convert.convert_issue_to_discussion,
            self.asker, "volmarr", "pub", issue.number, 99999),
            "category_not_found")
        self.assertEqual(self._counts(), before)
        self.convert.convert_issue_to_discussion(
            self.asker, "volmarr", "pub", issue.number,
            self.questions.id)
        mid = self._counts()
        self.assertEqual(self._reason(
            self.convert.convert_issue_to_discussion,
            self.asker, "volmarr", "pub", issue.number,
            self.questions.id), "already_converted")
        self.assertEqual(self._counts(), mid)

    # -- permissions ---------------------------------------------

    def test_author_writer_and_maintainer_may_convert(self):
        by_author = self._issue(title="Author's own")
        self.convert.convert_issue_to_discussion(
            self.asker, "volmarr", "pub", by_author.number,
            self.questions.id)
        by_writer = self._issue(title="Writer converts")
        self.convert.convert_issue_to_discussion(
            self.writer, "volmarr", "pub", by_writer.number,
            self.questions.id)
        thread = self._question(title="Maintainer converts?")
        self.convert.convert_discussion_to_issue(
            self.maintainer, "volmarr", "pub", thread.number)
        own_thread = self._question(title="Asker's own question?")
        self.convert.convert_discussion_to_issue(
            self.asker, "volmarr", "pub", own_thread.number)

    def test_reader_stranger_anonymous_cannot_convert(self):
        issue = self._issue()
        for actor in (self.stranger, self.answerer):
            self.assertEqual(self._reason(
                self.convert.convert_issue_to_discussion,
                actor, "volmarr", "pub", issue.number,
                self.questions.id), "permission_denied")
        self.assertEqual(self._reason(
            self.convert.convert_issue_to_discussion,
            None, "volmarr", "pub", issue.number,
            self.questions.id), "permission_denied")
        thread = self._question()
        for actor in (self.stranger, self.answerer):
            self.assertEqual(self._reason(
                self.convert.convert_discussion_to_issue,
                actor, "volmarr", "pub", thread.number),
                "permission_denied")
        self.assertEqual(self._reason(
            self.convert.convert_discussion_to_issue,
            None, "volmarr", "pub", thread.number),
            "permission_denied")
        self.assertIsNone(self.convert.conversion_for_issue(
            self.asker, "volmarr", "pub", issue.number))
        self.assertIsNone(self.convert.conversion_for_discussion(
            self.asker, "volmarr", "pub", thread.number))

    def test_announcement_category_create_rung_judged(self):
        issue = self._issue()
        self.assertEqual(self._reason(
            self.convert.convert_issue_to_discussion,
            self.asker, "volmarr", "pub", issue.number,
            self.announce.id), "permission_denied")
        link = self.convert.convert_issue_to_discussion(
            self.writer, "volmarr", "pub", issue.number,
            self.announce.id)
        thread = self.board.get_thread(
            self.asker, "volmarr", "pub", link.discussion_number)
        self.assertEqual(thread.category_id, self.announce.id)

    def test_missing_and_shapeless_category_refused(self):
        issue = self._issue()
        self.assertEqual(self._reason(
            self.convert.convert_issue_to_discussion,
            self.asker, "volmarr", "pub", issue.number, 99999),
            "category_not_found")
        self.assertEqual(self._reason(
            self.convert.convert_issue_to_discussion,
            self.asker, "volmarr", "pub", issue.number, "News"),
            "category_not_found")

    # -- private is missing ---------------------------------------

    def test_private_issue_answers_not_found(self):
        secret = self._issue(title="Secret work", repo="priv",
                             actor=self.owner)
        self.assertEqual(self._reason(
            self.convert.convert_issue_to_discussion,
            self.stranger, "volmarr", "priv", secret.number,
            self.priv_questions.id), "issue_not_found")
        self.assertEqual(self._reason(
            self.convert.conversion_for_issue,
            self.stranger, "volmarr", "priv", secret.number),
            "issue_not_found")
        self.assertEqual(self._reason(
            self.convert.forwarding_note_for_issue,
            self.stranger, "volmarr", "priv", secret.number),
            "issue_not_found")
        link = self.convert.convert_issue_to_discussion(
            self.owner, "volmarr", "priv", secret.number,
            self.priv_questions.id)
        self.assertEqual(link.issue_number, secret.number)
        self.assertEqual(self._reason(
            self.convert.conversion_for_discussion,
            self.stranger, "volmarr", "priv",
            link.discussion_number), "discussion_not_found")

    def test_private_discussion_answers_not_found(self):
        secret = self.board.create_thread(
            self.owner, "volmarr", "priv", self.priv_questions.id,
            "Secret question?", "Only the household.")
        self.assertEqual(self._reason(
            self.convert.convert_discussion_to_issue,
            self.stranger, "volmarr", "priv", secret.number),
            "discussion_not_found")
        self.assertEqual(self._reason(
            self.convert.conversion_for_discussion,
            self.stranger, "volmarr", "priv", secret.number),
            "discussion_not_found")
        link = self.convert.convert_discussion_to_issue(
            self.owner, "volmarr", "priv", secret.number)
        self.assertEqual(link.discussion_number, secret.number)
        self.assertEqual(self._reason(
            self.convert.conversion_for_issue,
            self.stranger, "volmarr", "priv", link.issue_number),
            "issue_not_found")

    def test_missing_and_shapeless_numbers_not_found(self):
        for bad in (99999, "one", 0, -1, None):
            self.assertEqual(self._reason(
                self.convert.convert_issue_to_discussion,
                self.asker, "volmarr", "pub", bad,
                self.questions.id), "issue_not_found")
            self.assertEqual(self._reason(
                self.convert.convert_discussion_to_issue,
                self.asker, "volmarr", "pub", bad),
                "discussion_not_found")
        self.assertEqual(self._reason(
            self.convert.conversion_for_issue,
            self.asker, "nowhere", "pub", 1),
            "issue_not_found")

    def test_pull_request_number_is_not_an_issue(self):
        claimed = self.issues.claim_number(
            "volmarr", "pub", "pull_request", self.asker.id)
        self.assertEqual(self._reason(
            self.convert.convert_issue_to_discussion,
            self.asker, "volmarr", "pub", claimed.number,
            self.questions.id), "issue_not_found")

    # -- state doors -----------------------------------------------

    def test_closed_issue_refused(self):
        issue = self._issue()
        self.issues.close_issue(
            self.asker, "volmarr", "pub", issue.number)
        self.assertEqual(self._reason(
            self.convert.convert_issue_to_discussion,
            self.asker, "volmarr", "pub", issue.number,
            self.questions.id), "issue_closed")
        self.assertIsNone(self.convert.conversion_for_issue(
            self.asker, "volmarr", "pub", issue.number))

    def test_closed_discussion_refused(self):
        thread = self._question()
        self.board.close_thread(
            self.asker, "volmarr", "pub", thread.number)
        self.assertEqual(self._reason(
            self.convert.convert_discussion_to_issue,
            self.asker, "volmarr", "pub", thread.number),
            "discussion_closed")
        self.assertIsNone(self.convert.conversion_for_discussion(
            self.asker, "volmarr", "pub", thread.number))

    def test_locked_discussion_may_still_convert(self):
        thread = self._question()
        self.board.lock_thread(
            self.owner, "volmarr", "pub", thread.number)
        link = self.convert.convert_discussion_to_issue(
            self.asker, "volmarr", "pub", thread.number)
        self.assertEqual(link.discussion_number, thread.number)

    def test_unconverted_objects_have_no_link_or_note(self):
        issue = self._issue()
        thread = self._question()
        self.assertIsNone(self.convert.conversion_for_issue(
            self.asker, "volmarr", "pub", issue.number))
        self.assertIsNone(self.convert.conversion_for_discussion(
            self.asker, "volmarr", "pub", thread.number))
        self.assertIsNone(self.convert.forwarding_note_for_issue(
            self.asker, "volmarr", "pub", issue.number))
        self.assertIsNone(
            self.convert.forwarding_note_for_discussion(
                self.asker, "volmarr", "pub", thread.number))

    # -- witnessing --------------------------------------------------

    def test_conversion_writes_no_audit_row(self):
        issue = self._issue()
        thread = self._question(title="Second thread?")
        before = self._audit_count()
        self.convert.convert_issue_to_discussion(
            self.asker, "volmarr", "pub", issue.number,
            self.questions.id)
        self.convert.convert_discussion_to_issue(
            self.asker, "volmarr", "pub", thread.number)
        self.assertEqual(self._audit_count(), before)

    # -- rendering -----------------------------------------------------

    def test_rendering_says_words_and_escapes(self):
        note = ForwardingNote(
            side_kind="issue", side_number=2,
            other_kind="discussion", other_number=5,
            relation="to", converted_by=self.asker.id,
            created_at=T0)
        self.assertEqual(
            note.words, "This issue was converted to discussion #5")
        self.assertEqual(
            render_forwarding_note(note),
            '<p class="forwarding-note">'
            "This issue was converted to discussion #5</p>")
        hostile = Conversion(
            id=1, repo_id=1, issue_id=1, issue_number=2,
            discussion_id=1, discussion_number=5,
            direction="issue_to_discussion",
            converted_by=self.asker.id, created_at=T0)
        banner = render_conversion_banner(hostile, "<b>evil</b>")
        self.assertIn("&lt;b&gt;evil&lt;/b&gt;", banner)
        self.assertNotIn("<b>evil</b>", banner)
        self.assertIn("converted to discussion #5", banner)


if __name__ == "__main__":
    unittest.main()
