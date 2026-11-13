"""S-248 acceptance battery: webhook subscriptions.

Acceptance (roadmap S-248): Webhook subscriptions --
repo and org level, event filters, active/inactive,
secret set at creation and never shown again.

The centre is samverk/webhook_subscriptions.py: one
store over migration 96 holding both levels, its
filters judged against S-247's taxonomy (verbs and
categories, scope law included), repository access
judged by S-190 at the admin rung and organization
access by S-186's owners, the secret stored only as
its SHA-256 digest and never returned by any face,
and delivery matching stated as the pure
decide_match plus subscriptions_for_event -- the
set S-250 will deliver to.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import hashlib, json, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog, verify_chain
from samverk.db import schema_version
from samverk.event_store import CanonicalEvent
from samverk.organization_members import OrgMembershipStore
from samverk.organizations import OrganizationStore
from samverk.org_repositories import OrgRepoStore
from samverk.repositories import RepositoryStore
from samverk.webhook_events import WEBHOOK_CATEGORIES
from samverk.webhook_subscriptions import (
    WebhookSubscriptionError, WebhookSubscriptionStore,
    decide_match, expand_filter, render_webhook_subscription,
    render_webhook_subscriptions, secret_digest, secret_matches,
    validate_active, validate_category_filter,
    validate_event_filter, validate_filter, validate_secret,
    validate_webhook_url)

PW = "correct horse battery"
URL = "https://hooks.example.com/samverk"
SECRET = "a very secret hook secret"


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now

    def __call__(self):
        return self.now


def make_world(root: Path) -> SimpleNamespace:
    conn = db.init_db(root / "samverk.db")
    clock = Clock()
    audit = AuditLog(conn, time_fn=clock)
    accounts = AccountStore(conn, audit=audit, time_fn=clock)
    owner = accounts.register("volmarr", PW)
    orgowner = accounts.register("yrsa", PW)
    member = accounts.register("freya", PW)
    stranger = accounts.register("mallory", PW)
    admin = accounts.register("sitemod", PW)
    with conn:
        conn.execute(
            "UPDATE users SET is_admin = 1 WHERE id = ?", (admin.id,))
    admin = accounts.get_by_id(admin.id)
    repos = RepositoryStore(conn, root, accounts, audit=audit,
                            time_fn=clock)
    repos.create_repository(owner.id, "volmarr", "pub",
                            visibility="public")
    repos.create_repository(owner.id, "volmarr", "priv",
                            visibility="private")
    orgs = OrganizationStore(conn, accounts, audit=audit,
                             time_fn=clock)
    org = orgs.create_organization(orgowner.id, "crew")
    members = OrgMembershipStore(conn, accounts, audit=audit,
                                 time_fn=clock)
    members.add_member(orgowner.id, org.id, member.id)
    org_repos = OrgRepoStore(conn, accounts, root, audit=audit,
                             time_fn=clock)
    crew_repo = org_repos.create_repository(
        orgowner.id, org.id, "crewdish", visibility="private")
    hooks = WebhookSubscriptionStore(
        conn, repos, orgs, accounts, audit=audit, time_fn=clock)
    return SimpleNamespace(
        conn=conn, clock=clock, audit=audit, accounts=accounts,
        owner=owner, orgowner=orgowner, member=member,
        stranger=stranger, admin=admin, repos=repos, orgs=orgs,
        org=org, members=members, crew_repo=crew_repo, hooks=hooks)


def event(verb, target_id, target_kind="repo"):
    return CanonicalEvent(
        id=7, audit_seq=7, actor_kind="user", actor_id=3,
        actor="volmarr", verb=verb, target_kind=target_kind,
        target_id=target_id, refs=(), detail={},
        outcome="success", created_at=1_700_000_000)


class PinTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.w = make_world(Path(self._td.name))
        self.addCleanup(self.w.conn.close)

    def test_pins_schema_99_taxonomy_133(self):
        self.assertEqual(schema_version(self.w.conn), 124)
        self.assertEqual(db.MIGRATIONS[-1][0], 124)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 135)
        families = {}
        for name in taxonomy.AUDIT_EVENTS:
            families[name.split(".")[0]] = (
                families.get(name.split(".")[0], 0) + 1)
        self.assertEqual(
            families, {"auth": 33, "repo": 89, "admin": 13})
        self.assertEqual(len(WEBHOOK_CATEGORIES), 14)

    def test_table_name_passes_the_billing_audit(self):
        from samverk.billing_hole import forbidden_terms_in
        names = {r["name"] for r in self.w.conn.execute(
            "SELECT name FROM sqlite_master"
            " WHERE type = 'table'")}
        self.assertIn("webhooks", names)
        self.assertNotIn("webhook_subscriptions", names)
        self.assertEqual(forbidden_terms_in("webhooks"), ())


class ValidatorTests(unittest.TestCase):
    def _reason(self, fn, *args):
        with self.assertRaises(WebhookSubscriptionError) as ctx:
            fn(*args)
        return ctx.exception.reason

    def test_url_accepts_http_and_https(self):
        self.assertEqual(
            validate_webhook_url("https://example.com/hook"),
            "https://example.com/hook")
        self.assertEqual(
            validate_webhook_url(" http://localhost:9000/x "),
            "http://localhost:9000/x")

    def test_url_refusals(self):
        self.assertEqual(
            self._reason(validate_webhook_url, None),
            "webhook_url_required")
        self.assertEqual(
            self._reason(validate_webhook_url, "  "),
            "webhook_url_required")
        for bad in ("ftp://example.com/x", "https://",
                    "example.com/hook",
                    "https://user:pw@example.com/x",
                    "https://example.com/x#frag",
                    "https://exam ple.com/x",
                    "https://example.com/" + "a" * 500,
                    42):
            self.assertEqual(
                self._reason(validate_webhook_url, bad),
                "webhook_url_invalid", bad)

    def test_secret_pure_law(self):
        self.assertIsNone(validate_secret(None))
        self.assertEqual(validate_secret(SECRET), SECRET)
        self.assertEqual(
            secret_digest(SECRET),
            hashlib.sha256(SECRET.encode("utf-8")).hexdigest())
        digest = secret_digest(SECRET)
        self.assertTrue(secret_matches(digest, SECRET))
        self.assertFalse(secret_matches(digest, "wrong"))
        self.assertFalse(secret_matches("", SECRET))
        self.assertFalse(secret_matches(digest, None))
        self.assertFalse(secret_matches(digest, ""))
        for bad in ("", "   ", "x" * 201, "has\ttab", 42):
            self.assertEqual(
                self._reason(validate_secret, bad),
                "webhook_secret_invalid", bad)

    def test_event_filter_repository_level(self):
        picked = validate_event_filter(
            ["repo.push", "repo.issue.create"], "repository")
        self.assertEqual(
            picked, ("repo.push", "repo.issue.create"))
        self.assertEqual(
            self._reason(validate_event_filter,
                         ["auth.organization.create"], "repository"),
            "webhook_event_scope_mismatch")
        self.assertEqual(
            self._reason(validate_event_filter,
                         ["auth.login.success"], "repository"),
            "webhook_event_not_deliverable")
        self.assertEqual(
            self._reason(validate_event_filter,
                         ["admin.user.create"], "organization"),
            "webhook_event_not_deliverable")
        self.assertEqual(
            self._reason(validate_event_filter,
                         ["repo.nope"], "repository"),
            "webhook_event_unknown")
        self.assertEqual(
            self._reason(validate_event_filter,
                         "repo.push", "repository"),
            "webhook_events_invalid")

    def test_event_filter_organization_level(self):
        picked = validate_event_filter(
            ["auth.organization.update", "repo.push"], "organization")
        self.assertEqual(
            set(picked), {"auth.organization.update", "repo.push"})

    def test_category_filter_law(self):
        self.assertEqual(
            validate_category_filter(["issues"], "repository"),
            ("issues",))
        self.assertEqual(
            validate_category_filter(["organization"], "organization"),
            ("organization",))
        self.assertEqual(
            self._reason(validate_category_filter,
                         ["organization"], "repository"),
            "webhook_category_not_deliverable")
        for level in ("repository", "organization"):
            self.assertEqual(
                self._reason(validate_category_filter,
                             ["account"], level),
                "webhook_category_not_deliverable")
            self.assertEqual(
                self._reason(validate_category_filter,
                             ["administration"], level),
                "webhook_category_not_deliverable")
        self.assertEqual(
            self._reason(validate_category_filter,
                         ["nope"], "repository"),
            "webhook_category_unknown")

    def test_filter_required(self):
        self.assertEqual(
            self._reason(validate_filter, (), (), "repository"),
            "webhook_filter_required")
        events, categories = validate_filter(
            ["repo.push"], ["issues"], "repository")
        self.assertEqual(events, ("repo.push",))
        self.assertEqual(categories, ("issues",))

    def test_expand_filter(self):
        expanded = expand_filter((), ("issues",), "repository")
        self.assertEqual(len(expanded), 24)
        self.assertTrue(
            all(v.startswith("repo.issue") or "issue" in v
                for v in expanded))
        self.assertIn("repo.issue.create", expanded)
        both = expand_filter(
            ("repo.push",), ("organization",), "organization")
        self.assertEqual(
            set(both), {"repo.push", "auth.organization.create",
                        "auth.organization.update"})
        repo_level = expand_filter(
            ("repo.push",), ("repository",), "repository")
        self.assertEqual(len(repo_level), 20)
        self.assertEqual(
            len(expand_filter((), ("repository",), "repository")), 19)
        self.assertNotIn("auth.login.success", repo_level)

    def test_validate_active(self):
        self.assertTrue(validate_active(True))
        self.assertFalse(validate_active(False))
        for bad in ("yes", 1, 0, None):
            self.assertEqual(
                self._reason(validate_active, bad),
                "webhook_active_invalid", bad)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.w = make_world(Path(self._td.name))
        self.addCleanup(self.w.conn.close)

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(WebhookSubscriptionError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    def _rows(self):
        return self.w.conn.execute(
            "SELECT COUNT(*) c FROM webhooks"
        ).fetchone()["c"]

    def _audit(self):
        rows = self.w.conn.execute(
            "SELECT action, target_kind, target_id, detail"
            " FROM audit_log ORDER BY seq").fetchall()
        return [(r["action"], r["target_kind"], r["target_id"],
                 json.loads(r["detail"]) if r["detail"] else {})
                for r in rows]

    def _repo_hook(self, **over):
        call = dict(url=URL, events=["repo.issue.create"],
                    secret=SECRET)
        call.update(over)
        return self.w.hooks.create_repository_subscription(
            self.w.owner, "volmarr", "pub", **call)

    # -- creation -----------------------------------

    def test_create_repository_subscription_happy(self):
        sub = self._repo_hook(
            events=["repo.issue.create", "repo.push"],
            categories=["labels"])
        self.assertEqual(sub.level, "repository")
        self.assertEqual(sub.parent_name, "volmarr/pub")
        self.assertEqual(sub.parent_key, "volmarr/pub")
        self.assertEqual(sub.url, URL)
        self.assertEqual(sub.host, "hooks.example.com")
        self.assertEqual(
            sub.events, ("repo.push", "repo.issue.create"))
        self.assertEqual(sub.categories, ("labels",))
        self.assertTrue(sub.active)
        self.assertEqual(sub.state_words, "active")
        self.assertTrue(sub.has_secret)
        self.assertEqual(sub.created_by, self.w.owner.id)
        self.assertEqual(sub.created_at, 1_700_000_000)
        self.assertIn("repo.label.create", sub.effective_events)
        self.assertEqual(self._rows(), 1)

    def test_create_without_secret(self):
        sub = self.w.hooks.create_repository_subscription(
            self.w.owner, "volmarr", "pub", URL,
            events=["repo.push"])
        self.assertFalse(sub.has_secret)
        self.assertEqual(sub.secret_words, "no secret set")
        self.assertFalse(self.w.hooks.verify_repository_secret(
            self.w.owner, "volmarr", "pub", sub.id, SECRET))

    def test_secret_never_shown_or_stored(self):
        sub = self._repo_hook()
        row = self.w.conn.execute(
            "SELECT * FROM webhooks WHERE id = ?",
            (sub.id,)).fetchone()
        self.assertEqual(
            row["secret_digest"],
            hashlib.sha256(SECRET.encode("utf-8")).hexdigest())
        for key in row.keys():
            self.assertNotIn(SECRET, str(row[key]), key)
        self.assertNotIn(SECRET, repr(sub))
        self.assertNotIn(SECRET, sub.words)
        self.assertNotIn(
            SECRET, render_webhook_subscription(sub))
        self.assertNotIn(row["secret_digest"], repr(sub))
        for _, _, _, detail in self._audit():
            self.assertNotIn(SECRET, json.dumps(detail))

    def test_create_organization_subscription_happy(self):
        sub = self.w.hooks.create_organization_subscription(
            self.w.orgowner, "crew", URL,
            events=["auth.organization.update"],
            categories=["issues"], secret=SECRET, active=False)
        self.assertEqual(sub.level, "organization")
        self.assertEqual(sub.parent_name, "crew")
        self.assertFalse(sub.active)
        self.assertEqual(sub.state_words, "inactive")
        self.assertIn(
            "auth.organization.update", sub.effective_events)
        self.assertIn("repo.issue.create", sub.effective_events)

    # -- permission law -------------------------------

    def test_anonymous_refused_everywhere(self):
        for fn, args in (
                (self.w.hooks.create_repository_subscription,
                 ("volmarr", "pub", URL)),
                (self.w.hooks.list_repository_subscriptions,
                 ("volmarr", "pub")),
                (self.w.hooks.create_organization_subscription,
                 ("crew", URL)),
                (self.w.hooks.list_organization_subscriptions,
                 ("crew",))):
            self.assertEqual(
                self._reason(fn, None, *args, events=["repo.push"])
                if "create" in fn.__name__ else
                self._reason(fn, None, *args),
                "authentication_required", fn.__name__)

    def test_repository_permission_law(self):
        self.assertEqual(
            self._reason(
                self.w.hooks.create_repository_subscription,
                self.w.stranger, "volmarr", "priv", URL,
                events=["repo.push"]),
            "repo_not_found")
        self.assertEqual(
            self._reason(
                self.w.hooks.create_repository_subscription,
                self.w.stranger, "volmarr", "pub", URL,
                events=["repo.push"]),
            "admin_required")
        self.assertEqual(
            self._reason(
                self.w.hooks.create_repository_subscription,
                self.w.owner, "volmarr", "missing", URL,
                events=["repo.push"]),
            "repo_not_found")
        sub = self.w.hooks.create_repository_subscription(
            self.w.admin, "volmarr", "priv", URL,
            events=["repo.push"])
        self.assertEqual(sub.parent_name, "volmarr/priv")

    def test_organization_permission_law(self):
        self.assertEqual(
            self._reason(
                self.w.hooks.create_organization_subscription,
                self.w.member, "crew", URL, events=["repo.push"]),
            "not_org_owner")
        self.assertEqual(
            self._reason(
                self.w.hooks.create_organization_subscription,
                self.w.stranger, "crew", URL, events=["repo.push"]),
            "not_org_owner")
        self.assertEqual(
            self._reason(
                self.w.hooks.create_organization_subscription,
                self.w.orgowner, "missing", URL,
                events=["repo.push"]),
            "org_not_found")
        sub = self.w.hooks.create_organization_subscription(
            self.w.admin, "crew", URL, events=["repo.push"])
        self.assertEqual(sub.parent_name, "crew")

    def test_create_refusals_store_nothing(self):
        before = len(self._audit())
        for over in (dict(url="ftp://example.com/x"),
                     dict(events=["auth.login.success"]),
                     dict(events=["auth.organization.create"]),
                     dict(categories=["account"]),
                     dict(secret=""),
                     dict(active="yes")):
            call = dict(url=URL, events=["repo.push"])
            call.update(over)
            with self.assertRaises(WebhookSubscriptionError):
                self.w.hooks.create_repository_subscription(
                    self.w.owner, "volmarr", "pub", **call)
        self.assertEqual(self._rows(), 0)
        self.assertEqual(len(self._audit()), before)

    # -- witnessing -----------------------------------

    def test_audit_repository_add_and_remove(self):
        sub = self._repo_hook()
        adds = [d for a, _, t, d in self._audit()
                if a == "repo.webhook.add" and t == "volmarr/pub"]
        self.assertEqual(adds, [{"host": "hooks.example.com"}])
        self.w.hooks.delete_repository_subscription(
            self.w.owner, "volmarr", "pub", sub.id)
        removes = [d for a, _, _, d in self._audit()
                   if a == "repo.webhook.remove"]
        self.assertEqual(removes, [{"host": "hooks.example.com"}])
        ok, _, _ = verify_chain(self.w.conn)
        self.assertTrue(ok)

    def test_audit_organization_rides_update(self):
        sub = self.w.hooks.create_organization_subscription(
            self.w.orgowner, "crew", URL, events=["repo.push"])
        rows = [(t, d) for a, k, t, d in self._audit()
                if a == "auth.organization.update" and k == "organization"]
        self.assertIn(
            ("crew", {"fields": "webhooks", "action": "add",
                      "host": "hooks.example.com"}), rows)
        self.w.hooks.delete_organization_subscription(
            self.w.orgowner, "crew", sub.id)
        rows = [d for a, _, _, d in self._audit()
                if a == "auth.organization.update"]
        self.assertIn(
            {"fields": "webhooks", "action": "remove",
             "host": "hooks.example.com"}, rows)

    # -- reads and scoping ------------------------------

    def test_list_and_get_scoping(self):
        first = self._repo_hook()
        second = self.w.hooks.create_repository_subscription(
            self.w.owner, "volmarr", "priv", URL,
            events=["repo.push"])
        self.assertEqual(
            [s.id for s in self.w.hooks.list_repository_subscriptions(
                self.w.owner, "volmarr", "pub")], [first.id])
        got = self.w.hooks.get_repository_subscription(
            self.w.owner, "volmarr", "pub", first.id)
        self.assertEqual(got, first)
        self.assertEqual(
            self._reason(
                self.w.hooks.get_repository_subscription,
                self.w.owner, "volmarr", "priv", first.id),
            "subscription_not_found")
        self.assertEqual(
            self._reason(
                self.w.hooks.get_repository_subscription,
                self.w.owner, "volmarr", "pub", second.id + 100),
            "subscription_not_found")
        self.assertEqual(
            self._reason(
                self.w.hooks.get_repository_subscription,
                self.w.owner, "volmarr", "pub", "1"),
            "subscription_not_found")

    # -- updates ----------------------------------------

    def test_update_url_and_filter(self):
        sub = self._repo_hook()
        self.w.clock.now += 60
        updated = self.w.hooks.update_repository_subscription(
            self.w.owner, "volmarr", "pub", sub.id,
            url="https://ci.example.org/hook",
            categories=["issues"])
        self.assertEqual(updated.url, "https://ci.example.org/hook")
        self.assertEqual(updated.host, "ci.example.org")
        self.assertEqual(updated.events, ())
        self.assertEqual(updated.categories, ("issues",))
        self.assertEqual(updated.updated_at, 1_700_000_060)
        changes = [d for a, _, _, d in self._audit()
                   if a == "repo.settings.change"]
        self.assertIn(
            {"key": "webhook.update", "host": "ci.example.org"},
            changes)

    def test_update_noop_is_quiet(self):
        sub = self._repo_hook()
        before = len(self._audit())
        again = self.w.hooks.update_repository_subscription(
            self.w.owner, "volmarr", "pub", sub.id, url=URL,
            events=["repo.issue.create"], active=True)
        self.assertEqual(again, sub)
        self.assertEqual(len(self._audit()), before)

    def test_update_cannot_touch_secret(self):
        sub = self._repo_hook()
        self.w.hooks.update_repository_subscription(
            self.w.owner, "volmarr", "pub", sub.id,
            url="https://ci.example.org/hook")
        self.assertTrue(self.w.hooks.verify_repository_secret(
            self.w.owner, "volmarr", "pub", sub.id, SECRET))

    def test_update_refusal_stores_nothing(self):
        sub = self._repo_hook()
        with self.assertRaises(WebhookSubscriptionError):
            self.w.hooks.update_repository_subscription(
                self.w.owner, "volmarr", "pub", sub.id,
                url="ftp://example.com/x")
        got = self.w.hooks.get_repository_subscription(
            self.w.owner, "volmarr", "pub", sub.id)
        self.assertEqual(got.url, URL)

    def test_set_active_flips_and_noop(self):
        sub = self._repo_hook()
        off = self.w.hooks.set_repository_subscription_active(
            self.w.owner, "volmarr", "pub", sub.id, False)
        self.assertFalse(off.active)
        before = len(self._audit())
        again = self.w.hooks.set_repository_subscription_active(
            self.w.owner, "volmarr", "pub", sub.id, False)
        self.assertFalse(again.active)
        self.assertEqual(len(self._audit()), before)
        on = self.w.hooks.set_repository_subscription_active(
            self.w.owner, "volmarr", "pub", sub.id, True)
        self.assertTrue(on.active)

    def test_delete(self):
        sub = self._repo_hook()
        gone = self.w.hooks.delete_repository_subscription(
            self.w.owner, "volmarr", "pub", sub.id)
        self.assertEqual(gone.id, sub.id)
        self.assertEqual(
            self.w.hooks.list_repository_subscriptions(
                self.w.owner, "volmarr", "pub"), ())
        self.assertEqual(
            self._reason(
                self.w.hooks.delete_repository_subscription,
                self.w.owner, "volmarr", "pub", sub.id),
            "subscription_not_found")

    def test_verify_secret(self):
        sub = self._repo_hook()
        self.assertTrue(self.w.hooks.verify_repository_secret(
            self.w.owner, "volmarr", "pub", sub.id, SECRET))
        self.assertFalse(self.w.hooks.verify_repository_secret(
            self.w.owner, "volmarr", "pub", sub.id, "wrong"))
        self.assertFalse(self.w.hooks.verify_repository_secret(
            self.w.owner, "volmarr", "pub", sub.id, None))
        org_sub = self.w.hooks.create_organization_subscription(
            self.w.orgowner, "crew", URL, events=["repo.push"],
            secret=SECRET)
        self.assertTrue(self.w.hooks.verify_organization_secret(
            self.w.orgowner, "crew", org_sub.id, SECRET))
        self.assertFalse(self.w.hooks.verify_organization_secret(
            self.w.orgowner, "crew", org_sub.id, "wrong"))


class MatchingTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.w = make_world(Path(self._td.name))
        self.addCleanup(self.w.conn.close)

    def test_subscriptions_for_event_repository(self):
        hooks = self.w.hooks
        mine = hooks.create_repository_subscription(
            self.w.owner, "volmarr", "pub", URL,
            events=["repo.issue.create"])
        by_category = hooks.create_repository_subscription(
            self.w.owner, "volmarr", "pub", URL,
            categories=["push"])
        inactive = hooks.create_repository_subscription(
            self.w.owner, "volmarr", "pub", URL,
            events=["repo.issue.create"], active=False)
        found = hooks.subscriptions_for_event(
            event("repo.issue.create", "volmarr/pub#1"))
        self.assertEqual([s.id for s in found], [mine.id])
        found = hooks.subscriptions_for_event(
            event("repo.push", "volmarr/pub"))
        self.assertEqual([s.id for s in found], [by_category.id])
        self.assertEqual(hooks.subscriptions_for_event(
            event("repo.issue.create", "volmarr/priv#1")), ())
        self.assertNotIn(
            inactive.id,
            [s.id for s in hooks.subscriptions_for_event(
                event("repo.issue.create", "volmarr/pub#2"))])

    def test_subscriptions_for_event_organization(self):
        hooks = self.w.hooks
        org_hook = hooks.create_organization_subscription(
            self.w.orgowner, "crew", URL, events=["repo.push"])
        crew_event = event("repo.push", "crew/crewdish")
        self.assertEqual(
            [s.id for s in hooks.subscriptions_for_event(crew_event)],
            [org_hook.id])
        personal = event("repo.push", "volmarr/pub")
        self.assertEqual(hooks.subscriptions_for_event(personal), ())

    def test_subscriptions_for_event_organization_scope(self):
        hooks = self.w.hooks
        org_hook = hooks.create_organization_subscription(
            self.w.orgowner, "crew", URL,
            events=["auth.organization.update"])
        hooks.create_repository_subscription(
            self.w.owner, "volmarr", "pub", URL,
            categories=["repository"])
        org_event = event(
            "auth.organization.update", "crew",
            target_kind="organization")
        self.assertEqual(
            [s.id for s in hooks.subscriptions_for_event(org_event)],
            [org_hook.id])
        other = event(
            "auth.organization.update", "other",
            target_kind="organization")
        self.assertEqual(hooks.subscriptions_for_event(other), ())

    def test_subscriptions_for_event_withheld_and_unknown(self):
        hooks = self.w.hooks
        hooks.create_repository_subscription(
            self.w.owner, "volmarr", "pub", URL,
            categories=["repository", "issues", "push"])
        self.assertEqual(hooks.subscriptions_for_event(
            event("auth.login.success", "volmarr/pub")), ())
        self.assertEqual(hooks.subscriptions_for_event(
            event("repo.nope", "volmarr/pub")), ())

    def test_decide_match_pure(self):
        sub = self.w.hooks.create_repository_subscription(
            self.w.owner, "volmarr", "pub", URL,
            events=["repo.push"])
        repo = self.w.repos.get_repository("volmarr", "pub")
        self.assertTrue(decide_match(sub, "repo.push", repo_id=repo.id))
        self.assertFalse(
            decide_match(sub, "repo.push", repo_id=repo.id + 100))
        self.assertFalse(decide_match(
            sub, "auth.organization.update", repo_id=repo.id,
            org_key="volmarr"))
        self.assertFalse(decide_match(sub, "repo.issue.create",
                                      repo_id=repo.id))


class RenderTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.w = make_world(Path(self._td.name))
        self.addCleanup(self.w.conn.close)

    def test_render_says_state_in_words(self):
        sub = self.w.hooks.create_repository_subscription(
            self.w.owner, "volmarr", "pub",
            "https://example.com/hook?a=1&b=2",
            events=["repo.push"], secret=SECRET, active=False)
        html = render_webhook_subscription(sub)
        self.assertIn("inactive", html)
        self.assertIn("a secret is set (never shown)", html)
        self.assertIn("a=1&amp;b=2", html)
        self.assertNotIn(SECRET, html)

    def test_render_empty_teaches(self):
        html = render_webhook_subscriptions("volmarr/pub", ())
        self.assertIn("No webhook subscriptions yet", html)
        html = render_webhook_subscriptions(
            "volmarr/pub",
            self.w.hooks.list_repository_subscriptions(
                self.w.owner, "volmarr", "pub"))
        self.assertIn("No webhook subscriptions yet", html)


if __name__ == "__main__":
    unittest.main()
