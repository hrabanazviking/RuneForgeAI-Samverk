"""S-252 acceptance battery: webhook ping and test events.

Acceptance (roadmap S-252): Webhook ping and test
events -- a synthetic event on demand so
integrations can be proven before they matter.

The centre is samverk/webhook_ping.py: two
synthetic sends to one named subscription under
S-248's own gate (S-190's admin rung for a
repository, S-186's owners for an organization,
site admins anywhere). A ping rides the event
name `ping`, which no taxonomy verb claims; a
test event rides one real S-247 verb, judged at
the door (unknown, withheld and scope-mismatched
names refused by name), with a sample detail
shaped by the verb's own detail contract and
marked synthetic in the payload. Each send
queues exactly one fresh row on S-250's outbox
under a negative event number -- nothing enters
the event store, nothing is deduped -- and is
ledgered in webhook_pings (migration 99, schema
98 to 99); the ordinary worker carries the proof,
signed under S-249 when a secret is set, and
S-251's delivery log shows it. Sends are
witnessed on the standing verbs only: taxonomy
stands at 131, no new event. No test touches the
network: every transport is a fake.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import json, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.organization_members import OrgMembershipStore
from samverk.organizations import OrganizationStore
from samverk.org_repositories import OrgRepoStore
from samverk.repositories import RepositoryStore
from samverk.webhook_delivery import (
    TransportResult, WebhookDeliveryStore)
from samverk.webhook_delivery_log import DeliveryLogStore
from samverk.webhook_events import (
    PAYLOAD_FIELDS, get_webhook_event)
from samverk.webhook_ping import (
    KINDS, PING_EVENT, PING_MESSAGE, WebhookPingError,
    WebhookPingStore, build_ping_payload,
    build_test_payload, decide_send,
    ping_delivery_key_for, ping_payload_json,
    render_webhook_ping, render_webhook_pings,
    sample_detail, test_delivery_key_for,
    validate_ping_kind, validate_test_verb)
from samverk.webhook_signing import (
    SIGNATURE_HEADER, verify_signature)
from samverk.webhook_subscriptions import (
    WebhookSubscriptionStore, secret_digest)

PW = "correct horse battery"
URL = "https://hooks.example.com/samverk"
SECRET = "a very secret hook secret"
T0 = 1_700_000_000


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


class FakeTransport:
    def __init__(self, script=(), clock=None, advance=0):
        self.script = list(script)
        self.calls = []
        self.clock = clock
        self.advance = advance

    def __call__(self, url, body, headers, timeout):
        self.calls.append((url, body, dict(headers), timeout))
        if self.clock is not None and self.advance:
            self.clock.now += self.advance
        outcome = self.script.pop(0) if self.script else 200
        if isinstance(outcome, BaseException):
            raise outcome
        return TransportResult(status_code=outcome)


def make_world(root: Path) -> SimpleNamespace:
    conn = db.init_db(root / "samverk.db")
    clock = Clock()
    audit = AuditLog(conn, time_fn=clock)
    accounts = AccountStore(conn, audit=audit, time_fn=clock)
    owner = accounts.register("volmarr", PW)
    orgowner = accounts.register("yrsa", PW)
    member = accounts.register("freya", PW)
    stranger = accounts.register("mallory", PW)
    boss = accounts.register("boss", PW)
    with conn:
        conn.execute(
            "UPDATE users SET is_admin = 1 WHERE id = ?",
            (boss.id,))
    admin = accounts.get_by_id(boss.id)
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
        org=org, members=members, crew_repo=crew_repo,
        hooks=hooks, root=root)


class WorldCase(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.w = make_world(Path(self._td.name))
        self.addCleanup(self.w.conn.close)

    def pings(self):
        return WebhookPingStore(
            self.w.conn, self.w.repos, self.w.orgs,
            self.w.accounts, audit=self.w.audit,
            time_fn=self.w.clock)

    def worker(self, transport=None):
        return WebhookDeliveryStore(
            self.w.conn, self.w.repos, self.w.orgs,
            self.w.accounts,
            transport=transport if transport is not None
            else FakeTransport(),
            time_fn=self.w.clock, jitter_fn=lambda delay: 0)

    def log(self):
        return DeliveryLogStore(
            self.w.conn, self.w.repos, self.w.orgs,
            self.w.accounts, audit=self.w.audit,
            time_fn=self.w.clock)

    def repo_hook(self, repo="pub", **over):
        kwargs = dict(events=["repo.issue.create"], secret=SECRET)
        kwargs.update(over)
        return self.w.hooks.create_repository_subscription(
            self.w.owner, "volmarr", repo, URL, **kwargs)

    def org_hook(self, **over):
        kwargs = dict(events=["repo.issue.create"], secret=SECRET)
        kwargs.update(over)
        return self.w.hooks.create_organization_subscription(
            self.w.orgowner, "crew", URL, **kwargs)

    def audit_count(self):
        return int(self.w.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"])

    def delivery_count(self):
        return int(self.w.conn.execute(
            "SELECT COUNT(*) AS n FROM webhook_deliveries"
        ).fetchone()["n"])

    def ping_count(self):
        return int(self.w.conn.execute(
            "SELECT COUNT(*) AS n FROM webhook_pings"
        ).fetchone()["n"])

    def event_count(self):
        return int(self.w.conn.execute(
            "SELECT COUNT(*) AS n FROM events").fetchone()["n"])

    def last_audit(self):
        return self.w.conn.execute(
            "SELECT * FROM audit_log ORDER BY seq DESC LIMIT 1"
        ).fetchone()


class PinTests(WorldCase):
    def test_pins_schema_99_taxonomy_133(self):
        self.assertEqual(schema_version(self.w.conn), 105)
        self.assertEqual(db.MIGRATIONS[-1][0], 105)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 133)
        families = {}
        for name in taxonomy.AUDIT_EVENTS:
            families[name.split(".")[0]] = (
                families.get(name.split(".")[0], 0) + 1)
        self.assertEqual(
            families, {"auth": 33, "repo": 87, "admin": 13})

    def test_ping_ledger_table_stands(self):
        cols = {r["name"] for r in self.w.conn.execute(
            "PRAGMA table_info(webhook_pings)")}
        self.assertTrue({
            "webhook_id", "kind", "verb", "delivery_id",
            "delivery_key", "actor_id", "created_at",
        } <= cols)

    def test_ping_event_name_is_claimed_by_no_verb(self):
        self.assertEqual(PING_EVENT, "ping")
        self.assertNotIn(PING_EVENT, taxonomy.AUDIT_EVENTS)
        self.assertEqual(KINDS, ("ping", "test"))


class PureLawTests(WorldCase):
    def test_kind_validation_names_the_honest_set(self):
        self.assertEqual(validate_ping_kind("ping"), "ping")
        self.assertEqual(validate_ping_kind("test"), "test")
        for bad in ("pong", "", None, 7):
            with self.assertRaises(WebhookPingError) as cm:
                validate_ping_kind(bad)
            self.assertEqual(cm.exception.reason,
                             "webhook_ping_kind_invalid")

    def test_delivery_keys_carry_their_own_stems(self):
        self.assertEqual(ping_delivery_key_for(3, 9),
                         "ping-3-hook-9")
        self.assertEqual(test_delivery_key_for(3, 9),
                         "test-3-hook-9")
        for key in (ping_delivery_key_for(3, 9),
                    test_delivery_key_for(3, 9)):
            self.assertFalse(key.startswith("evt-"))

    def test_decide_send_refuses_inactive_only(self):
        self.assertIsNone(decide_send(True))
        self.assertIsNone(decide_send(1))
        for inactive in (False, 0, None):
            with self.assertRaises(WebhookPingError) as cm:
                decide_send(inactive)
            self.assertEqual(cm.exception.reason,
                             "subscription_inactive")

    def test_sample_detail_follows_the_verbs_contract(self):
        push = sample_detail(get_webhook_event("repo.push"))
        self.assertEqual(push, {
            "synthetic": True, "test": True, "ref": "test-ref",
            "old": "test-old", "new": "test-new"})
        issue = sample_detail(
            get_webhook_event("repo.issue.create"))
        self.assertEqual(issue["number"], 1)
        self.assertIsInstance(issue["number"], int)

    def test_ping_payload_is_s247s_envelope(self):
        payload = build_ping_payload(
            ping_id=5, actor="volmarr", level="repository",
            parent_name="volmarr/pub",
            parent_key="volmarr/pub", occurred_at=T0)
        self.assertEqual(tuple(payload.keys()), PAYLOAD_FIELDS)
        self.assertEqual(payload["delivery_id"], "ping-5")
        self.assertEqual(payload["event"], "ping")
        self.assertEqual(payload["actor"], "volmarr")
        self.assertEqual(payload["target"], "volmarr/pub")
        self.assertEqual(payload["repository"], "volmarr/pub")
        self.assertEqual(payload["refs"], ["repo:volmarr/pub"])
        self.assertEqual(payload["detail"]["kind"], "ping")
        self.assertEqual(payload["detail"]["message"],
                         PING_MESSAGE)
        self.assertTrue(payload["detail"]["synthetic"])
        self.assertTrue(payload["detail"]["test"])
        self.assertEqual(
            json.loads(ping_payload_json(payload)), payload)

    def test_org_test_payload_belongs_to_no_repository(self):
        payload = build_test_payload(
            ping_id=6,
            spec=get_webhook_event("repo.issue.create"),
            actor="yrsa", level="organization",
            parent_name="crew", parent_key="crew",
            occurred_at=T0)
        self.assertEqual(tuple(payload.keys()), PAYLOAD_FIELDS)
        self.assertEqual(payload["delivery_id"], "test-6")
        self.assertEqual(payload["event"], "repo.issue.create")
        self.assertEqual(payload["target"], "crew")
        self.assertIsNone(payload["repository"])
        self.assertEqual(payload["refs"], ["org:crew"])
        self.assertEqual(payload["detail"]["number"], 1)

    def test_validate_test_verb_refusals(self):
        with self.assertRaises(WebhookPingError) as cm:
            validate_test_verb("repo.nope.nope", "repository")
        self.assertEqual(cm.exception.reason,
                         "webhook_event_unknown")
        with self.assertRaises(WebhookPingError) as cm:
            validate_test_verb("auth.login.success",
                               "repository")
        self.assertEqual(cm.exception.reason,
                         "webhook_event_not_deliverable")
        with self.assertRaises(WebhookPingError) as cm:
            validate_test_verb("auth.organization.create",
                               "repository")
        self.assertEqual(cm.exception.reason,
                         "webhook_event_scope_mismatch")
        spec = validate_test_verb("auth.organization.create",
                                  "organization")
        self.assertEqual(spec.verb, "auth.organization.create")


class RepoPingTests(WorldCase):
    def test_repo_ping_queues_one_synthetic_delivery(self):
        hook = self.repo_hook()
        ping = self.pings().send_repository_ping(
            self.w.owner, "volmarr", "pub", hook.id)
        self.assertEqual(ping.kind, "ping")
        self.assertEqual(ping.verb, "ping")
        self.assertTrue(ping.synthetic)
        self.assertFalse(ping.is_test_event)
        self.assertEqual(
            ping.delivery_key,
            f"ping-{ping.id}-hook-{hook.id}")
        delivery = ping.delivery
        self.assertEqual(delivery.event_id, -ping.id)
        self.assertEqual(delivery.status, "queued")
        self.assertEqual(delivery.attempts, 0)
        self.assertEqual(delivery.verb, "ping")
        self.assertEqual(delivery.url, URL)
        payload = json.loads(delivery.payload_json)
        self.assertEqual(payload["event"], "ping")
        self.assertEqual(payload["delivery_id"],
                         f"ping-{ping.id}")
        self.assertEqual(payload["actor"], "volmarr")
        self.assertTrue(payload["detail"]["synthetic"])
        self.assertEqual(self.delivery_count(), 1)
        self.assertEqual(self.ping_count(), 1)

    def test_repo_ping_writes_no_event_store_row(self):
        hook = self.repo_hook()
        before = self.event_count()
        self.pings().send_repository_ping(
            self.w.owner, "volmarr", "pub", hook.id)
        self.assertEqual(self.event_count(), before)

    def test_repo_ping_is_witnessed_on_a_standing_verb(self):
        hook = self.repo_hook()
        before = self.audit_count()
        ping = self.pings().send_repository_ping(
            self.w.owner, "volmarr", "pub", hook.id)
        self.assertEqual(self.audit_count(), before + 1)
        row = self.last_audit()
        self.assertEqual(row["action"], "repo.settings.change")
        self.assertIn("webhook.ping", row["detail"])
        self.assertIn(ping.delivery_key, row["detail"])
        self.assertNotIn(SECRET, row["detail"])

    def test_two_pings_are_two_sends_never_deduped(self):
        hook = self.repo_hook()
        store = self.pings()
        first = store.send_repository_ping(
            self.w.owner, "volmarr", "pub", hook.id)
        second = store.send_repository_ping(
            self.w.owner, "volmarr", "pub", hook.id)
        self.assertNotEqual(first.id, second.id)
        self.assertNotEqual(first.delivery_key,
                            second.delivery_key)
        self.assertEqual(first.delivery.event_id, -first.id)
        self.assertEqual(second.delivery.event_id, -second.id)
        self.assertEqual(self.delivery_count(), 2)
        self.assertEqual(self.ping_count(), 2)

    def test_site_admin_may_ping_any_repository(self):
        hook = self.repo_hook()
        ping = self.pings().send_repository_ping(
            self.w.admin, "volmarr", "pub", hook.id)
        self.assertEqual(ping.actor_id, self.w.admin.id)


class WorkerProofTests(WorldCase):
    def test_worker_carries_the_ping_signed(self):
        hook = self.repo_hook()
        ping = self.pings().send_repository_ping(
            self.w.owner, "volmarr", "pub", hook.id)
        transport = FakeTransport([200])
        self.worker(transport).run_due()
        self.assertEqual(len(transport.calls), 1)
        url, body, headers, _timeout = transport.calls[0]
        self.assertEqual(url, URL)
        self.assertEqual(headers["X-Samverk-Event"], "ping")
        self.assertEqual(headers["X-Samverk-Delivery"],
                         ping.delivery_key)
        self.assertTrue(verify_signature(
            body, headers[SIGNATURE_HEADER], SECRET))
        self.assertEqual(json.loads(body)["event"], "ping")
        entry = self.log().get_log_entry(
            self.w.owner, ping.delivery.id)
        self.assertEqual(entry.delivery.status, "delivered")
        self.assertEqual(entry.delivery.verb, "ping")
        self.assertEqual(len(entry.attempts), 1)
        self.assertEqual(entry.attempts[0].status_code, 200)

    def test_worker_carries_a_test_event_under_its_verb(self):
        hook = self.repo_hook()
        sent = self.pings().send_repository_test_event(
            self.w.owner, "volmarr", "pub", hook.id,
            "repo.issue.create")
        transport = FakeTransport([200])
        self.worker(transport).run_due()
        _url, body, headers, _t = transport.calls[0]
        self.assertEqual(headers["X-Samverk-Event"],
                         "repo.issue.create")
        self.assertEqual(headers["X-Samverk-Delivery"],
                         sent.delivery_key)
        payload = json.loads(body)
        self.assertEqual(payload["delivery_id"],
                         f"test-{sent.id}")
        self.assertEqual(payload["detail"]["number"], 1)
        self.assertTrue(payload["detail"]["synthetic"])


class TestEventTests(WorldCase):
    def test_test_event_bypasses_the_subscriptions_filter(self):
        hook = self.repo_hook(events=["repo.push"])
        sent = self.pings().send_repository_test_event(
            self.w.owner, "volmarr", "pub", hook.id,
            "repo.issue.create")
        self.assertEqual(sent.kind, "test")
        self.assertTrue(sent.is_test_event)
        self.assertEqual(sent.verb, "repo.issue.create")
        self.assertEqual(
            sent.delivery_key,
            f"test-{sent.id}-hook-{hook.id}")
        row = self.last_audit()
        self.assertEqual(row["action"], "repo.settings.change")
        self.assertIn("webhook.test", row["detail"])
        self.assertIn("repo.issue.create", row["detail"])

    def test_org_ping_and_org_scope_test_event(self):
        hook = self.org_hook()
        store = self.pings()
        ping = store.send_organization_ping(
            self.w.orgowner, "crew", hook.id)
        self.assertEqual(ping.level, "organization")
        payload = json.loads(ping.delivery.payload_json)
        self.assertEqual(payload["target"], "crew")
        self.assertIsNone(payload["repository"])
        sent = store.send_organization_test_event(
            self.w.orgowner, "crew", hook.id,
            "auth.organization.create")
        self.assertEqual(sent.verb, "auth.organization.create")
        detail = json.loads(
            sent.delivery.payload_json)["detail"]
        self.assertEqual(detail["org"], "test-org")
        row = self.last_audit()
        self.assertEqual(row["action"],
                         "auth.organization.update")
        self.assertIn("webhooks", row["detail"])
        self.assertIn("test", row["detail"])

    def test_org_subscription_carries_repo_verbs_too(self):
        hook = self.org_hook()
        sent = self.pings().send_organization_test_event(
            self.w.orgowner, "crew", hook.id,
            "repo.issue.create")
        self.assertEqual(sent.delivery.status, "queued")


class GateTests(WorldCase):
    def test_anonymous_is_refused_first(self):
        hook = self.repo_hook()
        store = self.pings()
        calls = (
            lambda: store.send_repository_ping(
                None, "volmarr", "pub", hook.id),
            lambda: store.send_repository_test_event(
                None, "volmarr", "pub", hook.id,
                "repo.issue.create"),
            lambda: store.send_organization_ping(
                None, "crew", hook.id),
            lambda: store.get_ping(None, 1),
        )
        for call in calls:
            with self.assertRaises(WebhookPingError) as cm:
                call()
            self.assertEqual(cm.exception.reason,
                             "authentication_required")
        self.assertEqual(self.delivery_count(), 0)

    def test_stranger_gate_public_admin_private_unseen(self):
        hook = self.repo_hook()
        with self.assertRaises(WebhookPingError) as cm:
            self.pings().send_repository_ping(
                self.w.stranger, "volmarr", "pub", hook.id)
        self.assertEqual(cm.exception.reason, "admin_required")
        priv = self.repo_hook(repo="priv")
        with self.assertRaises(WebhookPingError) as cm:
            self.pings().send_repository_ping(
                self.w.stranger, "volmarr", "priv", priv.id)
        self.assertEqual(cm.exception.reason, "repo_not_found")

    def test_org_member_is_not_an_owner(self):
        hook = self.org_hook()
        with self.assertRaises(WebhookPingError) as cm:
            self.pings().send_organization_ping(
                self.w.member, "crew", hook.id)
        self.assertEqual(cm.exception.reason, "not_org_owner")

    def test_subscription_is_read_scoped_by_its_parent(self):
        repo_hook = self.repo_hook()
        org_hook = self.org_hook()
        with self.assertRaises(WebhookPingError) as cm:
            self.pings().send_repository_ping(
                self.w.owner, "volmarr", "pub", org_hook.id)
        self.assertEqual(cm.exception.reason,
                         "subscription_not_found")
        with self.assertRaises(WebhookPingError) as cm:
            self.pings().send_organization_ping(
                self.w.orgowner, "crew", repo_hook.id)
        self.assertEqual(cm.exception.reason,
                         "subscription_not_found")

    def test_inactive_subscription_refuses_and_queues_nothing(
            self):
        hook = self.repo_hook()
        self.w.hooks.set_repository_subscription_active(
            self.w.owner, "volmarr", "pub", hook.id, False)
        before = self.audit_count()
        store = self.pings()
        with self.assertRaises(WebhookPingError) as cm:
            store.send_repository_ping(
                self.w.owner, "volmarr", "pub", hook.id)
        self.assertEqual(cm.exception.reason,
                         "subscription_inactive")
        with self.assertRaises(WebhookPingError) as cm:
            store.send_repository_test_event(
                self.w.owner, "volmarr", "pub", hook.id,
                "repo.issue.create")
        self.assertEqual(cm.exception.reason,
                         "subscription_inactive")
        self.assertEqual(self.delivery_count(), 0)
        self.assertEqual(self.ping_count(), 0)
        self.assertEqual(self.audit_count(), before)

    def test_taxonomy_refusals_queue_and_witness_nothing(self):
        hook = self.repo_hook()
        before = self.audit_count()
        store = self.pings()
        for verb, reason in (
                ("repo.nope.nope", "webhook_event_unknown"),
                ("auth.login.success",
                 "webhook_event_not_deliverable"),
                ("auth.organization.create",
                 "webhook_event_scope_mismatch")):
            with self.assertRaises(WebhookPingError) as cm:
                store.send_repository_test_event(
                    self.w.owner, "volmarr", "pub", hook.id,
                    verb)
            self.assertEqual(cm.exception.reason, reason)
        self.assertEqual(self.delivery_count(), 0)
        self.assertEqual(self.ping_count(), 0)
        self.assertEqual(self.audit_count(), before)


class ReadTests(WorldCase):
    def test_history_is_newest_first_with_counts(self):
        hook = self.repo_hook()
        store = self.pings()
        store.send_repository_ping(
            self.w.owner, "volmarr", "pub", hook.id)
        store.send_repository_test_event(
            self.w.owner, "volmarr", "pub", hook.id,
            "repo.issue.create")
        history = store.pings_for_repository(
            self.w.owner, "volmarr", "pub")
        self.assertEqual([p.kind for p in history],
                         ["test", "ping"])
        self.assertEqual(store.counts_for(history),
                         {"ping": 1, "test": 1})
        org_history = store.pings_for_organization(
            self.w.orgowner, "crew")
        self.assertEqual(org_history, ())

    def test_get_ping_gates_and_missing_names(self):
        hook = self.repo_hook()
        ping = self.pings().send_repository_ping(
            self.w.owner, "volmarr", "pub", hook.id)
        found = self.pings().get_ping(self.w.owner, ping.id)
        self.assertEqual(found.id, ping.id)
        with self.assertRaises(WebhookPingError) as cm:
            self.pings().get_ping(self.w.stranger, ping.id)
        self.assertEqual(cm.exception.reason, "admin_required")
        for missing in (999, "x", None):
            with self.assertRaises(WebhookPingError) as cm:
                self.pings().get_ping(self.w.owner, missing)
            self.assertEqual(cm.exception.reason,
                             "webhook_ping_not_found")


class RenderTests(WorldCase):
    def test_render_names_the_proof_and_hides_the_secret(self):
        hook = self.repo_hook()
        ping = self.pings().send_repository_ping(
            self.w.owner, "volmarr", "pub", hook.id)
        page = render_webhook_pings("Synthetic sends", [ping])
        self.assertIn(ping.delivery_key, page)
        self.assertIn("synthetic", page)
        self.assertNotIn(SECRET, page)
        self.assertNotIn(secret_digest(SECRET), page)
        self.assertIn("not a real", render_webhook_ping(ping))

    def test_empty_history_teaches_the_model(self):
        page = render_webhook_pings("Synthetic sends", [])
        self.assertIn("No webhook pings", page)

    def test_words_say_synthetic_in_plain_language(self):
        hook = self.repo_hook()
        ping = self.pings().send_repository_ping(
            self.w.owner, "volmarr", "pub", hook.id)
        self.assertIn("Synthetic", ping.words)
        self.assertIn("not a real", ping.words)


if __name__ == "__main__":
    unittest.main()
