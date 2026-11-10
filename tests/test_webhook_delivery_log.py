"""S-251 acceptance battery: delivery log and redelivery.

Acceptance (roadmap S-251): Delivery log and
redelivery -- admins and owners inspect attempts
(request/response, timing) and redeliver in one
click (findability law).

The centre is samverk/webhook_delivery_log.py:
the reading face over S-250's outbox and attempt
history (migration 98 adds the redelivery
lineage), gated by S-248's own standings --
S-190's admin rung for a repository delivery,
S-186's owners for an organization delivery,
site admins anywhere -- and the one-click
redelivery that queues a FRESH delivery (same
frozen payload, address snapshotted as the
subscription stands now, key numbered per
subscription x event, original named in
redelivery_of and never touched), judged by the
pure decide_redelivery and carried afterwards by
S-250's worker like any queued row. No test
touches the network: every transport is a fake.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.event_store import CanonicalEvent
from samverk.organization_members import OrgMembershipStore
from samverk.organizations import OrganizationStore
from samverk.org_repositories import OrgRepoStore
from samverk.repositories import RepositoryStore
from samverk.webhook_delivery import (
    TransportResult, WebhookDeliveryStore)
from samverk.webhook_delivery_log import (
    REDELIVERABLE_STATUSES, DeliveryLogStore,
    WebhookDeliveryLogError, can_inspect, decide_redelivery,
    redelivery_key_for, render_delivery_log_entry,
    render_delivery_log_page)
from samverk.webhook_subscriptions import (
    WebhookSubscriptionStore, secret_digest)

PW = "correct horse battery"
URL = "https://hooks.example.com/samverk"
URL2 = "https://hooks2.example.com/elsewhere"
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


def make_event(event_id=7, verb="repo.issue.create",
               target_id="volmarr/pub#1", target_kind="repo"):
    return CanonicalEvent(
        id=event_id, audit_seq=event_id, actor_kind="user",
        actor_id=3, actor="volmarr", verb=verb,
        target_kind=target_kind, target_id=target_id,
        refs=("repo:volmarr/pub", "number:1"),
        detail={"number": 1}, outcome="success", created_at=T0)


class WorldCase(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.w = make_world(Path(self._td.name))
        self.addCleanup(self.w.conn.close)

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

    def delivered(self, event_id=7):
        if not self.w.hooks.list_repository_subscriptions(
                self.w.owner, "volmarr", "pub"):
            self.repo_hook()
        store = self.worker(FakeTransport([200], clock=self.w.clock,
                                          advance=3))
        store.enqueue_event(make_event(event_id))
        store.run_due()
        return store.deliveries_for_event(event_id)[0]

    def dead(self, event_id=7, repo="pub"):
        hook = self.repo_hook(repo=repo) if repo else self.org_hook()
        store = self.worker(FakeTransport([500] * 5))
        store.enqueue_event(make_event(event_id))
        for step in (0, 100, 300, 600, 1100):
            self.w.clock.now = T0 + step
            store.run_due(now=T0 + step)
        found = store.deliveries_for_event(event_id)
        assert len(found) == 1 and found[0].status == "dead", found
        return hook, found[0]

    def audit_count(self):
        return int(self.w.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"])

    def delivery_count(self):
        return int(self.w.conn.execute(
            "SELECT COUNT(*) AS n FROM webhook_deliveries"
        ).fetchone()["n"])


class PinTests(WorldCase):
    def test_pins_schema_99_taxonomy_131(self):
        self.assertEqual(schema_version(self.w.conn), 102)
        self.assertEqual(db.MIGRATIONS[-1][0], 102)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 131)
        families = {}
        for name in taxonomy.AUDIT_EVENTS:
            families[name.split(".")[0]] = (
                families.get(name.split(".")[0], 0) + 1)
        self.assertEqual(
            families, {"auth": 33, "repo": 85, "admin": 13})

    def test_lineage_columns_and_index_stand(self):
        cols = {r["name"] for r in self.w.conn.execute(
            "PRAGMA table_info(webhook_deliveries)")}
        self.assertIn("redelivery_of", cols)
        self.assertIn("redelivery_number", cols)
        sql = self.w.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index'"
            " AND name = 'idx_webhook_deliveries_once'"
        ).fetchone()["sql"]
        self.assertIn("redelivery_number", sql)
        self.assertEqual(REDELIVERABLE_STATUSES, ("delivered", "dead"))


class PureLawTests(unittest.TestCase):
    def test_can_inspect_matrix(self):
        self.assertTrue(can_inspect(
            is_site_admin=True, level="repository"))
        self.assertTrue(can_inspect(
            is_site_admin=True, level="organization"))
        self.assertTrue(can_inspect(
            is_site_admin=False, level="repository",
            repo_role="admin"))
        self.assertFalse(can_inspect(
            is_site_admin=False, level="repository",
            repo_role="write"))
        self.assertFalse(can_inspect(
            is_site_admin=False, level="repository",
            repo_role=None))
        self.assertTrue(can_inspect(
            is_site_admin=False, level="organization",
            org_role="owner"))
        self.assertFalse(can_inspect(
            is_site_admin=False, level="organization",
            org_role="member"))
        self.assertFalse(can_inspect(
            is_site_admin=False, level="instance",
            repo_role="admin", org_role="owner"))

    def test_decide_redelivery_by_name(self):
        self.assertIsNone(decide_redelivery("delivered", True))
        self.assertIsNone(decide_redelivery("dead", True))
        for status in ("queued", "retrying", "bogus", None):
            with self.assertRaises(WebhookDeliveryLogError) as cm:
                decide_redelivery(status, True)
            self.assertEqual(cm.exception.reason,
                             "delivery_not_redeliverable")
        with self.assertRaises(WebhookDeliveryLogError) as cm:
            decide_redelivery("dead", False)
        self.assertEqual(cm.exception.reason, "subscription_gone")

    def test_redelivery_key_names_stem_and_number(self):
        self.assertEqual(redelivery_key_for(7, 3, 1),
                         "evt-7-hook-3-redelivery-1")
        self.assertEqual(redelivery_key_for(12, 30, 2),
                         "evt-12-hook-30-redelivery-2")


class InspectTests(WorldCase):
    def test_repo_admin_inspects_attempts_and_timing(self):
        delivery = self.delivered()
        entry = self.log().get_log_entry(self.w.owner, delivery.id)
        self.assertEqual(entry.delivery.id, delivery.id)
        self.assertEqual(entry.level, "repository")
        self.assertEqual(entry.parent_name, "volmarr/pub")
        self.assertTrue(entry.subscription_active)
        self.assertTrue(entry.subscription_has_secret)
        self.assertEqual(entry.secret_words,
                         "a secret is set (never shown)")
        self.assertFalse(entry.is_redelivery)
        self.assertEqual(entry.redelivery_number, 0)
        self.assertEqual(len(entry.attempts), 1)
        attempt = entry.attempts[0]
        self.assertEqual(attempt.attempt_number, 1)
        self.assertEqual(attempt.status_code, 200)
        self.assertEqual(attempt.error, "")
        self.assertEqual(attempt.duration_ms, 3000)
        self.assertEqual(entry.total_duration_ms, 3000)
        self.assertIn("HTTP 200", entry.words)
        self.assertIn("3000 ms", entry.words)

    def test_dead_delivery_shows_every_attempt_in_order(self):
        _, delivery = self.dead()
        entry = self.log().get_log_entry(self.w.owner, delivery.id)
        self.assertEqual(
            [a.attempt_number for a in entry.attempts],
            [1, 2, 3, 4, 5])
        self.assertTrue(all(
            a.status_code == 500 and a.error == "http_500"
            for a in entry.attempts))
        starts = [a.started_at for a in entry.attempts]
        self.assertEqual(starts, sorted(starts))
        self.assertTrue(entry.redeliverable)
        self.assertIn("dead-lettered", entry.words)
        self.assertIn("It can be redelivered.", entry.words)

    def test_anonymous_is_refused_before_any_read(self):
        delivery = self.delivered()
        with self.assertRaises(WebhookDeliveryLogError) as cm:
            self.log().get_log_entry(None, delivery.id)
        self.assertEqual(cm.exception.reason,
                         "authentication_required")
        with self.assertRaises(WebhookDeliveryLogError) as cm:
            self.log().log_for_repository(None, "volmarr", "pub")
        self.assertEqual(cm.exception.reason,
                         "authentication_required")

    def test_member_below_admin_is_refused_by_name(self):
        delivery = self.delivered()
        with self.assertRaises(WebhookDeliveryLogError) as cm:
            self.log().get_log_entry(self.w.member, delivery.id)
        self.assertEqual(cm.exception.reason, "admin_required")
        with self.assertRaises(WebhookDeliveryLogError) as cm:
            self.log().log_for_repository(
                self.w.member, "volmarr", "pub")
        self.assertEqual(cm.exception.reason, "admin_required")

    def test_private_repo_is_uniformly_not_found(self):
        self.repo_hook(repo="priv")
        store = self.worker(FakeTransport([200]))
        store.enqueue_event(make_event(9, target_id="volmarr/priv#1"))
        delivery = store.deliveries_for_event(9)[0]
        with self.assertRaises(WebhookDeliveryLogError) as cm:
            self.log().get_log_entry(self.w.stranger, delivery.id)
        self.assertEqual(cm.exception.reason, "repo_not_found")
        with self.assertRaises(WebhookDeliveryLogError) as cm:
            self.log().log_for_repository(
                self.w.stranger, "volmarr", "priv")
        self.assertEqual(cm.exception.reason, "repo_not_found")

    def test_missing_and_misshapen_ids_are_not_found(self):
        for bad in (9999, "7", None, True, 2.5):
            with self.assertRaises(WebhookDeliveryLogError) as cm:
                self.log().get_log_entry(self.w.owner, bad)
            self.assertEqual(cm.exception.reason,
                             "delivery_not_found")

    def test_org_owner_inspects_and_member_is_refused(self):
        self.org_hook()
        store = self.worker(FakeTransport([200]))
        store.enqueue_event(make_event(
            21, target_id="crew/crewdish#2"))
        delivery = store.deliveries_for_event(21)[0]
        entry = self.log().get_log_entry(self.w.orgowner, delivery.id)
        self.assertEqual(entry.level, "organization")
        self.assertEqual(entry.parent_name, "crew")
        for viewer in (self.w.member, self.w.stranger):
            with self.assertRaises(WebhookDeliveryLogError) as cm:
                self.log().get_log_entry(viewer, delivery.id)
            self.assertEqual(cm.exception.reason, "not_org_owner")
        with self.assertRaises(WebhookDeliveryLogError) as cm:
            self.log().log_for_organization(self.w.member, "crew")
        self.assertEqual(cm.exception.reason, "not_org_owner")

    def test_site_admin_inspects_repo_and_org(self):
        repo_delivery = self.delivered()
        self.org_hook()
        store = self.worker(FakeTransport([200]))
        store.enqueue_event(make_event(
            22, target_id="crew/crewdish#3"))
        org_delivery = store.deliveries_for_event(22)[0]
        log = self.log()
        self.assertEqual(
            log.get_log_entry(self.w.admin, repo_delivery.id)
            .delivery.id, repo_delivery.id)
        self.assertEqual(
            log.get_log_entry(self.w.admin, org_delivery.id)
            .delivery.id, org_delivery.id)
        self.assertEqual(len(log.log_for_repository(
            self.w.admin, "volmarr", "priv")), 0)

    def test_lists_are_scoped_newest_first_and_filterable(self):
        first = self.delivered(7)
        second = self.delivered(8)
        self.repo_hook(repo="priv")
        log = self.log()
        entries = log.log_for_repository(
            self.w.owner, "volmarr", "pub")
        self.assertEqual([e.delivery.id for e in entries],
                         [second.id, first.id])
        self.assertEqual(len(log.log_for_repository(
            self.w.owner, "volmarr", "pub", status="delivered")), 2)
        self.assertEqual(log.log_for_repository(
            self.w.owner, "volmarr", "pub", status="dead"), ())
        self.assertEqual(log.log_for_organization(
            self.w.orgowner, "crew"), ())
        with self.assertRaises(WebhookDeliveryLogError) as cm:
            log.log_for_repository(
                self.w.owner, "volmarr", "pub", status="bogus")
        self.assertEqual(cm.exception.reason,
                         "delivery_status_invalid")
        counts = log.counts_for(entries)
        self.assertEqual(counts, {"queued": 0, "retrying": 0,
                                  "delivered": 2, "dead": 0})

    def test_inspection_writes_and_audits_nothing(self):
        delivery = self.delivered()
        before_audit = self.audit_count()
        before_rows = self.delivery_count()
        log = self.log()
        log.get_log_entry(self.w.owner, delivery.id)
        log.log_for_repository(self.w.owner, "volmarr", "pub")
        self.assertEqual(self.audit_count(), before_audit)
        self.assertEqual(self.delivery_count(), before_rows)


class RedeliverTests(WorldCase):
    def test_redeliver_dead_queues_a_fresh_named_copy(self):
        hook, original = self.dead()
        self.w.hooks.update_repository_subscription(
            self.w.owner, "volmarr", "pub", hook.id, url=URL2)
        entry = self.log().redeliver(self.w.owner, original.id)
        fresh = entry.delivery
        self.assertNotEqual(fresh.id, original.id)
        self.assertEqual(fresh.status, "queued")
        self.assertEqual(fresh.attempts, 0)
        self.assertEqual(fresh.webhook_id, original.webhook_id)
        self.assertEqual(fresh.event_id, original.event_id)
        self.assertEqual(fresh.payload_json, original.payload_json)
        self.assertEqual(fresh.url, URL2)
        self.assertEqual(fresh.host, "hooks2.example.com")
        self.assertEqual(
            fresh.delivery_key,
            f"{original.delivery_key}-redelivery-1")
        self.assertTrue(entry.is_redelivery)
        self.assertEqual(entry.redelivery_of, original.id)
        self.assertEqual(entry.redelivery_number, 1)
        self.assertEqual(entry.attempts, ())
        after = self.worker().get_delivery(original.id)
        self.assertEqual(after.status, "dead")
        self.assertEqual(after.attempts, 5)
        self.assertEqual(after.url, URL)
        self.assertEqual(self.delivery_count(), 2)

    def test_redeliver_delivered_and_numbering(self):
        original = self.delivered()
        log = self.log()
        one = log.redeliver(self.w.owner, original.id)
        two = log.redeliver(self.w.owner, original.id)
        self.assertEqual(one.redelivery_number, 1)
        self.assertEqual(two.redelivery_number, 2)
        self.assertNotEqual(one.delivery.delivery_key,
                            two.delivery.delivery_key)
        self.assertEqual(two.redelivery_of, original.id)
        self.assertEqual(self.delivery_count(), 3)

    def test_redeliver_still_travelling_is_refused(self):
        self.repo_hook()
        store = self.worker(FakeTransport([500]))
        store.enqueue_event(make_event())
        queued = store.deliveries_for_event(7)[0]
        with self.assertRaises(WebhookDeliveryLogError) as cm:
            self.log().redeliver(self.w.owner, queued.id)
        self.assertEqual(cm.exception.reason,
                         "delivery_not_redeliverable")
        store.run_due()
        retrying = store.deliveries_for_event(7)[0]
        self.assertEqual(retrying.status, "retrying")
        with self.assertRaises(WebhookDeliveryLogError) as cm:
            self.log().redeliver(self.w.owner, retrying.id)
        self.assertEqual(cm.exception.reason,
                         "delivery_not_redeliverable")
        self.assertEqual(self.delivery_count(), 1)

    def test_redeliver_gate_matches_inspection_gate(self):
        original = self.delivered()
        with self.assertRaises(WebhookDeliveryLogError) as cm:
            self.log().redeliver(None, original.id)
        self.assertEqual(cm.exception.reason,
                         "authentication_required")
        with self.assertRaises(WebhookDeliveryLogError) as cm:
            self.log().redeliver(self.w.member, original.id)
        self.assertEqual(cm.exception.reason, "admin_required")
        self.assertEqual(self.delivery_count(), 1)
        entry = self.log().redeliver(self.w.admin, original.id)
        self.assertEqual(entry.delivery.status, "queued")

    def test_redelivery_is_carried_by_the_worker(self):
        _, original = self.dead()
        entry = self.log().redeliver(self.w.owner, original.id)
        store = self.worker(FakeTransport([200]))
        run = store.run_due(now=self.w.clock.now)
        self.assertEqual(run.delivered, 1)
        carried = store.get_delivery(entry.delivery.id)
        self.assertEqual(carried.status, "delivered")
        self.assertEqual(carried.attempts, 1)
        self.assertEqual(store.get_delivery(original.id).status,
                         "dead")

    def test_original_enqueue_stays_exactly_once(self):
        _, original = self.dead()
        self.log().redeliver(self.w.owner, original.id)
        store = self.worker()
        found = store.enqueue_event(make_event())
        self.assertEqual([d.id for d in found], [original.id])
        self.assertEqual(self.delivery_count(), 2)
        self.assertEqual(len(store.deliveries_for_event(7)), 2)

    def test_deleted_subscription_refuses_and_closes_the_log(self):
        hook, original = self.dead()
        self.w.hooks.delete_repository_subscription(
            self.w.owner, "volmarr", "pub", hook.id)
        with self.assertRaises(WebhookDeliveryLogError) as cm:
            self.log().redeliver(self.w.admin, original.id)
        self.assertEqual(cm.exception.reason, "subscription_gone")
        with self.assertRaises(WebhookDeliveryLogError) as cm:
            self.log().get_log_entry(self.w.owner, original.id)
        self.assertEqual(cm.exception.reason, "admin_required")
        entry = self.log().get_log_entry(self.w.admin, original.id)
        self.assertIsNone(entry.subscription_active)
        self.assertEqual(entry.secret_words, "subscription gone")
        self.assertFalse(entry.redeliverable)

    def test_redelivery_is_witnessed_and_refusals_are_not(self):
        _, original = self.dead()
        before = self.audit_count()
        self.log().redeliver(self.w.owner, original.id)
        rows = self.w.conn.execute(
            "SELECT * FROM audit_log ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        self.assertEqual(rows["action"], "repo.settings.change")
        self.assertIn("webhook.redeliver", rows["detail"])
        self.assertEqual(self.audit_count(), before + 1)
        with self.assertRaises(WebhookDeliveryLogError):
            self.log().redeliver(self.w.member, original.id)
        self.assertEqual(self.audit_count(), before + 1)

    def test_org_redelivery_by_owner_is_witnessed(self):
        self.org_hook()
        store = self.worker(FakeTransport([200]))
        store.enqueue_event(make_event(
            23, target_id="crew/crewdish#4"))
        store.run_due()
        original = store.deliveries_for_event(23)[0]
        with self.assertRaises(WebhookDeliveryLogError) as cm:
            self.log().redeliver(self.w.member, original.id)
        self.assertEqual(cm.exception.reason, "not_org_owner")
        entry = self.log().redeliver(self.w.orgowner, original.id)
        self.assertEqual(entry.level, "organization")
        rows = self.w.conn.execute(
            "SELECT * FROM audit_log ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        self.assertEqual(rows["action"],
                         "auth.organization.update")
        self.assertIn("redeliver", rows["detail"])


class RenderTests(WorldCase):
    def test_page_shows_attempts_timing_and_the_control(self):
        _, dead = self.dead()
        delivered = self.delivered(8)
        log = self.log()
        entries = log.log_for_repository(
            self.w.owner, "volmarr", "pub")
        page = render_delivery_log_page("Delivery log", entries)
        self.assertIn("Delivery log", page)
        self.assertIn(dead.delivery_key, page)
        self.assertIn("Attempt 5: http_500", page)
        self.assertIn("Total attempt time:", page)
        self.assertIn(
            f'action="/webhooks/deliveries/{dead.id}/redeliver"',
            page)
        self.assertIn(
            f"Redeliver delivery {dead.delivery_key}", page)
        self.assertIn(delivered.delivery_key, page)
        self.assertNotIn(SECRET, page)
        self.assertNotIn(secret_digest(SECRET), page)
        self.assertNotIn(dead.payload_json, page)

    def test_queued_entry_says_why_it_cannot_redeliver(self):
        self.repo_hook()
        store = self.worker()
        store.enqueue_event(make_event())
        entry = self.log().log_for_repository(
            self.w.owner, "volmarr", "pub")[0]
        html = render_delivery_log_entry(entry)
        self.assertIn("No attempts yet.", html)
        self.assertIn("still on its way", html)
        self.assertNotIn("<form", html)
        self.assertIn("queued, never attempted", html)

    def test_empty_log_teaches_the_model(self):
        page = render_delivery_log_page("Delivery log", ())
        self.assertIn("No webhook deliveries yet.", page)
        self.assertIn("redelivered from this", page)

    def test_render_escapes_every_value(self):
        from samverk.webhook_delivery import WebhookDelivery
        from samverk.webhook_delivery_log import DeliveryLogEntry
        delivery = WebhookDelivery(
            id=1, webhook_id=2, event_id=3,
            verb="repo.issue.create",
            delivery_key="evt-3-hook-2", url="https://x.example/",
            host="x.example", payload_json="{}", status="dead",
            attempts=5, next_attempt_at=T0, last_status_code=500,
            last_error="http_500", created_at=T0, updated_at=T0,
            delivered_at=None, dead_at=T0)
        entry = DeliveryLogEntry(
            delivery=delivery, level="repository",
            parent_name="<script>alert(1)</script>",
            parent_key="x/y", subscription_active=True,
            subscription_has_secret=False, redelivery_of=None,
            redelivery_number=0, attempts=())
        html = render_delivery_log_entry(entry)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)
