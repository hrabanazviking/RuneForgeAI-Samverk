"""S-257 acceptance battery: releases.

Acceptance (roadmap S-257): Releases — a release binds
a tag, a title, and Markdown notes; created from the
web, the API, or a tag push with notes file.

The centre is samverk/releases.py: ReleaseStore over
migration 100 (schema 99 to 100; states in migration
101, S-258), one row per
(repository, tag), the tag resolved in git at creation
and its peeled commit captured. Creation is a writer
act through all three doors (web create, the API
payload door, and the tag-push door that reads
RELEASE_NOTES.md at the tagged commit); reading rides
repository read access with the uniform repo_not_found
for strangers to a private repo. Publication is
witnessed on the standing repo.release.publish verb
— taxonomy stands at 131, no new event.

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
    NOTES_FILE, ReleaseError, ReleaseStore, parse_notes_file,
    release_to_dict, render_release, render_releases_page,
    validate_notes, validate_tag, validate_title)
from samverk.repositories import RepositoryStore
from test_repo_home import run_git

PW = "correct horse battery"
T0 = 1_700_000_000


class Clock:
    def __init__(self, now=T0):
        self.now = now
    def __call__(self):
        return self.now


class ReleaseTests(unittest.TestCase):
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
        run_git(self.work, "tag", "v1.2-bare")
        run_git(self.work, "push", str(self.bare), "v1.2-bare")
        self._write(NOTES_FILE, "# Anvil 1.1\n\nFirst **stable** cut.\n")
        self._write("app.py", "print('ho')\n")
        self.c2 = self._commit("second")
        run_git(self.work, "tag", "-a", "v1.1", "-m", "Anvil 1.1")
        run_git(self.work, "push", str(self.bare), "v1.1")

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

    # -- pins ------------------------------------------
    def test_pins_schema_100_taxonomy_133(self):
        self.assertEqual(schema_version(self.conn), 111)
        self.assertEqual(db.MIGRATIONS[-1][0], 111)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 133)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 87)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        self.assertIn("repo.release.publish", taxonomy.REPO_EVENTS)
        tables = {r["name"] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("releases", tables)

    def test_upgrade_from_100_adds_state_columns(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "old.db"
            conn = db.connect(path)
            for target, statements in db.MIGRATIONS:
                if target > 100:
                    continue
                with conn:
                    for stmt in statements:
                        conn.execute(stmt)
                    conn.execute(
                        "INSERT OR REPLACE INTO schema_meta"
                        " (key, value) VALUES ('version', ?)",
                        (str(target),))
            self.assertEqual(schema_version(conn), 100)
            db.migrate(conn)
            self.assertEqual(schema_version(conn), 111)
            tables = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("releases", tables)
            cols = {r["name"] for r in conn.execute(
                "PRAGMA table_info(releases)")}
            self.assertIn("draft", cols)
            self.assertIn("prerelease", cols)
            conn.close()

    # -- web door ---------------------------------------
    def test_web_create_binds_tag_title_notes(self):
        r = self.releases.create_release(self.owner, "volmarr", "pub", "v1.0", "Anvil 1.0", "First cut.")
        self.assertEqual((r.tag, r.title, r.notes), ("v1.0", "Anvil 1.0", "First cut."))
        self.assertEqual(r.target_oid, self.c1)
        self.assertEqual(r.source, "web")
        self.assertEqual(r.author_id, self.owner.id)
        got = self.releases.get_release(None, "volmarr", "pub", "v1.0")
        self.assertEqual(got.id, r.id)

    def test_annotated_tag_peels_to_commit(self):
        r = self.releases.create_release(self.owner, "volmarr", "pub", "v1.1", "Anvil 1.1")
        self.assertEqual(r.target_oid, self.c2)

    def test_create_refuses_missing_tag_and_duplicate(self):
        self.assertEqual(self._reason(self.releases.create_release, self.owner, "volmarr", "pub", "v9.9", "Nope"), "tag_not_found")
        self.releases.create_release(self.owner, "volmarr", "pub", "v1.0", "One")
        self.assertEqual(self._reason(self.releases.create_release, self.owner, "volmarr", "pub", "v1.0", "Two"), "release_taken")

    def test_create_is_writer_only(self):
        self.assertEqual(self._reason(self.releases.create_release, self.reader, "volmarr", "pub", "v1.0", "Nope"), "permission_denied")
        self.assertEqual(self._reason(self.releases.create_release, self.stranger, "volmarr", "priv", "v1.0", "Nope"), "repo_not_found")

    def test_validation(self):
        self.assertEqual(self._reason(validate_tag, "-bad"), "tag_invalid")
        self.assertEqual(self._reason(validate_tag, "a..b"), "tag_invalid")
        self.assertEqual(self._reason(validate_title, "  "), "release_title_required")
        self.assertEqual(self._reason(validate_title, "x" * 201), "release_title_invalid")
        self.assertEqual(self._reason(validate_notes, "x" * 65537), "notes_invalid")
        self.assertEqual(self._reason(self.releases.create_release, self.owner, "volmarr", "pub", "v1.0", "T", source="smoke-signal"), "source_invalid")

    def test_publish_is_audited_on_standing_verb(self):
        before = self.conn.execute("SELECT COUNT(*) c FROM audit_log").fetchone()["c"]
        self.releases.create_release(self.owner, "volmarr", "pub", "v1.0", "Anvil 1.0")
        rows = self.conn.execute("SELECT action, detail FROM audit_log WHERE action='repo.release.publish'").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertIn("v1.0", rows[0]["detail"])
        after = self.conn.execute("SELECT COUNT(*) c FROM audit_log").fetchone()["c"]
        self.assertEqual(after, before + 1)

    # -- API door ----------------------------------------
    def test_api_create_and_dict_shape(self):
        r = self.releases.create_release_from_api(self.owner, "volmarr", "pub", {"tag": "v1.0", "title": "Anvil 1.0", "notes": "Via API."})
        self.assertEqual(r.source, "api")
        d = release_to_dict(r, "volmarr/pub")
        self.assertEqual(d["repository"], "volmarr/pub")
        self.assertEqual(d["tag"], "v1.0")
        self.assertEqual(d["target_oid"], self.c1)
        self.assertEqual(set(d), {"repository", "tag", "title", "notes", "target_oid", "author_id", "source", "created_at", "updated_at", "draft", "prerelease", "state"})
        self.assertEqual((d["draft"], d["prerelease"], d["state"]), (False, False, "published"))

    def test_api_refuses_unknown_field_and_non_object(self):
        self.assertEqual(self._reason(self.releases.create_release_from_api, self.owner, "volmarr", "pub", {"tag": "v1.0", "title": "T", "assets": []}), "payload_unknown_field")
        self.assertEqual(self._reason(self.releases.create_release_from_api, self.owner, "volmarr", "pub", ["v1.0"]), "payload_invalid")

    # -- tag-push door ------------------------------------
    def test_tag_push_reads_notes_file(self):
        r = self.releases.create_release_from_tag_push(self.owner, "volmarr", "pub", "v1.1")
        self.assertEqual(r.title, "Anvil 1.1")
        self.assertEqual(r.notes, "First **stable** cut.")
        self.assertEqual(r.source, "tag_push")
        self.assertEqual(r.target_oid, self.c2)

    def test_tag_push_without_notes_file_creates_nothing(self):
        self.assertEqual(self._reason(self.releases.create_release_from_tag_push, self.owner, "volmarr", "pub", "v1.2-bare"), "notes_file_missing")
        self.assertEqual(self.releases.list_releases(None, "volmarr", "pub"), [])

    def test_tag_push_is_idempotent(self):
        first = self.releases.create_release_from_tag_push(self.owner, "volmarr", "pub", "v1.1")
        second = self.releases.create_release_from_tag_push(self.owner, "volmarr", "pub", "v1.1")
        self.assertEqual(first.id, second.id)
        rows = self.conn.execute("SELECT COUNT(*) c FROM audit_log WHERE action='repo.release.publish'").fetchone()["c"]
        self.assertEqual(rows, 1)

    def test_parse_notes_file(self):
        self.assertEqual(parse_notes_file("# Title\n\nBody.\n"), ("Title", "Body."))
        self.assertEqual(parse_notes_file("Just notes.\n"), (None, "Just notes."))
        self.assertEqual(parse_notes_file("\n\n# Late\nText"), ("Late", "Text"))
        self.assertEqual(parse_notes_file(""), (None, ""))

    # -- reads, edit, delete -------------------------------
    def test_list_newest_first_and_private_hiding(self):
        self.releases.create_release(self.owner, "volmarr", "pub", "v1.0", "One")
        self.clock.now += 10
        self.releases.create_release(self.owner, "volmarr", "pub", "v1.1", "Two")
        tags = [r.tag for r in self.releases.list_releases(None, "volmarr", "pub")]
        self.assertEqual(tags, ["v1.1", "v1.0"])
        self.assertEqual(self._reason(self.releases.list_releases, self.stranger, "volmarr", "priv"), "repo_not_found")
        self.assertEqual(self._reason(self.releases.get_release, None, "volmarr", "pub", "v9.9"), "release_not_found")

    def test_update_and_delete(self):
        self.releases.create_release(self.owner, "volmarr", "pub", "v1.0", "One", "old")
        updated = self.releases.update_release(self.owner, "volmarr", "pub", "v1.0", notes="new")
        self.assertEqual((updated.title, updated.notes), ("One", "new"))
        self.assertEqual(self._reason(self.releases.update_release, self.reader, "volmarr", "pub", "v1.0", title="X"), "permission_denied")
        gone = self.releases.delete_release(self.owner, "volmarr", "pub", "v1.0")
        self.assertEqual(gone.tag, "v1.0")
        self.assertEqual(self._reason(self.releases.get_release, None, "volmarr", "pub", "v1.0"), "release_not_found")

    def test_render_escapes_and_renders_markdown(self):
        r = self.releases.create_release(self.owner, "volmarr", "pub", "v1.0", "Anvil <One>", "Notes with **bold**.")
        html = render_release(r, "volmarr/pub")
        self.assertIn("Anvil &lt;One&gt;", html)
        self.assertIn("<strong>bold</strong>", html)
        self.assertIn("created from the web", html)
        page = render_releases_page("volmarr/pub", [r])
        self.assertIn("Releases of volmarr/pub", page)
        self.assertIn("No releases yet.", render_releases_page("volmarr/pub", []))


if __name__ == "__main__":
    unittest.main()
