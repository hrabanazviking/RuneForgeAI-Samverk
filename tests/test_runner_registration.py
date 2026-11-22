"""S-317 acceptance battery: runner registration.

Acceptance (roadmap S-317): Runner registration --
instance/org/repo-scoped runners with one-time
registration tokens and labels; the token page
passes the findability walk.

The centre is samverk/runner_registration.py:
tokens minted per scope by that scope's stewards
(site admin / org owner / repo admin), shown once
and stored only as a SHA-256 hash; registration
speaking S-316's own register message and
consuming its token exactly once, for exactly
the scope and target the token was minted for;
labels under S-316's label law; deregistration
freeing a runner's name; and the findability
walk -- runner home -> one click -> the scope's
token page -> mint / revoke / deregister -- in
S-034's and S-048's shape. Migration 129
(schema 128 -> 129); taxonomy unmoved at 135
(33 auth / 89 repo / 13 admin), the acts riding
the standing scoped verbs; S-316's audit now
admits exactly this slice's two tables as the
lawful runner surface.

Counted with: python3 -m unittest tests.test_runner_registration
"""
from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.organizations import OrganizationStore
from samverk.repositories import RepositoryStore
from samverk.runner_protocol import (
    RUNNER_SCOPES, audit_runner_protocol)
from samverk.runner_registration import (
    RUNNER_AREAS, TOKEN_PREFIX, RegistrationToken,
    Runner, RunnerRegistrationError, RunnerRegistrationStore,
    audit_runner_registration, decide_token_status,
    render_runner_home, render_runner_token_page,
    runner_areas, runner_to_dict, scope_word,
    token_page_path, token_to_dict, validate_labels,
    validate_scope, validate_target)

PW = "correct horse battery"
T0 = 1_700_000_000


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


def _reason(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except RunnerRegistrationError as exc:
        return exc.reason
    raise AssertionError("expected RunnerRegistrationError")


def _payload(token, name="longship-1", labels=("linux", "x64"),
             scope="repo", target="volmarr/widget",
             agent_version="0.1.0"):
    return {"kind": "register", "protocol": 1,
            "name": name, "labels": list(labels),
            "scope": scope, "target": target,
            "registration_token": token,
            "agent_version": agent_version}


class PureLawTests(unittest.TestCase):
    def test_scope_law(self):
        self.assertEqual(tuple(RUNNER_SCOPES),
                         ("instance", "org", "repo"))
        for scope in RUNNER_SCOPES:
            self.assertEqual(validate_scope(scope), scope)
            self.assertTrue(scope_word(scope))
        self.assertEqual(
            _reason(validate_scope, "user"), "runner_scope_unknown")
        self.assertEqual(
            _reason(validate_scope, ""), "runner_scope_unknown")
        self.assertEqual(
            _reason(validate_scope, None), "runner_scope_unknown")

    def test_target_law(self):
        self.assertEqual(validate_target("instance", ""), "")
        self.assertEqual(validate_target("instance", None), "")
        self.assertEqual(
            _reason(validate_target, "instance", "acme"),
            "runner_target_invalid")
        self.assertEqual(validate_target("org", "Acme"), "acme")
        self.assertEqual(
            _reason(validate_target, "org", "a/b"),
            "runner_target_invalid")
        self.assertEqual(
            _reason(validate_target, "org", ""), "runner_target_invalid")
        self.assertEqual(
            validate_target("repo", "Volmarr/Widget"),
            "volmarr/widget")
        for bad in ("widget", "a/b/c", "/widget", "volmarr/", ""):
            self.assertEqual(
                _reason(validate_target, "repo", bad),
                "runner_target_invalid", bad)

    def test_labels_law(self):
        self.assertEqual(validate_labels(["linux", "x64"]),
                         ("linux", "x64"))
        self.assertEqual(validate_labels(("self-hosted",)),
                         ("self-hosted",))
        self.assertEqual(
            _reason(validate_labels, []), "runner_labels_invalid")
        self.assertEqual(
            _reason(validate_labels, ["linux", "linux"]),
            "runner_labels_invalid")
        self.assertEqual(
            _reason(validate_labels, ["not a label"]),
            "runner_labels_invalid")
        self.assertEqual(
            _reason(validate_labels, [f"l{i}" for i in range(17)]),
            "runner_labels_invalid")
        self.assertEqual(
            _reason(validate_labels, "linux"), "runner_labels_invalid")

    def test_token_status_words(self):
        self.assertEqual(decide_token_status(
            revoked=False, used_at=None, expires_at=100, now=50),
            "live")
        self.assertEqual(decide_token_status(
            revoked=False, used_at=None, expires_at=100, now=100),
            "expired")
        self.assertEqual(decide_token_status(
            revoked=False, used_at=10, expires_at=100, now=50),
            "used")
        self.assertEqual(decide_token_status(
            revoked=True, used_at=None, expires_at=100, now=50),
            "revoked")

    def test_findability_map_is_data(self):
        areas = runner_areas()
        self.assertEqual([a["scope"] for a in areas],
                         ["instance", "org", "repo"])
        self.assertEqual(len(areas), len(RUNNER_AREAS))
        self.assertEqual(token_page_path("instance"),
                         "/admin/runners")
        self.assertEqual(token_page_path("org", "Acme"),
                         "/orgs/acme/settings/runners")
        self.assertEqual(token_page_path("repo", "Volmarr/Widget"),
                         "/volmarr/widget/settings/runners")
        home = render_runner_home()
        self.assertIn("/admin/runners", home)
        self.assertIn("/orgs/{target}/settings/runners", home)
        self.assertIn("/{target}/settings/runners", home)


class StoreTests(unittest.TestCase):
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
        self.admin = self.accounts.register("admina", PW)
        with self.conn:
            self.conn.execute(
                "UPDATE users SET is_admin = 1 WHERE id = ?",
                (self.admin.id,))
        self.owner = self.accounts.register("volmarr", PW)
        self.mallory = self.accounts.register("mallory", PW)
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.pub = self.repos.create_repository(
            self.owner.id, "volmarr", "widget", visibility="public")
        self.priv = self.repos.create_repository(
            self.owner.id, "volmarr", "secret", visibility="private")
        self.orgs = OrganizationStore(
            self.conn, self.accounts, audit=self.audit,
            time_fn=self.clock)
        self.org = self.orgs.create_organization(
            self.owner.id, "acme")
        self.store = RunnerRegistrationStore(
            self.conn, self.accounts, self.repos,
            audit=self.audit, time_fn=self.clock)

    # -- pins -------------------------------------------------

    def test_pins_hold(self):
        self.assertEqual(schema_version(self.conn), 138)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 138)

    # -- minting -----------------------------------------------

    def test_instance_mint_by_admin_shows_once_and_stores_hash(self):
        token, raw = self.store.mint_token(self.admin.id, "instance")
        self.assertTrue(raw.startswith(TOKEN_PREFIX))
        self.assertGreaterEqual(len(raw), 20)
        self.assertEqual(token.scope, "instance")
        self.assertEqual(token.target, "")
        self.assertEqual(token.prefix, raw[:12])
        self.assertEqual(token.status(self.clock.now), "live")
        self.assertEqual(token.expires_at, T0 + 3600)
        row = self.conn.execute(
            "SELECT token_hash FROM runner_registration_tokens"
            " WHERE id = ?", (token.id,)).fetchone()
        self.assertEqual(
            row["token_hash"],
            hashlib.sha256(raw.encode()).hexdigest())
        self.assertNotEqual(row["token_hash"], raw)
        db_bytes = (self.root / "samverk.db").read_bytes()
        self.assertNotIn(raw.encode(), db_bytes)

    def test_instance_mint_refused_for_non_admin(self):
        self.assertEqual(
            _reason(self.store.mint_token, self.owner.id, "instance"),
            "runner_not_permitted")
        self.assertEqual(
            _reason(self.store.mint_token, None, "instance"),
            "authentication_required")
        self.assertEqual(
            _reason(self.store.mint_token, 99999, "instance"),
            "no_such_user")

    def test_org_mint_by_owner_and_admin_only(self):
        token, _raw = self.store.mint_token(
            self.owner.id, "org", "acme")
        self.assertEqual(token.target, "acme")
        self.store.mint_token(self.admin.id, "org", "ACME")
        self.assertEqual(
            _reason(self.store.mint_token,
                    self.mallory.id, "org", "acme"),
            "runner_not_permitted")
        self.assertEqual(
            _reason(self.store.mint_token,
                    self.owner.id, "org", "ghost"),
            "org_not_found")

    def test_repo_mint_by_repo_admin_only(self):
        token, _raw = self.store.mint_token(
            self.owner.id, "repo", "volmarr/widget")
        self.assertEqual(token.target, "volmarr/widget")
        self.store.mint_token(
            self.admin.id, "repo", "volmarr/secret")
        # A stranger to a private repo learns nothing.
        self.assertEqual(
            _reason(self.store.mint_token,
                    self.mallory.id, "repo", "volmarr/secret"),
            "repo_not_found")
        # A reader of a public repo is not its admin.
        self.assertEqual(
            _reason(self.store.mint_token,
                    self.mallory.id, "repo", "volmarr/widget"),
            "runner_not_permitted")
        self.assertEqual(
            _reason(self.store.mint_token,
                    self.owner.id, "repo", "volmarr/ghost"),
            "repo_not_found")

    def test_ttl_judged_at_minting(self):
        for bad in (0, 59, 86401, "hour", True, None, 1.5):
            self.assertEqual(
                _reason(self.store.mint_token, self.admin.id,
                        "instance", "", bad),
                "runner_token_ttl_invalid", bad)
        low, _ = self.store.mint_token(
            self.admin.id, "instance", "", 60)
        self.assertEqual(low.expires_at, T0 + 60)
        high, _ = self.store.mint_token(
            self.admin.id, "instance", "", 86400)
        self.assertEqual(high.expires_at, T0 + 86400)
        rows = self.conn.execute(
            "SELECT COUNT(*) AS n FROM"
            " runner_registration_tokens").fetchone()
        self.assertEqual(rows["n"], 2)

    # -- registration -------------------------------------------

    def test_register_repo_runner_end_to_end(self):
        _token, raw = self.store.mint_token(
            self.owner.id, "repo", "volmarr/widget")
        runner = self.store.register_runner(_payload(raw))
        self.assertIsInstance(runner, Runner)
        self.assertEqual(runner.name, "longship-1")
        self.assertEqual(runner.labels, ("linux", "x64"))
        self.assertEqual(runner.scope, "repo")
        self.assertEqual(runner.target, "volmarr/widget")
        self.assertEqual(runner.agent_version, "0.1.0")
        self.assertTrue(runner.registered)
        self.assertEqual(runner.standing, "Registered")
        after = self.store.get_token(_token.id)
        self.assertEqual(after.status(self.clock.now), "used")
        self.assertEqual(after.used_runner, "longship-1")
        listed = self.store.list_runners(
            self.owner.id, "repo", "volmarr/widget")
        self.assertEqual([r.id for r in listed], [runner.id])
        actions = [r["action"] for r in self.conn.execute(
            "SELECT action FROM audit_log").fetchall()]
        self.assertIn("repo.settings.change", actions)

    def test_register_instance_and_org_runners(self):
        _t1, raw1 = self.store.mint_token(self.admin.id, "instance")
        r1 = self.store.register_runner(_payload(
            raw1, name="core-1", scope="instance", target=""))
        self.assertEqual(r1.target, "")
        _t2, raw2 = self.store.mint_token(
            self.owner.id, "org", "acme")
        r2 = self.store.register_runner(_payload(
            raw2, name="acme-1", scope="org", target="acme"))
        self.assertEqual(r2.target, "acme")
        actions = {(r["action"], r["target_kind"])
                   for r in self.conn.execute(
                       "SELECT action, target_kind FROM"
                       " audit_log").fetchall()}
        self.assertIn(("admin.settings.change", "instance"), actions)
        self.assertIn(
            ("auth.organization.update", "organization"), actions)

    def test_token_is_one_time(self):
        _token, raw = self.store.mint_token(
            self.owner.id, "repo", "volmarr/widget")
        self.store.register_runner(_payload(raw))
        self.assertEqual(
            _reason(self.store.register_runner,
                    _payload(raw, name="second-1")),
            "runner_token_used")

    def test_unknown_and_shapeless_tokens_refused(self):
        self.assertEqual(
            _reason(self.store.register_runner,
                    _payload("svr_never-minted-token-012345")),
            "runner_token_refused")
        _token, raw = self.store.mint_token(
            self.owner.id, "repo", "volmarr/widget")
        # The stored hash itself buys nothing (S-006 law).
        row = self.conn.execute(
            "SELECT token_hash FROM runner_registration_tokens"
            " WHERE id = ?", (_token.id,)).fetchone()
        self.assertEqual(
            _reason(self.store.register_runner,
                    _payload(row["token_hash"])),
            "runner_token_refused")
        # A shapeless message consumes nothing.
        self.assertEqual(
            _reason(self.store.register_runner,
                    _payload(raw, labels=())),
            "runner_invalid")
        runner = self.store.register_runner(_payload(raw))
        self.assertTrue(runner.registered)

    def test_scope_mismatch_consumes_nothing(self):
        _token, raw = self.store.mint_token(
            self.owner.id, "repo", "volmarr/widget")
        self.assertEqual(
            _reason(self.store.register_runner, _payload(
                raw, scope="instance", target="")),
            "runner_token_scope_mismatch")
        self.assertEqual(
            _reason(self.store.register_runner, _payload(
                raw, target="volmarr/secret")),
            "runner_token_scope_mismatch")
        runner = self.store.register_runner(_payload(raw))
        self.assertTrue(runner.registered)

    def test_expired_token_refused(self):
        _token, raw = self.store.mint_token(
            self.admin.id, "instance", "", 60)
        self.clock.now = T0 + 61
        self.assertEqual(
            _reason(self.store.register_runner, _payload(
                raw, scope="instance", target="")),
            "runner_token_expired")

    def test_revoke_law(self):
        token, raw = self.store.mint_token(
            self.owner.id, "repo", "volmarr/widget")
        self.assertEqual(
            _reason(self.store.revoke_token,
                    self.mallory.id, token.id),
            "runner_not_permitted")
        self.assertTrue(
            self.store.revoke_token(self.owner.id, token.id))
        self.assertFalse(
            self.store.revoke_token(self.owner.id, token.id))
        self.assertEqual(
            self.store.get_token(token.id).status(self.clock.now),
            "revoked")
        self.assertEqual(
            _reason(self.store.register_runner, _payload(raw)),
            "runner_token_refused")
        # A used token has nothing left to revoke.
        token2, raw2 = self.store.mint_token(
            self.owner.id, "repo", "volmarr/widget")
        self.store.register_runner(_payload(raw2))
        self.assertFalse(
            self.store.revoke_token(self.owner.id, token2.id))
        self.assertFalse(self.store.revoke_token(
            self.owner.id, 99999))

    def test_name_taken_within_scope_only(self):
        _t1, raw1 = self.store.mint_token(
            self.owner.id, "repo", "volmarr/widget")
        self.store.register_runner(_payload(raw1))
        _t2, raw2 = self.store.mint_token(
            self.owner.id, "repo", "volmarr/widget")
        self.assertEqual(
            _reason(self.store.register_runner, _payload(raw2)),
            "runner_name_taken")
        # The same name under another scope is another runner.
        _t3, raw3 = self.store.mint_token(self.admin.id, "instance")
        other = self.store.register_runner(_payload(
            raw3, scope="instance", target=""))
        self.assertEqual(other.name, "longship-1")

    def test_protocol_law_rides_whole(self):
        _token, raw = self.store.mint_token(
            self.owner.id, "repo", "volmarr/widget")
        bad = _payload(raw, labels=("linux", "linux"))
        self.assertEqual(
            _reason(self.store.register_runner, bad),
            "runner_invalid")
        bad2 = _payload(raw, scope="user", target="x")
        self.assertEqual(
            _reason(self.store.register_runner, bad2),
            "runner_scope_unknown")

    # -- deregistration ------------------------------------------

    def test_deregister_frees_the_name(self):
        _token, raw = self.store.mint_token(
            self.owner.id, "repo", "volmarr/widget")
        runner = self.store.register_runner(_payload(raw))
        self.assertEqual(
            _reason(self.store.deregister_runner,
                    self.mallory.id, runner.id),
            "runner_not_permitted")
        self.assertTrue(self.store.deregister_runner(
            self.owner.id, runner.id))
        gone = self.store.get_runner(runner.id)
        self.assertFalse(gone.registered)
        self.assertEqual(gone.standing, "Deregistered")
        self.assertFalse(self.store.deregister_runner(
            self.owner.id, runner.id))
        _t2, raw2 = self.store.mint_token(
            self.owner.id, "repo", "volmarr/widget")
        successor = self.store.register_runner(_payload(raw2))
        self.assertEqual(successor.name, "longship-1")
        listed = self.store.list_runners(
            self.owner.id, "repo", "volmarr/widget")
        self.assertEqual(
            [r.standing for r in listed],
            ["Deregistered", "Registered"])

    def test_listing_is_a_steward_read(self):
        self.store.mint_token(self.owner.id, "repo", "volmarr/widget")
        self.assertEqual(
            len(self.store.list_tokens(
                self.owner.id, "repo", "volmarr/widget")), 1)
        self.assertEqual(
            _reason(self.store.list_tokens,
                    self.mallory.id, "repo", "volmarr/secret"),
            "repo_not_found")
        self.assertEqual(
            _reason(self.store.list_runners,
                    self.mallory.id, "instance"),
            "runner_not_permitted")

    # -- dicts and audit ------------------------------------------

    def test_dict_faces_carry_no_secret(self):
        token, raw = self.store.mint_token(
            self.owner.id, "repo", "volmarr/widget")
        runner = self.store.register_runner(_payload(raw))
        tdict = token_to_dict(
            self.store.get_token(token.id), self.clock.now)
        self.assertEqual(tdict["status"], "used")
        self.assertNotIn("token_hash", tdict)
        self.assertNotIn(raw, str(tdict))
        rdict = runner_to_dict(runner)
        self.assertEqual(rdict["labels"], ["linux", "x64"])
        self.assertEqual(rdict["standing"], "Registered")

    def test_audit_clean_then_catches_damage(self):
        _token, raw = self.store.mint_token(
            self.owner.id, "repo", "volmarr/widget")
        self.store.register_runner(_payload(raw))
        audit = audit_runner_registration(self.conn)
        self.assertTrue(audit.stands_cleanly, audit.problems)
        self.assertEqual(audit.tokens_scanned, 1)
        self.assertEqual(audit.runners_scanned, 1)
        with self.conn:
            self.conn.execute(
                "UPDATE runners SET labels = ''")
        audit2 = audit_runner_registration(self.conn)
        self.assertFalse(audit2.stands_cleanly)
        self.assertTrue(audit2.problems)

    def test_s316_audit_admits_the_lawful_surface(self):
        audit = audit_runner_protocol(self.conn)
        self.assertTrue(audit.protocol_ok)
        self.assertTrue(audit.stands_cleanly, audit)
        self.assertEqual(audit.events_scanned, 138)
        with self.conn:
            self.conn.execute(
                "CREATE TABLE runner_backdoor (id INTEGER)")
        audit2 = audit_runner_protocol(self.conn)
        self.assertFalse(audit2.stands_cleanly)
        self.assertIn("runner_backdoor", audit2.offending_tables)

    # -- the findability walk --------------------------------------

    def test_token_page_findability_walk(self):
        home = render_runner_home()
        self.assertIn(token_page_path("instance"), home)
        # Repo scope: home -> token page -> mint -> page
        # lists the token -> revoke from the page's data.
        page_path = token_page_path("repo", "volmarr/widget")
        self.assertIn("/{target}/settings/runners", home)
        token, _raw = self.store.mint_token(
            self.owner.id, "repo", "volmarr/widget")
        tokens = self.store.list_tokens(
            self.owner.id, "repo", "volmarr/widget")
        runners = self.store.list_runners(
            self.owner.id, "repo", "volmarr/widget")
        page = render_runner_token_page(
            "repo", "volmarr/widget", tokens, runners,
            csrf_token="csrf-x", now=self.clock.now)
        self.assertIn("Mint token", page)
        self.assertIn(token.prefix, page)
        self.assertIn("live", page)
        self.assertIn("Revoke", page)
        self.assertIn(f"{page_path}/revoke", page)
        self.assertTrue(
            self.store.revoke_token(self.owner.id, token.id))
        page2 = render_runner_token_page(
            "repo", "volmarr/widget",
            self.store.list_tokens(
                self.owner.id, "repo", "volmarr/widget"),
            runners, now=self.clock.now)
        self.assertIn("revoked", page2)
        self.assertNotIn("Revoke", page2)
        # Org and instance pages render their own walks.
        self.store.mint_token(self.owner.id, "org", "acme")
        org_page = render_runner_token_page(
            "org", "acme",
            self.store.list_tokens(self.owner.id, "org", "acme"),
            [], now=self.clock.now)
        self.assertIn("orgs/acme/settings/runners/mint", org_page)
        inst_page = render_runner_token_page(
            "instance", "", [], [], now=self.clock.now)
        self.assertIn("the whole instance", inst_page)
        self.assertIn("Mint token", inst_page)

    def test_token_page_lists_runners_and_escapes(self):
        _token, raw = self.store.mint_token(
            self.owner.id, "repo", "volmarr/widget")
        runner = self.store.register_runner(_payload(
            raw, agent_version='1"><script>alert(1)</script>'))
        page = render_runner_token_page(
            "repo", "volmarr/widget",
            self.store.list_tokens(
                self.owner.id, "repo", "volmarr/widget"),
            self.store.list_runners(
                self.owner.id, "repo", "volmarr/widget"),
            now=self.clock.now)
        self.assertIn("longship-1", page)
        self.assertIn("linux, x64", page)
        self.assertIn("Registered", page)
        self.assertIn("Deregister", page)
        self.assertNotIn("<script", page)
        self.assertTrue(self.store.deregister_runner(
            self.owner.id, runner.id))
        page2 = render_runner_token_page(
            "repo", "volmarr/widget", [],
            self.store.list_runners(
                self.owner.id, "repo", "volmarr/widget"),
            now=self.clock.now)
        self.assertIn("Deregistered", page2)
        self.assertNotIn("Deregister", page2.replace(
            "Deregistered", ""))


if __name__ == "__main__":
    unittest.main()
