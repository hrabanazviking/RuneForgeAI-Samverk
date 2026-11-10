"""S-241 acceptance battery: API rate limiting.

Acceptance (roadmap S-241): Rate limiting on the
API -- per-token buckets, limit headers on every
response, honest `Retry-After`; limits are
instance-configurable.

The centre is samverk/api_rate_limit.py: buckets
keyed by the credential S-238's door resolved,
judged by one pure function, answered always
with the three limit headers, refused in S-240's
one problem format with a `Retry-After` the fake
clock proves honest, and configured through the
instance settings table (S-038's road) with the
change audited on the existing
`admin.settings.change` event.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import json, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.access_tokens import AccessTokenStore
from samverk.accounts import AccountStore
from samverk.api_auth import ApiAuthenticator, ApiIdentity
from samverk.api_contract import PROBLEM_FIELDS
from samverk.api_rate_limit import (
    HEADER_LIMIT, HEADER_REMAINING, HEADER_RESET, HEADER_RETRY_AFTER,
    RATE_LIMIT_HEADERS, RATE_LIMIT_PATH, SETTING_KEYS,
    ApiRateLimitError, ApiRateLimiter, RateLimitSettings,
    bucket_key_for, decide_bucket, default_settings, error_to_dict,
    load_rate_limit_settings, parse_rate_limit_settings,
    render_api_rate_limit_page, save_rate_limit_settings)
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.error_shape import decide_problem_status, is_registered_reason
from samverk.repositories import RepositoryStore

PW = "correct horse battery"


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = float(now)
    def __call__(self):
        return self.now


def small_settings(**overrides):
    values = dict(
        enabled=True, token_capacity=3.0,
        token_refill_per_second=1.0, anonymous_capacity=2.0,
        anonymous_refill_per_second=0.5)
    values.update(overrides)
    return RateLimitSettings(**values)


def token_identity(token_id=11, user_id=7, kind="classic_token"):
    return ApiIdentity(
        user=SimpleNamespace(id=user_id, username="volmarr"),
        kind=kind, token_id=token_id, token_title="t",
        token_prefix="svk_x", scopes=frozenset({"repo:read"}))


def password_identity(user_id=7):
    return ApiIdentity(
        user=SimpleNamespace(id=user_id, username="volmarr"),
        kind="password")


def anonymous_identity():
    return ApiIdentity(user=None, kind="anonymous")


class PureBucketTests(unittest.TestCase):
    def test_burst_up_to_capacity_then_refusal(self):
        allowed, after, wait = decide_bucket(3.0, 3.0, 1.0, 100.0, 100.0, 1.0)
        self.assertTrue(allowed)
        self.assertEqual(after, 2.0)
        self.assertEqual(wait, 0.0)
        allowed, after, wait = decide_bucket(0.5, 3.0, 1.0, 100.0, 100.0, 1.0)
        self.assertFalse(allowed)
        self.assertEqual(after, 0.5)  # a refusal charges nothing
        self.assertEqual(wait, 0.5)

    def test_refill_is_capped_and_honest(self):
        allowed, after, wait = decide_bucket(
            0.0, 3.0, 1.0, 102.0, 100.0, 1.0)
        self.assertTrue(allowed)  # two seconds refilled two tokens
        self.assertEqual(after, 1.0)
        allowed, after, wait = decide_bucket(
            2.9, 3.0, 1.0, 200.0, 100.0, 1.0)
        self.assertTrue(allowed)
        self.assertEqual(after, 2.0)  # refill never exceeds capacity

    def test_bucket_keys_are_per_token(self):
        self.assertEqual(
            bucket_key_for(token_identity(11)), "token:classic_token:11")
        self.assertEqual(
            bucket_key_for(token_identity(12)), "token:classic_token:12")
        self.assertNotEqual(
            bucket_key_for(token_identity(11)),
            bucket_key_for(token_identity(12)))
        self.assertEqual(
            bucket_key_for(password_identity()), "account:7")
        self.assertEqual(bucket_key_for(anonymous_identity()), "anonymous")


class SettingsTests(unittest.TestCase):
    def test_defaults_stand(self):
        settings = default_settings()
        self.assertTrue(settings.enabled)
        self.assertEqual(settings.token_capacity, 5000.0)
        self.assertEqual(settings.anonymous_capacity, 300.0)

    def test_parse_reads_stored_strings(self):
        settings = parse_rate_limit_settings({
            "api_rate_limit.enabled": "0",
            "api_rate_limit.token_capacity": "10",
            "api_rate_limit.token_refill_per_second": "0.25",
            "api_rate_limit.anonymous_capacity": "4",
            "api_rate_limit.anonymous_refill_per_second": "2"})
        self.assertFalse(settings.enabled)
        self.assertEqual(settings.token_capacity, 10.0)
        self.assertEqual(settings.token_refill_per_second, 0.25)
        self.assertEqual(settings.anonymous_capacity, 4.0)

    def test_parse_refuses_unreadable_values_loudly(self):
        for bad in ("many", "", "nan", "inf"):
            with self.assertRaises(ApiRateLimitError) as caught:
                parse_rate_limit_settings(
                    {"api_rate_limit.token_capacity": bad})
            self.assertEqual(
                caught.exception.reason, "rate_settings_invalid")
            self.assertEqual(
                error_to_dict(caught.exception)["status"], 400)

    def test_validate_refuses_nonpositive_limits(self):
        for field in ("token_capacity", "token_refill_per_second",
                      "anonymous_capacity",
                      "anonymous_refill_per_second"):
            with self.assertRaises(ApiRateLimitError):
                small_settings(**{field: 0.0}).validate()

    def test_settings_invalid_reason_is_registered_at_400(self):
        self.assertTrue(is_registered_reason("rate_settings_invalid"))
        self.assertEqual(
            decide_problem_status("rate_settings_invalid"), 400)
        self.assertEqual(decide_problem_status("rate_limited"), 429)


class LimiterTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.limiter = ApiRateLimiter(
            small_settings(), time_fn=self.clock)
        self.identity = token_identity()

    def test_every_judgement_carries_the_limit_headers(self):
        decision = self.limiter.check(self.identity)
        self.assertTrue(decision.allowed)
        headers = decision.headers()
        self.assertEqual(headers[HEADER_LIMIT], "3")
        self.assertEqual(headers[HEADER_REMAINING], "2")
        self.assertEqual(
            headers[HEADER_RESET], str(1_700_000_001))
        for name in RATE_LIMIT_HEADERS:
            self.assertIn(name, headers)
        self.assertNotIn(HEADER_RETRY_AFTER, headers)

    def test_burst_then_refusal_with_headers_and_retry_after(self):
        for remaining in ("2", "1", "0"):
            decision = self.limiter.check(self.identity)
            self.assertTrue(decision.allowed)
            self.assertEqual(decision.headers()[HEADER_REMAINING], remaining)
        decision = self.limiter.check(self.identity)
        self.assertFalse(decision.allowed)
        headers = decision.headers()
        self.assertEqual(headers[HEADER_LIMIT], "3")
        self.assertEqual(headers[HEADER_REMAINING], "0")
        self.assertEqual(headers[HEADER_RETRY_AFTER], "1")

    def test_retry_after_is_honest_against_the_clock(self):
        for _ in range(3):
            self.limiter.check(self.identity)
        refused = self.limiter.check(self.identity)
        self.assertFalse(refused.allowed)
        self.clock.now += 0.5
        still = self.limiter.check(self.identity)
        self.assertFalse(still.allowed)  # the promise is never early
        self.clock.now += 0.5  # the stated one second has now passed
        served = self.limiter.check(self.identity)
        self.assertTrue(served.allowed)

    def test_refusals_charge_nothing(self):
        for _ in range(3):
            self.limiter.check(self.identity)
        first = self.limiter.check(self.identity)
        second = self.limiter.check(self.identity)
        self.assertEqual(first.retry_after_seconds,
                         second.retry_after_seconds)
        self.assertEqual(
            self.limiter.peek(self.identity).remaining, 0)

    def test_peek_judges_without_charging(self):
        peeked = self.limiter.peek(self.identity)
        self.assertTrue(peeked.allowed)
        self.assertEqual(peeked.remaining, 3)
        self.assertEqual(self.limiter.peek(self.identity).remaining, 3)
        self.assertEqual(self.limiter.check(self.identity).remaining, 2)

    def test_buckets_are_per_token_not_per_account(self):
        other = token_identity(token_id=12)  # same account, other token
        for _ in range(3):
            self.limiter.check(self.identity)
        self.assertFalse(self.limiter.check(self.identity).allowed)
        self.assertTrue(self.limiter.check(other).allowed)
        # ... and neither spends the password bucket of the same account
        self.assertTrue(self.limiter.check(password_identity()).allowed)

    def test_anonymous_bucket_is_its_own_tighter_limit(self):
        anon = anonymous_identity()
        first = self.limiter.check(anon)
        self.assertEqual(first.limit, 2)
        self.assertTrue(self.limiter.check(anon).allowed)
        refused = self.limiter.check(anon)
        self.assertFalse(refused.allowed)
        self.assertEqual(refused.headers()[HEADER_RETRY_AFTER], "2")
        # the token bucket is untouched by the anonymous flood
        self.assertTrue(self.limiter.check(self.identity).allowed)

    def test_require_raises_the_problem_with_its_decision(self):
        for _ in range(3):
            self.limiter.require(self.identity)
        with self.assertRaises(ApiRateLimitError) as caught:
            self.limiter.require(self.identity)
        exc = caught.exception
        self.assertEqual(exc.reason, "rate_limited")
        self.assertIsNotNone(exc.decision)
        self.assertEqual(
            exc.decision.headers()[HEADER_RETRY_AFTER], "1")
        rendered = error_to_dict(exc)
        self.assertEqual(tuple(rendered), PROBLEM_FIELDS)
        self.assertEqual(rendered["status"], 429)
        self.assertEqual(
            rendered["type"], "/api/v1/problems/rate_limited")
        self.assertEqual(json.loads(json.dumps(rendered)), rendered)

    def test_headers_leak_no_private_fact(self):
        for _ in range(3):
            decision = self.limiter.check(self.identity)
        refused = self.limiter.check(self.identity)
        blob = json.dumps(refused.headers()) + str(error_to_dict(
            ApiRateLimitError("rate_limited", "x", decision=refused)))
        self.assertNotIn("volmarr", blob)
        self.assertNotIn("classic_token", blob)
        self.assertNotIn("token:classic_token:11", blob)

    def test_cost_outside_the_bucket_is_refused(self):
        for cost in (0.0, -1.0, 4.0):
            with self.assertRaises(ApiRateLimitError) as caught:
                self.limiter.check(self.identity, cost=cost)
            self.assertEqual(caught.exception.reason, "limit_invalid")

    def test_disabled_limiting_allows_and_still_states_limits(self):
        limiter = ApiRateLimiter(
            small_settings(enabled=False), time_fn=self.clock)
        for _ in range(10):
            decision = limiter.check(self.identity)
            self.assertTrue(decision.allowed)
            self.assertEqual(decision.headers()[HEADER_LIMIT], "3")
            self.assertEqual(decision.headers()[HEADER_REMAINING], "3")


class InstanceConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.conn = db.init_db(root / "samverk.db")
        self.clock = Clock()
        self.audit = AuditLog(self.conn, time_fn=self.clock)

    def test_save_load_round_trip_and_from_conn(self):
        save_rate_limit_settings(
            self.conn, small_settings(), audit=self.audit, actor_id=None)
        loaded = load_rate_limit_settings(self.conn)
        self.assertEqual(loaded, small_settings())
        limiter = ApiRateLimiter.from_conn(self.conn, time_fn=self.clock)
        self.assertEqual(limiter.settings, small_settings())
        rows = self.conn.execute(
            "SELECT key FROM settings WHERE key LIKE 'api_rate_limit.%'"
        ).fetchall()
        self.assertEqual({row["key"] for row in rows}, set(SETTING_KEYS))

    def test_save_is_audited_on_the_existing_event(self):
        before = self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
        save_rate_limit_settings(
            self.conn, small_settings(), audit=self.audit, actor_id=None)
        rows = self.conn.execute(
            "SELECT action, target_kind, target_id FROM audit_log"
            " WHERE seq > ?", (before,)).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["action"], "admin.settings.change")
        self.assertEqual(rows[0]["target_id"], "api_rate_limit")

    def test_unconfigured_instance_loads_the_defaults(self):
        self.assertEqual(
            load_rate_limit_settings(self.conn), default_settings())

    def test_stored_garbage_is_a_loud_refusal(self):
        with self.conn:
            self.conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)",
                ("api_rate_limit.token_capacity", "lots"))
        with self.assertRaises(ApiRateLimitError) as caught:
            load_rate_limit_settings(self.conn)
        self.assertEqual(caught.exception.reason, "rate_settings_invalid")


class DoorIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.conn = db.init_db(root / "samverk.db")
        self.clock = Clock()
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(
            self.conn, audit=self.audit, time_fn=self.clock)
        self.owner = self.accounts.register("volmarr", PW)
        repos = RepositoryStore(
            self.conn, root, self.accounts, audit=self.audit)
        repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        classic = AccessTokenStore(
            self.conn, self.accounts, audit=self.audit, time_fn=self.clock)
        expiry = int(self.clock.now) + 3600
        _, self.raw_one = classic.create_token(
            self.owner.id, "one", {"repo:read"}, expiry)
        _, self.raw_two = classic.create_token(
            self.owner.id, "two", {"repo:read"}, expiry)
        self.door = ApiAuthenticator(
            self.conn, self.accounts, repos,
            audit=self.audit, time_fn=self.clock)
        self.limiter = ApiRateLimiter(
            small_settings(), time_fn=self.clock)

    def test_tokens_resolved_at_the_door_are_limited_per_token(self):
        one = self.door.authenticate(f"Bearer {self.raw_one}")
        two = self.door.authenticate(f"Bearer {self.raw_two}")
        self.assertNotEqual(bucket_key_for(one), bucket_key_for(two))
        audit_before = self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
        for _ in range(3):
            self.assertTrue(self.limiter.check(one).allowed)
        self.assertFalse(self.limiter.check(one).allowed)
        self.assertTrue(self.limiter.check(two).allowed)
        # judging a call witnesses nothing of its own
        audit_after = self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
        self.assertEqual(audit_before, audit_after)

    def test_no_migration_and_no_new_taxonomy_event(self):
        self.assertEqual(schema_version(self.conn), 102)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 131)


class HelpPageTests(unittest.TestCase):
    def test_page_states_the_law_and_the_instances_numbers(self):
        page = render_api_rate_limit_page(small_settings())
        self.assertIn("per-token", page)
        self.assertIn(HEADER_LIMIT, page)
        self.assertIn(HEADER_RETRY_AFTER, page)
        self.assertIn("the per-token limit is 3 requests", page)
        self.assertTrue(RATE_LIMIT_PATH.startswith("/api/"))


if __name__ == "__main__":
    unittest.main()
