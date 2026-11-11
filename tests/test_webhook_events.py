"""S-247 acceptance battery: webhook events taxonomy.

Acceptance (roadmap S-247): Webhook events taxonomy --
the event store's verbs mapped to webhook payloads;
payload shape is Samverk's own, documented per event.

The centre is samverk/webhook_events.py: every one of
the frozen taxonomy's 131 verbs carries exactly one
ruling -- repository scope (85), organization scope
(2) or never delivered (44) -- the webhook event name
is the verb itself, the payload is S-221's own event
shape delegated to unchanged, the detail keys are the
audit taxonomy's per-event contract, and
docs/WEBHOOK_EVENTS.md documents every verb.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.event_store import CanonicalEvent, EventStore, event_payload
from samverk.issues import IssueStore
from samverk.repositories import RepositoryStore
from samverk.webhook_events import (
    PAYLOAD_FIELDS, SCOPES, WEBHOOK_CATEGORIES, WEBHOOK_EVENTS,
    WebhookEventsError, all_verbs, audit_webhook_events,
    deliverable_verbs, get_webhook_event, is_deliverable,
    payload_json, render_webhook_events_page, verbs_for_category,
    verbs_for_scope, webhook_payload)

PW = "correct horse battery"


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


def synthetic(verb, **over):
    base = dict(
        id=7, audit_seq=7, actor_kind="user", actor_id=3,
        actor="yrsa", verb=verb, target_kind="repo",
        target_id="volmarr/pub#1",
        refs=("repo:volmarr/pub", "number:1"),
        detail={"number": 1}, outcome="success",
        created_at=1_700_000_000)
    base.update(over)
    return CanonicalEvent(**base)


class WebhookTaxonomyDataTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.conn = db.init_db(Path(self._td.name) / "samverk.db")
        self.addCleanup(self.conn.close)

    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 113)
        self.assertEqual(db.MIGRATIONS[-1][0], 113)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 133)
        families = {}
        for event in taxonomy.AUDIT_EVENTS:
            families[event.split(".")[0]] = (
                families.get(event.split(".")[0], 0) + 1)
        self.assertEqual(
            families, {"auth": 33, "repo": 87, "admin": 13})

    def test_payload_fields_are_s221s_own_shape(self):
        self.assertEqual(PAYLOAD_FIELDS, (
            "delivery_id", "event", "action", "actor",
            "target", "repository", "number", "refs",
            "detail", "occurred_at"))
        probe = synthetic("repo.issue.create")
        self.assertEqual(
            tuple(event_payload(probe).keys()), PAYLOAD_FIELDS)

    def test_every_taxonomy_verb_ruled_exactly_once(self):
        verbs = all_verbs()
        self.assertEqual(len(verbs), 133)
        self.assertEqual(len(set(verbs)), 133)
        self.assertEqual(set(verbs), set(taxonomy.AUDIT_EVENTS))
        self.assertEqual(
            tuple(s.verb for s in WEBHOOK_EVENTS), verbs)

    def test_scope_counts(self):
        self.assertEqual(SCOPES, ("repository", "organization", "none"))
        self.assertEqual(len(verbs_for_scope("repository")), 87)
        self.assertEqual(len(verbs_for_scope("organization")), 2)
        self.assertEqual(len(verbs_for_scope("none")), 44)
        self.assertEqual(len(deliverable_verbs()), 89)
        self.assertEqual(len(deliverable_verbs("repository")), 87)
        self.assertEqual(len(deliverable_verbs("organization")), 2)
        self.assertEqual(deliverable_verbs("none"), ())

    def test_scope_law_by_family(self):
        for spec in WEBHOOK_EVENTS:
            if spec.verb.startswith("repo."):
                self.assertEqual(spec.scope, "repository", spec.verb)
            elif spec.verb.startswith("auth.organization."):
                self.assertEqual(spec.scope, "organization", spec.verb)
            else:
                self.assertEqual(spec.scope, "none", spec.verb)
            self.assertEqual(spec.deliverable, spec.scope != "none")

    def test_organization_scope_is_exactly_the_org_verbs(self):
        self.assertEqual(
            set(verbs_for_scope("organization")),
            {"auth.organization.create", "auth.organization.update"})

    def test_withheld_families(self):
        for verb in taxonomy.ADMIN_EVENTS:
            self.assertFalse(is_deliverable(verb), verb)
        for verb in ("auth.login.success", "auth.token.create",
                     "auth.password.change", "auth.ssh_key.add",
                     "auth.recovery.use", "auth.passkey.login",
                     "auth.follow", "auth.unfollow",
                     "auth.signup.success", "auth.deletion.execute"):
            self.assertFalse(is_deliverable(verb), verb)
            self.assertEqual(get_webhook_event(verb).scope, "none")

    def test_categories_exact(self):
        self.assertEqual(set(WEBHOOK_CATEGORIES), {
            "account", "administration", "branches", "checks",
            "following", "issues", "labels", "milestones",
            "organization", "pull_requests", "push", "releases",
            "repository", "webhooks"})
        counts = {c: len(verbs_for_category(c))
                  for c in WEBHOOK_CATEGORIES}
        self.assertEqual(counts, {
            "account": 29, "administration": 13, "branches": 2,
            "checks": 4, "following": 2, "issues": 24,
            "labels": 3, "milestones": 3, "organization": 2,
            "pull_requests": 28, "push": 1, "releases": 1,
            "repository": 19, "webhooks": 2})
        self.assertEqual(sum(counts.values()), 133)

    def test_category_spot_checks(self):
        self.assertEqual(
            get_webhook_event("repo.push").category, "push")
        self.assertEqual(
            get_webhook_event("repo.issue.create").category, "issues")
        self.assertEqual(
            get_webhook_event("repo.pull_request.merge").category,
            "pull_requests")
        self.assertEqual(
            get_webhook_event("repo.status.post").category, "checks")
        self.assertEqual(
            get_webhook_event("repo.check_run.post").category, "checks")
        self.assertEqual(
            get_webhook_event("repo.webhook.add").category, "webhooks")
        self.assertEqual(
            get_webhook_event("admin.user.delete").category,
            "administration")

    def test_spec_properties(self):
        spec = get_webhook_event("repo.issue.create")
        self.assertEqual(spec.event_name, "repo.issue.create")
        self.assertEqual(spec.action, "create")
        self.assertEqual(spec.family, "repo")
        self.assertTrue(spec.deliverable)
        self.assertEqual(
            get_webhook_event("repo.pull_request.merge").action, "merge")

    def test_detail_fields_spot_checks(self):
        self.assertEqual(
            get_webhook_event("repo.push").detail_fields,
            ("ref", "old", "new"))
        self.assertEqual(
            get_webhook_event("repo.issue.create").detail_fields,
            ("number",))
        self.assertEqual(
            get_webhook_event("auth.logout").detail_fields, ())
        self.assertEqual(
            get_webhook_event("repo.status.post").detail_fields,
            ("poster", "credential", "token_id", "oid", "context", "state"))
        self.assertEqual(
            get_webhook_event("repo.check_run.post").detail_fields,
            ("poster", "credential", "token_id", "oid", "name",
             "status", "conclusion"))
        self.assertEqual(
            get_webhook_event("auth.organization.create").detail_fields,
            ("org",))
        self.assertEqual(
            get_webhook_event("auth.follow").detail_fields, ("followed",))
        self.assertEqual(
            get_webhook_event("repo.protection.bypass").detail_fields,
            ("branch", "patterns", "rule_ids", "bypass_entry",
             "gate", "actor"))

    def test_every_spec_is_documented_in_itself(self):
        for spec in WEBHOOK_EVENTS:
            self.assertTrue(spec.summary, spec.verb)
            self.assertIn(spec.scope, SCOPES, spec.verb)
            self.assertIn(spec.category, WEBHOOK_CATEGORIES, spec.verb)
            for key in spec.detail_fields:
                self.assertTrue(key.isidentifier(), (spec.verb, key))

    def test_unknown_verb_refused(self):
        for bad in ("repo.bogus.thing", "webhook.ping", "", None, 42):
            with self.assertRaises(WebhookEventsError) as cm:
                get_webhook_event(bad)
            self.assertEqual(cm.exception.reason, "webhook_event_unknown")
            self.assertFalse(is_deliverable(bad))

    def test_unknown_scope_and_category_refused(self):
        with self.assertRaises(WebhookEventsError) as cm:
            verbs_for_scope("instance")
        self.assertEqual(cm.exception.reason, "webhook_scope_unknown")
        with self.assertRaises(WebhookEventsError) as cm:
            verbs_for_category("everything")
        self.assertEqual(cm.exception.reason, "webhook_category_unknown")


class WebhookPayloadTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(
            self.conn, audit=self.audit, time_fn=self.clock)
        self.owner = self.accounts.register("volmarr", PW)
        self.reader = self.accounts.register("yrsa", PW)
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts, audit=self.audit)
        self.issues = IssueStore(
            self.conn, self.repos, self.accounts, audit=self.audit)
        self.events = EventStore(self.conn, self.repos, self.accounts)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")

    def test_payload_from_a_real_store_event(self):
        self.issues.create_issue(self.reader, "volmarr", "pub", "Crash")
        events = self.events.list_for_repo(self.owner, "volmarr", "pub")
        created = [e for e in events if e.verb == "repo.issue.create"][0]
        payload = webhook_payload(created)
        self.assertEqual(payload, event_payload(created))
        self.assertEqual(tuple(payload.keys()), PAYLOAD_FIELDS)
        self.assertEqual(payload["event"], "repo.issue.create")
        self.assertEqual(payload["action"], "create")
        self.assertEqual(payload["actor"], "yrsa")
        self.assertEqual(payload["repository"], "volmarr/pub")
        self.assertEqual(payload["number"], 1)
        self.assertEqual(payload["delivery_id"], f"evt-{created.id}")
        self.assertEqual(payload["occurred_at"], 1_700_000_000)
        self.assertEqual(
            json.loads(json.dumps(payload)), payload)

    def test_repo_create_event_is_deliverable(self):
        events = self.events.list_for_repo(self.owner, "volmarr", "pub")
        created = [e for e in events if e.verb == "repo.create"][0]
        payload = webhook_payload(created)
        self.assertEqual(payload["event"], "repo.create")
        self.assertEqual(payload["detail"], {"visibility": "public"})

    def test_payload_json_is_canonical(self):
        event = synthetic("repo.issue.create")
        text = payload_json(event)
        self.assertEqual(
            text, json.dumps(webhook_payload(event), sort_keys=True,
                             separators=(",", ":")))
        self.assertEqual(json.loads(text), webhook_payload(event))
        self.assertTrue(text.startswith('{"action":'))

    def test_delivery_id_stable_for_same_event(self):
        event = synthetic("repo.push", detail={"ref": "refs/heads/main"})
        self.assertEqual(
            webhook_payload(event)["delivery_id"],
            webhook_payload(event)["delivery_id"])
        self.assertEqual(payload_json(event), payload_json(event))

    def test_withheld_verbs_refused(self):
        for verb in ("auth.login.success", "auth.token.create",
                     "admin.user.delete", "auth.follow"):
            with self.assertRaises(WebhookEventsError) as cm:
                webhook_payload(synthetic(verb))
            self.assertEqual(
                cm.exception.reason, "webhook_event_not_deliverable")
            with self.assertRaises(WebhookEventsError):
                payload_json(synthetic(verb))

    def test_unknown_verb_event_refused(self):
        with self.assertRaises(WebhookEventsError) as cm:
            webhook_payload(synthetic("repo.bogus.thing"))
        self.assertEqual(cm.exception.reason, "webhook_event_unknown")

    def test_organization_scope_payload(self):
        event = synthetic(
            "auth.organization.create", target_kind="organization",
            target_id="acme", refs=(), detail={"org": "acme"})
        payload = webhook_payload(event)
        self.assertEqual(payload["event"], "auth.organization.create")
        self.assertEqual(payload["detail"], {"org": "acme"})
        self.assertIsNone(payload["repository"])

    def test_detail_carried_unchanged(self):
        detail = {"number": 4, "reason": "completed"}
        event = synthetic("repo.issue.close", detail=detail)
        self.assertEqual(webhook_payload(event)["detail"], detail)


class WebhookAuditAndRenderTests(unittest.TestCase):
    def test_audit_ratified_with_exact_counts(self):
        audit = audit_webhook_events()
        self.assertTrue(audit.ratified, audit.problems)
        self.assertEqual(audit.problems, ())
        self.assertEqual(audit.verbs_checked, 133)
        self.assertEqual(audit.deliverable, 89)
        self.assertEqual(audit.repository_scope, 87)
        self.assertEqual(audit.organization_scope, 2)
        self.assertEqual(audit.withheld, 44)

    def test_document_names_every_verb(self):
        doc = (Path(__file__).resolve().parent.parent
               / "docs" / "WEBHOOK_EVENTS.md").read_text(
                   encoding="utf-8")
        for verb in all_verbs():
            self.assertIn(f"`{verb}`", doc, verb)
        for field in PAYLOAD_FIELDS:
            self.assertIn(f"`{field}`", doc, field)
        self.assertIn("Never delivered (44 verbs)", doc)
        self.assertIn("Repository scope (85 verbs)", doc)

    def test_render_page_says_the_law_in_words(self):
        page = render_webhook_events_page(audit_webhook_events())
        self.assertIn("Webhook events", page)
        self.assertIn("repo.issue.create", page)
        self.assertIn("auth.organization.create", page)
        self.assertIn("never delivered", page)
        self.assertIn("Checked, not just claimed", page)
        self.assertIn("89 of them deliverable", page)
        self.assertIn("44 withheld", page)
        self.assertIn("docs/WEBHOOK_EVENTS.md", page)
        for verb in all_verbs():
            self.assertIn(verb, page, verb)

    def test_render_without_audit_still_complete(self):
        page = render_webhook_events_page()
        self.assertIn("admin.user.delete", page)
        self.assertNotIn("Checked, not just claimed", page)

    def test_api_contract_still_ratified(self):
        from samverk.api_contract import audit_api_contract
        self.assertTrue(audit_api_contract().ratified)


if __name__ == "__main__":
    unittest.main()
