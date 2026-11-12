"""S-278 acceptance battery: gist create and edit.

Acceptance (roadmap S-278): Gist create and edit --
web editor, public or secret (unlisted-but-linkable,
honestly named -- "secret" gists are not private
and the UI says so).

The face is samverk/gist_web.py (GistWeb) over
S-277's GistStore; the choice itself lives in the
store (samverk/gists.py): migration 109's
`visibility` column (schema 108 -> 109), judged by
validate_visibility. A public gist is listed for
everyone and readable by anyone; a secret gist is
unlisted in every listing but its owner's, yet
readable in full by anyone who has the link -- and
every face that offers or reports the choice
carries the store's honest words, SECRET_WORDS
saying plainly that a secret gist is not private.
The editor loads the standing file set with the tip
it read (expected_oid) and saves the full set as
one revision, so a moved gist answers gist_conflict
whole. No new taxonomy event -- 133 stand.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import dataclasses, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.gist_web import (
    GistWeb, GistWebError, editor_files_to_mapping,
    render_gist_create_form, render_gist_edit_form,
    render_gist_list_page, render_gist_view_page)
from samverk.gists import (
    PUBLIC_WORDS, SECRET_WORDS, GistError, GistStore,
    validate_visibility, visibility_words)

PW = "correct horse battery"
T0 = 1_700_000_000


class Clock:
    def __init__(self, now=T0):
        self.now = now
    def __call__(self):
        return self.now


class GistEditorTests(unittest.TestCase):
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
        self.gists = GistStore(
            self.conn, self.root, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.web = GistWeb(
            self.conn, self.root, self.accounts,
            gists=self.gists, audit=self.audit,
            time_fn=self.clock)

    def _reason(self, fn, *a, **k):
        with self.assertRaises((GistError, GistWebError)) as ctx:
            fn(*a, **k)
        return ctx.exception.reason

    def _make(self, visibility="public", description="demo"):
        return self.web.create_gist(
            self.owner, description, visibility,
            [("hello.py", "print('hi')\n"),
             ("notes.md", "# Notes\n")])

    # -- schema / taxonomy pins ---------------------------

    def test_schema_and_taxonomy_stand(self):
        self.assertEqual(schema_version(self.conn), 114)
        self.assertEqual(db.MIGRATIONS[-1][0], 114)
        self.assertEqual(db.migrate(self.conn), 114)
        from samverk.taxonomy import AUDIT_EVENTS
        self.assertEqual(len(AUDIT_EVENTS), 133)

    def test_pre_s278_rows_default_to_secret(self):
        # A row written the S-277 way (no visibility
        # named) stands as 'secret' -- the narrower
        # widening, never silently public.
        cur = self.conn.execute(
            "INSERT INTO gists (owner_id, description,"
            " created_at, updated_at) VALUES (?, '', ?, ?)",
            (self.owner.id, T0, T0))
        self.conn.commit()
        row = self.conn.execute(
            "SELECT visibility FROM gists WHERE id = ?",
            (cur.lastrowid,)).fetchone()
        self.assertEqual(row["visibility"], "secret")

    # -- the choice, judged --------------------------------

    def test_visibility_is_judged(self):
        self.assertEqual(validate_visibility("public"), "public")
        self.assertEqual(validate_visibility("secret"), "secret")
        for bad in ("private", "hidden", "", None, "PUBLIC"):
            self.assertEqual(
                self._reason(validate_visibility, bad),
                "visibility_invalid", bad)
        self.assertEqual(
            self._reason(self.gists.create_gist, self.owner,
                         "d", {"a.txt": "a"},
                         visibility="private"),
            "visibility_invalid")

    def test_honest_words(self):
        self.assertIn("not private", SECRET_WORDS)
        self.assertIn("anyone who has the link can read",
                      SECRET_WORDS)
        self.assertEqual(visibility_words("secret"), SECRET_WORDS)
        self.assertEqual(visibility_words("public"), PUBLIC_WORDS)

    # -- public reading --------------------------------------

    def test_public_gist_readable_and_listed_for_all(self):
        gist = self._make("public")
        for viewer in (None, self.other, self.owner):
            view = self.web.view_gist(viewer, gist.id)
            self.assertEqual(view.gist.visibility, "public")
            self.assertEqual(
                [f.name for f in view.files],
                ["hello.py", "notes.md"])
            self.assertEqual(view.files[0].content, "print('hi')\n")
            self.assertEqual(
                [g.id for g in self.web.list_gists(
                    viewer, "volmarr")], [gist.id])
        self.assertFalse(self.web.view_gist(None, gist.id).can_edit)
        self.assertTrue(
            self.web.view_gist(self.owner, gist.id).can_edit)

    # -- secret: unlisted but linkable ------------------------

    def test_secret_gist_unlisted_but_linkable(self):
        gist = self._make("secret")
        for viewer in (None, self.other):
            # Unlisted for everyone but the owner...
            self.assertEqual(
                self.web.list_gists(viewer, "volmarr"), [])
            # ...yet readable in full by the link.
            view = self.web.view_gist(viewer, gist.id)
            self.assertEqual(view.gist.visibility, "secret")
            self.assertEqual(view.files[1].content, "# Notes\n")
            self.assertEqual(
                self.gists.read_file(
                    viewer, gist.id, "hello.py").content,
                "print('hi')\n")
            self.assertEqual(
                len(self.gists.list_revisions(viewer, gist.id)), 1)
        self.assertEqual(
            [g.id for g in self.web.list_gists(
                self.owner, "volmarr")], [gist.id])
        admin = dataclasses.replace(self.other, is_admin=True)
        self.assertEqual(
            [g.id for g in self.web.list_gists(admin, "volmarr")],
            [gist.id])

    def test_mixed_listing_shows_strangers_public_only(self):
        pub = self._make("public", "open one")
        self._make("secret", "quiet one")
        self.assertEqual(
            [g.id for g in self.web.list_gists(None, "volmarr")],
            [pub.id])
        self.assertEqual(
            len(self.web.list_gists(self.owner, "volmarr")), 2)

    # -- editor create ----------------------------------------

    def test_editor_create_requires_sign_in(self):
        self.assertEqual(
            self._reason(self.web.create_gist, None, "d",
                         "public", [("a.txt", "a")]),
            "permission_denied")

    def test_editor_rows_become_the_file_set(self):
        self.assertEqual(
            editor_files_to_mapping([("a.txt", "1"), ("B.py", "2")]),
            {"a.txt": "1", "B.py": "2"})
        self.assertEqual(
            self._reason(editor_files_to_mapping,
                         [("A.txt", "1"), ("a.txt", "2")]),
            "file_duplicate")
        self.assertEqual(
            self._reason(editor_files_to_mapping, "nope"),
            "file_invalid")
        self.assertEqual(
            self._reason(self.web.create_gist, self.owner, "d",
                         "public", []),
            "files_empty")
        self.assertEqual(
            self._reason(self.web.create_gist, self.owner, "d",
                         "public", [("a/b.txt", "x")]),
            "filename_invalid")

    # -- editor edit --------------------------------------------

    def test_edit_view_loads_standing_set_and_tip(self):
        gist = self._make("secret")
        view = self.web.edit_view(self.owner, gist.id)
        self.assertEqual(view.expected_oid, gist.head_oid)
        self.assertEqual(view.gist.visibility, "secret")
        self.assertEqual(
            [(f.name, f.content) for f in view.files],
            [("hello.py", "print('hi')\n"),
             ("notes.md", "# Notes\n")])
        self.assertEqual(
            self._reason(self.web.edit_view, self.other, gist.id),
            "permission_denied")
        self.assertEqual(
            self._reason(self.web.edit_view, None, gist.id),
            "permission_denied")

    def test_save_replaces_set_in_one_revision(self):
        gist = self._make("public")
        view = self.web.edit_view(self.owner, gist.id)
        saved = self.web.save_gist(
            self.owner, gist.id,
            pairs=[("hello.py", "print('v2')\n")],
            message="Trim to one file",
            expected_oid=view.expected_oid)
        self.assertEqual(saved.revision_count, 2)
        after = self.web.view_gist(self.owner, gist.id)
        self.assertEqual([f.name for f in after.files], ["hello.py"])
        self.assertEqual(after.files[0].content, "print('v2')\n")

    def test_save_conflict_refused_whole(self):
        gist = self._make("public")
        view = self.web.edit_view(self.owner, gist.id)
        self.gists.update_gist(
            self.owner, gist.id, files={"hello.py": "moved\n"})
        self.assertEqual(
            self._reason(self.web.save_gist, self.owner, gist.id,
                         pairs=[("hello.py", "stale\n")],
                         expected_oid=view.expected_oid),
            "gist_conflict")
        self.assertEqual(
            self.gists.read_file(
                self.owner, gist.id, "hello.py").content, "moved\n")

    def test_visibility_change_is_metadata_only(self):
        gist = self._make("public")
        self.clock.now = T0 + 30
        saved = self.web.save_gist(
            self.owner, gist.id, visibility="secret")
        self.assertEqual(saved.visibility, "secret")
        self.assertEqual(saved.revision_count, 1)
        self.assertEqual(saved.head_oid, gist.head_oid)
        self.assertEqual(saved.updated_at, T0 + 30)
        self.assertEqual(
            self.web.list_gists(None, "volmarr"), [])
        back = self.web.save_gist(
            self.owner, gist.id, visibility="public")
        self.assertEqual(back.revision_count, 1)
        self.assertEqual(
            self._reason(self.web.save_gist, self.other, gist.id,
                         visibility="public"),
            "permission_denied")
        self.assertEqual(
            self._reason(self.web.save_gist, self.owner, gist.id),
            "update_empty")

    # -- faces ---------------------------------------------------

    def test_create_and_edit_forms_carry_honest_words(self):
        form = render_gist_create_form()
        self.assertIn("not private", form)
        self.assertIn("anyone who has the link can read", form)
        self.assertIn('value="public" checked', form)
        self.assertIn('value="secret"', form)
        gist = self._make("secret", "<b>desc</b>")
        edit = render_gist_edit_form(
            self.web.edit_view(self.owner, gist.id))
        self.assertIn("not private", edit)
        self.assertIn('value="secret" checked', edit)
        self.assertIn("&lt;b&gt;desc&lt;/b&gt;", edit)
        self.assertIn('name="expected_oid"', edit)
        self.assertIn(gist.head_oid, edit)

    def test_view_page_escapes_and_warns(self):
        gist = self.web.create_gist(
            self.owner, "<script>alert(1)</script>", "secret",
            [("x.html", "<script>alert(2)</script>")])
        html = render_gist_view_page(self.web.view_gist(None, gist.id))
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertNotIn("<script>alert(2)</script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("not private", html)
        self.assertIn("Secret", html)
        pub = self._make("public")
        pub_html = render_gist_view_page(
            self.web.view_gist(None, pub.id))
        self.assertIn("Public", pub_html)
        self.assertNotIn("not private", pub_html)

    def test_list_page_names_visibility(self):
        self._make("public", "open one")
        html = render_gist_list_page(
            "volmarr", self.web.list_gists(None, "volmarr"))
        self.assertIn("open one", html)
        self.assertIn("[public]", html)
        empty = render_gist_list_page("volmarr", [])
        self.assertIn("unlisted", empty)


if __name__ == "__main__":
    unittest.main()
