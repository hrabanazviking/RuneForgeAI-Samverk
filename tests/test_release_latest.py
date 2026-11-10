"""S-261 acceptance battery: latest release pointer.

Acceptance (roadmap S-261): Latest release pointer
— "latest" excludes prereleases and drafts; the
rule is stated on the releases page.

The centre is the computed pointer:
is_latest_eligible / select_latest_release (pure,
in samverk/releases.py) over S-258's two flags,
ReleaseStore.get_latest_release resolving through
the listing itself, and samverk/release_latest.py's
ReleaseLatestStore face (get_latest /
get_latest_release / is_latest, latest_to_dict,
render_latest_section). The pointer is derived on
every read — no migration, schema 102 stands — so
publishing a draft, moving a prerelease mark, or
deleting the standing latest moves it at once.
Drafts are excluded even for writers who can see
them; a private repository answers the uniform
repo_not_found. The releases page states
LATEST_RULE in words and marks the latest release
in text. No new taxonomy event — 131 stand.

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
from samverk.release_latest import (
    LatestPointer, ReleaseLatestError, ReleaseLatestStore,
    latest_to_dict, render_latest_section)
from samverk.releases import (
    LATEST_MARKER, LATEST_RULE, Release, ReleaseError,
    ReleaseStore, is_latest_eligible, release_state,
    render_releases_page, select_latest_release)
from samverk.repositories import RepositoryStore
from test_repo_home import run_git

PW = "correct horse battery"
T0 = 1_700_000_000


class Clock:
    def __init__(self, now=T0):
        self.now = now
    def __call__(self):
        return self.now


def _rel(rid, created, draft=False, prerelease=False):
    return Release(
        id=rid, repo_id=1, tag=f"v{rid}", title=f"R{rid}",
        notes="", target_oid="a" * 40, author_id=1,
        source="web", created_at=created, updated_at=created,
        draft=draft, prerelease=prerelease)


class ReleaseLatestTests(unittest.TestCase):
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
        self.latest = ReleaseLatestStore(
            self.conn, self.repos, self.releases,
            self.accounts, audit=self.audit, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        self.bare = self.repos.path_for("volmarr", "pub")
        self.priv_bare = self.repos.path_for("volmarr", "priv")
        self.work = self.root / "work"; self.work.mkdir()
        run_git(self.work, "init", "-b", "main")
        for i, tag in enumerate(
                ["v1.0", "v1.1", "v1.2", "v1.3", "v1.4", "v1.5"]):
            self._write("app.py", f"print({i})\n")
            self._commit(f"cut {tag}")
            run_git(self.work, "tag", tag)
            run_git(self.work, "push", str(self.bare), tag)
        run_git(self.work, "push", str(self.priv_bare), "v1.0")

    def _write(self, rel, text):
        p = self.work / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def _commit(self, msg):
        run_git(self.work, "add", "-A")
        run_git(self.work, "commit", "-m", msg)
        run_git(self.work, "push", str(self.bare), "main")
        return run_git(self.work, "rev-parse", "HEAD")

    def _reason(self, fn, *a, **k):
        with self.assertRaises(ReleaseLatestError) as ctx:
            fn(*a, **k)
        return ctx.exception.reason

    def _create(self, tag, title=None, repo="pub", **kw):
        self.clock.now += 10
        return self.releases.create_release(
            self.owner, "volmarr", repo, tag,
            title if title else f"Release {tag}", **kw)

    def _three(self):
        self._create("v1.0")
        self._create("v1.1")
        return self._create("v1.2")

    # -- pins ------------------------------------------
    def test_pins_schema_102_taxonomy_133(self):
        self.assertEqual(schema_version(self.conn), 105)
        self.assertEqual(db.MIGRATIONS[-1][0], 105)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 133)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 87)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        self.assertIn("excludes prereleases and drafts", LATEST_RULE)
        self.assertEqual(LATEST_MARKER, "Latest release")

    # -- pure rule --------------------------------------
    def test_eligibility_is_published_only(self):
        self.assertTrue(is_latest_eligible(_rel(1, 100)))
        self.assertFalse(is_latest_eligible(_rel(2, 100, draft=True)))
        self.assertFalse(is_latest_eligible(_rel(3, 100, prerelease=True)))
        self.assertFalse(is_latest_eligible(
            _rel(4, 100, draft=True, prerelease=True)))
        self.assertEqual(release_state(_rel(1, 100)), "published")

    def test_select_picks_newest_eligible_any_order(self):
        rows = [_rel(1, 100), _rel(2, 300), _rel(3, 200)]
        self.assertEqual(select_latest_release(rows).id, 2)
        self.assertEqual(select_latest_release(list(reversed(rows))).id, 2)
        self.assertEqual(select_latest_release(rows[::2]).id, 3)

    def test_select_tie_breaks_by_id(self):
        rows = [_rel(1, 100), _rel(2, 100)]
        self.assertEqual(select_latest_release(rows).id, 2)

    def test_select_skips_newer_excluded_and_empty(self):
        rows = [_rel(1, 100), _rel(2, 900, prerelease=True),
                _rel(3, 950, draft=True)]
        self.assertEqual(select_latest_release(rows).id, 1)
        self.assertIsNone(select_latest_release([]))
        self.assertIsNone(select_latest_release(rows[1:]))

    # -- store pointer -----------------------------------
    def test_latest_is_newest_published(self):
        newest = self._three()
        pointer = self.latest.get_latest(None, "volmarr", "pub")
        self.assertTrue(pointer.has_latest)
        self.assertEqual(pointer.release.id, newest.id)
        self.assertEqual(pointer.tag, "v1.2")
        self.assertEqual(pointer.repository, "volmarr/pub")
        self.assertEqual(pointer.rule, LATEST_RULE)
        self.assertEqual(
            self.releases.get_latest_release(
                None, "volmarr", "pub").tag, "v1.2")

    def test_newer_prerelease_is_never_latest(self):
        self._create("v1.0")
        self._create("v1.1", prerelease=True)
        for viewer in (None, self.reader, self.owner):
            self.assertEqual(
                self.latest.get_latest_release(
                    viewer, "volmarr", "pub").tag, "v1.0")

    def test_newer_draft_is_never_latest_even_for_writer(self):
        self._create("v1.0")
        self._create("v1.1", draft=True)
        writer_view = self.releases.list_releases(
            self.owner, "volmarr", "pub")
        self.assertEqual([r.tag for r in writer_view], ["v1.1", "v1.0"])
        self.assertEqual(
            self.latest.get_latest_release(
                self.owner, "volmarr", "pub").tag, "v1.0")
        self.assertEqual(
            self.latest.get_latest_release(
                None, "volmarr", "pub").tag, "v1.0")

    def test_only_excluded_releases_have_no_latest(self):
        self._create("v1.0", prerelease=True)
        self._create("v1.1", draft=True)
        pointer = self.latest.get_latest(self.owner, "volmarr", "pub")
        self.assertFalse(pointer.has_latest)
        self.assertIsNone(pointer.release)
        self.assertIsNone(pointer.tag)

    def test_no_releases_have_no_latest(self):
        pointer = self.latest.get_latest(None, "volmarr", "pub")
        self.assertFalse(pointer.has_latest)
        self.assertIsNone(
            self.releases.get_latest_release(None, "volmarr", "pub"))

    def test_publishing_newest_draft_moves_pointer(self):
        self._create("v1.0")
        self._create("v1.1", draft=True)
        self.assertEqual(self.latest.get_latest_release(
            None, "volmarr", "pub").tag, "v1.0")
        self.releases.publish_release(
            self.owner, "volmarr", "pub", "v1.1")
        self.assertEqual(self.latest.get_latest_release(
            None, "volmarr", "pub").tag, "v1.1")

    def test_publishing_draft_as_prerelease_does_not(self):
        self._create("v1.0")
        self._create("v1.1", draft=True, prerelease=True)
        self.releases.publish_release(
            self.owner, "volmarr", "pub", "v1.1")
        self.assertEqual(self.latest.get_latest_release(
            None, "volmarr", "pub").tag, "v1.0")

    def test_prerelease_mark_moves_pointer_both_ways(self):
        self._three()
        self.releases.update_release(
            self.owner, "volmarr", "pub", "v1.2", prerelease=True)
        self.assertEqual(self.latest.get_latest_release(
            None, "volmarr", "pub").tag, "v1.1")
        self._create("v1.3", prerelease=True)
        self.assertEqual(self.latest.get_latest_release(
            None, "volmarr", "pub").tag, "v1.1")
        self.releases.update_release(
            self.owner, "volmarr", "pub", "v1.3", prerelease=False)
        self.assertEqual(self.latest.get_latest_release(
            None, "volmarr", "pub").tag, "v1.3")

    def test_deleting_latest_falls_back_then_empty(self):
        self._create("v1.0")
        self._create("v1.1")
        self.releases.delete_release(self.owner, "volmarr", "pub", "v1.1")
        self.assertEqual(self.latest.get_latest_release(
            None, "volmarr", "pub").tag, "v1.0")
        self.releases.delete_release(self.owner, "volmarr", "pub", "v1.0")
        self.assertIsNone(self.latest.get_latest_release(
            None, "volmarr", "pub"))

    # -- visibility ---------------------------------------
    def test_private_repo_pointer_is_owner_only(self):
        self._create("v1.0", repo="priv")
        self.assertEqual(self.latest.get_latest_release(
            self.owner, "volmarr", "priv").tag, "v1.0")
        for viewer in (None, self.reader, self.stranger):
            self.assertEqual(self._reason(
                self.latest.get_latest, viewer, "volmarr", "priv"),
                "repo_not_found")

    def test_missing_repo_answers_repo_not_found(self):
        for viewer in (None, self.owner):
            self.assertEqual(self._reason(
                self.latest.get_latest, viewer, "volmarr", "nope"),
                "repo_not_found")
            self.assertEqual(self._reason(
                self.latest.get_latest, viewer, "nobody", "pub"),
                "repo_not_found")

    # -- is_latest ------------------------------------------
    def test_is_latest_answers_by_identity(self):
        self._three()
        self.assertTrue(self.latest.is_latest(
            None, "volmarr", "pub", "v1.2"))
        self.assertFalse(self.latest.is_latest(
            None, "volmarr", "pub", "v1.1"))
        self.assertFalse(self.latest.is_latest(
            self.owner, "volmarr", "pub", "v1.0"))

    def test_is_latest_excluded_states_answer_false(self):
        self._create("v1.0")
        self._create("v1.1", prerelease=True)
        self._create("v1.2", draft=True)
        self.assertFalse(self.latest.is_latest(
            None, "volmarr", "pub", "v1.1"))
        self.assertFalse(self.latest.is_latest(
            self.owner, "volmarr", "pub", "v1.2"))

    def test_is_latest_missing_and_hidden_answer_not_found(self):
        self._create("v1.0", draft=True)
        self.assertEqual(self._reason(
            self.latest.is_latest, None, "volmarr", "pub", "v1.0"),
            "release_not_found")
        self.assertEqual(self._reason(
            self.latest.is_latest, self.owner, "volmarr", "pub", "v9.9"),
            "release_not_found")
        self.assertEqual(self._reason(
            self.latest.is_latest, None, "volmarr", "priv", "v1.0"),
            "repo_not_found")

    # -- API shape ------------------------------------------
    def test_dict_shape_with_latest(self):
        self._three()
        pointer = self.latest.get_latest(None, "volmarr", "pub")
        d = latest_to_dict(pointer)
        self.assertEqual(d["repository"], "volmarr/pub")
        self.assertEqual(d["rule"], LATEST_RULE)
        self.assertTrue(d["has_latest"])
        self.assertEqual(d["tag"], "v1.2")
        self.assertEqual(d["latest"]["tag"], "v1.2")
        self.assertEqual(d["latest"]["state"], "published")
        self.assertEqual(
            (d["latest"]["draft"], d["latest"]["prerelease"]),
            (False, False))

    def test_dict_shape_without_latest(self):
        self._create("v1.0", prerelease=True)
        d = latest_to_dict(self.latest.get_latest(
            None, "volmarr", "pub"))
        self.assertFalse(d["has_latest"])
        self.assertIsNone(d["tag"])
        self.assertIsNone(d["latest"])
        self.assertEqual(d["rule"], LATEST_RULE)

    # -- the releases page states the rule -------------------
    def test_page_states_rule_and_marks_latest_once(self):
        self._three()
        self._create("v1.3", prerelease=True)
        page = render_releases_page(
            "volmarr/pub",
            self.releases.list_releases(None, "volmarr", "pub"))
        self.assertIn(LATEST_RULE, page)
        self.assertEqual(page.count('class="latest-release"'), 1)
        self.assertEqual(page.count(LATEST_MARKER), 1)
        marker_at = page.index('class="latest-release"')
        latest_at = page.index("Release v1.2")
        pre_at = page.index("Release v1.3")
        self.assertLess(pre_at, marker_at)
        self.assertLess(marker_at, latest_at)

    def test_page_states_rule_when_empty_and_unmarked(self):
        page = render_releases_page("volmarr/pub", [])
        self.assertIn(LATEST_RULE, page)
        self.assertIn("No releases yet.", page)
        self.assertNotIn('class="latest-release"', page)
        self._create("v1.0", prerelease=True)
        self._create("v1.1", draft=True)
        page = render_releases_page(
            "volmarr/pub",
            self.releases.list_releases(self.owner, "volmarr", "pub"))
        self.assertIn(LATEST_RULE, page)
        self.assertNotIn('class="latest-release"', page)

    def test_latest_section_states_rule_and_names_latest(self):
        self._three()
        html = render_latest_section(
            self.latest.get_latest(None, "volmarr", "pub"))
        self.assertIn(LATEST_RULE, html)
        self.assertIn("Latest release: Release v1.2", html)
        self.assertIn("tag v1.2", html)

    def test_latest_section_empty_is_honest(self):
        html = render_latest_section(
            self.latest.get_latest(None, "volmarr", "pub"))
        self.assertIn(LATEST_RULE, html)
        self.assertIn("There is no latest release yet", html)
        self.assertIn("volmarr/pub", html)

    def test_latest_section_escapes_title(self):
        self._create("v1.0", title="<script>alert(1)</script>")
        html = render_latest_section(
            self.latest.get_latest(None, "volmarr", "pub"))
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    # -- reads are pure ---------------------------------------
    def test_pointer_reads_write_and_audit_nothing(self):
        self._three()
        audit_before = self.conn.execute(
            "SELECT COUNT(*) c FROM audit_log").fetchone()["c"]
        rows_before = self.conn.execute(
            "SELECT COUNT(*) c FROM releases").fetchone()["c"]
        stamps_before = [tuple(r) for r in self.conn.execute(
            "SELECT id, updated_at FROM releases ORDER BY id")]
        pointer = self.latest.get_latest(None, "volmarr", "pub")
        latest_to_dict(pointer)
        render_latest_section(pointer)
        render_releases_page(
            "volmarr/pub",
            self.releases.list_releases(None, "volmarr", "pub"))
        self.latest.is_latest(None, "volmarr", "pub", "v1.2")
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) c FROM audit_log").fetchone()["c"],
            audit_before)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) c FROM releases").fetchone()["c"],
            rows_before)
        self.assertEqual([tuple(r) for r in self.conn.execute(
            "SELECT id, updated_at FROM releases ORDER BY id")],
            stamps_before)


if __name__ == "__main__":
    unittest.main()
