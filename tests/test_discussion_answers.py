"""S-284 acceptance battery: answer marking.

Acceptance (roadmap S-284): Answer marking (if in)
-- asker or maintainer marks an answer; the mark is
an event, and conversion to an issue keeps the
thread linked. S-282 verdicted answer marking IN
and S-283 built the board it marks on, so this
battery proves the build in samverk/discussions.py
(mark_answer / unmark_answer / accepted_answer on
DiscussionStore, judged pure by can_mark_answer)
under the verdict's invariants:

- the hands are the asker's or a maintainer's (the
  maintain rung or above through S-190) -- proven
  per rung: asker, maintainer, administrator mark;
  writer, fellow reader, reply author alone,
  stranger and anonymous are refused;
- the mark is an event, never an edit: an
  answer_marked / answer_unmarked row on the
  thread's one timeline in the same transaction,
  the marked reply byte-for-byte untouched;
- exactly one answer stands at a time: marking
  another reply moves the mark and names the
  replaced answer; re-marking and unmarking an
  unmarked question are quiet no-ops;
- only a question has an answer: announcement and
  open-discussion threads refuse not_a_question;
- deleting the accepted reply clears the standing
  mark in the deletion's own transaction, while
  both events stay on the timeline;
- private is missing: a private board's mark
  answers discussion_not_found to anyone who
  cannot read the board;
- answered is said in words (state words, the
  thread page's Accepted answer label, the board
  list's answered filter), and conversion stays
  S-285's road: marking never converts, copies or
  closes the thread -- a converted question keeps
  this thread, mark and timeline as its linked
  origin, named here and built there.

Storage is migration 113's accepted_reply_id /
accepted_by / accepted_at columns on
discussion_threads (schema 112 -> 113). No new
taxonomy event -- 133 stand (33 auth / 87 repo /
13 admin); the mark is recorded on the thread's
own timeline, not the audit vocabulary.
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.discussions import (
    DiscussionError, DiscussionStore, can_mark_answer,
    describe_timeline_entry, render_board_page,
    render_thread_page, reply_to_dict, thread_to_dict)
from samverk.discussions_verdict import audit_discussions_verdict
from samverk.outside_collaborators import OutsideCollaboratorStore
from samverk.repositories import RepositoryStore

PW = "correct horse battery"
T0 = 1_700_000_000


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


class AnswerMarkingTests(unittest.TestCase):
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
        self.board = DiscussionStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
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
        with self.assertRaises(DiscussionError) as ctx:
            fn(*a, **k)
        return ctx.exception.reason

    def _question(self, title="How do tides work?", repo="pub",
                  cat=None, actor=None):
        return self.board.create_thread(
            actor or self.asker, "volmarr", repo,
            (cat or self.questions).id, title, "Asking the village.")

    def _reply(self, thread, actor=None, body="Use the moon.",
               repo="pub"):
        return self.board.add_reply(
            actor or self.answerer, "volmarr", repo,
            thread.number, body)

    def _events(self, thread, repo="pub", viewer=None):
        return [e.event.kind for e in self.board.timeline(
            viewer or self.asker, "volmarr", repo, thread.number)
            if e.event is not None]

    def _audit_count(self):
        return int(self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"])

    # -- schema / taxonomy / verdict seam -------------------

    def test_schema_and_taxonomy_stand(self):
        self.assertEqual(schema_version(self.conn), 116)
        self.assertEqual(db.MIGRATIONS[-1][0], 116)
        self.assertEqual(db.migrate(self.conn), 116)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 133)
        families = {}
        for event in taxonomy.AUDIT_EVENTS:
            families[event.split(".")[0]] = (
                families.get(event.split(".")[0], 0) + 1)
        self.assertEqual(
            families, {"auth": 33, "repo": 87, "admin": 13})

    def test_verdict_audit_still_clean(self):
        audit = audit_discussions_verdict(self.conn)
        self.assertTrue(audit.build_queued_cleanly)
        self.assertEqual(audit.offending_tables, ())
        self.assertEqual(audit.offending_columns, ())
        self.assertEqual(audit.offending_events, ())

    # -- the pure judgement ----------------------------------

    def test_can_mark_answer_pure_matrix(self):
        self.assertTrue(can_mark_answer(
            "question", is_asker=True, role="read"))
        self.assertTrue(can_mark_answer(
            "question", is_asker=False, role="maintain"))
        self.assertTrue(can_mark_answer(
            "question", is_asker=False, role="admin"))
        self.assertFalse(can_mark_answer(
            "question", is_asker=False, role="write"))
        self.assertFalse(can_mark_answer(
            "question", is_asker=False, role="triage"))
        self.assertFalse(can_mark_answer(
            "question", is_asker=False, role="read"))
        self.assertFalse(can_mark_answer(
            "question", is_asker=False, role=None))
        self.assertFalse(can_mark_answer(
            "discussion", is_asker=True, role="admin"))
        self.assertFalse(can_mark_answer(
            "announcement", is_asker=True, role="admin"))
        self.assertFalse(can_mark_answer(
            "bogus", is_asker=True, role="admin"))
        self.assertFalse(can_mark_answer(
            None, is_asker=True, role="admin"))

    # -- the mark itself --------------------------------------

    def test_asker_marks_answer(self):
        thread = self._question()
        reply = self._reply(thread)
        marked = self.board.mark_answer(
            self.asker, "volmarr", "pub", thread.number, reply.id)
        self.assertTrue(marked.is_answered)
        self.assertEqual(marked.accepted_reply_id, reply.id)
        self.assertEqual(marked.accepted_by, self.asker.id)
        self.assertEqual(marked.accepted_at, T0)
        found = self.board.accepted_answer(
            self.asker, "volmarr", "pub", thread.number)
        self.assertIsNotNone(found)
        self.assertEqual(found.id, reply.id)
        self.assertEqual(found.body, "Use the moon.")
        as_dict = thread_to_dict(marked)
        self.assertTrue(as_dict["is_answered"])
        self.assertEqual(as_dict["accepted_reply_id"], reply.id)

    def test_mark_is_event_and_never_an_edit(self):
        thread = self._question()
        reply = self._reply(thread)
        before = reply_to_dict(self.board.get_reply(
            self.asker, "volmarr", "pub", thread.number, reply.id))
        self.board.mark_answer(
            self.asker, "volmarr", "pub", thread.number, reply.id)
        after = reply_to_dict(self.board.get_reply(
            self.asker, "volmarr", "pub", thread.number, reply.id))
        self.assertEqual(before, after)
        self.assertIsNone(after["edited_at"])
        events = [e.event for e in self.board.timeline(
            self.asker, "volmarr", "pub", thread.number)
            if e.event is not None]
        marks = [e for e in events if e.kind == "answer_marked"]
        self.assertEqual(len(marks), 1)
        self.assertEqual(marks[0].actor_id, self.asker.id)
        self.assertEqual(marks[0].detail, f"reply {reply.id}")
        entry = [e for e in self.board.timeline(
            self.asker, "volmarr", "pub", thread.number)
            if e.event is not None and e.event.kind == "answer_marked"][0]
        words = describe_timeline_entry(
            entry, {self.asker.id: "tess"})
        self.assertEqual(
            words, f"tess marked reply {reply.id} as the answer")

    def test_maintainer_and_administrator_mark(self):
        thread = self._question()
        reply = self._reply(thread)
        marked = self.board.mark_answer(
            self.maintainer, "volmarr", "pub", thread.number, reply.id)
        self.assertEqual(marked.accepted_by, self.maintainer.id)
        other = self._question(title="Second question?")
        other_reply = self._reply(other)
        marked2 = self.board.mark_answer(
            self.owner, "volmarr", "pub", other.number, other_reply.id)
        self.assertEqual(marked2.accepted_by, self.owner.id)

    def test_unmark_by_asker_and_maintainer(self):
        thread = self._question()
        reply = self._reply(thread)
        self.board.mark_answer(
            self.asker, "volmarr", "pub", thread.number, reply.id)
        cleared = self.board.unmark_answer(
            self.maintainer, "volmarr", "pub", thread.number)
        self.assertFalse(cleared.is_answered)
        self.assertIsNone(cleared.accepted_reply_id)
        self.assertIsNone(cleared.accepted_by)
        self.assertIsNone(cleared.accepted_at)
        self.assertIsNone(self.board.accepted_answer(
            self.asker, "volmarr", "pub", thread.number))
        self.board.mark_answer(
            self.maintainer, "volmarr", "pub", thread.number, reply.id)
        cleared2 = self.board.unmark_answer(
            self.asker, "volmarr", "pub", thread.number)
        self.assertFalse(cleared2.is_answered)
        kinds = self._events(thread)
        self.assertEqual(kinds.count("answer_marked"), 2)
        self.assertEqual(kinds.count("answer_unmarked"), 2)

    def test_writer_reader_stranger_anonymous_cannot_mark(self):
        thread = self._question()
        reply = self._reply(thread)
        for actor in (self.writer, self.stranger, self.answerer):
            self.assertEqual(self._reason(
                self.board.mark_answer, actor, "volmarr", "pub",
                thread.number, reply.id), "permission_denied")
        self.assertEqual(self._reason(
            self.board.mark_answer, None, "volmarr", "pub",
            thread.number, reply.id), "permission_denied")
        self.board.mark_answer(
            self.asker, "volmarr", "pub", thread.number, reply.id)
        for actor in (self.writer, self.stranger):
            self.assertEqual(self._reason(
                self.board.unmark_answer, actor, "volmarr", "pub",
                thread.number), "permission_denied")
        self.assertTrue(self.board.get_thread(
            self.asker, "volmarr", "pub", thread.number).is_answered)

    def test_reply_author_alone_cannot_mark_own_reply(self):
        thread = self._question()
        reply = self._reply(thread)  # the answerer's own reply
        self.assertEqual(self._reason(
            self.board.mark_answer, self.answerer, "volmarr", "pub",
            thread.number, reply.id), "permission_denied")

    def test_mark_moves_exactly_one_answer(self):
        thread = self._question()
        first = self._reply(thread, body="First guess.")
        second = self._reply(thread, body="Better answer.")
        self.board.mark_answer(
            self.asker, "volmarr", "pub", thread.number, first.id)
        moved = self.board.mark_answer(
            self.maintainer, "volmarr", "pub", thread.number, second.id)
        self.assertEqual(moved.accepted_reply_id, second.id)
        self.assertEqual(moved.accepted_by, self.maintainer.id)
        found = self.board.accepted_answer(
            self.asker, "volmarr", "pub", thread.number)
        self.assertEqual(found.id, second.id)
        marks = [e.event for e in self.board.timeline(
            self.asker, "volmarr", "pub", thread.number)
            if e.event is not None and e.event.kind == "answer_marked"]
        self.assertEqual(len(marks), 2)
        self.assertEqual(marks[0].detail, f"reply {first.id}")
        self.assertEqual(
            marks[1].detail, f"reply {second.id} (was reply {first.id})")

    def test_remark_standing_answer_is_noop(self):
        thread = self._question()
        reply = self._reply(thread)
        self.board.mark_answer(
            self.asker, "volmarr", "pub", thread.number, reply.id)
        before = self._events(thread)
        again = self.board.mark_answer(
            self.maintainer, "volmarr", "pub", thread.number, reply.id)
        self.assertEqual(again.accepted_by, self.asker.id)
        self.assertEqual(self._events(thread), before)

    def test_unmark_without_mark_is_noop(self):
        thread = self._question()
        self._reply(thread)
        before = self._events(thread)
        cleared = self.board.unmark_answer(
            self.asker, "volmarr", "pub", thread.number)
        self.assertFalse(cleared.is_answered)
        self.assertEqual(self._events(thread), before)

    def test_only_question_kind_has_an_answer(self):
        news = self.board.create_thread(
            self.owner, "volmarr", "pub", self.announce.id,
            "Harbour closed", "Ice on the water.")
        news_reply = self.board.add_reply(
            self.asker, "volmarr", "pub", news.number, "Noted.")
        self.assertEqual(self._reason(
            self.board.mark_answer, self.owner, "volmarr", "pub",
            news.number, news_reply.id), "not_a_question")
        self.assertEqual(self._reason(
            self.board.unmark_answer, self.owner, "volmarr", "pub",
            news.number), "not_a_question")
        chat = self._question(
            title="Just chatting", cat=self.open_cat)
        chat_reply = self._reply(chat)
        self.assertEqual(self._reason(
            self.board.mark_answer, self.asker, "volmarr", "pub",
            chat.number, chat_reply.id), "not_a_question")
        self.assertIsNone(self.board.accepted_answer(
            self.asker, "volmarr", "pub", chat.number))

    def test_mark_missing_foreign_or_shapeless_reply(self):
        thread = self._question()
        other = self._question(title="Another question?")
        foreign = self._reply(other)
        self.assertEqual(self._reason(
            self.board.mark_answer, self.asker, "volmarr", "pub",
            thread.number, foreign.id), "reply_not_found")
        self.assertEqual(self._reason(
            self.board.mark_answer, self.asker, "volmarr", "pub",
            thread.number, 99999), "reply_not_found")
        self.assertEqual(self._reason(
            self.board.mark_answer, self.asker, "volmarr", "pub",
            thread.number, "the good one"), "reply_not_found")

    def test_mark_deleted_reply_refused(self):
        thread = self._question()
        reply = self._reply(thread)
        self.board.delete_reply(
            self.answerer, "volmarr", "pub", thread.number, reply.id)
        self.assertEqual(self._reason(
            self.board.mark_answer, self.asker, "volmarr", "pub",
            thread.number, reply.id), "reply_not_found")

    # -- deletion interplay ------------------------------------

    def test_deleting_accepted_reply_clears_mark(self):
        thread = self._question()
        reply = self._reply(thread)
        self.board.mark_answer(
            self.asker, "volmarr", "pub", thread.number, reply.id)
        self.board.delete_reply(
            self.answerer, "volmarr", "pub", thread.number, reply.id)
        after = self.board.get_thread(
            self.asker, "volmarr", "pub", thread.number)
        self.assertFalse(after.is_answered)
        self.assertIsNone(self.board.accepted_answer(
            self.asker, "volmarr", "pub", thread.number))
        kinds = self._events(thread)
        self.assertIn("answer_marked", kinds)
        self.assertIn("reply_deleted", kinds)

    def test_deleting_unmarked_reply_keeps_mark(self):
        thread = self._question()
        answer = self._reply(thread, body="The answer.")
        noise = self._reply(thread, body="Noise.")
        self.board.mark_answer(
            self.asker, "volmarr", "pub", thread.number, answer.id)
        self.board.delete_reply(
            self.answerer, "volmarr", "pub", thread.number, noise.id)
        after = self.board.get_thread(
            self.asker, "volmarr", "pub", thread.number)
        self.assertTrue(after.is_answered)
        self.assertEqual(after.accepted_reply_id, answer.id)

    # -- doors, filters, words ----------------------------------

    def test_private_board_mark_is_missing(self):
        thread = self.board.create_thread(
            self.owner, "volmarr", "priv", self.priv_questions.id,
            "Secret tides?", "Quietly.")
        reply = self.board.add_reply(
            self.owner, "volmarr", "priv", thread.number, "Shh.")
        self.assertEqual(self._reason(
            self.board.mark_answer, self.stranger, "volmarr", "priv",
            thread.number, reply.id), "discussion_not_found")
        self.assertEqual(self._reason(
            self.board.accepted_answer, self.stranger, "volmarr",
            "priv", thread.number), "discussion_not_found")
        marked = self.board.mark_answer(
            self.owner, "volmarr", "priv", thread.number, reply.id)
        self.assertTrue(marked.is_answered)

    def test_answered_filter_partitions_board(self):
        answered = self._question()
        reply = self._reply(answered)
        open_q = self._question(title="Still open?")
        self._reply(open_q)
        chat = self._question(title="Chat thread", cat=self.open_cat)
        self.board.mark_answer(
            self.asker, "volmarr", "pub", answered.number, reply.id)
        yes = self.board.list_threads(
            self.asker, "volmarr", "pub", answered=True)
        self.assertEqual([t.number for t in yes], [answered.number])
        no = self.board.list_threads(
            self.asker, "volmarr", "pub", answered=False)
        self.assertEqual(
            sorted(t.number for t in no),
            sorted([open_q.number, chat.number]))
        self.board.unmark_answer(
            self.asker, "volmarr", "pub", answered.number)
        self.assertEqual(self.board.list_threads(
            self.asker, "volmarr", "pub", answered=True), [])

    def test_closed_and_locked_question_still_markable(self):
        thread = self._question()
        reply = self._reply(thread)
        self.board.close_thread(
            self.asker, "volmarr", "pub", thread.number)
        marked = self.board.mark_answer(
            self.asker, "volmarr", "pub", thread.number, reply.id)
        self.assertTrue(marked.is_answered)
        self.assertEqual(marked.state, "closed")
        other = self._question(title="Locked question?")
        other_reply = self._reply(other)
        self.board.lock_thread(
            self.owner, "volmarr", "pub", other.number)
        marked2 = self.board.mark_answer(
            self.maintainer, "volmarr", "pub", other.number,
            other_reply.id)
        self.assertTrue(marked2.is_answered)
        self.assertTrue(marked2.locked)

    def test_states_and_pages_say_answered_in_words(self):
        thread = self._question()
        reply = self._reply(thread)
        marked = self.board.mark_answer(
            self.asker, "volmarr", "pub", thread.number, reply.id)
        self.assertIn("answered", marked.state_words)
        authors = {self.asker.id: "tess", self.answerer.id: "yrsa"}
        page = render_thread_page(
            marked, self.questions,
            self.board.timeline(self.asker, "volmarr", "pub",
                                thread.number), authors)
        self.assertIn("Accepted answer", page)
        self.assertIn("answered", page)
        board_page = render_board_page(
            [self.questions], [marked], authors)
        self.assertIn("answered", board_page)
        unmarked_page = render_thread_page(
            self.board.unmark_answer(
                self.asker, "volmarr", "pub", thread.number),
            self.questions,
            self.board.timeline(self.asker, "volmarr", "pub",
                                thread.number), authors)
        self.assertNotIn("Accepted answer", unmarked_page)

    def test_marking_witnesses_no_audit_event(self):
        thread = self._question()
        reply = self._reply(thread)
        before = self._audit_count()
        self.board.mark_answer(
            self.asker, "volmarr", "pub", thread.number, reply.id)
        self.board.unmark_answer(
            self.asker, "volmarr", "pub", thread.number)
        self.board.mark_answer(
            self.maintainer, "volmarr", "pub", thread.number, reply.id)
        self.assertEqual(self._audit_count(), before)

    def test_timeline_holds_mark_in_order(self):
        thread = self._question()
        self.clock.now += 10
        reply = self._reply(thread)
        self.clock.now += 10
        self.board.mark_answer(
            self.asker, "volmarr", "pub", thread.number, reply.id)
        entries = self.board.timeline(
            self.asker, "volmarr", "pub", thread.number)
        shape = ["event:" + e.event.kind if e.event is not None
                 else "reply" for e in entries]
        self.assertEqual(
            shape, ["event:created", "reply", "event:answer_marked"])

    def test_marking_never_converts_copies_or_closes(self):
        thread = self._question()
        reply = self._reply(thread)
        marked = self.board.mark_answer(
            self.asker, "volmarr", "pub", thread.number, reply.id)
        self.assertEqual(marked.state, "open")
        self.assertEqual(marked.title, thread.title)
        self.assertEqual(marked.body, thread.body)
        self.assertEqual(
            self.board.thread_count(self.asker, "volmarr", "pub"), 1)
        self.assertNotIn("converted", thread_to_dict(marked))

    def test_readers_see_the_standing_mark(self):
        thread = self._question()
        reply = self._reply(thread)
        self.board.mark_answer(
            self.maintainer, "volmarr", "pub", thread.number, reply.id)
        seen = self.board.get_thread(
            self.stranger, "volmarr", "pub", thread.number)
        self.assertTrue(seen.is_answered)
        found = self.board.accepted_answer(
            None, "volmarr", "pub", thread.number)
        self.assertIsNotNone(found)
        self.assertEqual(found.id, reply.id)

    def test_mark_records_marker_and_moment(self):
        thread = self._question()
        first = self._reply(thread, body="One.")
        second = self._reply(thread, body="Two.")
        self.board.mark_answer(
            self.asker, "volmarr", "pub", thread.number, first.id)
        self.clock.now += 500
        moved = self.board.mark_answer(
            self.maintainer, "volmarr", "pub", thread.number, second.id)
        self.assertEqual(moved.accepted_by, self.maintainer.id)
        self.assertEqual(moved.accepted_at, T0 + 500)


if __name__ == "__main__":
    unittest.main()
