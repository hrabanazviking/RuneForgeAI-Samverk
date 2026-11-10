"""S-230 acceptance battery: profile activity.

Acceptance (roadmap S-230): a user's public actions
on their profile, privacy-respecting by construction
(S-209's rule applied to feeds). The profile is a
public surface: visibility is judged by the resource,
never by who is asking.

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
from samverk.event_store import CanonicalEvent
from samverk.issue_comments import IssueCommentStore
from samverk.issues import IssueStore
from samverk.organizations import OrganizationStore
from samverk.profile_activity import (
    PROFILE_ACTIVITY_SCOPE, ProfileActivity, ProfileActivityError,
    ProfileActivityStore, is_profile_public, profile_empty_words,
    render_profile_activity_page, render_profile_activity_section,
    render_profile_page_with_activity)
from samverk.profiles import ProfileStore
from samverk.repositories import Repository, RepositoryStore


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


def _repo(visibility):
    return Repository(id=1, owner="volmarr", owner_lower="volmarr", name="r", name_lower="r", created_by=1, created_at=1, visibility=visibility)


def _event(target_kind="repo", target_id="volmarr/pub#1"):
    return CanonicalEvent(
        id=1, audit_seq=1, actor_kind="user", actor_id=1,
        actor="volmarr", verb="repo.issue.create",
        target_kind=target_kind, target_id=target_id,
        refs=(), detail={}, outcome="success", created_at=1)


class PureLawTests(unittest.TestCase):
    def test_public_repo_event_is_profile_public(self):
        self.assertTrue(is_profile_public(_event(), _repo("public")))

    def test_private_and_internal_are_never_profile_public(self):
        self.assertFalse(is_profile_public(_event(), _repo("private")))
        self.assertFalse(is_profile_public(_event(), _repo("internal")))
        self.assertFalse(is_profile_public(_event(), None))

    def test_org_event_is_public_other_non_repo_is_not(self):
        org = _event(target_kind="organization", target_id="crew")
        self.assertTrue(is_profile_public(org, None))
        login = _event(target_kind="user", target_id="1")
        self.assertFalse(is_profile_public(login, None))


class ProfileActivityTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, audit=self.audit, time_fn=self.clock)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.reader = self.accounts.register("yrsa", "correct horse battery")
        self.stranger = self.accounts.register("mallory", "correct horse battery")
        with self.conn:
            self.conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (self.owner.id,))
        self.admin = self.accounts.get_by_id(self.owner.id)
        self.repos = RepositoryStore(self.conn, self.root, self.accounts, audit=self.audit)
        self.issues = IssueStore(self.conn, self.repos, self.accounts, audit=self.audit)
        self.comments = IssueCommentStore(self.conn, self.repos, self.accounts, self.issues, audit=self.audit)
        self.activity = ProfileActivityStore(self.conn, self.repos, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(self.owner.id, "volmarr", "priv", visibility="private")
        self.repos.create_repository(self.owner.id, "volmarr", "int", visibility="internal")

    def _audit_count(self):
        return self.conn.execute("SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]

    def _mutate_all(self):
        self.issues.create_issue(self.owner, "volmarr", "pub", "Crash on startup")
        self.comments.add_comment(self.owner, "volmarr", "pub", 1, "Looking now")
        self.issues.create_issue(self.owner, "volmarr", "priv", "Secret plans")
        self.issues.create_issue(self.owner, "volmarr", "int", "Crew notes")

    def _viewers(self):
        return (None, self.stranger, self.owner, self.admin)

    # -- the public listing --------------------------------------
    def test_lists_subject_public_actions_newest_first(self):
        self._mutate_all()
        act = self.activity.profile_activity(None, self.owner)
        self.assertEqual(act.subject, "volmarr")
        self.assertTrue(all(e.actor_id == self.owner.id for e in act.events))
        self.assertTrue(all((e.repository or "").startswith("volmarr/pub") for e in act.events))
        ids = [e.id for e in act.events]
        self.assertEqual(ids, sorted(ids, reverse=True))
        verbs = [e.verb for e in act.events]
        self.assertIn("repo.issue.create", verbs)
        self.assertIn("repo.create", verbs)  # creating the public repo is public
        self.assertEqual(act.events[0].verb, "repo.issue.comment")

    def test_only_subjects_own_actions_appear(self):
        self.issues.create_issue(self.reader, "volmarr", "pub", "Crash on startup")
        self.comments.add_comment(self.owner, "volmarr", "pub", 1, "Looking now")
        act = self.activity.profile_activity(None, self.reader)
        self.assertTrue(act.events)
        self.assertTrue(all(e.actor_id == self.reader.id for e in act.events))
        self.assertNotIn("repo.issue.comment", [e.verb for e in act.events])

    # -- the no-leak law, for every viewer class -------------------
    def test_private_and_internal_absent_for_every_viewer(self):
        self._mutate_all()
        for viewer in self._viewers():
            act = self.activity.profile_activity(viewer, self.owner)
            targets = [e.target_id or "" for e in act.events]
            self.assertTrue(any(t.startswith("volmarr/pub") for t in targets))
            self.assertFalse(any("priv" in t for t in targets), targets)
            self.assertFalse(any("/int" in t for t in targets), targets)
            self.assertFalse(any(e.repository in ("volmarr/priv", "volmarr/int") for e in act.events))

    def test_every_viewer_gets_the_same_list(self):
        self._mutate_all()
        seen = [[e.id for e in self.activity.profile_activity(v, self.owner).events] for v in self._viewers()]
        self.assertTrue(all(s == seen[0] for s in seen))

    def test_counts_count_only_what_is_shown(self):
        self._mutate_all()
        for viewer in self._viewers():
            act = self.activity.profile_activity(viewer, self.owner)
            self.assertEqual(act.count, len(act.events))
            page = render_profile_activity_page(act)
            self.assertIn(f"{act.count} events", page)
            self.assertNotIn("Secret plans", page)
            self.assertNotIn("Crew notes", page)
            self.assertNotIn("volmarr/priv", page)
            self.assertNotIn("volmarr/int", page)

    def test_org_actions_are_genuinely_public(self):
        orgs = OrganizationStore(self.conn, self.accounts, audit=self.audit)
        orgs.create_organization(self.owner.id, "crew")
        for viewer in self._viewers():
            act = self.activity.profile_activity(viewer, self.owner)
            self.assertIn("auth.organization.create", [e.verb for e in act.events])

    def test_limit_is_honoured(self):
        self._mutate_all()
        act = self.activity.profile_activity(None, self.owner, limit=1)
        self.assertEqual(act.count, 1)
        self.assertEqual(act.events[0].verb, "repo.issue.comment")

    def test_unknown_subject_refused(self):
        for subject in ("ghost", 99999):
            with self.assertRaises(ProfileActivityError) as caught:
                self.activity.profile_activity(None, subject)
            self.assertEqual(caught.exception.reason, "no_such_user")

    def test_reading_writes_and_audits_nothing(self):
        self._mutate_all()
        before = self._audit_count()
        self.activity.profile_activity(self.admin, self.owner)
        self.assertEqual(self._audit_count(), before)

    # -- empty state + rendering -----------------------------------
    def test_subject_with_only_private_actions_is_empty(self):
        quiet = self.accounts.register("quiet", "correct horse battery")
        self.repos.create_repository(quiet.id, "quiet", "secret", visibility="private")
        self.issues.create_issue(quiet, "quiet", "secret", "Hidden work")
        for viewer in (None, quiet, self.admin):
            act = self.activity.profile_activity(viewer, quiet)
            self.assertEqual(act.events, ())
            self.assertEqual(act.count, 0)
        page = render_profile_activity_page(self.activity.profile_activity(None, quiet))
        self.assertIn("No public activity by quiet yet", page)
        self.assertIn("never appear on a profile", page)
        self.assertNotIn("Hidden work", page)
        self.assertNotIn("quiet/secret", page)

    def test_new_subject_gets_honest_empty_state(self):
        newbie = self.accounts.register("newbie", "correct horse battery")
        act = self.activity.profile_activity(self.stranger, newbie)
        self.assertEqual(act.events, ())
        self.assertIn(profile_empty_words("newbie"), render_profile_activity_page(act))
        self.assertIn("No public activity by newbie yet", render_profile_activity_page(act))

    def test_page_labels_the_public_surface(self):
        self._mutate_all()
        page = render_profile_activity_page(self.activity.profile_activity(None, self.owner))
        self.assertIn("A profile is a public surface", page)
        self.assertIn("not even for", page)
        self.assertIn(PROFILE_ACTIVITY_SCOPE.split(". ")[0], page)
        self.assertIn("newest first", page)

    def test_render_escapes_user_text(self):
        event = CanonicalEvent(
            id=1, audit_seq=1, actor_kind="user", actor_id=1,
            actor="<script>alert(1)</script>", verb="repo.issue.create",
            target_kind="repo", target_id="x/<b>bold</b>",
            refs=("<i>ref</i>",), detail={}, outcome="success", created_at=1)
        act = ProfileActivity(subject="<u>mallory</u>", scope=PROFILE_ACTIVITY_SCOPE, events=(event,))
        page = render_profile_activity_section(act)
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;u&gt;mallory&lt;/u&gt;", page)
        self.assertNotIn("<u>mallory</u>", page)

    def test_profile_page_carries_the_activity_section(self):
        self._mutate_all()
        profiles = ProfileStore(self.conn, self.accounts, audit=self.audit)
        profiles.update_profile(self.owner.id, display_name="Volmarr", bio="Forge keeper")
        page = render_profile_page_with_activity(
            "volmarr", profiles.get_profile(self.owner.id),
            self.activity.profile_activity(None, self.owner))
        self.assertIn("Forge keeper", page)
        self.assertIn("Activity — volmarr", page)
        self.assertIn("A profile is a public surface", page)
        self.assertNotIn("volmarr/priv", page)

    def test_pins_schema_and_taxonomy(self):
        self.assertEqual(schema_version(self.conn), 105)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 87)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 133)


if __name__ == "__main__":
    unittest.main()
