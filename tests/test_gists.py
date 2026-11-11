"""S-277 acceptance battery: gist model.

Acceptance (roadmap S-277): Gist model -- a gist is
a mini-repository: multiple files, full revision
history, one description.

The centre is samverk/gists.py: GistStore. A gist
stands alone as `<data_root>/gists/<owner>/<id>.git`,
created by `git init --bare` at creation; migration
108's `gists` table holds the owner, the one
description, and the stamps. Files are flat text
under one filename law (separators / `..` / leading
dot refused, identity case-insensitive), each
file-set change is one plumbing commit guarded by an
expected-tip conflict (gist_conflict), and the
history is the gist repo's own git log. S-278 has
since landed the public/secret choice on this model
(see tests/test_gist_editor.py): reads by link are
open, listings show secret gists to their owner
only. No new taxonomy event -- 133 stand;
schema 108 -> 109 (S-278's visibility column).

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import dataclasses, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.gists import (
    DESCRIPTION_MAX, FILE_MAX, GistError, GistStore,
    gist_to_dict, render_gist, render_gist_list,
    validate_description, validate_filename, validate_files)
from test_repo_home import run_git

PW = "correct horse battery"
T0 = 1_700_000_000


class Clock:
    def __init__(self, now=T0):
        self.now = now
    def __call__(self):
        return self.now


class GistModelTests(unittest.TestCase):
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

    def _reason(self, fn, *a, **k):
        with self.assertRaises(GistError) as ctx:
            fn(*a, **k)
        return ctx.exception.reason

    def _make(self, description="demo gist", files=None):
        return self.gists.create_gist(
            self.owner, description,
            files if files is not None else {
                "hello.py": "print('hi')\n", "notes.md": "# Notes\n"})

    # -- schema / taxonomy pins ---------------------------

    def test_schema_and_taxonomy_stand(self):
        self.assertEqual(schema_version(self.conn), 109)
        self.assertEqual(db.MIGRATIONS[-1][0], 109)
        self.assertEqual(db.migrate(self.conn), 109)
        from samverk.taxonomy import AUDIT_EVENTS
        self.assertEqual(len(AUDIT_EVENTS), 133)

    # -- creation ------------------------------------------

    def test_create_requires_signed_in(self):
        self.assertEqual(
            self._reason(self.gists.create_gist,
                         None, "x", {"a.txt": "a"}),
            "permission_denied")

    def test_create_makes_bare_repo_and_first_revision(self):
        gist = self._make()
        path = self.root / "gists" / "volmarr" / f"{gist.id}.git"
        self.assertTrue(path.is_dir())
        self.assertEqual(self.gists.gist_path(gist.id), path)
        out = subprocess.run(
            ["git", f"--git-dir={path}", "rev-parse",
             "--is-bare-repository"],
            capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "true")
        self.assertEqual(gist.owner, "volmarr")
        self.assertEqual(gist.description, "demo gist")
        self.assertEqual(gist.revision_count, 1)
        self.assertIsNotNone(gist.head_oid)
        self.assertEqual(gist.created_at, T0)

    def test_gist_is_stock_git_cloneable(self):
        gist = self._make()
        work = self.root / "clone"
        run_git(self.root, "clone",
                str(self.gists.gist_path(gist.id)), str(work))
        self.assertEqual(
            (work / "hello.py").read_text(), "print('hi')\n")
        self.assertEqual(
            (work / "notes.md").read_text(), "# Notes\n")

    def test_multiple_files_round_trip(self):
        gist = self._make(files={
            "b.txt": "second", "A.txt": "first", "c.py": "third"})
        files = self.gists.list_files(self.owner, gist.id)
        self.assertEqual(
            [f.name for f in files], ["A.txt", "b.txt", "c.py"])
        read = self.gists.read_file(self.owner, gist.id, "b.txt")
        self.assertEqual(read.content, "second")
        self.assertEqual(read.size, 6)
        # File identity is case-insensitive.
        self.assertEqual(
            self.gists.read_file(self.owner, gist.id, "B.TXT").name,
            "b.txt")

    # -- the one description --------------------------------

    def test_description_is_one_and_validated(self):
        self.assertEqual(validate_description(""), "")
        self.assertEqual(
            self._reason(validate_description, None),
            "description_invalid")
        self.assertEqual(
            self._reason(validate_description,
                         "x" * (DESCRIPTION_MAX + 1)),
            "description_invalid")
        gist = self._make(description="before")
        self.clock.now = T0 + 60
        updated = self.gists.update_gist(
            self.owner, gist.id, description="after")
        self.assertEqual(updated.description, "after")
        self.assertEqual(updated.updated_at, T0 + 60)
        # A description edit is metadata: no new revision.
        self.assertEqual(updated.revision_count, 1)
        self.assertEqual(updated.head_oid, gist.head_oid)

    # -- filename / file-set law -----------------------------

    def test_filename_law(self):
        for bad in ("../evil.txt", "a/b.txt", "a\\b.txt",
                    ".hidden", "trail.", "", "a..b", "sp ace.txt"):
            self.assertEqual(
                self._reason(validate_filename, bad),
                "filename_invalid", bad)
        self.assertEqual(
            validate_filename("ok-1_file.md"), "ok-1_file.md")

    def test_file_set_law(self):
        self.assertEqual(
            self._reason(validate_files, {}), "files_empty")
        self.assertEqual(
            self._reason(validate_files, {"a.txt": 3}), "file_invalid")
        self.assertEqual(
            self._reason(validate_files,
                         {"A.txt": "x", "a.txt": "y"}),
            "file_duplicate")
        self.assertEqual(
            self._reason(validate_files,
                         {"big.txt": "x" * (FILE_MAX + 1)}),
            "file_too_large")
        self.assertEqual(
            self._reason(self.gists.create_gist,
                         self.owner, "d", {}), "files_empty")

    # -- revision history ------------------------------------

    def test_full_revision_history(self):
        gist = self._make()
        first = gist.head_oid
        self.gists.update_gist(
            self.owner, gist.id,
            files={"hello.py": "print('v2')\n", "notes.md": "# N\n"},
            message="Second revision")
        self.gists.update_gist(
            self.owner, gist.id,
            files={"hello.py": "print('v3')\n"},
            message="Third revision")
        view = self.gists.get_gist(self.owner, gist.id)
        self.assertEqual(view.revision_count, 3)
        revs = self.gists.list_revisions(self.owner, gist.id)
        self.assertEqual(len(revs), 3)
        self.assertEqual(revs[0].oid, view.head_oid)
        self.assertEqual(revs[0].message, "Third revision")
        self.assertEqual(revs[0].parent_oid, revs[1].oid)
        self.assertEqual(revs[1].parent_oid, revs[2].oid)
        self.assertIsNone(revs[2].parent_oid)
        self.assertEqual(revs[2].oid, first)
        self.assertEqual(revs[2].author, "volmarr")

    def test_read_file_at_revision(self):
        gist = self._make()
        first = gist.head_oid
        self.gists.update_gist(
            self.owner, gist.id,
            files={"hello.py": "print('new')\n", "notes.md": "# Notes\n"})
        old = self.gists.read_file(
            self.owner, gist.id, "hello.py", revision=first)
        self.assertEqual(old.content, "print('hi')\n")
        self.assertEqual(old.commit_oid, first)
        names = [f.name for f in self.gists.list_files(
            self.owner, gist.id, revision=first)]
        self.assertEqual(names, ["hello.py", "notes.md"])
        self.assertEqual(
            self._reason(self.gists.read_file, self.owner, gist.id,
                         "hello.py", revision="deadbeef"),
            "revision_not_found")

    def test_update_replaces_whole_set_in_one_commit(self):
        gist = self._make()
        updated = self.gists.update_gist(
            self.owner, gist.id,
            files={"only.txt": "the one file"})
        self.assertEqual(updated.revision_count, 2)
        self.assertEqual(
            [f.name for f in self.gists.list_files(self.owner, gist.id)],
            ["only.txt"])
        self.assertEqual(
            self._reason(self.gists.read_file,
                         self.owner, gist.id, "hello.py"),
            "file_not_found")

    def test_expected_tip_conflict(self):
        gist = self._make()
        self.gists.update_gist(
            self.owner, gist.id, files={"a.txt": "moved"})
        self.assertEqual(
            self._reason(self.gists.update_gist, self.owner, gist.id,
                         files={"a.txt": "stale"},
                         expected_oid=gist.head_oid),
            "gist_conflict")
        ok = self.gists.update_gist(
            self.owner, gist.id, files={"a.txt": "fresh"},
            expected_oid=self.gists.get_gist(self.owner, gist.id).head_oid)
        self.assertEqual(ok.revision_count, 3)

    def test_update_empty_refused(self):
        gist = self._make()
        self.assertEqual(
            self._reason(self.gists.update_gist, self.owner, gist.id),
            "update_empty")

    # -- permissions ------------------------------------------

    def test_strangers_see_nothing(self):
        # S-278 restates this S-277 law: a secret gist
        # is unlisted for strangers (it stands in no
        # listing but its owner's), though it stays
        # readable by its link -- unlisted-but-linkable,
        # never private. An unknown id is still the
        # uniform gist_not_found for every viewer.
        gist = self.gists.create_gist(
            self.owner, "quiet", {"a.txt": "a"},
            visibility="secret")
        for viewer in (None, self.other):
            self.assertEqual(
                self.gists.list_gists(viewer, "volmarr"), [])
            self.assertEqual(
                self.gists.get_gist(viewer, gist.id).id, gist.id)
        self.assertEqual(
            [g.id for g in self.gists.list_gists(
                self.owner, "volmarr")], [gist.id])
        self.assertEqual(
            self._reason(self.gists.get_gist, self.owner, 99999),
            "gist_not_found")
        self.assertEqual(
            self._reason(self.gists.list_gists,
                         self.owner, "nosuchuser"),
            "gist_not_found")

    def test_only_owner_writes(self):
        gist = self._make()
        self.assertEqual(
            self._reason(self.gists.update_gist, self.other, gist.id,
                         description="hijack"),
            "permission_denied")
        self.assertEqual(
            self._reason(self.gists.delete_gist, self.other, gist.id),
            "permission_denied")
        self.assertEqual(
            self._reason(self.gists.update_gist, None, gist.id,
                         description="anon"),
            "permission_denied")

    def test_admin_may_read(self):
        gist = self._make()
        admin = dataclasses.replace(self.other, is_admin=True)
        self.assertEqual(
            self.gists.get_gist(admin, gist.id).id, gist.id)

    def test_list_gists_for_owner(self):
        self._make(description="one")
        self.clock.now = T0 + 10
        self._make(description="two")
        listed = self.gists.list_gists(self.owner, "volmarr")
        self.assertEqual(
            [g.description for g in listed], ["two", "one"])
        self.assertEqual(self.gists.list_gists(self.other, "yrsa"), [])

    # -- deletion ----------------------------------------------

    def test_delete_removes_row_and_repo(self):
        gist = self._make()
        path = self.gists.gist_path(gist.id)
        before = self.gists.delete_gist(self.owner, gist.id)
        self.assertEqual(before.id, gist.id)
        self.assertFalse(path.exists())
        self.assertEqual(
            self._reason(self.gists.get_gist, self.owner, gist.id),
            "gist_not_found")
        self.assertEqual(self.gists.list_gists(self.owner, "volmarr"), [])

    # -- faces ---------------------------------------------------

    def test_dict_and_render_escape(self):
        gist = self._make(description="<script>alert(1)</script>")
        files = self.gists.list_files(self.owner, gist.id)
        data = gist_to_dict(gist, files)
        self.assertEqual(data["description"], "<script>alert(1)</script>")
        self.assertEqual(data["revision_count"], 1)
        self.assertEqual(len(data["files"]), 2)
        html = render_gist(gist, files)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("1 revision(s)", html)
        listing = render_gist_list([gist])
        self.assertIn("&lt;script&gt;", listing)
        self.assertIn("No gists yet", render_gist_list([]))


if __name__ == "__main__":
    unittest.main()
