"""S-280 acceptance battery: gist comments.

Acceptance (roadmap S-280): Gist comments -- the
issue-comment machinery (S-123) reused, not duplicated.

The machinery is S-123's, in samverk/gist_comments.py
over S-277's GistStore: the body law is S-123's own
validator (comment_required / comment_invalid, the
one BODY_MAX cap), editing records the previous body
in migration 111's gist_comment_edits before the new
body lands and edits_for shows that history, and
deletion is a tombstone (body cleared, deleted_at /
deleted_by stamped, list views skip it). The tables
are migration 35's shape carried whole with gist_id
for issue_id (schema 110 -> 112).

Permissions ride the gist's, not a repository's:
reading follows S-278 -- public and secret alike are
readable by link, signed in or not, and an unknown
gist is the uniform gist_not_found for every comment
operation; commenting is a signed-in act; editing is
the author's alone; deletion is by the author, the
gist's owner (the moderator here), or a site admin.
Comments belong to the gist, not a revision: a file
edit moves none, a fork starts with none, and
deleting the gist deletes its conversation.

No new taxonomy event -- 133 stand (33 auth /
87 repo / 13 admin); gist acts unwitnessed, as
S-277's law, proven here against the audit log.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import dataclasses, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.gist_comments import (
    GistCommentStore, gist_comment_to_dict, render_gist_comments)
from samverk.gist_web import GistWeb, GistWebError
from samverk.gists import GistError, GistStore

PW = "correct horse battery"
T0 = 1_700_000_000


class Clock:
    def __init__(self, now=T0):
        self.now = now
    def __call__(self):
        return self.now


class GistCommentTests(unittest.TestCase):
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
        self.other = self.accounts.register("yrsa", PW)
        self.third = self.accounts.register("tess", PW)
        self.admin = dataclasses.replace(
            self.accounts.register("admina", PW), is_admin=True)
        self.gists = GistStore(
            self.conn, self.root, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.comments = GistCommentStore(
            self.conn, self.root, self.accounts, gists=self.gists,
            audit=self.audit, time_fn=self.clock)
        self.web = GistWeb(
            self.conn, self.root, self.accounts,
            gists=self.gists, comments=self.comments,
            audit=self.audit, time_fn=self.clock)
        self.gist = self.gists.create_gist(
            self.owner, "demo gist",
            {"hello.py": "print('hi')\n"}, visibility="public")
        self.secret = self.gists.create_gist(
            self.owner, "quiet gist",
            {"notes.md": "# Notes\n"}, visibility="secret")

    def _reason(self, fn, *a, **k):
        with self.assertRaises((GistError, GistWebError)) as ctx:
            fn(*a, **k)
        return ctx.exception.reason

    def _audit_count(self):
        return self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]

    # -- schema / taxonomy pins ---------------------------

    def test_schema_and_taxonomy_stand(self):
        self.assertEqual(schema_version(self.conn), 113)
        self.assertEqual(db.MIGRATIONS[-1][0], 113)
        self.assertEqual(db.migrate(self.conn), 113)
        from samverk.taxonomy import AUDIT_EVENTS
        self.assertEqual(len(AUDIT_EVENTS), 133)

    def test_comment_acts_are_unwitnessed(self):
        before = self._audit_count()
        c = self.comments.add_comment(self.other, self.gist.id, "Hi")
        self.comments.edit_comment(self.other, self.gist.id, c.id, "Ho")
        self.comments.delete_comment(self.other, self.gist.id, c.id)
        self.assertEqual(self._audit_count(), before)

    # -- create / read --------------------------------------

    def test_add_and_list_in_order(self):
        a = self.comments.add_comment(
            self.other, self.gist.id, "First **thought**")
        b = self.comments.add_comment(self.owner, self.gist.id, "Second")
        listed = self.comments.list_comments(None, self.gist.id)
        self.assertEqual([c.id for c in listed], [a.id, b.id])
        self.assertEqual(listed[0].body, "First **thought**")
        self.assertEqual(listed[0].author_id, self.other.id)
        self.assertEqual(listed[0].gist_id, self.gist.id)
        self.assertFalse(listed[0].was_edited)
        self.assertFalse(listed[0].is_deleted)
        self.assertEqual(
            self.comments.comment_count(None, self.gist.id), 2)
        d = gist_comment_to_dict(a)
        self.assertEqual(d["gist_id"], self.gist.id)
        self.assertEqual(d["body"], "First **thought**")

    def test_add_requires_signed_in(self):
        self.assertEqual(
            self._reason(self.comments.add_comment,
                         None, self.gist.id, "Anon"),
            "permission_denied")
        self.assertEqual(
            self.comments.list_comments(None, self.gist.id), [])

    def test_unknown_gist_is_uniform_not_found(self):
        c = self.comments.add_comment(self.other, self.gist.id, "Hi")
        for bad in (99999, "x", None):
            self.assertEqual(
                self._reason(self.comments.add_comment,
                             self.other, bad, "Hi"),
                "gist_not_found")
            self.assertEqual(
                self._reason(self.comments.list_comments, None, bad),
                "gist_not_found")
            self.assertEqual(
                self._reason(self.comments.get_comment, None, bad, c.id),
                "gist_not_found")
            self.assertEqual(
                self._reason(self.comments.edit_comment,
                             self.other, bad, c.id, "Ho"),
                "gist_not_found")
            self.assertEqual(
                self._reason(self.comments.delete_comment,
                             self.other, bad, c.id),
                "gist_not_found")

    def test_body_law_is_s123s(self):
        for body, reason in (("", "comment_required"),
                             ("  ", "comment_required"),
                             (None, "comment_required"),
                             ("bad\x01body", "comment_invalid"),
                             ("x" * 65537, "comment_invalid")):
            self.assertEqual(
                self._reason(self.comments.add_comment,
                             self.owner, self.gist.id, body),
                reason)
        ok = self.comments.add_comment(
            self.owner, self.gist.id, "x" * 65536)
        self.assertEqual(len(ok.body), 65536)

    def test_secret_gist_comments_ride_the_link(self):
        # S-278: a secret gist is unlisted, not private --
        # anyone signed in who reaches it by its link may
        # comment, and anyone may read the conversation.
        c = self.comments.add_comment(self.other, self.secret.id, "Seen")
        listed = self.comments.list_comments(None, self.secret.id)
        self.assertEqual([x.id for x in listed], [c.id])
        self.assertEqual(
            self._reason(self.comments.add_comment,
                         None, self.secret.id, "Anon"),
            "permission_denied")

    # -- edit -------------------------------------------------

    def test_edit_records_visible_history_and_is_author_only(self):
        c = self.comments.add_comment(self.other, self.gist.id, "Original")
        edited = self.comments.edit_comment(
            self.other, self.gist.id, c.id, "Revised")
        self.assertEqual(edited.body, "Revised")
        self.assertTrue(edited.was_edited)
        history = self.comments.edits_for(None, self.gist.id, c.id)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].previous_body, "Original")
        self.assertEqual(history[0].editor_id, self.other.id)
        self.comments.edit_comment(self.other, self.gist.id, c.id, "Third")
        self.assertEqual(
            [h.previous_body for h in
             self.comments.edits_for(None, self.gist.id, c.id)],
            ["Original", "Revised"])
        # Not even the gist's owner may edit another's words.
        for actor in (self.owner, self.admin, self.third):
            self.assertEqual(
                self._reason(self.comments.edit_comment,
                             actor, self.gist.id, c.id, "Hijack"),
                "permission_denied")
        self.assertEqual(
            self._reason(self.comments.edit_comment,
                         None, self.gist.id, c.id, "Hijack"),
            "permission_denied")
        self.assertEqual(
            self._reason(self.comments.edit_comment,
                         self.other, self.gist.id, c.id, ""),
            "comment_required")

    # -- delete -------------------------------------------------

    def test_delete_by_author_tombstones(self):
        c = self.comments.add_comment(self.other, self.gist.id, "Regret")
        deleted = self.comments.delete_comment(
            self.other, self.gist.id, c.id)
        self.assertTrue(deleted.is_deleted)
        self.assertEqual(deleted.body, "")
        self.assertEqual(deleted.deleted_by, self.other.id)
        self.assertEqual(self.comments.list_comments(None, self.gist.id), [])
        self.assertEqual(
            self.comments.comment_count(None, self.gist.id), 0)
        tomb = self.comments.get_comment(None, self.gist.id, c.id)
        self.assertTrue(tomb.is_deleted)
        self.assertEqual(
            self._reason(self.comments.delete_comment,
                         self.other, self.gist.id, c.id),
            "comment_not_found")
        self.assertEqual(
            self._reason(self.comments.edit_comment,
                         self.other, self.gist.id, c.id, "Again"),
            "comment_not_found")

    def test_delete_by_owner_or_admin_not_by_stranger(self):
        c = self.comments.add_comment(self.other, self.gist.id, "Abusive")
        self.assertEqual(
            self._reason(self.comments.delete_comment,
                         self.third, self.gist.id, c.id),
            "permission_denied")
        self.assertEqual(
            self._reason(self.comments.delete_comment,
                         None, self.gist.id, c.id),
            "permission_denied")
        by_owner = self.comments.delete_comment(
            self.owner, self.gist.id, c.id)
        self.assertEqual(by_owner.deleted_by, self.owner.id)
        c2 = self.comments.add_comment(self.other, self.gist.id, "More")
        by_admin = self.comments.delete_comment(
            self.admin, self.gist.id, c2.id)
        self.assertEqual(by_admin.deleted_by, self.admin.id)

    def test_comment_ids_do_not_cross_gists(self):
        c = self.comments.add_comment(self.other, self.gist.id, "On one")
        for fn, extra in ((self.comments.get_comment, ()),
                          (self.comments.edits_for, ()),
                          (self.comments.edit_comment, ("Ho",)),
                          (self.comments.delete_comment, ())):
            self.assertEqual(
                self._reason(fn, self.other, self.secret.id, c.id, *extra),
                "comment_not_found")
        self.assertEqual(
            self._reason(self.comments.get_comment,
                         None, self.gist.id, 99999),
            "comment_not_found")

    # -- conversation vs revisions / forks / deletion -----------

    def test_comments_survive_file_edits(self):
        c = self.comments.add_comment(self.other, self.gist.id, "Standing")
        self.gists.update_gist(
            self.owner, self.gist.id,
            files={"hello.py": "print('v2')\n"}, message="v2")
        listed = self.comments.list_comments(None, self.gist.id)
        self.assertEqual([x.id for x in listed], [c.id])

    def test_fork_starts_with_no_comments(self):
        self.comments.add_comment(self.other, self.gist.id, "On source")
        fork = self.gists.fork_gist(self.third, self.gist.id)
        self.assertEqual(self.comments.list_comments(None, fork.id), [])
        self.assertEqual(
            len(self.comments.list_comments(None, self.gist.id)), 1)

    def test_deleting_gist_deletes_its_conversation(self):
        c = self.comments.add_comment(self.other, self.gist.id, "Bye")
        self.comments.edit_comment(self.other, self.gist.id, c.id, "Bye!")
        self.gists.delete_gist(self.owner, self.gist.id)
        for table in ("gist_comments", "gist_comment_edits"):
            n = self.conn.execute(
                f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            self.assertEqual(n, 0, table)
        self.assertEqual(
            self._reason(self.comments.list_comments, None, self.gist.id),
            "gist_not_found")

    # -- rendering ---------------------------------------------------

    def test_render_escapes_and_marks_edited(self):
        c = self.comments.add_comment(
            self.other, self.gist.id, "<script>alert(1)</script>")
        self.comments.edit_comment(
            self.other, self.gist.id, c.id, "<b>bold</b> & raw")
        html = render_gist_comments(
            self.comments.list_comments(None, self.gist.id),
            {self.other.id: "yrsa<admin>"})
        self.assertNotIn("<script>", html)
        self.assertNotIn("<b>bold</b>", html)
        self.assertIn("&lt;b&gt;bold&lt;/b&gt; &amp; raw", html)
        self.assertIn("yrsa&lt;admin&gt;", html)
        self.assertIn("edited", html)
        self.assertIn("No comments on this gist yet.",
                      render_gist_comments([]))

    # -- web face -------------------------------------------------------

    def test_web_face_passes_and_translates(self):
        c = self.web.add_comment(self.other, self.gist.id, "Via web")
        listed = self.web.list_comments(None, self.gist.id)
        self.assertEqual([x.id for x in listed], [c.id])
        self.assertEqual(
            [h.previous_body for h in
             self.web.comment_edits(None, self.gist.id, c.id)], [])
        self.web.edit_comment(self.other, self.gist.id, c.id, "Edited")
        self.assertEqual(
            self.web.comment_count(None, self.gist.id), 1)
        self.assertEqual(
            self._reason(self.web.add_comment, None, self.gist.id, "x"),
            "permission_denied")
        self.assertEqual(
            self._reason(self.web.add_comment, self.other, 99999, "x"),
            "gist_not_found")
        self.web.delete_comment(self.owner, self.gist.id, c.id)
        self.assertEqual(self.web.list_comments(None, self.gist.id), [])

    def test_web_view_carries_the_conversation(self):
        self.web.add_comment(
            self.other, self.gist.id, "Shown <here>")
        view = self.web.view_gist(None, self.gist.id)
        self.assertEqual(view.comment_count, 1)
        self.assertEqual(len(view.comments), 1)
        from samverk.gist_web import render_gist_view_page
        page = render_gist_view_page(view)
        self.assertIn("Shown &lt;here&gt;", page)
        self.assertIn("Comments: 1", page)
        self.assertIn("yrsa", page)


if __name__ == "__main__":
    unittest.main()
