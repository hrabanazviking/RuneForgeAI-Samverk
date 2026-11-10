"""S-258 acceptance battery: draft and prerelease states.

Acceptance (roadmap S-258): Draft and prerelease
states \u2014 drafts are private to writers; prereleases
are marked in every listing (text, not colour alone).

The centre is samverk/releases.py extended in place:
two independent flags on the S-257 row (migration 101,
schema 100 to 101; standing rows default to published,
not prerelease). A draft is visible only through
S-054's can_write: listings omit it for everyone else
and a direct read answers the uniform
release_not_found, so a draft's existence is itself
private. Creating a draft witnesses nothing;
publish_release is the publication, witnessed on the
standing repo.release.publish verb \u2014 taxonomy stands
at 131, no new event. The prerelease mark rides every
face in words: Draft / Pre-release markers in the
rendered listings, draft / prerelease / state in the
API shape.

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
from samverk.releases import (
    NOTES_FILE, ReleaseError, ReleaseStore, release_state,
    release_to_dict, render_release, render_releases_page,
    state_markers, validate_state_flag)
from samverk.repositories import RepositoryStore
from test_repo_home import run_git

PW = "correct horse battery"
T0 = 1_700_000_000


class Clock:
    def __init__(self, now=T0):
        self.now = now
    def __call__(self):
        return self.now


class ReleaseStateTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.clock = Clock()
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, audit=self.audit, time_fn=self.clock)
        self.owner = self.accounts.register("volmarr", PW)
        self.reader = self.accounts.register("yrsa", PW)
        self.stranger = self.accounts.register("mallory", PW)
        admin = self.accounts.register("secondwriter", PW)
        with self.conn:
            self.conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (admin.id,))
        self.writer2 = self.accounts.get_by_id(admin.id)
        self.repos = RepositoryStore(self.conn, self.root, self.accounts, audit=self.audit, time_fn=self.clock)
        self.releases = ReleaseStore(self.conn, self.repos, self.accounts, audit=self.audit, time_fn=self.clock)
        self.repos.create_repository(self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(self.owner.id, "volmarr", "priv", visibility="private")
        self.bare = self.repos.path_for("volmarr", "pub")
        self.work = self.root / "work"; self.work.mkdir()
        run_git(self.work, "init", "-b", "main")
        self._write("app.py", "print('hi')\n")
        self.c1 = self._commit("first")
        run_git(self.work, "tag", "v1.0")
        run_git(self.work, "push", str(self.bare), "v1.0")
        self._write(NOTES_FILE, "# Anvil 1.1\n\nFirst **stable** cut.\n")
        self._write("app.py", "print('ho')\n")
        self.c2 = self._commit("second")
        run_git(self.work, "tag", "-a", "v1.1", "-m", "Anvil 1.1")
        run_git(self.work, "push", str(self.bare), "v1.1")
        run_git(self.work, "tag", "v1.2")
        run_git(self.work, "push", str(self.bare), "v1.2")

    def _write(self, rel, text):
        p = self.work / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text)

    def _commit(self, msg):
        run_git(self.work, "add", "-A"); run_git(self.work, "commit", "-m", msg)
        run_git(self.work, "push", str(self.bare), "main")
        return run_git(self.work, "rev-parse", "HEAD")

    def _reason(self, fn, *a, **k):
        with self.assertRaises(ReleaseError) as ctx:
            fn(*a, **k)
        return ctx.exception.reason

    def _publish_rows(self):
        return self.conn.execute("SELECT COUNT(*) c FROM audit_log WHERE action='repo.release.publish'").fetchone()["c"]

    # -- pins ------------------------------------------
    def test_pins_schema_101_taxonomy_131(self):
        self.assertEqual(schema_version(self.conn), 102)
        self.assertEqual(db.MIGRATIONS[-1][0], 102)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 131)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 85)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(releases)")}
        self.assertIn("draft", cols)
        self.assertIn("prerelease", cols)

    def test_upgrade_from_100_defaults_published(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "old.db"
            conn = db.connect(path)
            for target, statements in db.MIGRATIONS:
                if target > 100:
                    continue
                with conn:
                    for stmt in statements:
                        conn.execute(stmt)
                    conn.execute("INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('version', ?)", (str(target),))
            with conn:
                conn.execute("INSERT INTO releases (repo_id, tag, title, notes, target_oid, author_id, source, created_at, updated_at) VALUES (1, 'v0', 'Old', '', 'abc', 1, 'web', 1, 1)")
            self.assertEqual(schema_version(conn), 100)
            db.migrate(conn)
            self.assertEqual(schema_version(conn), 102)
            row = conn.execute("SELECT draft, prerelease FROM releases WHERE tag='v0'").fetchone()
            self.assertEqual((row["draft"], row["prerelease"]), (0, 0))
            conn.close()

    # -- pure law ---------------------------------------
    def test_pure_state_law(self):
        self.assertEqual(validate_state_flag(True, "draft"), True)
        self.assertEqual(self._reason(validate_state_flag, "yes", "draft"), "state_flag_invalid")
        self.assertEqual(self._reason(validate_state_flag, 1, "draft"), "state_flag_invalid")
        pub = self.releases.create_release(self.owner, "volmarr", "pub", "v1.0", "One")
        pre = self.releases.create_release(self.owner, "volmarr", "pub", "v1.1", "Two", prerelease=True)
        dr = self.releases.create_release(self.owner, "volmarr", "pub", "v1.2", "Three", draft=True, prerelease=True)
        self.assertEqual(release_state(pub), "published")
        self.assertEqual(release_state(pre), "prerelease")
        self.assertEqual(release_state(dr), "draft")
        self.assertEqual(state_markers(pub), [])
        self.assertEqual(state_markers(pre), ["Pre-release"])
        self.assertEqual(state_markers(dr), ["Draft", "Pre-release"])

    # -- creation states ---------------------------------
    def test_create_defaults_to_published(self):
        r = self.releases.create_release(self.owner, "volmarr", "pub", "v1.0", "One")
        self.assertEqual((r.draft, r.prerelease), (False, False))
        self.assertEqual(self._publish_rows(), 1)

    def test_create_rejects_non_bool_flags(self):
        self.assertEqual(self._reason(self.releases.create_release, self.owner, "volmarr", "pub", "v1.0", "One", draft="yes"), "state_flag_invalid")
        self.assertEqual(self._reason(self.releases.create_release_from_api, self.owner, "volmarr", "pub", {"tag": "v1.0", "title": "One", "prerelease": 1}), "state_flag_invalid")

    def test_draft_creation_witnesses_nothing(self):
        self.releases.create_release(self.owner, "volmarr", "pub", "v1.0", "Secret", draft=True)
        self.assertEqual(self._publish_rows(), 0)

    # -- draft privacy ------------------------------------
    def test_draft_hidden_from_readers_and_anonymous(self):
        self.releases.create_release(self.owner, "volmarr", "pub", "v1.0", "Secret", draft=True)
        self.releases.create_release(self.owner, "volmarr", "pub", "v1.1", "Open")
        for viewer in (None, self.reader, self.stranger):
            tags = [r.tag for r in self.releases.list_releases(viewer, "volmarr", "pub")]
            self.assertEqual(tags, ["v1.1"])
            self.assertEqual(self._reason(self.releases.get_release, viewer, "volmarr", "pub", "v1.0"), "release_not_found")

    def test_draft_visible_to_writers(self):
        self.releases.create_release(self.owner, "volmarr", "pub", "v1.0", "Secret", draft=True)
        for viewer in (self.owner, self.writer2):
            got = self.releases.get_release(viewer, "volmarr", "pub", "v1.0")
            self.assertTrue(got.draft)
            tags = [r.tag for r in self.releases.list_releases(viewer, "volmarr", "pub")]
            self.assertEqual(tags, ["v1.0"])

    def test_draft_in_private_repo_stays_uniform(self):
        bare_priv = self.repos.path_for("volmarr", "priv")
        run_git(self.work, "push", str(bare_priv), "v1.0")
        self.releases.create_release(self.owner, "volmarr", "priv", "v1.0", "Secret", draft=True)
        self.assertEqual(self._reason(self.releases.get_release, self.stranger, "volmarr", "priv", "v1.0"), "repo_not_found")
        self.assertEqual(self._reason(self.releases.list_releases, self.stranger, "volmarr", "priv"), "repo_not_found")
        self.assertTrue(self.releases.get_release(self.owner, "volmarr", "priv", "v1.0").draft)

    # -- publishing ---------------------------------------
    def test_publish_release_opens_the_draft(self):
        self.releases.create_release(self.owner, "volmarr", "pub", "v1.0", "Secret", draft=True)
        self.clock.now += 5
        out = self.releases.publish_release(self.owner, "volmarr", "pub", "v1.0")
        self.assertFalse(out.draft)
        self.assertEqual(out.updated_at, T0 + 5)
        self.assertEqual(self._publish_rows(), 1)
        got = self.releases.get_release(None, "volmarr", "pub", "v1.0")
        self.assertEqual(got.title, "Secret")

    def test_publish_refusals(self):
        self.releases.create_release(self.owner, "volmarr", "pub", "v1.0", "Open")
        self.assertEqual(self._reason(self.releases.publish_release, self.owner, "volmarr", "pub", "v1.0"), "release_not_draft")
        self.assertEqual(self._reason(self.releases.publish_release, self.owner, "volmarr", "pub", "v9.9"), "release_not_found")
        self.releases.create_release(self.owner, "volmarr", "pub", "v1.1", "Secret", draft=True)
        self.assertEqual(self._reason(self.releases.publish_release, self.reader, "volmarr", "pub", "v1.1"), "permission_denied")
        self.assertTrue(self.releases.get_release(self.owner, "volmarr", "pub", "v1.1").draft)

    def test_publish_keeps_prerelease_mark(self):
        self.releases.create_release(self.owner, "volmarr", "pub", "v1.0", "Beta", draft=True, prerelease=True)
        out = self.releases.publish_release(self.owner, "volmarr", "pub", "v1.0")
        self.assertEqual((out.draft, out.prerelease), (False, True))
        self.assertEqual(release_state(out), "prerelease")
        self.assertIn("Pre-release", render_release(out, "volmarr/pub"))

    # -- prerelease marking ---------------------------------
    def test_prerelease_visible_and_marked_everywhere(self):
        r = self.releases.create_release(self.owner, "volmarr", "pub", "v1.0", "Beta", prerelease=True)
        got = self.releases.get_release(None, "volmarr", "pub", "v1.0")
        self.assertTrue(got.prerelease)
        d = release_to_dict(got, "volmarr/pub")
        self.assertEqual((d["draft"], d["prerelease"], d["state"]), (False, True, "prerelease"))
        html = render_release(got, "volmarr/pub")
        self.assertIn("Pre-release", html)
        page = render_releases_page("volmarr/pub", self.releases.list_releases(None, "volmarr", "pub"))
        self.assertIn("Pre-release", page)
        self.assertEqual(self._publish_rows(), 1)
        self.assertEqual(r.id, got.id)

    def test_published_release_carries_no_marker(self):
        r = self.releases.create_release(self.owner, "volmarr", "pub", "v1.0", "One")
        html = render_release(r, "volmarr/pub")
        self.assertNotIn("Pre-release", html)
        self.assertNotIn("release-state", html)
        d = release_to_dict(r)
        self.assertEqual(d["state"], "published")

    def test_draft_listing_for_writer_is_marked(self):
        self.releases.create_release(self.owner, "volmarr", "pub", "v1.0", "Secret", draft=True)
        page = render_releases_page("volmarr/pub", self.releases.list_releases(self.owner, "volmarr", "pub"))
        self.assertIn("Draft", page)
        anon_page = render_releases_page("volmarr/pub", self.releases.list_releases(None, "volmarr", "pub"))
        self.assertIn("No releases yet.", anon_page)

    def test_every_prerelease_in_page_is_marked(self):
        self.releases.create_release(self.owner, "volmarr", "pub", "v1.0", "A", prerelease=True)
        self.releases.create_release(self.owner, "volmarr", "pub", "v1.1", "B", prerelease=True)
        self.releases.create_release(self.owner, "volmarr", "pub", "v1.2", "C")
        page = render_releases_page("volmarr/pub", self.releases.list_releases(None, "volmarr", "pub"))
        self.assertEqual(page.count("Pre-release"), 2)

    # -- API door -------------------------------------------
    def test_api_create_with_state_flags(self):
        r = self.releases.create_release_from_api(self.owner, "volmarr", "pub", {"tag": "v1.0", "title": "Beta", "draft": True, "prerelease": True})
        self.assertEqual((r.draft, r.prerelease, r.source), (True, True, "api"))
        self.assertEqual(self._publish_rows(), 0)
        self.assertEqual(self._reason(self.releases.create_release_from_api, self.owner, "volmarr", "pub", {"tag": "v1.1", "title": "T", "bogus": 1}), "payload_unknown_field")

    # -- edits -----------------------------------------------
    def test_update_sets_and_clears_prerelease(self):
        self.releases.create_release(self.owner, "volmarr", "pub", "v1.0", "One")
        out = self.releases.update_release(self.owner, "volmarr", "pub", "v1.0", prerelease=True)
        self.assertTrue(out.prerelease)
        self.assertIn("Pre-release", render_release(out))
        out = self.releases.update_release(self.owner, "volmarr", "pub", "v1.0", prerelease=False)
        self.assertFalse(out.prerelease)
        out = self.releases.update_release(self.owner, "volmarr", "pub", "v1.0", title="Renamed")
        self.assertEqual((out.title, out.prerelease), ("Renamed", False))
        self.assertEqual(self._reason(self.releases.update_release, self.reader, "volmarr", "pub", "v1.0", prerelease=True), "permission_denied")
        self.assertEqual(self._reason(self.releases.update_release, self.owner, "volmarr", "pub", "v1.0", prerelease="yes"), "state_flag_invalid")

    def test_update_draft_keeps_it_draft(self):
        self.releases.create_release(self.owner, "volmarr", "pub", "v1.0", "Secret", draft=True)
        out = self.releases.update_release(self.owner, "volmarr", "pub", "v1.0", notes="revised")
        self.assertTrue(out.draft)
        self.assertEqual(self._publish_rows(), 0)
        self.assertEqual(self._reason(self.releases.get_release, None, "volmarr", "pub", "v1.0"), "release_not_found")

    # -- tag-push door ----------------------------------------
    def test_tag_push_creates_published_never_draft(self):
        r = self.releases.create_release_from_tag_push(self.owner, "volmarr", "pub", "v1.1")
        self.assertEqual((r.draft, r.prerelease), (False, False))
        self.assertEqual(self._publish_rows(), 1)

    def test_tag_push_returns_standing_draft_unchanged(self):
        self.releases.create_release(self.owner, "volmarr", "pub", "v1.1", "Handmade", draft=True)
        r = self.releases.create_release_from_tag_push(self.owner, "volmarr", "pub", "v1.1")
        self.assertTrue(r.draft)
        self.assertEqual(r.title, "Handmade")
        self.assertEqual(self._publish_rows(), 0)

    # -- ordering / deletion -----------------------------------
    def test_list_order_with_mixed_states(self):
        self.releases.create_release(self.owner, "volmarr", "pub", "v1.0", "One")
        self.clock.now += 10
        self.releases.create_release(self.owner, "volmarr", "pub", "v1.1", "Two", draft=True)
        self.clock.now += 10
        self.releases.create_release(self.owner, "volmarr", "pub", "v1.2", "Three", prerelease=True)
        writer_tags = [r.tag for r in self.releases.list_releases(self.owner, "volmarr", "pub")]
        self.assertEqual(writer_tags, ["v1.2", "v1.1", "v1.0"])
        reader_tags = [r.tag for r in self.releases.list_releases(self.reader, "volmarr", "pub")]
        self.assertEqual(reader_tags, ["v1.2", "v1.0"])

    def test_writer_can_delete_a_draft(self):
        self.releases.create_release(self.owner, "volmarr", "pub", "v1.0", "Secret", draft=True)
        gone = self.releases.delete_release(self.owner, "volmarr", "pub", "v1.0")
        self.assertTrue(gone.draft)
        self.assertEqual(self._reason(self.releases.get_release, self.owner, "volmarr", "pub", "v1.0"), "release_not_found")


if __name__ == "__main__":
    unittest.main()
