"""S-320 acceptance battery: fork-PR safety.

Acceptance (roadmap S-320): Fork-PR safety --
workflows from fork PRs run with no secrets and
read-only tokens by default; the rule is in the
scheduler, not in docs alone.

The centre is samverk/fork_pr_safety.py: the
scheduler judgement ``schedule_dispatch`` that
every dispatch passes through. A run is a fork
run exactly when its event is pull_request and
its canonical head repository differs from its
base; a fork run's plan carries an empty secret
environment (handed values dropped, handed names
recorded as withheld) and token permissions
capped to read-only, while any other run carries
the handed environment whole and the declared
permissions as declared (read-only when
undeclared -- S-313's read-by-default).
``resolve_dispatch_env`` is the dispatch road
over S-319: for a fork run the secrets store is
never consulted, so no value is decrypted and no
instance key is needed. No migration (schema
stays 130); taxonomy unmoved at 135 (33 auth /
89 repo / 13 admin).

Counted with: python3 -m unittest tests.test_fork_pr_safety
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.ci_secrets import CISecretsStore
from samverk.db import schema_version
from samverk.fork_pr_safety import (
    EVENT_KINDS, PERMISSION_LEVELS, DispatchPlan, ForkSafetyError,
    RunRequest, TokenPermissions, assignment_env_names,
    audit_fork_pr_safety, cap_to_read_only, canonical_repo,
    describe_permissions, effective_permissions, is_fork_head,
    parse_permissions, plan_to_dict, render_fork_pr_safety_page,
    resolve_dispatch_env, schedule_dispatch)
from samverk.organizations import OrganizationStore
from samverk.repositories import RepositoryStore
from samverk.workflow_format import TRIGGER_EVENTS

PW = "correct horse battery"
T0 = 1_700_000_000
KEY = bytes(range(32))
OTHER_KEY = bytes(reversed(range(32)))
SEEDED = "seeded-fork-secret-320"
BASE = "volmarr/widget"
FORK = "mallory/widget"


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


def _reason(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except ForkSafetyError as exc:
        return exc.reason
    raise AssertionError("expected ForkSafetyError")


def _fork_request(**overrides):
    fields = {"event": "pull_request", "base_repository": BASE,
              "head_repository": FORK}
    fields.update(overrides)
    return RunRequest(**fields)


class PureLawTests(unittest.TestCase):
    def test_event_vocabulary_pinned(self):
        self.assertEqual(tuple(EVENT_KINDS), tuple(TRIGGER_EVENTS))
        self.assertEqual(
            tuple(EVENT_KINDS),
            ("push", "pull_request", "tag", "schedule",
             "workflow_dispatch"))
        self.assertEqual(tuple(PERMISSION_LEVELS),
                         ("none", "read", "write"))

    def test_repo_canonicalisation(self):
        self.assertEqual(canonical_repo("Volmarr/Widget"), BASE)
        self.assertEqual(canonical_repo(BASE), BASE)
        for bad in ("widget", "a/b/c", "", None, 7, "a b/c"):
            self.assertEqual(
                _reason(canonical_repo, bad), "fork_repo_invalid", bad)

    def test_fork_head_detection(self):
        self.assertTrue(is_fork_head(BASE, FORK))
        self.assertTrue(is_fork_head(BASE, "Mallory/WIDGET"))
        self.assertFalse(is_fork_head(BASE, BASE))
        self.assertFalse(is_fork_head(BASE, "Volmarr/Widget"))
        self.assertFalse(is_fork_head(BASE, ""))
        self.assertFalse(is_fork_head(BASE, None))

    def test_permissions_default_is_read_only(self):
        perms = parse_permissions(None)
        self.assertEqual(perms, TokenPermissions("read", ()))
        self.assertTrue(perms.is_read_only)
        self.assertEqual(perms.level_for("contents"), "read")
        self.assertEqual(perms.level_for("anything"), "read")

    def test_permissions_shorthands(self):
        self.assertEqual(parse_permissions("read-all"),
                         TokenPermissions("read", ()))
        self.assertEqual(parse_permissions("write-all"),
                         TokenPermissions("write", ()))
        self.assertEqual(parse_permissions("none"),
                         TokenPermissions("none", ()))
        self.assertFalse(parse_permissions("write-all").is_read_only)
        self.assertTrue(parse_permissions("none").is_read_only)

    def test_permissions_mapping(self):
        perms = parse_permissions(
            {"Contents": "write", "issues": "read",
             "checks": "none"})
        self.assertEqual(perms.fallback, "none")
        self.assertEqual(
            perms.scopes, (("checks", "none"),
                           ("contents", "write"),
                           ("issues", "read")))
        self.assertEqual(perms.level_for("contents"), "write")
        self.assertEqual(perms.level_for("CONTENTS"), "write")
        self.assertEqual(perms.level_for("statuses"), "none")
        self.assertFalse(perms.is_read_only)
        self.assertEqual(parse_permissions({}),
                         TokenPermissions("none", ()))
        parsed = parse_permissions("write-all")
        self.assertIs(parse_permissions(parsed), parsed)

    def test_permissions_invalid_refused(self):
        for bad in ("read_all", "WRITE-ALL", "", 7, ["read"],
                    {"contents": "admin"}, {"contents": None},
                    {"bad scope!": "read"}, {"": "read"},
                    {"Contents": "read", "contents": "write"}):
            self.assertEqual(
                _reason(parse_permissions, bad),
                "fork_permissions_invalid", repr(bad)[:40])

    def test_cap_law(self):
        self.assertEqual(cap_to_read_only(parse_permissions("write-all")),
                         TokenPermissions("read", ()))
        self.assertEqual(cap_to_read_only(parse_permissions("read-all")),
                         TokenPermissions("read", ()))
        self.assertEqual(cap_to_read_only(parse_permissions("none")),
                         TokenPermissions("none", ()))
        capped = cap_to_read_only(parse_permissions(
            {"contents": "write", "issues": "read",
             "checks": "none"}))
        self.assertEqual(
            capped.scopes, (("checks", "none"),
                            ("contents", "read"),
                            ("issues", "read")))
        self.assertTrue(capped.is_read_only)
        self.assertEqual(cap_to_read_only(capped), capped)

    def test_effective_permissions(self):
        self.assertEqual(
            effective_permissions("write-all", is_fork=True),
            TokenPermissions("read", ()))
        self.assertEqual(
            effective_permissions("write-all", is_fork=False),
            TokenPermissions("write", ()))
        self.assertEqual(
            effective_permissions(None, is_fork=True),
            TokenPermissions("read", ()))
        words = describe_permissions(parse_permissions("write-all"))
        self.assertIn("read/write", words)
        self.assertIn(
            "read-only",
            describe_permissions(parse_permissions(None)))

class SchedulerTests(unittest.TestCase):
    def test_fork_pr_strips_all_secrets(self):
        plan = schedule_dispatch(
            _fork_request(),
            secret_env={"API_KEY": SEEDED, "TOKEN": "second-value"})
        self.assertIsInstance(plan, DispatchPlan)
        self.assertTrue(plan.is_fork)
        self.assertEqual(plan.env, {})
        self.assertEqual(plan.env_items, ())
        self.assertEqual(plan.secret_names, ())
        self.assertEqual(plan.withheld_secret_names,
                         ("API_KEY", "TOKEN"))
        self.assertTrue(plan.secrets_withheld)
        self.assertEqual(plan.base_repository, BASE)
        self.assertEqual(plan.head_repository, FORK)
        self.assertEqual(
            plan.reasons,
            ("fork_pull_request", "no_secrets", "read_only_token"))

    def test_fork_pr_values_nowhere(self):
        plan = schedule_dispatch(
            _fork_request(declared_permissions="write-all"),
            secret_env={"API_KEY": SEEDED})
        self.assertNotIn(SEEDED, repr(plan))
        self.assertNotIn(SEEDED, str(plan_to_dict(plan)))
        self.assertNotIn(SEEDED, plan.summary)
        page = render_fork_pr_safety_page(plan=plan)
        self.assertNotIn(SEEDED, page)
        self.assertIn("API_KEY", page)

    def test_fork_pr_token_capped_from_write_all(self):
        plan = schedule_dispatch(
            _fork_request(declared_permissions="write-all"),
            secret_env={})
        self.assertTrue(plan.token_read_only)
        self.assertTrue(plan.permissions_capped)
        self.assertEqual(plan.permissions, TokenPermissions("read", ()))
        self.assertEqual(plan.declared_permissions,
                         TokenPermissions("write", ()))
        self.assertIn("permissions_capped", plan.reasons)
        self.assertIn("capped to read", plan.summary)

    def test_fork_pr_token_capped_from_mapping(self):
        plan = schedule_dispatch(_fork_request(
            declared_permissions={"contents": "write",
                                  "issues": "write"}))
        self.assertTrue(plan.token_read_only)
        self.assertTrue(plan.permissions_capped)
        self.assertEqual(plan.permissions.level_for("contents"), "read")
        self.assertEqual(plan.permissions.level_for("issues"), "read")
        self.assertEqual(plan.permissions.level_for("checks"), "none")

    def test_fork_pr_already_read_only_not_capped(self):
        for declared in (None, "read-all", "none",
                         {"contents": "read"}):
            plan = schedule_dispatch(
                _fork_request(declared_permissions=declared))
            self.assertTrue(plan.token_read_only, declared)
            self.assertFalse(plan.permissions_capped, declared)
            self.assertNotIn("permissions_capped", plan.reasons)

    def test_same_repo_pr_keeps_secrets_and_write(self):
        plan = schedule_dispatch(
            RunRequest("pull_request", BASE, BASE, "write-all"),
            secret_env={"TOKEN": "kept-value", "API_KEY": SEEDED})
        self.assertFalse(plan.is_fork)
        self.assertEqual(plan.env,
                         {"API_KEY": SEEDED, "TOKEN": "kept-value"})
        self.assertEqual(plan.secret_names, ("API_KEY", "TOKEN"))
        self.assertEqual(plan.withheld_secret_names, ())
        self.assertFalse(plan.token_read_only)
        self.assertFalse(plan.permissions_capped)
        self.assertEqual(plan.reasons,
                         ("same_repository_pull_request",))
        # A head named with different case is the same repo.
        plan2 = schedule_dispatch(
            RunRequest("pull_request", BASE, "Volmarr/Widget"))
        self.assertFalse(plan2.is_fork)
        # An empty head is the base itself.
        plan3 = schedule_dispatch(RunRequest("pull_request", BASE))
        self.assertFalse(plan3.is_fork)
        self.assertEqual(plan3.head_repository, BASE)

    def test_non_pr_events_are_never_fork_runs(self):
        for event in ("push", "tag", "schedule", "workflow_dispatch"):
            plan = schedule_dispatch(
                RunRequest(event, BASE, FORK, "write-all"),
                secret_env={"API_KEY": SEEDED})
            self.assertFalse(plan.is_fork, event)
            self.assertEqual(plan.env, {"API_KEY": SEEDED}, event)
            self.assertFalse(plan.token_read_only, event)
            self.assertEqual(plan.head_repository, BASE, event)
            self.assertEqual(plan.reasons, ("not_a_pull_request",), event)

    def test_undeclared_nonfork_is_read_only(self):
        plan = schedule_dispatch(RunRequest("push", BASE))
        self.assertTrue(plan.token_read_only)
        self.assertEqual(plan.permissions, TokenPermissions("read", ()))
        self.assertIn("read-only",
                      describe_permissions(plan.permissions))

    def test_secret_names_only_flow_withholds(self):
        plan = schedule_dispatch(
            _fork_request(), secret_names=["API_KEY", "TOKEN"])
        self.assertEqual(plan.env, {})
        self.assertEqual(plan.withheld_secret_names,
                         ("API_KEY", "TOKEN"))
        plan = schedule_dispatch(
            _fork_request(), secret_env={"API_KEY": SEEDED},
            secret_names=["TOKEN", "API_KEY", "TOKEN"])
        self.assertEqual(plan.withheld_secret_names,
                         ("API_KEY", "TOKEN"))
        # Names handed for a non-fork run withhold nothing.
        plan = schedule_dispatch(
            RunRequest("push", BASE), secret_names=["API_KEY"])
        self.assertEqual(plan.withheld_secret_names, ())

    def test_scheduler_judges_what_it_is_handed(self):
        self.assertEqual(
            _reason(schedule_dispatch, "not-a-request"),
            "fork_safety_invalid")
        self.assertEqual(
            _reason(schedule_dispatch,
                    RunRequest("explode", BASE)),
            "fork_event_unknown")
        self.assertEqual(
            _reason(schedule_dispatch,
                    RunRequest("push", "not-a-repo")),
            "fork_repo_invalid")
        self.assertEqual(
            _reason(schedule_dispatch, _fork_request(),
                    secret_env={"bad name": "x"}),
            "fork_safety_invalid")
        self.assertEqual(
            _reason(schedule_dispatch, _fork_request(),
                    secret_env={"API_KEY": 7}),
            "fork_safety_invalid")
        self.assertEqual(
            _reason(schedule_dispatch, _fork_request(),
                    secret_env=[("API_KEY", "x")]),
            "fork_safety_invalid")
        self.assertEqual(
            _reason(schedule_dispatch, _fork_request(),
                    secret_names="API_KEY"),
            "fork_safety_invalid")

    def test_assignment_env_names(self):
        fork_plan = schedule_dispatch(
            _fork_request(), secret_env={"API_KEY": SEEDED})
        self.assertEqual(
            assignment_env_names(
                ["API_KEY", "SAMVERK_RUN_ID", "PLAIN"], fork_plan),
            ("SAMVERK_RUN_ID", "PLAIN"))
        push_plan = schedule_dispatch(
            RunRequest("push", BASE), secret_env={"API_KEY": SEEDED})
        self.assertEqual(
            assignment_env_names(["API_KEY", "PLAIN"], push_plan),
            ("API_KEY", "PLAIN"))
        self.assertEqual(
            _reason(assignment_env_names, ["A", "A"], push_plan),
            "fork_safety_invalid")
        self.assertEqual(
            _reason(assignment_env_names, ["bad name"], push_plan),
            "fork_safety_invalid")
        self.assertEqual(
            _reason(assignment_env_names, "API_KEY", push_plan),
            "fork_safety_invalid")

    def test_plan_to_dict_is_names_only(self):
        plan = schedule_dispatch(
            RunRequest("push", BASE, "", "write-all"),
            secret_env={"API_KEY": SEEDED})
        face = plan_to_dict(plan)
        self.assertEqual(
            set(face),
            {"event", "base_repository", "head_repository", "is_fork",
             "secret_names", "withheld_secret_names", "secrets_withheld",
             "declared_permissions", "permissions",
             "permissions_capped", "token_read_only", "reasons",
             "summary"})
        self.assertEqual(face["secret_names"], ["API_KEY"])
        self.assertEqual(face["permissions"],
                         {"fallback": "write", "scopes": {}})
        self.assertNotIn(SEEDED, str(face))

class DispatchRoadTests(unittest.TestCase):
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
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.pub = self.repos.create_repository(
            self.owner.id, "volmarr", "widget", visibility="public")
        self.orgs = OrganizationStore(
            self.conn, self.accounts, audit=self.audit,
            time_fn=self.clock)
        self.store = CISecretsStore(
            self.conn, self.accounts, self.repos,
            audit=self.audit, encryption_key=KEY, time_fn=self.clock)
        self.nokey = CISecretsStore(
            self.conn, self.accounts, self.repos,
            audit=self.audit, time_fn=self.clock)
        self.wrongkey = CISecretsStore(
            self.conn, self.accounts, self.repos,
            audit=self.audit, encryption_key=OTHER_KEY,
            time_fn=self.clock)
        self.store.set_secret(
            self.owner.id, "repo", BASE, "API_KEY", SEEDED)
        self.store.set_secret(
            self.owner.id, "repo", BASE, "TOKEN", "second-value")

    def test_pins_hold(self):
        self.assertEqual(schema_version(self.conn), 134)
        self.assertEqual(db.MIGRATIONS[-1][0], 134)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 138)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 92)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)

    def test_fork_dispatch_never_consults_the_store(self):
        # No key at all, and a wrong key: a non-fork resolve
        # would refuse (encryption_unavailable /
        # ci_secret_unreadable); the fork dispatch plans
        # cleanly because the store's values road is
        # never walked -- only its names face is read.
        for store in (self.nokey, self.wrongkey):
            plan = resolve_dispatch_env(store, _fork_request())
            self.assertTrue(plan.is_fork)
            self.assertEqual(plan.env, {})
            self.assertEqual(plan.secret_names, ())
            self.assertEqual(plan.withheld_secret_names,
                             ("API_KEY", "TOKEN"))
            self.assertTrue(plan.token_read_only)

    def test_same_repo_dispatch_injects(self):
        plan = resolve_dispatch_env(
            self.store, RunRequest("pull_request", BASE, BASE))
        self.assertFalse(plan.is_fork)
        self.assertEqual(
            plan.env, {"API_KEY": SEEDED, "TOKEN": "second-value"})
        plan = resolve_dispatch_env(
            self.store, RunRequest("push", BASE))
        self.assertEqual(plan.env["API_KEY"], SEEDED)

    def test_fork_dispatch_with_declared_write_is_capped(self):
        plan = resolve_dispatch_env(
            self.store, _fork_request(declared_permissions="write-all"))
        self.assertEqual(plan.env, {})
        self.assertTrue(plan.permissions_capped)
        self.assertTrue(plan.token_read_only)

    def test_dispatch_planning_writes_and_audits_nothing(self):
        before = self.conn.execute(
            "SELECT COUNT(*) c FROM audit_log").fetchone()["c"]
        resolve_dispatch_env(self.store, _fork_request())
        resolve_dispatch_env(
            self.store, RunRequest("pull_request", BASE, BASE))
        after = self.conn.execute(
            "SELECT COUNT(*) c FROM audit_log").fetchone()["c"]
        self.assertEqual(after, before)

    def test_audit_stands_cleanly(self):
        audit = audit_fork_pr_safety(self.conn)
        self.assertTrue(audit.stands_cleanly, audit)
        self.assertTrue(audit.defaults_ok)
        self.assertTrue(audit.levels_ok)
        self.assertTrue(audit.schema_ok)
        self.assertEqual(audit.schema_version, 134)
        self.assertTrue(audit.events_ok)
        self.assertEqual(audit.events_scanned, 138)
        self.assertEqual(audit.offending_tables, ())
        self.assertEqual(audit.offending_columns, ())
        self.assertEqual(audit.offending_events, ())
        self.assertGreater(audit.tables_scanned, 0)
        self.assertGreater(audit.columns_scanned, 0)

    def test_audit_catches_a_planted_table(self):
        with self.conn:
            self.conn.execute(
                "CREATE TABLE workflow_fork_runs (id INTEGER)")
        audit = audit_fork_pr_safety(self.conn)
        self.assertFalse(audit.stands_cleanly)
        self.assertEqual(audit.offending_tables,
                         ("workflow_fork_runs",))

    def test_audit_catches_a_planted_column(self):
        with self.conn:
            self.conn.execute(
                "ALTER TABLE ci_secrets ADD COLUMN"
                " fork_dispatch_note TEXT")
        audit = audit_fork_pr_safety(self.conn)
        self.assertFalse(audit.stands_cleanly)
        self.assertEqual(audit.offending_columns,
                         ("ci_secrets.fork_dispatch_note",))

    def test_page_renders_the_rule(self):
        page = render_fork_pr_safety_page(
            audit=audit_fork_pr_safety(self.conn))
        self.assertIn("Fork-PR safety (S-320)", page)
        self.assertIn("no secrets", page)
        self.assertIn("read-only token", page)
        self.assertIn("scheduler", page)
        self.assertIn("stands cleanly", page)
        self.assertNotIn(SEEDED, page)
        bare = render_fork_pr_safety_page()
        self.assertIn("no privileged fork trigger", bare)


if __name__ == "__main__":
    unittest.main()
