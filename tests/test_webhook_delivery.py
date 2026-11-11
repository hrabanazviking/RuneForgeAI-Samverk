"""S-250 acceptance battery: webhook delivery worker.

Acceptance (roadmap S-250): Delivery worker --
queued deliveries with exponential backoff,
dead-letter after the stated attempts, all off
the request path.

The centre is samverk/webhook_delivery.py: a
durable outbox (migration 97) filled only through
S-248's own routing (subscriptions_for_event),
its payload frozen from S-247's payload_json and
its address snapshotted at enqueue, attempted by
an off-path worker over an injected transport
seam, signed at attempt time through S-249's
delivery_headers and no other road, retrying
failures under the pure backoff law (60s doubling,
3600s cap, plus the worker's jitter seam) and
resting dead after the stated MAX_ATTEMPTS (5),
with every attempt recorded redacted for S-251's
log. No test touches the network: every transport
is a fake.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import io, sys, tempfile, unittest
from contextlib import redirect_stdout
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
    BATCH_LIMIT, BASE_DELAY_SECONDS, DELIVERY_HEADER,
    DELIVERY_STATUSES, DELIVERY_TIMEOUT_SECONDS, EVENT_HEADER,
    MAX_ATTEMPTS, MAX_DELAY_SECONDS, TransportResult,
    WebhookDelivery, WebhookDeliveryError, WebhookDeliveryStore,
    backoff_delay, build_delivery_headers, delivery_key_for, main,
    render_deliveries, render_delivery, render_delivery_attempt)
from samverk.webhook_events import WebhookEventsError, payload_json
from samverk.webhook_signing import (
    SIGNATURE_HEADER, verify_signature, verify_signature_with_digest)
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
    """A scripted transport: each call pops the
    next outcome -- an int is a status, an
    exception instance is raised. Every call is
    recorded (url, body, headers, timeout); an
    unscripted call answers 200."""

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
        stranger=stranger, repos=repos, orgs=orgs, org=org,
        members=members, crew_repo=crew_repo, hooks=hooks,
        root=root)


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

    def store(self, transport=None, jitter_fn=None):
        return WebhookDeliveryStore(
            self.w.conn, self.w.repos, self.w.orgs, self.w.accounts,
            transport=transport if transport is not None
            else FakeTransport(),
            time_fn=self.w.clock,
            jitter_fn=jitter_fn if jitter_fn is not None
            else (lambda delay: 0))

    def repo_hook(self, **over):
        kwargs = dict(events=["repo.issue.create"], secret=SECRET)
        kwargs.update(over)
        return self.w.hooks.create_repository_subscription(
            self.w.owner, "volmarr", "pub", URL, **kwargs)

    def audit_count(self):
        return int(self.w.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"])


class PinTests(WorldCase):
    def test_pins_schema_99_taxonomy_133(self):
        self.assertEqual(schema_version(self.w.conn), 113)
        self.assertEqual(db.MIGRATIONS[-1][0], 113)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 133)
        families = {}
        for name in taxonomy.AUDIT_EVENTS:
            families[name.split(".")[0]] = (
                families.get(name.split(".")[0], 0) + 1)
        self.assertEqual(
            families, {"auth": 33, "repo": 87, "admin": 13})

    def test_table_names_pass_the_billing_audit(self):
        from samverk.billing_hole import forbidden_terms_in
        names = {r["name"] for r in self.w.conn.execute(
            "SELECT name FROM sqlite_master"
            " WHERE type = 'table'")}
        self.assertIn("webhook_deliveries", names)
        self.assertIn("webhook_delivery_attempts", names)
        self.assertEqual(forbidden_terms_in("webhook_deliveries"), ())
        self.assertEqual(
            forbidden_terms_in("webhook_delivery_attempts"), ())

    def test_stated_constants(self):
        self.assertEqual(MAX_ATTEMPTS, 5)
        self.assertEqual(BASE_DELAY_SECONDS, 60)
        self.assertEqual(MAX_DELAY_SECONDS, 3600)
        self.assertEqual(DELIVERY_TIMEOUT_SECONDS, 10.0)
        self.assertEqual(BATCH_LIMIT, 100)
        self.assertEqual(
            DELIVERY_STATUSES,
            ("queued", "retrying", "delivered", "dead"))


class BackoffTests(unittest.TestCase):
    def test_delay_doubles_from_the_base(self):
        self.assertEqual(
            [backoff_delay(n) for n in (1, 2, 3, 4, 5, 6)],
            [60, 120, 240, 480, 960, 1920])

    def test_delay_caps_at_an_hour(self):
        self.assertEqual(backoff_delay(7), 3600)
        self.assertEqual(backoff_delay(40), 3600)

    def test_bad_counts_refused_by_name(self):
        for bad in (0, -1, True, "3", None, 2.5):
            with self.assertRaises(WebhookDeliveryError) as cm:
                backoff_delay(bad)
            self.assertEqual(
                cm.exception.reason, "webhook_attempts_invalid")


class HeaderTests(unittest.TestCase):
    def test_delivery_key_names_event_and_hook(self):
        self.assertEqual(delivery_key_for(7, 3), "evt-7-hook-3")
        self.assertEqual(delivery_key_for(12, 30), "evt-12-hook-30")

    def test_signed_headers_verify_both_roads(self):
        body = payload_json(make_event())
        headers = build_delivery_headers(
            secret_digest(SECRET), body, "repo.issue.create",
            "evt-7-hook-3")
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(headers[EVENT_HEADER], "repo.issue.create")
        self.assertEqual(headers[DELIVERY_HEADER], "evt-7-hook-3")
        presented = headers[SIGNATURE_HEADER]
        self.assertTrue(verify_signature(body, presented, SECRET))
        self.assertTrue(verify_signature_with_digest(
            body, presented, secret_digest(SECRET)))

    def test_unsigned_headers_carry_no_signature(self):
        body = payload_json(make_event())
        for digest in ("", None):
            headers = build_delivery_headers(
                digest, body, "repo.issue.create", "evt-7-hook-3")
            self.assertNotIn(SIGNATURE_HEADER, headers)
            self.assertEqual(headers[DELIVERY_HEADER], "evt-7-hook-3")


class EnqueueTests(WorldCase):
    def test_repo_event_queues_one_frozen_delivery(self):
        sub = self.repo_hook()
        store = self.store()
        event = make_event()
        found = store.enqueue_event(event)
        self.assertEqual(len(found), 1)
        delivery = found[0]
        self.assertEqual(delivery.webhook_id, sub.id)
        self.assertEqual(delivery.event_id, 7)
        self.assertEqual(delivery.verb, "repo.issue.create")
        self.assertEqual(delivery.delivery_key, f"evt-7-hook-{sub.id}")
        self.assertEqual(delivery.url, URL)
        self.assertEqual(delivery.host, "hooks.example.com")
        self.assertEqual(delivery.payload_json, payload_json(event))
        self.assertEqual(delivery.status, "queued")
        self.assertEqual(delivery.attempts, 0)
        self.assertEqual(delivery.next_attempt_at, T0)
        self.assertIsNone(delivery.last_status_code)
        self.assertEqual(delivery.last_error, "")
        self.assertEqual(store.counts(), {
            "queued": 1, "retrying": 0, "delivered": 0, "dead": 0})

    def test_enqueue_is_exactly_once(self):
        sub = self.repo_hook()
        store = self.store()
        event = make_event()
        first, created = store.enqueue_delivery(event, sub)
        self.assertTrue(created)
        second, created = store.enqueue_delivery(event, sub)
        self.assertFalse(created)
        self.assertEqual(second.id, first.id)
        self.assertEqual(len(store.enqueue_event(event)), 1)
        self.assertEqual(store.counts()["queued"], 1)

    def test_unmatched_inactive_withheld_unknown_queue_nothing(self):
        self.repo_hook()
        self.w.hooks.create_repository_subscription(
            self.w.owner, "volmarr", "pub", URL,
            events=["repo.issue.create"], active=False)
        store = self.store()
        self.assertEqual(store.enqueue_event(
            make_event(8, "repo.push", "volmarr/pub")), ())
        self.assertEqual(store.enqueue_event(
            make_event(9, "auth.login.success", "volmarr",
                       target_kind="user")), ())
        self.assertEqual(store.enqueue_event(
            make_event(10, "repo.nope", "volmarr/pub")), ())
        self.assertEqual(store.enqueue_event(
            make_event(11, "repo.issue.create", "volmarr/priv#1")), ())
        self.assertEqual(store.counts()["queued"], 0)

    def test_org_hook_gets_org_repo_and_org_scope_events(self):
        org_hook = self.w.hooks.create_organization_subscription(
            self.w.orgowner, "crew", URL,
            events=["repo.issue.create", "auth.organization.update"],
            secret=SECRET)
        self.repo_hook()
        store = self.store()
        crew_event = make_event(21, "repo.issue.create", "crew/crewdish#2")
        found = store.enqueue_event(crew_event)
        self.assertEqual([d.webhook_id for d in found], [org_hook.id])
        org_event = make_event(
            22, "auth.organization.update", "crew",
            target_kind="organization")
        found = store.enqueue_event(org_event)
        self.assertEqual([d.webhook_id for d in found], [org_hook.id])
        personal = store.enqueue_event(make_event(23))
        self.assertEqual(len(personal), 1)
        self.assertNotEqual(personal[0].webhook_id, org_hook.id)

    def test_enqueue_delivery_refuses_withheld_verb(self):
        sub = self.repo_hook()
        store = self.store()
        with self.assertRaises(WebhookEventsError) as cm:
            store.enqueue_delivery(
                make_event(31, "auth.login.success", "volmarr",
                           target_kind="user"), sub)
        self.assertEqual(
            cm.exception.reason, "webhook_event_not_deliverable")
        self.assertEqual(store.counts()["queued"], 0)

    def test_enqueue_and_attempts_audit_nothing(self):
        self.repo_hook()
        store = self.store()
        before = self.audit_count()
        store.enqueue_event(make_event())
        store.run_due()
        self.assertEqual(self.audit_count(), before)


class WorkerTests(WorldCase):
    def test_success_delivers_signed_first_try(self):
        sub = self.repo_hook()
        fake = FakeTransport([200])
        store = self.store(fake)
        event = make_event()
        store.enqueue_event(event)
        run = store.run_due()
        self.assertEqual(
            (run.due, run.attempted, run.delivered, run.retried,
             run.dead, run.skipped_inactive), (1, 1, 1, 0, 0, 0))
        delivery = store.deliveries_for_event(7)[0]
        self.assertEqual(delivery.status, "delivered")
        self.assertEqual(delivery.attempts, 1)
        self.assertEqual(delivery.last_status_code, 200)
        self.assertEqual(delivery.delivered_at, T0)
        url, body, headers, timeout = fake.calls[0]
        self.assertEqual(url, URL)
        self.assertEqual(body, payload_json(event).encode("utf-8"))
        self.assertEqual(timeout, DELIVERY_TIMEOUT_SECONDS)
        self.assertEqual(headers[EVENT_HEADER], "repo.issue.create")
        self.assertEqual(
            headers[DELIVERY_HEADER], f"evt-7-hook-{sub.id}")
        self.assertTrue(verify_signature(
            body, headers[SIGNATURE_HEADER], SECRET))
        attempts = store.attempts_for(delivery.id)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0].attempt_number, 1)
        self.assertEqual(attempts[0].status_code, 200)
        self.assertEqual(attempts[0].error, "")
        again = store.run_due()
        self.assertEqual(again.due, 0)
        self.assertEqual(len(fake.calls), 1)

    def test_unsigned_subscription_delivers_without_signature(self):
        self.w.hooks.create_repository_subscription(
            self.w.owner, "volmarr", "pub", URL,
            events=["repo.issue.create"])
        fake = FakeTransport([204])
        store = self.store(fake)
        store.enqueue_event(make_event())
        run = store.run_due()
        self.assertEqual(run.delivered, 1)
        _, _, headers, _ = fake.calls[0]
        self.assertNotIn(SIGNATURE_HEADER, headers)
        self.assertEqual(
            store.deliveries_for_event(7)[0].last_status_code, 204)

    def test_failure_retries_after_backoff_then_delivers(self):
        self.repo_hook()
        fake = FakeTransport([500, 200])
        store = self.store(fake)
        store.enqueue_event(make_event())
        run = store.run_due()
        self.assertEqual((run.attempted, run.retried), (1, 1))
        delivery = store.deliveries_for_event(7)[0]
        self.assertEqual(delivery.status, "retrying")
        self.assertEqual(delivery.attempts, 1)
        self.assertEqual(delivery.last_error, "http_500")
        self.assertEqual(delivery.last_status_code, 500)
        self.assertEqual(delivery.next_attempt_at, T0 + 60)
        self.assertEqual(store.run_due().due, 0)
        self.w.clock.now = T0 + 59
        self.assertEqual(store.run_due().due, 0)
        self.w.clock.now = T0 + 60
        run = store.run_due()
        self.assertEqual(run.delivered, 1)
        delivery = store.deliveries_for_event(7)[0]
        self.assertEqual(delivery.status, "delivered")
        self.assertEqual(delivery.attempts, 2)
        self.assertEqual(delivery.last_error, "")
        attempts = store.attempts_for(delivery.id)
        self.assertEqual(
            [(a.attempt_number, a.status_code, a.error)
             for a in attempts],
            [(1, 500, "http_500"), (2, 200, "")])
        keys = [call[2][DELIVERY_HEADER] for call in fake.calls]
        self.assertEqual(keys[0], keys[1])

    def test_five_failures_dead_letter_and_stay_kept(self):
        self.repo_hook()
        fake = FakeTransport([503] * 5)
        store = self.store(fake)
        store.enqueue_event(make_event())
        waits = []
        for step in range(5):
            run = store.run_due()
            self.assertEqual(run.attempted, 1)
            delivery = store.deliveries_for_event(7)[0]
            if step < 4:
                self.assertEqual(run.retried, 1)
                waits.append(
                    delivery.next_attempt_at - self.w.clock.now)
                self.w.clock.now = delivery.next_attempt_at
            else:
                self.assertEqual(run.dead, 1)
        self.assertEqual(waits, [60, 120, 240, 480])
        self.assertEqual(delivery.status, "dead")
        self.assertEqual(delivery.attempts, MAX_ATTEMPTS)
        self.assertEqual(delivery.last_error, "http_503")
        self.assertEqual(delivery.dead_at, self.w.clock.now)
        self.assertEqual(
            [d.id for d in store.dead_letters()], [delivery.id])
        self.assertEqual(len(store.attempts_for(delivery.id)), 5)
        self.assertEqual(store.run_due().due, 0)
        self.assertEqual(len(fake.calls), 5)
        self.assertEqual(store.counts(), {
            "queued": 0, "retrying": 0, "delivered": 0, "dead": 1})

    def test_redirect_429_and_404_are_failures_not_deliveries(self):
        self.repo_hook()
        for code in (302, 429, 404):
            with self.w.conn:
                self.w.conn.execute(
                    "DELETE FROM webhook_delivery_attempts")
                self.w.conn.execute(
                    "DELETE FROM webhook_deliveries")
            fake = FakeTransport([code])
            store = self.store(fake)
            event = make_event(100 + code)
            store.enqueue_event(event)
            run = store.run_due()
            self.assertEqual((run.delivered, run.retried), (0, 1))
            delivery = store.deliveries_for_event(100 + code)[0]
            self.assertEqual(delivery.last_error, f"http_{code}")
            self.w.clock.now += 100000

    def test_transport_error_is_redacted_and_retried(self):
        self.repo_hook()
        fake = FakeTransport([
            TimeoutError("dial https://hooks.example.com" + SECRET)])
        store = self.store(fake)
        store.enqueue_event(make_event())
        run = store.run_due()
        self.assertEqual((run.attempted, run.retried), (1, 1))
        delivery = store.deliveries_for_event(7)[0]
        self.assertEqual(delivery.last_error, "transport_TimeoutError")
        self.assertIsNone(delivery.last_status_code)
        attempt = store.attempts_for(delivery.id)[0]
        self.assertEqual(attempt.error, "transport_TimeoutError")
        self.assertIsNone(attempt.status_code)
        self.assertNotIn(SECRET, delivery.last_error)
        self.assertNotIn(SECRET, attempt.error)
        self.assertNotIn(SECRET, delivery.words)

    def test_jitter_seam_extends_the_wait(self):
        self.repo_hook()
        fake = FakeTransport([500])
        store = self.store(fake, jitter_fn=lambda delay: 30)
        store.enqueue_event(make_event())
        store.run_due()
        delivery = store.deliveries_for_event(7)[0]
        self.assertEqual(delivery.next_attempt_at, T0 + 60 + 30)

    def test_attempt_duration_comes_from_the_clock(self):
        self.repo_hook()
        fake = FakeTransport([200], clock=self.w.clock, advance=3)
        store = self.store(fake)
        store.enqueue_event(make_event())
        store.run_due()
        delivery = store.deliveries_for_event(7)[0]
        attempt = store.attempts_for(delivery.id)[0]
        self.assertEqual(attempt.duration_ms, 3000)
        self.assertEqual(attempt.finished_at - attempt.started_at, 3)

    def test_deleted_subscription_rests_dead_without_an_attempt(self):
        sub = self.repo_hook()
        fake = FakeTransport([200])
        store = self.store(fake)
        store.enqueue_event(make_event())
        self.w.hooks.delete_repository_subscription(
            self.w.owner, "volmarr", "pub", sub.id)
        run = store.run_due()
        self.assertEqual((run.attempted, run.dead), (0, 1))
        self.assertEqual(fake.calls, [])
        delivery = store.deliveries_for_event(7)[0]
        self.assertEqual(delivery.status, "dead")
        self.assertEqual(delivery.attempts, 0)
        self.assertEqual(delivery.last_error, "subscription_gone")
        self.assertEqual(delivery.dead_at, T0)
        self.assertEqual(store.attempts_for(delivery.id), ())

    def test_inactive_subscription_is_skipped_then_delivers(self):
        sub = self.repo_hook()
        fake = FakeTransport([200])
        store = self.store(fake)
        store.enqueue_event(make_event())
        self.w.hooks.set_repository_subscription_active(
            self.w.owner, "volmarr", "pub", sub.id, False)
        run = store.run_due()
        self.assertEqual(
            (run.attempted, run.skipped_inactive), (0, 1))
        delivery = store.deliveries_for_event(7)[0]
        self.assertEqual(delivery.status, "queued")
        self.assertEqual(delivery.attempts, 0)
        self.w.hooks.set_repository_subscription_active(
            self.w.owner, "volmarr", "pub", sub.id, True)
        run = store.run_due()
        self.assertEqual(run.delivered, 1)

    def test_address_is_the_enqueue_snapshot_not_the_edit(self):
        sub = self.repo_hook()
        fake = FakeTransport([200])
        store = self.store(fake)
        store.enqueue_event(make_event())
        self.w.hooks.update_repository_subscription(
            self.w.owner, "volmarr", "pub", sub.id,
            url="https://elsewhere.example.com/hook",
            events=["repo.issue.create"])
        store.run_due()
        self.assertEqual(fake.calls[0][0], URL)

    def test_batch_limit_and_oldest_due_first(self):
        self.repo_hook()
        fake = FakeTransport([200, 200, 200])
        store = self.store(fake)
        for event_id in (41, 42, 43):
            store.enqueue_event(make_event(event_id))
            self.w.clock.now += 1
        run = store.run_due(limit=2)
        self.assertEqual((run.due, run.delivered), (2, 2))
        self.assertEqual(
            [d.event_id for d in store.due_deliveries()], [43])
        run = store.run_due()
        self.assertEqual(run.delivered, 1)
        bodies = [call[1] for call in fake.calls]
        self.assertIn(b"evt-41", bodies[0])
        self.assertIn(b"evt-42", bodies[1])
        self.assertIn(b"evt-43", bodies[2])


class ReadTests(WorldCase):
    def test_get_delivery_and_not_found(self):
        self.repo_hook()
        store = self.store()
        delivery = store.enqueue_event(make_event())[0]
        self.assertEqual(store.get_delivery(delivery.id).id, delivery.id)
        for bad in (9999, "7", None, True):
            with self.assertRaises(WebhookDeliveryError) as cm:
                store.get_delivery(bad)
            self.assertEqual(cm.exception.reason, "delivery_not_found")
        with self.assertRaises(WebhookDeliveryError) as cm:
            store.attempts_for(9999)
        self.assertEqual(cm.exception.reason, "delivery_not_found")

    def test_lists_are_scoped_and_shaped(self):
        sub = self.repo_hook()
        store = self.store()
        store.enqueue_event(make_event(51))
        store.enqueue_event(make_event(52))
        mine = store.deliveries_for_subscription(sub.id)
        self.assertEqual([d.event_id for d in mine], [52, 51])
        self.assertEqual(store.deliveries_for_subscription(9999), ())
        self.assertEqual(store.deliveries_for_subscription("x"), ())
        self.assertEqual(
            [d.event_id for d in store.deliveries_for_event(51)], [51])
        self.assertEqual(store.deliveries_for_event("x"), ())
        self.assertEqual(store.dead_letters(), ())


class RenderTests(unittest.TestCase):
    def _delivery(self, **over):
        base = dict(
            id=1, webhook_id=2, event_id=7,
            verb="repo.issue.create", delivery_key="evt-7-hook-2",
            url="https://hooks.example.com/<x>",
            host="hooks.example.com", payload_json="{}",
            status="retrying", attempts=2, next_attempt_at=T0,
            last_status_code=500, last_error="http_500",
            created_at=T0, updated_at=T0, delivered_at=None,
            dead_at=None)
        base.update(over)
        return WebhookDelivery(**base)

    def test_render_escapes_and_speaks_in_words(self):
        html = render_delivery(self._delivery())
        self.assertIn("&lt;x&gt;", html)
        self.assertNotIn("<x>", html)
        self.assertIn("waiting to retry", html)
        self.assertIn("2 of 5 attempts", html)
        self.assertNotIn(SECRET, html)
        self.assertNotIn(secret_digest(SECRET), html)

    def test_render_empty_list_teaches_the_model(self):
        html = render_deliveries("Deliveries", [])
        self.assertIn("No webhook deliveries yet", html)
        self.assertIn("off the request path", html)
        self.assertIn("5", html)

    def test_render_attempt_words(self):
        from samverk.webhook_delivery import DeliveryAttempt
        attempt = DeliveryAttempt(
            id=1, delivery_id=1, attempt_number=3, status_code=None,
            error="transport_TimeoutError", duration_ms=10000,
            started_at=T0, finished_at=T0 + 10)
        html = render_delivery_attempt(attempt)
        self.assertIn("Attempt 3", html)
        self.assertIn("transport_TimeoutError", html)
        self.assertIn("10000 ms", html)

    def test_words_say_the_standing(self):
        delivery = self._delivery()
        self.assertIn("evt-7-hook-2", delivery.words)
        self.assertIn("http_500", delivery.words)
        done = self._delivery(status="delivered", last_error="")
        self.assertIn("HTTP 500", done.words)


class MainTests(WorldCase):
    def test_main_usage_error(self):
        self.assertEqual(main([]), 2)
        self.assertEqual(main(["only-one"]), 2)

    def test_main_runs_an_empty_queue_quietly(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main([str(self.w.root / "fresh.db"),
                         str(self.w.root)])
        self.assertEqual(code, 0)
        self.assertIn("0 due", out.getvalue())
        self.assertIn("0 attempted", out.getvalue())


if __name__ == "__main__":
    unittest.main()
