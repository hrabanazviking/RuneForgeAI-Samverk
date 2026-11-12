"""S-269 acceptance battery: release-from-tag automation.

Acceptance (roadmap S-269): Release-from-tag
automation — pushing a version tag can draft a
release with generated notes from merged PRs
(honest, editable draft — never auto-published).

The centre is samverk/release_from_tag.py:
ReleaseFromTagStore over migration 106
(release_tag_automation; schema 105 to 106).
The switch is off by default and writer-flipped;
on_tag_push drafts only for version tags, only
when on, and only as an S-258 draft through
S-257's ReleaseStore — never published, never
witnessed, never notified. Notes are generated
from pull_request_merges rows whose merge commit
is an ancestor of the tag target and not of the
previous version tag's target, and carry the
honesty footer. No new taxonomy event — 133 stand.

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
from samverk.release_from_tag import (
    AUTOMATION_RULE, DRAFT_FOOTER, MergedPullRequestNote,
    ReleaseFromTagError, ReleaseFromTagStore, generate_notes,
    is_version_tag, parse_version_tag,
    render_automation_section, version_key)
from samverk.releases import ReleaseError, ReleaseStore
from samverk.repositories import RepositoryStore
from test_repo_home import run_git

PW = "correct horse battery"
T0 = 1_700_000_000


class Clock:
    def __init__(self, now=T0):
        self.now = now
    def __call__(self):
        return self.now


class ReleaseFromTagTests(unittest.TestCase):
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
        self.auto = ReleaseFromTagStore(
            self.conn, self.repos, self.releases,
            self.accounts, audit=self.audit, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        self.bare = self.repos.path_for("volmarr", "pub")
        self.work = self.root / "work"; self.work.mkdir()
        run_git(self.work, "init", "-b", "main")
        # c1 tagged v1.0; c2, c3 land after; c3 tagged v1.1;
        # c4 lands after v1.1 and is tagged v1.2 + a bare tag.
        self.c1 = self._commit("app.py", "print(1)\n", "first")
        self._tag("v1.0")
        self.c2 = self._commit("app.py", "print(2)\n", "second")
        self.c3 = self._commit("app.py", "print(3)\n", "third")
        self._tag("v1.1")
        self.c4 = self._commit("app.py", "print(4)\n", "fourth")
        self._tag("v1.2")
        self._tag("release-notes")
        self.repo_row = self.repos.get_repository("volmarr", "pub")
        # Merged PRs: #1 landed in c2 (in v1.1's range, not
        # v1.0's), #2 landed in c3 (v1.1), #3 landed in c4
        # (only v1.2's range).
        self._merged_pr(1, "Add the anvil", self.owner.id, self.c2, T0 + 10)
        self._merged_pr(2, "Fix the bellows", self.reader.id, self.c3, T0 + 20)
        self._merged_pr(3, "Polish the hammer", self.owner.id, self.c4, T0 + 30)

    def _commit(self, rel, text, msg):
        p = self.work / rel
        p.write_text(text)
        run_git(self.work, "add", "-A")
        run_git(self.work, "commit", "-m", msg)
        return run_git(self.work, "rev-parse", "HEAD").strip()

    def _tag(self, tag):
        run_git(self.work, "tag", tag)
        run_git(self.work, "push", str(self.bare), tag)

    def _merged_pr(self, number, title, author_id, merge_oid, merged_at):
        cur = self.conn.execute(
            "INSERT INTO issues (repo_id, number, kind, author_id,"
            " title, body, state, created_at, updated_at)"
            " VALUES (?, ?, 'pull_request', ?, ?, '', 'closed', ?, ?)",
            (self.repo_row.id, number, author_id, title,
             merged_at - 5, merged_at - 5))
        issue_id = int(cur.lastrowid)
        cur = self.conn.execute(
            "INSERT INTO pull_requests (issue_id, repo_id, base_branch,"
            " head_branch, base_oid, head_oid, is_draft, created_at,"
            " updated_at) VALUES (?, ?, 'main', ?, '', '', 0, ?, ?)",
            (issue_id, self.repo_row.id, f"pr-{number}",
             merged_at - 5, merged_at - 5))
        pr_id = int(cur.lastrowid)
        self.conn.execute(
            "INSERT INTO pull_request_merges (pull_request_id, repo_id,"
            " strategy, merge_commit_oid, base_branch, head_branch,"
            " base_oid, head_oid, message, merged_by, created_at,"
            " merged_at, message_edited)"
            " VALUES (?, ?, 'merge_commit', ?, 'main', ?, '', '', ?, ?, ?, ?, 0)",
            (pr_id, self.repo_row.id, merge_oid, f"pr-{number}",
             title, author_id, merged_at, merged_at))
        self.conn.commit()

    # -- pure version-tag law --------------------------------------

    def test_version_tag_parsing(self):
        self.assertEqual(parse_version_tag("v1.2.3"), (1, 2, 3, None))
        self.assertEqual(parse_version_tag("1.2.3"), (1, 2, 3, None))
        self.assertEqual(
            parse_version_tag("v1.2.3-rc.1"), (1, 2, 3, "rc.1"))
        self.assertTrue(is_version_tag("v0.0.1"))
        self.assertEqual(parse_version_tag("v1.2"), (1, 2, 0, None))
        for bad in ("v1", "release-1.2.3", "v1.2.3.4",
                    "latest", "", None, 123):
            self.assertFalse(is_version_tag(bad), bad)
            self.assertIsNone(parse_version_tag(bad), bad)

    def test_version_key_orders_numerically(self):
        tags = ["v1.10.0", "v1.9.0", "v1.10.0-rc.1", "v2.0.0"]
        self.assertEqual(
            sorted(tags, key=version_key),
            ["v1.9.0", "v1.10.0-rc.1", "v1.10.0", "v2.0.0"])

    def test_generate_notes_words(self):
        prs = [MergedPullRequestNote(
            7, "Add the anvil", "yrsa", T0, "a" * 40)]
        notes = generate_notes("v1.1.0", "v1.0.0", prs)
        self.assertIn("since v1.0.0 (1)", notes)
        self.assertIn("- #7 Add the anvil (@yrsa)", notes)
        self.assertIn(DRAFT_FOOTER, notes)
        empty = generate_notes("v1.1.0", None, [])
        self.assertIn("from the beginning (0)", empty)
        self.assertIn("No merged pull requests were found", empty)

    # -- pins --------------------------------------------------------

    def test_pins_schema_107_taxonomy_133(self):
        self.assertEqual(schema_version(self.conn), 118)
        self.assertEqual(db.MIGRATIONS[-1][0], 118)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 134)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 88)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)

    # -- the switch --------------------------------------------------

    def test_switch_defaults_off_and_flips_for_writer(self):
        self.assertFalse(self.auto.is_enabled(
            self.owner, "volmarr", "pub"))
        self.assertTrue(self.auto.set_enabled(
            self.owner, "volmarr", "pub", True))
        self.assertTrue(self.auto.is_enabled(
            self.reader, "volmarr", "pub"))
        self.assertTrue(self.auto.set_enabled(
            self.owner, "volmarr", "pub", True))  # no-op success
        self.assertFalse(self.auto.set_enabled(
            self.owner, "volmarr", "pub", False))
        self.assertFalse(self.auto.is_enabled(
            self.owner, "volmarr", "pub"))

    def test_switch_writer_only_and_validated(self):
        with self.assertRaises(ReleaseFromTagError) as cm:
            self.auto.set_enabled(self.reader, "volmarr", "pub", True)
        self.assertEqual(cm.exception.reason, "permission_denied")
        with self.assertRaises(ReleaseFromTagError) as cm:
            self.auto.set_enabled(self.owner, "volmarr", "pub", "yes")
        self.assertEqual(cm.exception.reason, "enabled_invalid")

    def test_switch_private_repo_uniform_not_found(self):
        with self.assertRaises(ReleaseFromTagError) as cm:
            self.auto.is_enabled(self.stranger, "volmarr", "priv")
        self.assertEqual(cm.exception.reason, "repo_not_found")
        with self.assertRaises(ReleaseFromTagError) as cm:
            self.auto.set_enabled(self.stranger, "volmarr", "priv", True)
        self.assertEqual(cm.exception.reason, "repo_not_found")

    # -- the range ---------------------------------------------------

    def test_previous_version_tag(self):
        self.assertEqual(self.auto.previous_version_tag(
            self.owner, "volmarr", "pub", "v1.2"), "v1.1")
        self.assertEqual(self.auto.previous_version_tag(
            self.owner, "volmarr", "pub", "v1.1"), "v1.0")
        self.assertIsNone(self.auto.previous_version_tag(
            self.owner, "volmarr", "pub", "v1.0"))

    def test_merged_pull_requests_range(self):
        prs = self.auto.merged_pull_requests(
            self.owner, "volmarr", "pub", "v1.1")
        self.assertEqual([p.number for p in prs], [1, 2])
        self.assertEqual(prs[0].title, "Add the anvil")
        self.assertEqual(prs[0].author, "volmarr")
        self.assertEqual(prs[1].author, "yrsa")
        prs = self.auto.merged_pull_requests(
            self.owner, "volmarr", "pub", "v1.2")
        self.assertEqual([p.number for p in prs], [3])
        prs = self.auto.merged_pull_requests(
            self.owner, "volmarr", "pub", "v1.0")
        self.assertEqual(prs, [])

    def test_range_refuses_non_version_tag(self):
        with self.assertRaises(ReleaseFromTagError) as cm:
            self.auto.merged_pull_requests(
                self.owner, "volmarr", "pub", "release-notes")
        self.assertEqual(cm.exception.reason, "not_version_tag")

    # -- the explicit door ------------------------------------------

    def test_draft_release_from_tag_creates_draft(self):
        release = self.auto.draft_release_from_tag(
            self.owner, "volmarr", "pub", "v1.1")
        self.assertTrue(release.draft)
        self.assertFalse(release.prerelease)
        self.assertEqual(release.tag, "v1.1")
        self.assertEqual(release.title, "v1.1")
        self.assertEqual(release.source, "tag_push")
        self.assertEqual(release.target_oid, self.c3)
        self.assertIn("since v1.0 (2)", release.notes)
        self.assertIn("- #1 Add the anvil (@volmarr)", release.notes)
        self.assertIn("- #2 Fix the bellows (@yrsa)", release.notes)
        self.assertNotIn("#3", release.notes)
        self.assertIn(DRAFT_FOOTER, release.notes)

    def test_draft_is_never_published_or_witnessed(self):
        self.auto.draft_release_from_tag(
            self.owner, "volmarr", "pub", "v1.1")
        rows = self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log"
            " WHERE action = 'repo.release.publish'").fetchone()
        self.assertEqual(rows["n"], 0)
        # A draft is private to writers: readers do not see it.
        listing = self.releases.list_releases(
            self.reader, "volmarr", "pub")
        self.assertEqual(listing, [])
        with self.assertRaises(ReleaseError) as cm:
            self.releases.get_release(
                self.reader, "volmarr", "pub", "v1.1")
        self.assertEqual(cm.exception.reason, "release_not_found")
        # ... until a writer publishes it by hand.
        published = self.releases.publish_release(
            self.owner, "volmarr", "pub", "v1.1")
        self.assertFalse(published.draft)

    def test_draft_retry_answers_standing_release(self):
        first = self.auto.draft_release_from_tag(
            self.owner, "volmarr", "pub", "v1.1")
        second = self.auto.draft_release_from_tag(
            self.owner, "volmarr", "pub", "v1.1")
        self.assertEqual(first.id, second.id)

    def test_draft_refusals_write_nothing(self):
        with self.assertRaises(ReleaseFromTagError) as cm:
            self.auto.draft_release_from_tag(
                self.owner, "volmarr", "pub", "release-notes")
        self.assertEqual(cm.exception.reason, "not_version_tag")
        with self.assertRaises(ReleaseFromTagError) as cm:
            self.auto.draft_release_from_tag(
                self.owner, "volmarr", "pub", "v9.9.9")
        self.assertEqual(cm.exception.reason, "tag_not_found")
        with self.assertRaises(ReleaseFromTagError) as cm:
            self.auto.draft_release_from_tag(
                self.reader, "volmarr", "pub", "v1.1")
        self.assertEqual(cm.exception.reason, "permission_denied")
        self.assertEqual(self.releases.list_releases(
            self.owner, "volmarr", "pub"), [])

    def test_draft_notes_are_editable(self):
        release = self.auto.draft_release_from_tag(
            self.owner, "volmarr", "pub", "v1.2")
        edited = self.releases.update_release(
            self.owner, "volmarr", "pub", "v1.2",
            title="Anvil 1.2", notes="Hand-written notes.\n")
        self.assertEqual(edited.id, release.id)
        self.assertEqual(edited.notes, "Hand-written notes.\n")
        self.assertTrue(edited.draft)

    # -- the push door ------------------------------------------------

    def test_push_door_disabled_by_default(self):
        outcome = self.auto.on_tag_push(
            self.owner, "volmarr", "pub", "v1.1")
        self.assertEqual(outcome.action, "disabled")
        self.assertFalse(outcome.drafted)
        self.assertIsNone(outcome.release)
        self.assertEqual(self.releases.list_releases(
            self.owner, "volmarr", "pub"), [])

    def test_push_door_drafts_when_on(self):
        self.auto.set_enabled(self.owner, "volmarr", "pub", True)
        outcome = self.auto.on_tag_push(
            self.owner, "volmarr", "pub", "v1.1")
        self.assertEqual(outcome.action, "drafted")
        self.assertTrue(outcome.release.draft)
        again = self.auto.on_tag_push(
            self.owner, "volmarr", "pub", "v1.1")
        self.assertEqual(again.action, "already_exists")
        self.assertEqual(again.release.id, outcome.release.id)

    def test_push_door_skips_non_version_tag(self):
        self.auto.set_enabled(self.owner, "volmarr", "pub", True)
        outcome = self.auto.on_tag_push(
            self.owner, "volmarr", "pub", "release-notes")
        self.assertEqual(outcome.action, "not_version_tag")
        self.assertIn("not a version tag", outcome.words)
        self.assertEqual(self.releases.list_releases(
            self.owner, "volmarr", "pub"), [])

    def test_push_door_first_tag_notes_from_beginning(self):
        self.auto.set_enabled(self.owner, "volmarr", "pub", True)
        outcome = self.auto.on_tag_push(
            self.owner, "volmarr", "pub", "v1.0")
        self.assertEqual(outcome.action, "drafted")
        self.assertIn("from the beginning (0)", outcome.release.notes)
        self.assertIn(
            "No merged pull requests were found", outcome.release.notes)

    # -- rendering ------------------------------------------------------

    def test_render_automation_section(self):
        html = render_automation_section(True, "volmarr/pub")
        self.assertIn(AUTOMATION_RULE, html)
        self.assertIn("<strong>On</strong>", html)
        html = render_automation_section(False, "volmarr/pub")
        self.assertIn("<strong>Off</strong>", html)


if __name__ == "__main__":
    unittest.main()
