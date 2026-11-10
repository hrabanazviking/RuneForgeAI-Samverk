"""S-255 acceptance battery: API abuse defences.

Acceptance (roadmap S-255): API abuse defences --
payload size caps, expensive-endpoint accounting,
per-token concurrency limits.

The centre is samverk/api_abuse.py: every
endpoint of the contract's route table catalogued
with a body size class and a price in cost units,
payloads judged by one pure function before a
body is read for meaning, every admitted call
accounted to its caller in a ledger the battery
reconciles count for count (a refused call is
never in the counts), and per-token concurrency
ceilings held in leases -- all configured through
the instance settings table (S-038's road) with
the change audited on the existing
`admin.settings.change` event, and all checked
against the live contract by an audit the battery
plants drift into. The defences stand beside
S-241's buckets in the contract's rate-limits
rule, which now records them as landed.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.api_auth import ApiIdentity
from samverk.api_contract import API_RESOURCES, PROBLEM_FIELDS, get_rule
import samverk.api_abuse as abuse_module
from samverk.api_abuse import (
    ABUSE_PATH, ALLOWED, CONCURRENCY_LIMIT_EXCEEDED,
    EXPENSIVE_COST, EXPENSIVE_ENDPOINTS, ORDINARY_COST,
    PAYLOAD_SIZE_INVALID, PAYLOAD_TOO_LARGE, SETTING_KEYS,
    TIER_EXPENSIVE, TIER_ORDINARY, AbuseSettings, ApiAbuseError,
    ApiAbuseGuard, decide_concurrency, decide_payload,
    default_settings, endpoint_cost, error_to_dict, get_endpoint,
    load_abuse_settings, parse_abuse_settings, payload_cap_for,
    render_api_abuse_page, save_abuse_settings, audit_api_abuse)
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.error_shape import decide_problem_status, is_registered_reason

EXPECTED_EXPENSIVE = (
    "repository-contents", "repository-forks", "pull-merge", "search")


def small_settings(**overrides):
    values = dict(
        enabled=True, payload_cap_bytes=100,
        max_concurrent_per_token=3,
        expensive_max_concurrent_per_token=1)
    values.update(overrides)
    return AbuseSettings(**values)


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


class PinTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.conn = db.init_db(Path(self._td.name) / "samverk.db")
        self.addCleanup(self.conn.close)

    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 104)
        self.assertEqual(db.MIGRATIONS[-1][0], 104)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 131)
        families = {}
        for event in taxonomy.AUDIT_EVENTS:
            families[event.split(".")[0]] = (
                families.get(event.split(".")[0], 0) + 1)
        self.assertEqual(
            families, {"auth": 33, "repo": 85, "admin": 13})

    def test_reasons_registered_at_their_statuses(self):
        expected = {
            "payload_too_large": 413,
            "payload_size_invalid": 400,
            "concurrency_limit_exceeded": 429,
            "abuse_settings_invalid": 400,
            "endpoint_unknown": 404,
            "lease_invalid": 400,
        }
        for reason, status in expected.items():
            self.assertTrue(is_registered_reason(reason), reason)
            self.assertEqual(decide_problem_status(reason), status, reason)

    def test_refusals_render_in_the_one_problem_format(self):
        guard = ApiAbuseGuard(small_settings())
        with self.assertRaises(ApiAbuseError) as caught:
            guard.require_payload("issues", 101)
        problem = error_to_dict(caught.exception)
        self.assertEqual(tuple(problem), PROBLEM_FIELDS)
        self.assertEqual(problem["status"], 413)
        self.assertTrue(problem["type"].endswith("/payload_too_large"))


class CatalogueTests(unittest.TestCase):
    def test_catalogue_covers_the_route_table_in_order(self):
        self.assertEqual(
            tuple(spec.id for spec in abuse_module.ENDPOINTS),
            tuple(resource.id for resource in API_RESOURCES))

    def test_expensive_four_named_and_priced(self):
        self.assertEqual(EXPENSIVE_ENDPOINTS, EXPECTED_EXPENSIVE)
        for endpoint_id in EXPECTED_EXPENSIVE:
            spec = get_endpoint(endpoint_id)
            self.assertEqual(spec.tier, TIER_EXPENSIVE)
            self.assertEqual(spec.cost, EXPENSIVE_COST)
            self.assertEqual(endpoint_cost(endpoint_id), 10)

    def test_ordinary_endpoints_cost_one(self):
        for spec in abuse_module.ENDPOINTS:
            if spec.id in EXPECTED_EXPENSIVE:
                continue
            self.assertEqual(spec.tier, TIER_ORDINARY, spec.id)
            self.assertEqual(spec.cost, ORDINARY_COST, spec.id)

    def test_payload_classes_are_the_two_honest_ones(self):
        for spec in abuse_module.ENDPOINTS:
            self.assertIn(spec.payload_class, ("none", "json"), spec.id)
        # Bodiless faces: the reads. Body-carrying
        # faces: the writes of the table.
        self.assertEqual(get_endpoint("search").payload_class, "none")
        self.assertEqual(get_endpoint("events").payload_class, "none")
        self.assertEqual(get_endpoint("issues").payload_class, "json")
        self.assertEqual(get_endpoint("pull-merge").payload_class, "json")

    def test_unknown_endpoint_refused(self):
        guard = ApiAbuseGuard(small_settings())
        for fn in (get_endpoint, endpoint_cost):
            with self.assertRaises(ApiAbuseError) as caught:
                fn("teleport")
            self.assertEqual(caught.exception.reason, "endpoint_unknown")
        with self.assertRaises(ApiAbuseError) as caught:
            guard.judge_payload("teleport", 0)
        self.assertEqual(caught.exception.reason, "endpoint_unknown")

    def test_payload_cap_for_reads_the_class(self):
        settings = small_settings()
        self.assertIsNone(
            payload_cap_for(get_endpoint("search"), settings))
        self.assertEqual(
            payload_cap_for(get_endpoint("issues"), settings), 100)


class PurePayloadTests(unittest.TestCase):
    def test_decide_payload_boundaries(self):
        self.assertEqual(decide_payload(0, 100), ALLOWED)
        self.assertEqual(decide_payload(100, 100), ALLOWED)
        self.assertEqual(decide_payload(101, 100), PAYLOAD_TOO_LARGE)

    def test_decide_payload_shapeless_sizes(self):
        for bad in (-1, 1.5, "10", None, True):
            self.assertEqual(
                decide_payload(bad, 100), PAYLOAD_SIZE_INVALID, bad)

    def test_decide_payload_bodiless_endpoints(self):
        self.assertEqual(decide_payload(0, None), ALLOWED)
        self.assertEqual(
            decide_payload(1, None), PAYLOAD_SIZE_INVALID)


class PureConcurrencyTests(unittest.TestCase):
    def test_decide_concurrency_boundaries(self):
        self.assertEqual(decide_concurrency(0, 3), ALLOWED)
        self.assertEqual(decide_concurrency(2, 3), ALLOWED)
        self.assertEqual(
            decide_concurrency(3, 3), CONCURRENCY_LIMIT_EXCEEDED)
        self.assertEqual(
            decide_concurrency(4, 3), CONCURRENCY_LIMIT_EXCEEDED)

    def test_decide_concurrency_fails_closed_on_shapeless(self):
        for in_flight, limit in ((-1, 3), (0, 0), ("1", 3), (0, None)):
            self.assertEqual(
                decide_concurrency(in_flight, limit),
                CONCURRENCY_LIMIT_EXCEEDED, (in_flight, limit))


class PayloadGuardTests(unittest.TestCase):
    def setUp(self):
        self.guard = ApiAbuseGuard(small_settings())
        self.identity = token_identity()

    def test_judge_states_size_and_cap(self):
        decision = self.guard.judge_payload("issues", 100)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.size_bytes, 100)
        self.assertEqual(decision.cap_bytes, 100)
        decision = self.guard.judge_payload("issues", 101)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.verdict, PAYLOAD_TOO_LARGE)

    def test_require_raises_the_registered_refusals(self):
        with self.assertRaises(ApiAbuseError) as caught:
            self.guard.require_payload("issues", 10_000)
        self.assertEqual(caught.exception.reason, "payload_too_large")
        self.assertEqual(error_to_dict(caught.exception)["status"], 413)
        with self.assertRaises(ApiAbuseError) as caught:
            self.guard.require_payload("issues", -1)
        self.assertEqual(caught.exception.reason, "payload_size_invalid")

    def test_bodiless_endpoint_refuses_a_claimed_body(self):
        with self.assertRaises(ApiAbuseError) as caught:
            self.guard.require_payload("search", 5)
        self.assertEqual(caught.exception.reason, "payload_size_invalid")
        self.assertTrue(self.guard.require_payload("search", 0).allowed)


class AccountingTests(unittest.TestCase):
    def setUp(self):
        self.guard = ApiAbuseGuard(small_settings())
        self.identity = token_identity()

    def test_accounting_charges_price_and_splits(self):
        self.guard.account(self.identity, "issues")
        self.guard.account(self.identity, "issues")
        view = self.guard.account(self.identity, "search")
        self.assertEqual(view.calls, 3)
        self.assertEqual(view.cost_units, 1 + 1 + 10)
        self.assertEqual(
            view.by_endpoint,
            (("issues", 2, 2), ("search", 1, 10)))
        self.assertEqual(view.bucket_key, "token:classic_token:11")

    def test_endpoint_totals_across_callers(self):
        other = token_identity(token_id=12)
        self.guard.account(self.identity, "search")
        self.guard.account(other, "search")
        self.guard.account(other, "issues")
        totals = {
            total.endpoint_id: total
            for total in self.guard.endpoint_totals()}
        self.assertEqual(totals["search"].calls, 2)
        self.assertEqual(totals["search"].cost_units, 20)
        self.assertEqual(totals["issues"].calls, 1)
        # A caller never charged stands at zero,
        # and the two tokens' ledgers are separate.
        self.assertEqual(
            self.guard.accounting_for(token_identity(99)).calls, 0)
        self.assertEqual(
            self.guard.accounting_for(other).cost_units, 11)

    def test_ledgers_key_like_the_rate_buckets(self):
        self.guard.account(password_identity(), "issues")
        self.guard.account(anonymous_identity(), "issues")
        self.assertEqual(
            self.guard.accounting_for(password_identity()).bucket_key,
            "account:7")
        self.assertEqual(
            self.guard.accounting_for(anonymous_identity()).bucket_key,
            "anonymous")
        self.assertEqual(
            self.guard.accounting_for(anonymous_identity()).calls, 1)


class ConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.guard = ApiAbuseGuard(small_settings())
        self.identity = token_identity()

    def test_ceiling_admits_then_refuses_and_release_frees(self):
        leases = [
            self.guard.acquire(self.identity, "issues")
            for _ in range(3)]
        self.assertEqual(self.guard.in_flight(self.identity), 3)
        with self.assertRaises(ApiAbuseError) as caught:
            self.guard.acquire(self.identity, "issues")
        self.assertEqual(
            caught.exception.reason, "concurrency_limit_exceeded")
        self.assertEqual(error_to_dict(caught.exception)["status"], 429)
        decision = caught.exception.decision
        self.assertEqual(decision.in_flight, 3)
        self.assertEqual(decision.limit, 3)
        self.assertFalse(decision.allowed)
        leases[0].release()
        self.assertEqual(self.guard.in_flight(self.identity), 2)
        lease = self.guard.acquire(self.identity, "issues")
        self.assertEqual(self.guard.in_flight(self.identity), 3)
        for held in leases[1:] + [lease]:
            held.release()
        self.assertEqual(self.guard.in_flight(self.identity), 0)

    def test_expensive_ceiling_is_tighter(self):
        lease = self.guard.acquire(self.identity, "search")
        with self.assertRaises(ApiAbuseError) as caught:
            self.guard.acquire(self.identity, "pull-merge")
        self.assertEqual(
            caught.exception.reason, "concurrency_limit_exceeded")
        self.assertEqual(caught.exception.decision.limit, 1)
        self.assertEqual(caught.exception.decision.tier_in_flight, 1)
        # The ordinary ceiling still has room for
        # ordinary work beside the expensive call.
        ordinary = self.guard.acquire(self.identity, "issues")
        self.assertEqual(self.guard.in_flight(self.identity), 2)
        ordinary.release()
        lease.release()
        self.assertEqual(self.guard.in_flight(self.identity), 0)

    def test_ceilings_are_per_token(self):
        other = token_identity(token_id=12)
        leases = [
            self.guard.acquire(self.identity, "issues")
            for _ in range(3)]
        lease = self.guard.acquire(other, "issues")
        self.assertEqual(self.guard.in_flight(other), 1)
        lease.release()
        for held in leases:
            held.release()

    def test_lease_context_manager_releases_on_exception(self):
        with self.assertRaises(RuntimeError):
            with self.guard.acquire(self.identity, "issues"):
                self.assertEqual(
                    self.guard.in_flight(self.identity), 1)
                raise RuntimeError("the call died")
        self.assertEqual(self.guard.in_flight(self.identity), 0)

    def test_double_release_is_refused_and_counts_hold(self):
        lease = self.guard.acquire(self.identity, "issues")
        lease.release()
        with self.assertRaises(ApiAbuseError) as caught:
            lease.release()
        self.assertEqual(caught.exception.reason, "lease_invalid")
        self.assertEqual(self.guard.in_flight(self.identity), 0)

    def test_foreign_lease_is_refused(self):
        other_guard = ApiAbuseGuard(small_settings())
        lease = self.guard.acquire(self.identity, "issues")
        with self.assertRaises(ApiAbuseError) as caught:
            other_guard._release(lease)
        self.assertEqual(caught.exception.reason, "lease_invalid")
        self.assertEqual(self.guard.in_flight(self.identity), 1)
        lease.release()


class AdmitDoorTests(unittest.TestCase):
    def setUp(self):
        self.guard = ApiAbuseGuard(small_settings())
        self.identity = token_identity()

    def test_admit_charges_only_admitted_calls(self):
        lease = self.guard.admit(self.identity, "search", 0)
        view = self.guard.accounting_for(self.identity)
        self.assertEqual((view.calls, view.cost_units), (1, 10))
        # A payload refusal: read no further,
        # charged nothing, holds no slot.
        with self.assertRaises(ApiAbuseError):
            self.guard.admit(self.identity, "issues", 101)
        # A concurrency refusal (the expensive
        # ceiling stands at 1 and search holds it):
        # charged nothing, holds no slot.
        with self.assertRaises(ApiAbuseError):
            self.guard.admit(self.identity, "pull-merge", 10)
        view = self.guard.accounting_for(self.identity)
        self.assertEqual((view.calls, view.cost_units), (1, 10))
        self.assertEqual(self.guard.in_flight(self.identity), 1)
        lease.release()
        self.assertEqual(self.guard.in_flight(self.identity), 0)

    def test_admit_order_payload_before_concurrency(self):
        leases = [
            self.guard.admit(self.identity, "issues", 10)
            for _ in range(3)]
        # The token is at its ceiling AND the body
        # is oversized: the payload refusal answers
        # first, because the body is judged before
        # any slot is asked for.
        with self.assertRaises(ApiAbuseError) as caught:
            self.guard.admit(self.identity, "issues", 101)
        self.assertEqual(caught.exception.reason, "payload_too_large")
        for held in leases:
            held.release()


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.conn = db.init_db(root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn)

    def test_defaults_stand(self):
        settings = default_settings()
        self.assertTrue(settings.enabled)
        self.assertEqual(settings.payload_cap_bytes, 1024 * 1024)
        self.assertEqual(settings.max_concurrent_per_token, 8)
        self.assertEqual(
            settings.expensive_max_concurrent_per_token, 2)

    def test_parse_reads_stored_strings(self):
        settings = parse_abuse_settings({
            "api_abuse.enabled": "0",
            "api_abuse.payload_cap_bytes": "2048",
            "api_abuse.max_concurrent_per_token": "4",
            "api_abuse.expensive_max_concurrent_per_token": "1"})
        self.assertFalse(settings.enabled)
        self.assertEqual(settings.payload_cap_bytes, 2048)
        self.assertEqual(settings.max_concurrent_per_token, 4)
        self.assertEqual(
            settings.expensive_max_concurrent_per_token, 1)

    def test_parse_refuses_unreadable_values_loudly(self):
        for bad in ("many", "", "1.5", "nan"):
            with self.assertRaises(ApiAbuseError) as caught:
                parse_abuse_settings(
                    {"api_abuse.payload_cap_bytes": bad})
            self.assertEqual(
                caught.exception.reason, "abuse_settings_invalid")
            self.assertEqual(
                error_to_dict(caught.exception)["status"], 400)

    def test_validate_refuses_zero_and_inverted_ceilings(self):
        for overrides in (
                dict(payload_cap_bytes=0),
                dict(max_concurrent_per_token=0),
                dict(expensive_max_concurrent_per_token=-1),
                dict(max_concurrent_per_token=1,
                     expensive_max_concurrent_per_token=2)):
            with self.assertRaises(ApiAbuseError):
                small_settings(**overrides).validate()

    def test_save_load_round_trip_and_from_conn(self):
        save_abuse_settings(
            self.conn, small_settings(), audit=self.audit,
            actor_id=None)
        self.assertEqual(load_abuse_settings(self.conn), small_settings())
        guard = ApiAbuseGuard.from_conn(self.conn)
        self.assertEqual(guard.settings, small_settings())
        rows = self.conn.execute(
            "SELECT key FROM settings WHERE key LIKE 'api_abuse.%'"
        ).fetchall()
        self.assertEqual({row["key"] for row in rows}, set(SETTING_KEYS))

    def test_save_is_audited_on_the_existing_event(self):
        before = self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
        save_abuse_settings(
            self.conn, small_settings(), audit=self.audit,
            actor_id=None)
        rows = self.conn.execute(
            "SELECT action, target_kind, target_id FROM audit_log"
            " WHERE seq > ?", (before,)).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["action"], "admin.settings.change")
        self.assertEqual(rows[0]["target_id"], "api_abuse")

    def test_unconfigured_instance_loads_the_defaults(self):
        self.assertEqual(
            load_abuse_settings(self.conn), default_settings())

    def test_stored_garbage_is_a_loud_refusal(self):
        with self.conn:
            self.conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)",
                ("api_abuse.payload_cap_bytes", "lots"))
        with self.assertRaises(ApiAbuseError) as caught:
            load_abuse_settings(self.conn)
        self.assertEqual(
            caught.exception.reason, "abuse_settings_invalid")

    def test_judging_and_accounting_write_and_audit_nothing(self):
        guard = ApiAbuseGuard(small_settings())
        identity = token_identity()
        lease = guard.admit(identity, "search", 0)
        lease.release()
        counts = (
            self.conn.execute(
                "SELECT COUNT(*) AS n FROM audit_log"
            ).fetchone()["n"],
            self.conn.execute(
                "SELECT COUNT(*) AS n FROM settings"
            ).fetchone()["n"])
        self.assertEqual(counts, (0, 0))


class DisabledTests(unittest.TestCase):
    def test_disabled_admits_everything_and_still_accounts(self):
        guard = ApiAbuseGuard(small_settings(enabled=False))
        identity = token_identity()
        decision = guard.judge_payload("issues", 10 ** 9)
        self.assertTrue(decision.allowed)
        self.assertFalse(decision.enabled)
        self.assertEqual(decision.cap_bytes, 100)
        leases = [
            guard.admit(identity, "search", 0) for _ in range(3)]
        self.assertEqual(guard.in_flight(identity), 3)
        view = guard.accounting_for(identity)
        self.assertEqual((view.calls, view.cost_units), (3, 30))
        for held in leases:
            held.release()
        self.assertEqual(guard.in_flight(identity), 0)


class AuditAndPageTests(unittest.TestCase):
    def test_audit_holds_against_the_live_contract(self):
        audit = audit_api_abuse()
        self.assertTrue(audit.defences_hold, audit)
        self.assertTrue(audit.rest_ratified)
        self.assertTrue(audit.rule_ok)
        self.assertEqual(
            audit.endpoints_checked, len(API_RESOURCES))
        self.assertEqual(audit.uncatalogued_resources, ())
        self.assertEqual(audit.unknown_endpoints, ())
        self.assertEqual(audit.mispriced_endpoints, ())

    def test_audit_catches_an_uncatalogued_resource(self):
        shrunk = tuple(
            spec for spec in abuse_module.ENDPOINTS
            if spec.id != "search")
        with mock.patch.object(abuse_module, "ENDPOINTS", shrunk):
            audit = audit_api_abuse()
        self.assertFalse(audit.defences_hold)
        self.assertEqual(audit.uncatalogued_resources, ("search",))

    def test_audit_catches_a_mispriced_endpoint(self):
        from dataclasses import replace
        drifted = tuple(
            replace(spec, cost=3) if spec.id == "issues" else spec
            for spec in abuse_module.ENDPOINTS)
        with mock.patch.object(abuse_module, "ENDPOINTS", drifted):
            audit = audit_api_abuse()
        self.assertFalse(audit.defences_hold)
        self.assertEqual(audit.mispriced_endpoints, ("issues",))

    def test_contract_rule_records_s255_as_landed(self):
        rule = get_rule("rate-limits")
        self.assertIn("S-255", rule.title + rule.statement)
        self.assertIn("api_abuse", rule.statement)
        for token in ("payload_too_large",
                      "concurrency_limit_exceeded", "413", "429"):
            self.assertIn(token, rule.statement)

    def test_page_states_the_defences_and_the_numbers(self):
        page = render_api_abuse_page(
            small_settings(), audit_api_abuse())
        for token in ("payload_too_large", "search",
                      "concurrency_limit_exceeded",
                      "100 bytes", "Checked"):
            self.assertIn(token, page)
        self.assertEqual(ABUSE_PATH, "/api/abuse-defences")

    def test_page_escapes_and_reports_a_broken_audit(self):
        page = render_api_abuse_page(small_settings())
        self.assertNotIn("<script", page)
        shrunk = tuple(
            spec for spec in abuse_module.ENDPOINTS
            if spec.id != "search")
        with mock.patch.object(abuse_module, "ENDPOINTS", shrunk):
            broken = render_api_abuse_page(
                small_settings(), audit_api_abuse())
        self.assertIn("not clean", broken)
        self.assertIn("search", broken)
