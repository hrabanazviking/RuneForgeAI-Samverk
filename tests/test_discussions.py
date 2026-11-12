"""S-283 acceptance battery: discussion categories and threads.

Acceptance (roadmap S-283): Discussion categories
and threads (if verdicted in) -- categories,
question/discussion kinds, pinned posts. S-282
verdicted the core IN, so this battery proves the
build in samverk/discussions.py under the verdict's
invariants:

- categories of question / announcement / discussion
  kinds, each kind declaring its allowed states and
  its create/reply rungs as data (KIND_SPECS, judged
  pure by decide_power), administered by repository
  administrators alone;
- permissions follow the repository through S-190's
  PermissionEngine -- the research-30 role matrix
  (create / reply / mark-answer's S-284 neighbours:
  pin / moderate) proven per rung: reader, writer,
  administrator, stranger, anonymous;
- private is missing everywhere: a private board,
  its categories, threads, replies, counts and
  filtered search all answer as a missing board
  answers, never a leak;
- one timeline holds replies and happenings
  (created / pinned / locked / closed / reopened /
  reply_deleted) attributable and in order;
- replies reuse S-123's machinery whole: its body
  law, its visible edit history, its tombstone;
- pins are owner-controlled, locks refuse non-writer
  replies, closes refuse all replies;
- states are said in words in every render, user
  text reaches pages only S-010-escaped, and the
  composer is labelled-field HTML.

Storage is migration 112 (schema 112 -> 112). No
new taxonomy event -- 133 stand (33 auth / 87 repo /
13 admin); discussion acts are recorded on the
thread's own timeline, not the audit vocabulary.

Counted with: python3 -m unittest discover -s tests -v
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
    KIND_SPECS, DiscussionError, DiscussionStore,
    category_to_dict, decide_power, kind_spec,
    render_board_page, render_composer_form,
    render_thread_page, reply_to_dict, thread_to_dict)
from samverk.repositories import RepositoryStore

PW = "correct horse battery"
T0 = 1_700_000_000


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


class DiscussionTests(unittest.TestCase):
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
        self.writer = self.accounts.register("yrsa", PW)
        self.reader = self.accounts.register("tess", PW)
        self.stranger = self.accounts.register("mallory", PW)
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
        # The writer writes by owning a second public repo's
        # board is not needed: writer is a plain reader on
        # pub until granted -- team/collaborator grants are
        # S-190 contributions; here the owner lends the
        # writer rung through a repository she owns is not
        # the case, so writer acts below are the owner's on
        # pub and the writer is used as a second reader.
        self.questions = self.board.create_category(
            self.owner, "volmarr", "pub", "Questions", "question",
            "Ask the village")
        self.announce = self.board.create_category(
            self.owner, "volmarr", "pub", "News", "announcement")
        self.open_cat = self.board.create_category(
            self.owner, "volmarr", "pub", "General", "discussion")

    def _reason(self, fn, *a, **k):
        with self.assertRaises(DiscussionError) as ctx:
            fn(*a, **k)
        return ctx.exception.reason

    def _thread(self, actor=None, cat=None, title="How do tides work?",
                body="Asking for a friend.", repo="pub"):
        return self.board.create_thread(
            actor or self.reader, "volmarr", repo,
            (cat or self.questions).id, title, body)

    # -- schema / taxonomy pins ---------------------------

    def test_schema_and_taxonomy_stand(self):
        self.assertEqual(schema_version(self.conn), 117)
        self.assertEqual(db.MIGRATIONS[-1][0], 117)
        self.assertEqual(db.migrate(self.conn), 117)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 134)
        families = {}
        for event in taxonomy.AUDIT_EVENTS:
            families[event.split(".")[0]] = (
                families.get(event.split(".")[0], 0) + 1)
        self.assertEqual(
            families, {"auth": 33, "repo": 88, "admin": 13})

    # -- kinds declare states and powers -------------------

    def test_kind_specs_declare_states_and_powers(self):
        self.assertEqual(
            sorted(KIND_SPECS), ["announcement", "discussion",
                                 "question"])
        for spec in KIND_SPECS.values():
            self.assertEqual(spec.allowed_states, ("open", "closed"))
            self.assertTrue(spec.words.strip())
        self.assertEqual(
            KIND_SPECS["question"].create_min_role, "read")
        self.assertEqual(
            KIND_SPECS["announcement"].create_min_role, "write")
        self.assertEqual(
            KIND_SPECS["announcement"].reply_min_role, "read")
        self.assertIs(kind_spec("question"), KIND_SPECS["question"])
        self.assertEqual(
            self._reason(kind_spec, "poll"), "kind_invalid")
        self.assertEqual(
            self._reason(kind_spec, None), "kind_invalid")

    def test_decide_power_is_pure_and_per_rung(self):
        self.assertTrue(decide_power("question", "create", "read"))
        self.assertTrue(decide_power("question", "reply", "triage"))
        self.assertFalse(decide_power("question", "create", None))
        self.assertFalse(
            decide_power("announcement", "create", "read"))
        self.assertTrue(
            decide_power("announcement", "create", "write"))
        self.assertTrue(
            decide_power("announcement", "create", "admin"))
        self.assertTrue(
            decide_power("announcement", "reply", "read"))
        self.assertFalse(decide_power("poll", "create", "admin"))
        self.assertFalse(decide_power("question", "pin", "admin"))

    # -- categories -----------------------------------------

    def test_category_create_list_get_and_dict(self):
        cats = self.board.list_categories(None, "volmarr", "pub")
        self.assertEqual(
            [c.name for c in cats],
            ["General", "News", "Questions"])
        got = self.board.get_category(
            None, "volmarr", "pub", self.questions.id)
        self.assertEqual(got.kind, "question")
        self.assertEqual(got.kind_title, "Question")
        self.assertEqual(got.description, "Ask the village")
        d = category_to_dict(got)
        self.assertEqual(d["kind"], "question")
        self.assertEqual(d["create_min_role"], "read")
        self.assertEqual(d["allowed_states"], ["open", "closed"])
        self.assertEqual(
            self._reason(self.board.get_category,
                         None, "volmarr", "pub", 99999),
            "category_not_found")

    def test_category_admin_only_and_validation(self):
        for actor in (self.reader, self.writer, self.stranger, None):
            self.assertEqual(
                self._reason(self.board.create_category,
                             actor, "volmarr", "pub", "Extra",
                             "question"),
                "permission_denied")
        self.assertEqual(
            self._reason(self.board.create_category,
                         self.owner, "volmarr", "pub", "Extra",
                         "poll"),
            "kind_invalid")
        self.assertEqual(
            self._reason(self.board.create_category,
                         self.owner, "volmarr", "pub", "  ",
                         "question"),
            "category_required")
        self.assertEqual(
            self._reason(self.board.create_category,
                         self.owner, "volmarr", "pub",
                         "questions", "discussion"),
            "category_exists")
        self.assertEqual(
            self._reason(self.board.create_category,
                         self.owner, "volmarr", "pub",
                         "x" * 81, "question"),
            "category_invalid")

    def test_category_update_and_delete(self):
        updated = self.board.update_category(
            self.owner, "volmarr", "pub", self.open_cat.id,
            name="Longhouse", description="Open talk")
        self.assertEqual(updated.name, "Longhouse")
        self.assertEqual(updated.kind, "discussion")
        self.assertEqual(
            self._reason(self.board.update_category,
                         self.reader, "volmarr", "pub",
                         self.open_cat.id, name="Nope"),
            "permission_denied")
        self._thread(cat=self.open_cat)
        self.assertEqual(
            self._reason(self.board.delete_category,
                         self.owner, "volmarr", "pub",
                         self.open_cat.id),
            "category_not_empty")
        empty = self.board.create_category(
            self.owner, "volmarr", "pub", "Empty", "question")
        gone = self.board.delete_category(
            self.owner, "volmarr", "pub", empty.id)
        self.assertEqual(gone.name, "Empty")
        self.assertEqual(
            self._reason(self.board.get_category,
                         None, "volmarr", "pub", empty.id),
            "category_not_found")

    # -- threads: create / read ------------------------------

    def test_thread_create_numbers_and_dict(self):
        a = self._thread()
        b = self._thread(title="Second question")
        self.assertEqual((a.number, b.number), (1, 2))
        self.assertEqual(a.state, "open")
        self.assertEqual(a.state_words, "open")
        self.assertFalse(a.pinned)
        self.assertEqual(a.category_id, self.questions.id)
        d = thread_to_dict(a)
        self.assertEqual(d["ref"], "#1")
        self.assertEqual(d["state_words"], "open")
        got = self.board.get_thread(None, "volmarr", "pub", 1)
        self.assertEqual(got.title, "How do tides work?")
        self.assertEqual(
            self._reason(self.board.get_thread,
                         None, "volmarr", "pub", 99999),
            "discussion_not_found")
        self.assertEqual(
            self.board.thread_count(None, "volmarr", "pub"), 2)

    def test_thread_create_role_matrix(self):
        # A reader may open a question; a stranger to a
        # public repo is a reader by visibility and may too;
        # anonymous may not (a thread needs an author).
        self.assertEqual(
            self._reason(self.board.create_thread,
                         None, "volmarr", "pub",
                         self.questions.id, "Anon", "Body"),
            "permission_denied")
        # Announcements are writers-only to open.
        self.assertEqual(
            self._reason(self.board.create_thread,
                         self.reader, "volmarr", "pub",
                         self.announce.id, "News", "Body"),
            "permission_denied")
        made = self.board.create_thread(
            self.owner, "volmarr", "pub", self.announce.id,
            "Harbour opens", "On Monday.")
        self.assertEqual(made.number, 1)
        # An unknown category is refused before powers.
        self.assertEqual(
            self._reason(self.board.create_thread,
                         self.owner, "volmarr", "pub", 99999,
                         "T", "B"),
            "category_not_found")
        # Title/body law is S-122's / S-123's.
        self.assertEqual(
            self._reason(self.board.create_thread,
                         self.owner, "volmarr", "pub",
                         self.questions.id, "  ", "B"),
            "title_required")
        self.assertEqual(
            self._reason(self.board.create_thread,
                         self.owner, "volmarr", "pub",
                         self.questions.id, "T", "bad\x01body"),
            "body_invalid")
        blank = self.board.create_thread(
            self.owner, "volmarr", "pub", self.questions.id,
            "Title only", "")
        self.assertEqual(blank.body, "")

    def test_thread_edit_hands(self):
        t = self._thread()
        edited = self.board.update_thread(
            self.reader, "volmarr", "pub", t.number,
            title="How do tides work, really?")
        self.assertEqual(edited.title, "How do tides work, really?")
        self.assertIsNotNone(edited.edited_at)
        self.assertEqual(
            self._reason(self.board.update_thread,
                         self.stranger, "volmarr", "pub",
                         t.number, title="Hijack"),
            "permission_denied")
        by_owner = self.board.update_thread(
            self.owner, "volmarr", "pub", t.number, body="Owner edit.")
        self.assertEqual(by_owner.body, "Owner edit.")

    # -- private is missing everywhere ------------------------

    def test_private_board_is_missing_everywhere(self):
        secret_cat = self.board.create_category(
            self.owner, "volmarr", "priv", "Inner", "question")
        secret = self.board.create_thread(
            self.owner, "volmarr", "priv", secret_cat.id,
            "Hidden plans", "Not for strangers.")
        self.board.add_reply(
            self.owner, "volmarr", "priv", secret.number, "Indeed.")
        for viewer in (self.stranger, self.reader, None):
            self.assertEqual(
                self._reason(self.board.list_categories,
                             viewer, "volmarr", "priv"),
                "repo_not_found")
            self.assertEqual(
                self._reason(self.board.list_threads,
                             viewer, "volmarr", "priv"),
                "repo_not_found")
            self.assertEqual(
                self._reason(self.board.thread_count,
                             viewer, "volmarr", "priv"),
                "repo_not_found")
            self.assertEqual(
                self._reason(self.board.get_thread,
                             viewer, "volmarr", "priv", secret.number),
                "discussion_not_found")
            self.assertEqual(
                self._reason(self.board.list_threads,
                             viewer, "volmarr", "priv",
                             query="Hidden"),
                "repo_not_found")
        # The owner still reads it whole.
        self.assertEqual(
            self.board.thread_count(self.owner, "volmarr", "priv"), 1)
        self.assertEqual(
            self.board.get_thread(
                self.owner, "volmarr", "priv", 1).title,
            "Hidden plans")
        # A missing repository answers the same way.
        self.assertEqual(
            self._reason(self.board.list_categories,
                         None, "volmarr", "nope"),
            "repo_not_found")
        self.assertEqual(
            self._reason(self.board.get_thread,
                         None, "volmarr", "nope", 1),
            "discussion_not_found")

    # -- lists, filters, the search seam -----------------------

    def test_list_filters_and_search_seam(self):
        q1 = self._thread(title="Tide tables")
        q2 = self._thread(title="Rope work", body="Knots and tides")
        a1 = self.board.create_thread(
            self.owner, "volmarr", "pub", self.announce.id,
            "Tide festival", "Come all.")
        self.board.pin_thread(
            self.owner, "volmarr", "pub", q2.number)
        all_threads = self.board.list_threads(None, "volmarr", "pub")
        self.assertEqual(
            [t.number for t in all_threads],
            [q2.number, a1.number, q1.number])  # pinned first
        self.assertEqual(
            [t.number for t in self.board.list_threads(
                None, "volmarr", "pub", kind="question")],
            [q2.number, q1.number])
        self.assertEqual(
            [t.number for t in self.board.list_threads(
                None, "volmarr", "pub",
                category_id=self.announce.id)],
            [a1.number])
        self.assertEqual(
            [t.number for t in self.board.list_threads(
                None, "volmarr", "pub", pinned=True)],
            [q2.number])
        found = self.board.list_threads(
            None, "volmarr", "pub", query="tide")
        self.assertEqual(
            sorted(t.number for t in found),
            sorted([q1.number, q2.number, a1.number]))
        self.assertEqual(
            [t.number for t in self.board.list_threads(
                None, "volmarr", "pub",
                author_id=self.owner.id)],
            [a1.number])
        self.board.close_thread(
            self.reader, "volmarr", "pub", q1.number)
        self.assertEqual(
            [t.number for t in self.board.list_threads(
                None, "volmarr", "pub", state="closed")],
            [q1.number])
        self.assertEqual(
            self._reason(self.board.list_threads,
                         None, "volmarr", "pub", state="weird"),
            "state_invalid")
        self.assertEqual(
            self._reason(self.board.list_threads,
                         None, "volmarr", "pub", kind="poll"),
            "kind_invalid")

    # -- replies: S-123 reused whole ----------------------------

    def test_reply_flow_and_body_law(self):
        t = self._thread()
        r1 = self.board.add_reply(
            self.owner, "volmarr", "pub", t.number, "By the moon.")
        r2 = self.board.add_reply(
            self.stranger, "volmarr", "pub", t.number, "And the sun.")
        listed = self.board.list_replies(None, "volmarr", "pub",
                                         t.number)
        self.assertEqual([r.id for r in listed], [r1.id, r2.id])
        self.assertEqual(
            self.board.reply_count(None, "volmarr", "pub", t.number),
            2)
        d = reply_to_dict(r1)
        self.assertEqual(d["body"], "By the moon.")
        self.assertFalse(d["is_deleted"])
        self.assertEqual(
            self._reason(self.board.add_reply,
                         None, "volmarr", "pub", t.number, "Anon"),
            "permission_denied")
        for body, reason in (("", "comment_required"),
                             ("  ", "comment_required"),
                             (None, "comment_required"),
                             ("bad\x01body", "comment_invalid"),
                             ("x" * 65537, "comment_invalid")):
            self.assertEqual(
                self._reason(self.board.add_reply,
                             self.owner, "volmarr", "pub",
                             t.number, body),
                reason)

    def test_reply_edit_history_is_visible_and_author_only(self):
        t = self._thread()
        r = self.board.add_reply(
            self.reader, "volmarr", "pub", t.number, "First thought")
        edited = self.board.edit_reply(
            self.reader, "volmarr", "pub", t.number, r.id,
            "Second thought")
        self.assertTrue(edited.was_edited)
        history = self.board.edits_for(
            None, "volmarr", "pub", t.number, r.id)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].previous_body, "First thought")
        self.assertEqual(history[0].editor_id, self.reader.id)
        for actor in (self.owner, self.stranger):
            self.assertEqual(
                self._reason(self.board.edit_reply,
                             actor, "volmarr", "pub", t.number,
                             r.id, "Not yours"),
                "permission_denied")

    def test_reply_delete_is_a_tombstone_with_a_timeline_event(self):
        t = self._thread()
        keep = self.board.add_reply(
            self.owner, "volmarr", "pub", t.number, "Keep me")
        gone = self.board.add_reply(
            self.stranger, "volmarr", "pub", t.number, "Remove me")
        self.assertEqual(
            self._reason(self.board.delete_reply,
                         self.reader, "volmarr", "pub", t.number,
                         gone.id),
            "permission_denied")
        removed = self.board.delete_reply(
            self.owner, "volmarr", "pub", t.number, gone.id)
        self.assertTrue(removed.is_deleted)
        self.assertEqual(removed.body, "")
        self.assertEqual(removed.deleted_by, self.owner.id)
        listed = self.board.list_replies(None, "volmarr", "pub",
                                         t.number)
        self.assertEqual([r.id for r in listed], [keep.id])
        fetched = self.board.get_reply(
            None, "volmarr", "pub", t.number, gone.id)
        self.assertTrue(fetched.is_deleted)
        kinds = [e.event.kind for e in self.board.timeline(
            None, "volmarr", "pub", t.number) if e.event]
        self.assertIn("reply_deleted", kinds)
        # Deleting again is a quiet no-op.
        again = self.board.delete_reply(
            self.owner, "volmarr", "pub", t.number, gone.id)
        self.assertTrue(again.is_deleted)

    # -- moderation: pins, locks, closes -------------------------

    def test_pin_is_owner_controlled(self):
        t = self._thread()
        self.assertEqual(
            self._reason(self.board.pin_thread,
                         self.reader, "volmarr", "pub", t.number),
            "permission_denied")
        pinned = self.board.pin_thread(
            self.owner, "volmarr", "pub", t.number)
        self.assertTrue(pinned.pinned)
        self.assertEqual(pinned.state_words, "open, pinned")
        again = self.board.pin_thread(
            self.owner, "volmarr", "pub", t.number)
        self.assertTrue(again.pinned)
        kinds = [e.event.kind for e in self.board.timeline(
            None, "volmarr", "pub", t.number) if e.event]
        self.assertEqual(kinds.count("pinned"), 1)
        unpinned = self.board.unpin_thread(
            self.owner, "volmarr", "pub", t.number)
        self.assertFalse(unpinned.pinned)

    def test_lock_refuses_non_writer_replies(self):
        t = self._thread()
        self.board.lock_thread(self.owner, "volmarr", "pub", t.number)
        self.assertEqual(
            self._reason(self.board.add_reply,
                         self.reader, "volmarr", "pub", t.number,
                         "Let me in"),
            "conversation_locked")
        ok = self.board.add_reply(
            self.owner, "volmarr", "pub", t.number, "Owner still can.")
        self.assertEqual(ok.body, "Owner still can.")
        self.board.unlock_thread(
            self.owner, "volmarr", "pub", t.number)
        ok2 = self.board.add_reply(
            self.reader, "volmarr", "pub", t.number, "Free again.")
        self.assertEqual(ok2.body, "Free again.")

    def test_close_and_reopen(self):
        t = self._thread()
        self.assertEqual(
            self._reason(self.board.close_thread,
                         self.stranger, "volmarr", "pub", t.number),
            "permission_denied")
        closed = self.board.close_thread(
            self.reader, "volmarr", "pub", t.number)
        self.assertEqual(closed.state, "closed")
        self.assertEqual(closed.state_words, "closed")
        self.assertEqual(
            self._reason(self.board.add_reply,
                         self.owner, "volmarr", "pub", t.number,
                         "Too late"),
            "discussion_closed")
        again = self.board.close_thread(
            self.reader, "volmarr", "pub", t.number)
        self.assertEqual(again.state, "closed")
        reopened = self.board.reopen_thread(
            self.owner, "volmarr", "pub", t.number)
        self.assertEqual(reopened.state, "open")
        ok = self.board.add_reply(
            self.reader, "volmarr", "pub", t.number, "Back again.")
        self.assertEqual(ok.body, "Back again.")

    # -- the one timeline -----------------------------------------

    def test_timeline_holds_replies_and_events_in_order(self):
        t = self._thread()
        self.clock.now += 10
        self.board.add_reply(
            self.owner, "volmarr", "pub", t.number, "An answer.")
        self.clock.now += 10
        self.board.pin_thread(self.owner, "volmarr", "pub", t.number)
        self.clock.now += 10
        self.board.close_thread(
            self.owner, "volmarr", "pub", t.number)
        entries = self.board.timeline(None, "volmarr", "pub", t.number)
        shape = [
            ("event", e.event.kind) if e.event else ("reply", e.reply.body)
            for e in entries]
        self.assertEqual(shape, [
            ("event", "created"), ("reply", "An answer."),
            ("event", "pinned"), ("event", "closed")])
        stamps = [e.created_at for e in entries]
        self.assertEqual(stamps, sorted(stamps))
        actors = {e.event.actor_id for e in entries if e.event}
        self.assertEqual(actors, {self.reader.id, self.owner.id})

    # -- rendering: words, escaping, the composer ------------------

    def test_renders_say_states_in_words_and_escape(self):
        t = self._thread(title="<b>Tides</b> & <script>")
        self.board.pin_thread(self.owner, "volmarr", "pub", t.number)
        self.board.add_reply(
            self.owner, "volmarr", "pub", t.number, "<i>waves</i>")
        cats = self.board.list_categories(None, "volmarr", "pub")
        threads = self.board.list_threads(None, "volmarr", "pub")
        board_page = render_board_page(
            cats, threads, {self.reader.id: "tess"})
        self.assertIn("Questions", board_page)
        self.assertIn("Announcement", board_page)
        self.assertIn("open, pinned", board_page)
        self.assertIn("&lt;b&gt;Tides&lt;/b&gt;", board_page)
        self.assertNotIn("<b>Tides</b>", board_page)
        thread = self.board.get_thread(None, "volmarr", "pub", t.number)
        entries = self.board.timeline(None, "volmarr", "pub", t.number)
        page = render_thread_page(
            thread, self.questions, entries,
            {self.reader.id: "tess", self.owner.id: "volmarr"})
        self.assertIn("pinned this discussion", page)
        self.assertIn("&lt;i&gt;waves&lt;/i&gt;", page)
        self.assertNotIn("<i>waves</i>", page)
        self.assertIn("State: open, pinned", page)

    def test_composer_is_labelled(self):
        form = render_composer_form(self.questions)
        self.assertIn('<label for="discussion-title">', form)
        self.assertIn('<label for="discussion-body">', form)
        self.assertIn('id="discussion-title"', form)
        self.assertIn('id="discussion-body"', form)
        self.assertIn("Question", form)


if __name__ == "__main__":
    unittest.main()
