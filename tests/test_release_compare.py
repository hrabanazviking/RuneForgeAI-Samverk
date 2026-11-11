"""S-270 acceptance battery: compare-in-release.

Acceptance (roadmap S-270): Compare-in-release —
release notes can embed the compare range (S-105)
between the previous tag and this one.

The centre is samverk/release_compare.py:
ReleaseCompareStore with no migration and no new
taxonomy event (schema 106, 133 events stand).
The previous tag is S-269's previous version tag
for a version tag, else the newest earlier release
whose target is an ancestor; the range itself is
S-105's CompareService.compare unchanged. Embedding
is explicit, marked (COMPARE_MARKER), placeholder-
aware ({{compare}}), and once — a second embed is
refused compare_already_embedded. Reads resolve
through the release's own S-257/S-258 gate; the
write rides S-257's update_release (writer only,
flags unmoved, notes limit enforced, unwitnessed).

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
from samverk.compare_view import CompareService
from samverk.db import schema_version
from samverk.release_compare import (
    COMPARE_MARKER, EMBED_PLACEHOLDER, ReleaseCompare,
    ReleaseCompareError, ReleaseCompareStore,
    build_compare_section, compare_to_dict, embed_compare,
    has_embedded_compare, render_compare_section)
from samverk.releases import Release, ReleaseStore
from samverk.repositories import RepositoryStore
from test_repo_home import run_git

PW = "correct horse battery"
T0 = 1_700_000_000


class Clock:
    def __init__(self, now=T0):
        self.now = now
    def __call__(self):
        return self.now


class ReleaseCompareTests(unittest.TestCase):
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
        self.reader = self.accounts.register("yrsa", PW)
        self.stranger = self.accounts.register("mallory", PW)
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.releases = ReleaseStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.store = ReleaseCompareStore(
            self.conn, self.repos, self.releases,
            self.accounts, audit=self.audit, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        self.bare = self.repos.path_for("volmarr", "pub")
        self.work = self.root / "work"; self.work.mkdir()
        run_git(self.work, "init", "-b", "main")
        # c1 tagged v1.0; c2, c3 land after (c3 tagged v1.1);
        # c4 tagged v1.2 and "party"; c5 tagged v1.3 and
        # carries markup in its subject.
        self.c1 = self._commit(
            {"a.txt": "one\n"}, "first")
        self._tag("v1.0")
        self.c2 = self._commit(
            {"a.txt": "one\ntwo\n", "b.txt": "bee\n"}, "second")
        self.c3 = self._commit(
            {"a.txt": "one\ntwo\nthree\n"}, "third")
        self._tag("v1.1")
        self.c4 = self._commit({"c.txt": "see\n"}, "fourth")
        self._tag("v1.2")
        self._tag("party")
        self.c5 = self._commit(
            {"a.txt": "one\ntwo\nthree\nfour <x>\n"},
            "fifth <evil>")
        self._tag("v1.3")

    def _commit(self, files, msg):
        for rel, text in files.items():
            (self.work / rel).write_text(text)
        run_git(self.work, "add", "-A")
        run_git(self.work, "commit", "-m", msg)
        return run_git(self.work, "rev-parse", "HEAD").strip()

    def _tag(self, tag):
        run_git(self.work, "tag", tag)
        run_git(self.work, "push", str(self.bare), tag)

    def _release(self, tag, notes="Hand notes.\n", **kw):
        return self.releases.create_release(
            self.owner, "volmarr", "pub", tag, tag, notes, **kw)

    # -- pins ------------------------------------------------------

    def test_pins_schema_107_taxonomy_133(self):
        self.assertEqual(schema_version(self.conn), 107)
        self.assertEqual(db.MIGRATIONS[-1][0], 107)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 133)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 87)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)

    # -- the previous tag ------------------------------------------

    def test_previous_tag_for_version_tags_is_s269s(self):
        self._release("v1.0"); self._release("v1.1")
        self._release("v1.2")
        self.assertEqual(self.store.previous_tag(
            self.owner, "volmarr", "pub", "v1.2"), "v1.1")
        self.assertEqual(self.store.previous_tag(
            self.owner, "volmarr", "pub", "v1.1"), "v1.0")
        self.assertIsNone(self.store.previous_tag(
            self.owner, "volmarr", "pub", "v1.0"))

    def test_previous_tag_for_plain_tag_is_previous_release(self):
        # "party" stands at c4, the same commit as v1.2:
        # its own target can never be its previous, so
        # the newest ancestor release before it rules.
        self._release("v1.0"); self._release("v1.1")
        self._release("v1.2"); self._release("party")
        self.assertEqual(self.store.previous_tag(
            self.owner, "volmarr", "pub", "party"), "v1.1")

    def test_previous_tag_none_when_no_earlier_release(self):
        self._release("party")
        self.assertIsNone(self.store.previous_tag(
            self.owner, "volmarr", "pub", "party"))

    # -- the compare ------------------------------------------------

    def test_compare_for_release_matches_s105(self):
        self._release("v1.0"); self._release("v1.1")
        rc = self.store.compare_for_release(
            self.owner, "volmarr", "pub", "v1.1")
        self.assertEqual(rc.tag, "v1.1")
        self.assertEqual(rc.previous_tag, "v1.0")
        self.assertTrue(rc.has_previous)
        self.assertEqual(rc.range_words, "v1.0…v1.1")
        view = rc.compare
        self.assertEqual((view.ahead, view.behind), (2, 0))
        self.assertEqual(
            [c.subject for c in view.commits], ["third", "second"])
        self.assertEqual(view.files_changed, 2)
        self.assertEqual(
            (view.diff.additions, view.diff.deletions), (3, 0))
        direct = CompareService(self.repos).compare(
            self.owner, "volmarr", "pub", "v1.0", "v1.1")
        self.assertEqual(
            (view.base_oid, view.head_oid, view.ahead),
            (direct.base_oid, direct.head_oid, direct.ahead))

    def test_compare_first_tag_is_honestly_empty(self):
        self._release("v1.0")
        rc = self.store.compare_for_release(
            self.owner, "volmarr", "pub", "v1.0")
        self.assertIsNone(rc.previous_tag)
        self.assertIsNone(rc.compare)
        self.assertFalse(rc.has_previous)
        self.assertIn("No previous tag stands", rc.range_words)
        data = compare_to_dict(rc)
        self.assertIsNone(data["previous_tag"])
        self.assertIsNone(data["ahead"])
        self.assertEqual(data["commits"], [])

    def test_compare_to_dict_shape(self):
        self._release("v1.0"); self._release("v1.1")
        rc = self.store.compare_for_release(
            self.reader, "volmarr", "pub", "v1.1")
        data = compare_to_dict(rc)
        self.assertEqual(data["tag"], "v1.1")
        self.assertEqual(data["previous_tag"], "v1.0")
        self.assertEqual((data["ahead"], data["behind"]), (2, 0))
        self.assertEqual(data["files_changed"], 2)
        self.assertFalse(data["embedded"])
        self.assertEqual(
            [c["subject"] for c in data["commits"]],
            ["third", "second"])
        self.assertEqual(
            sorted(f["path"] for f in data["files"]),
            ["a.txt", "b.txt"])

    # -- the section (pure) -----------------------------------------

    def test_build_section_words(self):
        self._release("v1.0"); self._release("v1.1")
        rc = self.store.compare_for_release(
            self.owner, "volmarr", "pub", "v1.1")
        section = build_compare_section(rc)
        self.assertTrue(section.startswith(COMPARE_MARKER))
        self.assertIn("## Compare: v1.0…v1.1", section)
        self.assertIn("2 ahead · 0 behind · 2 files changed", section)
        self.assertIn("third", section)
        self.assertIn("second", section)
        self.assertIn("- a.txt (+2 −0)", section)
        self.assertIn("- b.txt (new file, +1 −0)", section)

    def test_build_section_same_commit_says_so(self):
        view = CompareService(self.repos).compare(
            self.owner, "volmarr", "pub", "v1.2", "v1.2")
        release = Release(
            id=1, repo_id=1, tag="v1.2", title="v1.2", notes="",
            target_oid=self.c4, author_id=self.owner.id,
            source="web", created_at=T0, updated_at=T0)
        section = build_compare_section(
            ReleaseCompare(release, "v1.2", view))
        self.assertIn("name the same commit", section)

    def test_build_section_refuses_no_previous(self):
        self._release("v1.0")
        rc = self.store.compare_for_release(
            self.owner, "volmarr", "pub", "v1.0")
        with self.assertRaises(ReleaseCompareError) as cm:
            build_compare_section(rc)
        self.assertEqual(cm.exception.reason, "no_previous_tag")

    # -- embedding (pure) -------------------------------------------

    def test_embed_appends_and_marks_once(self):
        self._release("v1.0"); self._release("v1.1")
        rc = self.store.compare_for_release(
            self.owner, "volmarr", "pub", "v1.1")
        notes = embed_compare("Hand notes.\n", rc)
        self.assertTrue(notes.startswith("Hand notes."))
        self.assertTrue(has_embedded_compare(notes))
        self.assertEqual(notes.count(COMPARE_MARKER), 1)
        with self.assertRaises(ReleaseCompareError) as cm:
            embed_compare(notes, rc)
        self.assertEqual(
            cm.exception.reason, "compare_already_embedded")

    def test_embed_replaces_placeholder(self):
        self._release("v1.0"); self._release("v1.1")
        rc = self.store.compare_for_release(
            self.owner, "volmarr", "pub", "v1.1")
        notes = embed_compare(
            "Intro.\n\n" + EMBED_PLACEHOLDER + "\n\nOutro.\n", rc)
        self.assertNotIn(EMBED_PLACEHOLDER, notes)
        self.assertLess(notes.index("Intro."), notes.index("## Compare:"))
        self.assertLess(notes.index("## Compare:"), notes.index("Outro."))

    # -- embedding (the write) ---------------------------------------

    def test_embed_in_release_writes_notes(self):
        self._release("v1.0")
        self._release("v1.1", notes="Read me.\n\n" + EMBED_PLACEHOLDER + "\n")
        updated = self.store.embed_in_release(
            self.owner, "volmarr", "pub", "v1.1")
        self.assertIn("## Compare: v1.0…v1.1", updated.notes)
        self.assertNotIn(EMBED_PLACEHOLDER, updated.notes)
        standing = self.releases.get_release(
            self.owner, "volmarr", "pub", "v1.1")
        self.assertEqual(standing.notes, updated.notes)
        with self.assertRaises(ReleaseCompareError) as cm:
            self.store.embed_in_release(
                self.owner, "volmarr", "pub", "v1.1")
        self.assertEqual(
            cm.exception.reason, "compare_already_embedded")

    def test_embed_preview_writes_nothing(self):
        self._release("v1.0"); self._release("v1.1")
        preview = self.store.preview_embedded_notes(
            self.reader, "volmarr", "pub", "v1.1")
        self.assertIn("## Compare: v1.0…v1.1", preview)
        standing = self.releases.get_release(
            self.owner, "volmarr", "pub", "v1.1")
        self.assertEqual(standing.notes, "Hand notes.\n")

    def test_embed_no_previous_refuses_and_changes_nothing(self):
        self._release("v1.0")
        with self.assertRaises(ReleaseCompareError) as cm:
            self.store.embed_in_release(
                self.owner, "volmarr", "pub", "v1.0")
        self.assertEqual(cm.exception.reason, "no_previous_tag")
        standing = self.releases.get_release(
            self.owner, "volmarr", "pub", "v1.0")
        self.assertEqual(standing.notes, "Hand notes.\n")

    def test_embed_writer_only(self):
        self._release("v1.0"); self._release("v1.1")
        with self.assertRaises(ReleaseCompareError) as cm:
            self.store.embed_in_release(
                self.reader, "volmarr", "pub", "v1.1")
        self.assertEqual(cm.exception.reason, "permission_denied")
        standing = self.releases.get_release(
            self.owner, "volmarr", "pub", "v1.1")
        self.assertFalse(has_embedded_compare(standing.notes))

    def test_embed_keeps_draft_state_and_witnesses_nothing(self):
        self._release("v1.0")
        self._release("v1.1", draft=True)
        before = self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log"
            " WHERE action = 'repo.release.publish'").fetchone()["n"]
        updated = self.store.embed_in_release(
            self.owner, "volmarr", "pub", "v1.1")
        self.assertTrue(updated.draft)
        after = self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log"
            " WHERE action = 'repo.release.publish'").fetchone()["n"]
        self.assertEqual(before, after)

    def test_embed_overflow_refused_notes_unchanged(self):
        self._release("v1.0")
        big = "x" * 65400 + "\n"
        self._release("v1.1", notes=big)
        with self.assertRaises(ReleaseCompareError) as cm:
            self.store.embed_in_release(
                self.owner, "volmarr", "pub", "v1.1")
        self.assertEqual(cm.exception.reason, "notes_invalid")
        standing = self.releases.get_release(
            self.owner, "volmarr", "pub", "v1.1")
        self.assertEqual(standing.notes, big)

    # -- permission / visibility law ---------------------------------

    def test_draft_compare_is_private_to_writers(self):
        self._release("v1.0"); self._release("v1.1", draft=True)
        with self.assertRaises(ReleaseCompareError) as cm:
            self.store.compare_for_release(
                self.reader, "volmarr", "pub", "v1.1")
        self.assertEqual(cm.exception.reason, "release_not_found")
        rc = self.store.compare_for_release(
            self.owner, "volmarr", "pub", "v1.1")
        self.assertEqual(rc.previous_tag, "v1.0")

    def test_missing_release_and_private_repo_uniform(self):
        with self.assertRaises(ReleaseCompareError) as cm:
            self.store.compare_for_release(
                self.owner, "volmarr", "pub", "v9.9")
        self.assertEqual(cm.exception.reason, "release_not_found")
        with self.assertRaises(ReleaseCompareError) as cm:
            self.store.compare_for_release(
                self.stranger, "volmarr", "priv", "v1.0")
        self.assertEqual(cm.exception.reason, "repo_not_found")

    # -- rendering -----------------------------------------------------

    def test_render_section_escapes_commit_subjects(self):
        self._release("v1.2"); self._release("v1.3")
        rc = self.store.compare_for_release(
            self.owner, "volmarr", "pub", "v1.3")
        html = render_compare_section(rc)
        self.assertIn("v1.2…v1.3", html)
        self.assertIn("fifth &lt;evil&gt;", html)
        self.assertNotIn("<evil>", html)
        self.assertIn("1 ahead", html)

    def test_render_no_previous_says_so(self):
        self._release("v1.0")
        rc = self.store.compare_for_release(
            self.owner, "volmarr", "pub", "v1.0")
        html = render_compare_section(rc)
        self.assertIn("No previous tag stands", html)


if __name__ == "__main__":
    unittest.main()
