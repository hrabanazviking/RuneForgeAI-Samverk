"""S-256 — PART XII GATE battery: API & webhooks, assembled.

The whole Part XII system struck at once, in the house
gate shape of S-204/S-220/S-236 — no new production
code, only the battery that walks the landed
S-237..S-255 machinery end to end through its public
seams, at the thing the gate names: **every documented
endpoint exercised against its contract tests**.

- **The contract itself (S-237)** — the 36-resource
  route table and its ten rules, judged pure and
  judged by `audit_api_contract` against the live
  serialisers: ratified, 63 routes, 20 landed shapes,
  no drift. The two hook resources stand contracted
  in the table and are exercised here through the
  S-248 store that stands behind them.
- **The door (S-238..S-241, S-254, S-255)** — bearer
  and Basic authentication through S-190, cursor
  pagination with ETag/`If-None-Match` crawls, the
  one problem shape, per-token rate buckets with
  honest headers, the versioning policy, and the
  abuse defences, each judged pure and composed.
- **The families (S-242..S-246)** — repositories,
  issues/pulls (a script drives a pull from open to
  merge), users/orgs/teams, search, and status/checks,
  each exercised against its contracted fields, with
  the private repository invisible identically.
- **Webhooks (S-247..S-252)** — the taxonomy audit,
  subscriptions whose secret is set once and never
  shown, HMAC signing verified and tamper refused,
  the delivery worker (success, backoff, exactly-once
  enqueue), the delivery log with one-call
  redelivery, and the ping/test-event sender.
- **GraphQL (S-253)** — the deferred verdict: every
  GraphQL action refused by name, the audit clean.

The gate claimed no migration and no taxonomy event:
the assembled system stands at schema 99 with 131
audit events (33 auth / 85 repo / 13 admin), and the
battery proves both pins.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db, taxonomy
from samverk.access_tokens import AccessTokenStore
from samverk.accounts import AccountStore
from samverk.api_abuse import (
    ApiAbuseGuard, audit_api_abuse, decide_concurrency,
    decide_payload)
from samverk.api_auth import (
    ApiAuthenticator, decide_token_scope, parse_bearer_token,
    scope_requirement)
from samverk.api_checks import StatusChecksAPI, StatusChecksAPIError
from samverk.api_contract import (
    PROBLEM_FIELDS, ApiContractError, audit_api_contract,
    get_resource, get_rule, render_api_contract_page,
    resource_ids, rule_ids)
from samverk.api_issues_pulls import (
    IssuesPullsAPI, IssuesPullsAPIError)
from samverk.api_orgs import UsersOrgsTeamsAPI, UsersOrgsTeamsAPIError
from samverk.api_pagination import (
    ApiPaginationError, conditional_response, decode_cursor,
    encode_cursor, etag_for, link_header, paginate)
from samverk.api_rate_limit import (
    ApiRateLimiter, RateLimitSettings, decide_bucket)
from samverk.api_repositories import (
    RepositoriesAPI, RepositoriesAPIError)
from samverk.api_search import PublicSearchAPI, PublicSearchAPIError
from samverk.api_versioning import audit_api_versioning, decide_change
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.error_shape import (
    decide_problem_status, is_registered_reason, make_problem,
    problem_from_error, problem_to_dict, registered_reasons)
from samverk.event_store import CanonicalEvent
from samverk.fine_grained_tokens import FineTokenStore
from samverk.graphql_verdict import (
    GraphQLVerdictError, attempt_graphql_action,
    audit_graphql_verdict, decide_graphql_request)
from samverk.issues import IssueStore
from samverk.organizations import OrganizationStore
from samverk.org_repositories import OrgRepoStore
from samverk.organization_members import OrgMembershipStore
from samverk.repositories import RepositoryStore
from samverk.webhook_delivery import (
    TransportResult, WebhookDeliveryStore, backoff_delay)
from samverk.webhook_delivery_log import DeliveryLogStore
from samverk.webhook_events import (
    all_verbs, audit_webhook_events, deliverable_verbs,
    is_deliverable, webhook_payload)
from samverk.webhook_ping import WebhookPingStore
from samverk.webhook_signing import (
    signature_header, sign_payload, verify_signature)
from samverk.webhook_subscriptions import (
    WebhookSubscriptionStore, decide_match, secret_digest,
    secret_matches)

PW = "correct horse battery"
NOW = 1_700_000_000
OID = "a" * 40
RESOURCE_IDS = (
    "root", "repositories", "repository",
    "repository-branches", "repository-contents",
    "repository-forks", "issues", "issue",
    "issue-comments", "pulls", "pull", "pull-merge",
    "pull-reviews", "user", "organizations",
    "organization", "organization-members",
    "organization-member", "organization-teams",
    "team", "team-members", "team-member",
    "team-repositories", "team-repository",
    "organization-default-permission",
    "repository-collaborators", "repository-collaborator",
    "search", "events", "user-events",
    "repository-events", "event", "statuses",
    "check-runs", "repository-hooks", "organization-hooks")
RULE_IDS = (
    "versioned-base", "permission-parity",
    "uniform-not-found", "json-utf8", "list-envelope",
    "cursor-pagination", "error-shape", "rate-limits",
    "no-back-doors", "graphql-deferred")


class Clock:
    def __init__(self, now=NOW):
        self.now = now
    def __call__(self):
        return self.now


def basic(username, credential):
    raw = base64.b64encode(f"{username}:{credential}".encode())
    return "Basic " + raw.decode("ascii")


def git(repo, *args, input_bytes=None):
    env = {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": "/usr/bin:/bin"}
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         capture_output=True, input=input_bytes, env=env)
    assert out.returncode == 0, out.stderr.decode()
    return out.stdout.decode().strip()


def build_tree(repo, mapping):
    lines = []
    for name in sorted(mapping):
        value = mapping[name]
        if isinstance(value, dict):
            oid = build_tree(repo, value)
            lines.append(f"040000 tree {oid}\t{name}")
        else:
            oid = git(repo, "hash-object", "-w", "--stdin",
                      input_bytes=value)
            lines.append(f"100644 blob {oid}\t{name}")
    return git(repo, "mktree",
               input_bytes=("\n".join(lines) + "\n").encode())


def commit_tree(repo, tree, message, parent=None):
    args = ["commit-tree", tree]
    if parent:
        args += ["-p", parent]
    return git(repo, *args, input_bytes=(message + "\n").encode())


class FakeTransport:
    def __init__(self, script=()):
        self.script = list(script)
        self.calls = []
    def __call__(self, url, body, headers, timeout):
        self.calls.append((url, body, dict(headers), timeout))
        outcome = self.script.pop(0) if self.script else 200
        if isinstance(outcome, BaseException):
            raise outcome
        return TransportResult(status_code=outcome)


def make_event(event_id=7, verb="repo.issue.create"):
    return CanonicalEvent(
        id=event_id, audit_seq=event_id, actor_kind="user",
        actor_id=3, actor="volmarr", verb=verb,
        target_kind="repo", target_id="volmarr/pub#1",
        refs=("repo:volmarr/pub", "number:1"),
        detail={"number": 1}, outcome="success", created_at=NOW)


def make_world(root: Path) -> SimpleNamespace:
    conn = db.init_db(root / "samverk.db")
    clock = Clock()
    audit = AuditLog(conn, time_fn=clock)
    accounts = AccountStore(conn, audit=audit, time_fn=clock)
    owner = accounts.register("volmarr", PW)
    reader = accounts.register("yrsa", PW)
    stranger = accounts.register("mallory", PW)
    repos = RepositoryStore(conn, root, accounts, audit=audit)
    orgs = OrganizationStore(conn, accounts, audit=audit, time_fn=clock)
    org = orgs.create_organization(
        owner.id, "Forge", display_name="The Forge", bio="Tools.")
    members = OrgMembershipStore(conn, accounts, audit=audit, time_fn=clock)
    members.add_member(owner.id, org.id, reader.id)
    org_repos = OrgRepoStore(conn, accounts, root, audit=audit, time_fn=clock)
    org_repos.create_repository(owner.id, org.id, "anvil",
                                visibility="private")
    issues = IssueStore(conn, repos, accounts, audit=audit, time_fn=clock)
    pub = repos.create_repository(owner.id, "volmarr", "pub",
                                  visibility="public")
    path = repos.path_for("volmarr", "pub")
    t1 = build_tree(path, {"hello.txt": b"hello world\n",
                           "dir": {"note.txt": b"nested\n"}})
    c1 = commit_tree(path, t1, "first")
    git(path, "update-ref", "refs/heads/main", c1)
    t2 = build_tree(path, {"hello.txt": b"hello world\n",
                           "feature.txt": b"new work\n"})
    c2 = commit_tree(path, t2, "feature work", parent=c1)
    git(path, "update-ref", "refs/heads/feature", c2)
    repos.create_repository(owner.id, "volmarr", "priv",
                            visibility="private")
    issues.create_issue(owner, "volmarr", "priv", "Secret zorblax plans")
    classic = AccessTokenStore(conn, accounts, audit=audit, time_fn=clock)
    fine = FineTokenStore(conn, accounts, audit=audit, time_fn=clock)
    expiry = NOW + 3600
    _, tok_read = classic.create_token(owner.id, "read", {"repo:read"}, expiry)
    _, tok_write = classic.create_token(owner.id, "write", {"repo:write"}, expiry)
    w = SimpleNamespace(
        conn=conn, clock=clock, audit=audit, accounts=accounts,
        owner=owner, reader=reader, stranger=stranger, repos=repos,
        orgs=orgs, org=org, members=members, issues=issues,
        pub=pub, c1=c1, c2=c2, path=path, root=root,
        tok_read=tok_read, tok_write=tok_write,
        auth=ApiAuthenticator(conn, accounts, repos, time_fn=clock),
        repo_api=RepositoriesAPI(conn, root, accounts, repos,
                                 audit=audit, time_fn=clock),
        ip_api=IssuesPullsAPI(conn, accounts, repos, audit=audit,
                              time_fn=clock),
        org_api=UsersOrgsTeamsAPI(conn, accounts, repos, audit=audit,
                                  time_fn=clock),
        search_api=PublicSearchAPI(conn, accounts, repos, orgs,
                                   audit=audit, time_fn=clock),
        checks_api=StatusChecksAPI(conn, accounts, repos, issues,
                                   audit=audit, time_fn=clock),
        hooks=WebhookSubscriptionStore(conn, repos, orgs, accounts,
                                       audit=audit, time_fn=clock))
    w.owner_h = basic("volmarr", PW)
    w.reader_h = basic("yrsa", PW)
    w.stranger_h = basic("mallory", PW)
    return w


class PartXIIGateTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.w = make_world(Path(self._td.name))
        self.addCleanup(self.w.conn.close)

    # -- pins ------------------------------------------------
    def test_pins_schema_99_taxonomy_131(self):
        w = self.w
        self.assertEqual(schema_version(w.conn), 101)
        self.assertEqual(db.MIGRATIONS[-1][0], 101)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 131)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 85)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        tables = {r["name"] for r in w.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ("webhooks", "webhook_deliveries",
                      "webhook_pings"):
            self.assertIn(table, tables)

    # -- S-237 contract ---------------------------------------
    def test_contract_route_table_is_exact_and_ratified(self):
        self.assertEqual(resource_ids(), RESOURCE_IDS)
        self.assertEqual(rule_ids(), RULE_IDS)
        audit = audit_api_contract()
        self.assertTrue(audit.ratified, audit)
        self.assertEqual(audit.resources_checked, 36)
        self.assertEqual(audit.routes_checked, 63)
        self.assertEqual(audit.landed_shapes_checked, 20)
        self.assertEqual(audit.route_problems, ())
        self.assertEqual(audit.landed_shape_mismatches, ())
        self.assertTrue(audit.error_shape_ok)
        self.assertTrue(audit.permission_engine_present)

    def test_every_resource_row_is_well_formed(self):
        landed = 0
        for rid in RESOURCE_IDS:
            res = get_resource(rid)
            self.assertEqual(res.id, rid)
            self.assertTrue(res.path.startswith("/api/v1"), rid)
            self.assertTrue(res.methods, rid)
            for method in res.methods:
                self.assertIn(method,
                    ("GET", "POST", "PUT", "PATCH", "DELETE"), rid)
            self.assertTrue(res.fields, rid)
            self.assertTrue(res.slice.startswith("S-"), rid)
            if res.standing == "landed":
                landed += 1
            else:
                self.assertEqual(res.standing, "contracted", rid)
        self.assertEqual(landed, 34)
        for rid in ("repository-hooks", "organization-hooks"):
            res = get_resource(rid)
            self.assertEqual(res.standing, "contracted", rid)
            self.assertEqual(res.slice, "S-248", rid)
        with self.assertRaises(ApiContractError):
            get_resource("no-such-resource")
        with self.assertRaises(ApiContractError):
            get_rule("no-such-rule")
        for rid in RULE_IDS:
            self.assertTrue(get_rule(rid).statement, rid)

    def test_root_endpoint_answers_the_contract(self):
        root = self.w.repo_api.root(None)
        self.assertEqual(tuple(root.keys()),
                         get_resource("root").fields)
        self.assertEqual(json.loads(
            self.w.repo_api.root_json(None)), root)
        page = render_api_contract_page(audit_api_contract())
        self.assertIn("/api/v1", page)

    # -- S-238 auth --------------------------------------------
    def test_auth_bearer_basic_anonymous_and_refusals(self):
        w = self.w
        ident = w.auth.authenticate("Bearer " + w.tok_read)
        self.assertTrue(ident.authenticated)
        self.assertEqual(ident.username, "volmarr")
        ident = w.auth.authenticate(w.owner_h)
        self.assertTrue(ident.authenticated)
        self.assertEqual(ident.username, "volmarr")
        anon = w.auth.resolve_caller(None, required=False)
        self.assertFalse(anon.authenticated)
        self.assertIsNone(anon.username)
        with self.assertRaises(Exception):
            w.auth.authenticate(None)
        self.assertEqual(parse_bearer_token("Bearer abc"), "abc")
        self.assertIsNone(parse_bearer_token("Basic abc"))
        self.assertIsNone(parse_bearer_token(None))
        with self.assertRaises(Exception):
            w.auth.authenticate("Bearer svk_not-a-real-token")
        with self.assertRaises(Exception):
            w.auth.authenticate(basic("volmarr", "nope"))

    def test_auth_scope_law(self):
        self.assertEqual(scope_requirement("repo", "read"),
                         ("repo:read", "contents:read"))
        self.assertEqual(scope_requirement("repo", "write"),
                         ("repo:write", "contents:write"))
        read = frozenset({"repo:read"})
        write = frozenset({"repo:write"})
        self.assertTrue(decide_token_scope(
            "classic_token", read, "repo", "read"))
        self.assertFalse(decide_token_scope(
            "classic_token", read, "repo", "write"))
        self.assertTrue(decide_token_scope(
            "classic_token", write, "repo", "read"))
        self.assertTrue(decide_token_scope(
            "password", frozenset(), "repo", "write"))
        self.assertFalse(decide_token_scope(
            "fine_token", read, "repo", "read", bound_matches=False))

    # -- S-239 pagination + ETag --------------------------------
    def test_pagination_cursor_crawl_is_bounded_and_complete(self):
        items = list(range(25, 0, -1))
        seen, cursor, pages = [], None, 0
        while True:
            page = paginate(items, key=lambda n: n, per_page=7,
                            cursor=cursor)
            pages += 1
            self.assertLessEqual(page.returned, 7)
            seen.extend(page.items)
            if page.complete:
                break
            cursor = page.next_cursor
            self.assertIsNotNone(cursor)
        self.assertEqual(seen, items)
        self.assertEqual(pages, 4)
        token = encode_cursor(7, "ctx")
        self.assertEqual(decode_cursor(token, "ctx"), 7)
        with self.assertRaises(ApiPaginationError):
            decode_cursor(token, "other-ctx")
        with self.assertRaises(ApiPaginationError):
            decode_cursor("not-a-cursor", "ctx")

    def test_etag_conditional_and_link_headers(self):
        payload = {"hello": "world"}
        first = conditional_response(payload, None)
        self.assertFalse(first.not_modified)
        self.assertEqual(first.etag, etag_for(payload))
        second = conditional_response(payload, first.etag)
        self.assertTrue(second.not_modified)
        page = paginate(list(range(30, 0, -1)), key=lambda n: n, per_page=10)
        header = link_header("/api/v1/search", page)
        self.assertIn('rel="next"', header)
        self.assertIn("/api/v1/search", header)

    # -- S-240 error shape ---------------------------------------
    def test_error_shape_is_one_problem_format_everywhere(self):
        problem = make_problem("repo_not_found", "No such repo.")
        as_dict = problem_to_dict(problem)
        self.assertEqual(tuple(as_dict.keys()), PROBLEM_FIELDS)
        self.assertEqual(as_dict["status"],
                         decide_problem_status("repo_not_found"))
        self.assertEqual(decide_problem_status("rate_limited"), 429)
        self.assertIn("repo_not_found", registered_reasons())
        self.assertTrue(is_registered_reason("rate_limited"))
        self.assertFalse(is_registered_reason("no_such_reason"))
        try:
            self.w.repo_api.get_repository(
                self.w.stranger_h, "volmarr", "priv")
            self.fail("private repo must refuse")
        except RepositoriesAPIError as exc:
            mapped = problem_from_error(exc)
            self.assertEqual(tuple(problem_to_dict(mapped).keys()),
                             PROBLEM_FIELDS)
            self.assertEqual(mapped.reason, exc.reason)

    # -- S-241 rate limiting -------------------------------------
    def test_rate_limit_bucket_pure_and_composed(self):
        allowed, after, wait = decide_bucket(3.0, 3.0, 1.0, 100.0, 100.0, 1.0)
        self.assertTrue(allowed)
        self.assertEqual(after, 2.0)
        ident = self.w.auth.authenticate("Bearer " + self.w.tok_read)
        settings = RateLimitSettings(
            enabled=True, token_capacity=3.0,
            token_refill_per_second=1.0, anonymous_capacity=2.0,
            anonymous_refill_per_second=0.5)
        limiter = ApiRateLimiter(settings, time_fn=self.w.clock)
        first = limiter.check(ident)
        self.assertTrue(first.allowed)
        headers = first.headers()
        self.assertEqual(headers["X-RateLimit-Limit"], "3")
        self.assertEqual(headers["X-RateLimit-Remaining"], "2")
        self.assertIn("X-RateLimit-Reset", headers)
        peeked = limiter.peek(ident)
        self.assertEqual(peeked.headers()["X-RateLimit-Remaining"], "2")
        limiter.check(ident)
        limiter.check(ident)
        refused = limiter.check(ident)
        self.assertFalse(refused.allowed)
        self.assertIsNotNone(refused.retry_after_header)
        self.assertIn("Retry-After", refused.headers())

    # -- S-254 versioning + S-253 GraphQL -------------------------
    def test_versioning_policy_matrix_and_audit(self):
        audit = audit_api_versioning()
        self.assertEqual(audit.current_version, "v1")
        self.assertEqual(audit.served_base, "/api/v1")
        self.assertTrue(audit.rest_ratified)
        self.assertTrue(audit.rule_ok)
        self.assertEqual(audit.rest_resources_checked, 36)
        self.assertEqual(decide_change("add-endpoint"), "allowed-in-v1")
        self.assertEqual(decide_change("remove-endpoint"), "requires-v2")
        self.assertEqual(decide_change(""), "change_kind_invalid")

    def test_graphql_is_deferred_and_refused_by_name(self):
        self.assertEqual(decide_graphql_request("query"),
                         "graphql_deferred")
        self.assertEqual(decide_graphql_request("mutation"),
                         "graphql_deferred")
        self.assertEqual(decide_graphql_request(""),
                         "graphql_action_invalid")
        with self.assertRaises(GraphQLVerdictError):
            attempt_graphql_action("query")
        audit = audit_graphql_verdict(self.w.conn)
        self.assertEqual(audit.verdict, "deferred")
        self.assertTrue(audit.rest_ratified)
        self.assertTrue(audit.invariant_rules_ok)
        self.assertEqual(audit.offending_tables, ())
        self.assertEqual(get_rule("graphql-deferred").id,
                         "graphql-deferred")

    # -- S-255 abuse defences --------------------------------------
    def test_abuse_defences_pure_composed_and_audited(self):
        audit = audit_api_abuse()
        self.assertTrue(audit.rest_ratified)
        self.assertTrue(audit.rule_ok)
        self.assertEqual(audit.endpoints_checked, 36)
        self.assertEqual(audit.uncatalogued_resources, ())
        self.assertEqual(decide_payload(100, 100), "allowed")
        self.assertEqual(decide_payload(101, 100), "payload_too_large")
        self.assertEqual(decide_concurrency(2, 3), "allowed")
        ident = self.w.auth.authenticate("Bearer " + self.w.tok_write)
        guard = ApiAbuseGuard.from_conn(self.w.conn)
        self.assertTrue(audit_api_abuse().defences_hold)
        decision = guard.judge_payload("repositories", 10)
        self.assertTrue(decision.allowed)
        totals = guard.endpoint_totals()
        self.assertIsInstance(totals, tuple)

    # -- S-242 repositories API ------------------------------------
    def test_repositories_api_full_surface(self):
        w = self.w
        listed = w.repo_api.list_repositories(w.owner_h)
        self.assertEqual(tuple(listed["repositories"][0].keys()),
                         get_resource("repositories").fields)
        names = {r["name"] for r in listed["repositories"]}
        self.assertIn("pub", names)
        created = w.repo_api.create_repository(
            w.owner_h, {"name": "fresh", "visibility": "public",
                        "description": "Made by script."})
        self.assertEqual(created["full_name"], "volmarr/fresh")
        got = w.repo_api.get_repository(w.owner_h, "volmarr", "fresh")
        self.assertEqual(tuple(got.keys()),
                         get_resource("repository").fields)
        updated = w.repo_api.update_repository(
            w.owner_h, "volmarr", "fresh",
            {"description": "Updated by script."})
        self.assertEqual(updated["description"], "Updated by script.")
        branches = w.repo_api.list_branches(w.owner_h, "volmarr", "pub")
        branch_names = {b["name"] for b in branches["branches"]}
        self.assertEqual(branch_names, {"main", "feature"})
        self.assertEqual(tuple(branches["branches"][0].keys()),
                         get_resource("repository-branches").fields)
        contents = w.repo_api.get_contents(
            w.owner_h, "volmarr", "pub", "dir")
        self.assertEqual(tuple(contents.keys())[:5],
            get_resource("repository-contents").fields)
        self.assertEqual(contents["kind"], "tree")
        self.assertEqual(len(contents["entries"]), 1)
        fork = w.repo_api.create_fork(w.reader_h, "volmarr", "pub")
        self.assertEqual(fork["owner"], "yrsa")
        forks = w.repo_api.list_forks(None, "volmarr", "pub")
        self.assertEqual(forks["total"], 1)

    def test_repositories_api_private_invisible_and_writes_gated(self):
        w = self.w
        with self.assertRaises(RepositoriesAPIError) as ctx:
            w.repo_api.get_repository(w.stranger_h, "volmarr", "priv")
        self.assertEqual(ctx.exception.reason, "repo_not_found")
        anon_list = w.repo_api.list_repositories(None)
        self.assertNotIn("priv",
            {r["name"] for r in anon_list["repositories"]})
        with self.assertRaises(RepositoriesAPIError):
            w.repo_api.create_repository(
                None, {"name": "anonrepo", "visibility": "public"})
        with self.assertRaises(RepositoriesAPIError):
            w.repo_api.create_repository(
                w.owner_h, {"name": "bad", "bogus_field": 1})

    # -- S-243 issues & pulls API -----------------------------------
    def test_issues_api_lifecycle(self):
        w = self.w
        issue = w.ip_api.create_issue(
            w.owner_h, "volmarr", "pub",
            {"title": "First bug", "body": "It broke."})
        self.assertEqual(tuple(issue.keys()),
                         get_resource("issues").fields)
        self.assertEqual(issue["state"], "open")
        number = issue["number"]
        comment = w.ip_api.add_issue_comment(
            w.reader_h, "volmarr", "pub", number, {"body": "Seen."})
        self.assertEqual(tuple(comment.keys()),
                         get_resource("issue-comments").fields)
        comments = w.ip_api.list_issue_comments(
            None, "volmarr", "pub", number)
        self.assertEqual(comments["total"], 1)
        closed = w.ip_api.update_issue(
            w.owner_h, "volmarr", "pub", number, {"state": "closed"})
        self.assertEqual(closed["state"], "closed")
        listed = w.ip_api.list_issues(None, "volmarr", "pub")
        self.assertEqual(listed["total"], 1)

    def test_script_drives_pull_from_open_to_merge(self):
        w = self.w
        pull = w.ip_api.create_pull(
            w.owner_h, "volmarr", "pub",
            {"base": "main", "head": "feature",
             "title": "Add the feature", "body": "For review."})
        self.assertEqual(tuple(pull.keys()),
                         get_resource("pulls").fields)
        number = pull["number"]
        self.assertEqual(pull["state"], "open")
        self.assertFalse(pull["merged"])
        w.ip_api.add_pull_comment(
            w.reader_h, "volmarr", "pub", number, {"body": "Looking."})
        review = w.ip_api.submit_review(
            w.reader_h, "volmarr", "pub", number,
            {"verdict": "approve", "summary": "Ship it."})
        self.assertEqual(tuple(review.keys()),
                         get_resource("pull-reviews").fields)
        self.assertEqual(review["state"], "approved")
        merged = w.ip_api.merge_pull(w.owner_h, "volmarr", "pub", number)
        self.assertTrue(merged["merged"])
        stored = w.ip_api.get_pull(None, "volmarr", "pub", number)
        self.assertTrue(stored["merged"])

    def test_issues_api_private_repo_never_leaks(self):
        w = self.w
        with self.assertRaises(IssuesPullsAPIError):
            w.ip_api.list_issues(w.stranger_h, "volmarr", "priv")
        with self.assertRaises(IssuesPullsAPIError):
            w.ip_api.create_issue(
                w.stranger_h, "volmarr", "priv", {"title": "x"})

    # -- S-244 users, orgs, teams API --------------------------------
    def test_orgs_api_administration_end_to_end(self):
        w = self.w
        user = w.org_api.get_user(None, "yrsa")
        self.assertEqual(tuple(user.keys()), get_resource("user").fields)
        self.assertEqual(user["username"], "yrsa")
        created = w.org_api.create_organization(
            w.owner_h, {"name": "Newforge", "display_name": "New Forge"})
        self.assertEqual(tuple(created.keys()),
                         get_resource("organizations").fields)
        added = w.org_api.add_member(
            w.owner_h, "Forge", {"username": "mallory", "role": "member"})
        self.assertEqual(tuple(added.keys()),
                         get_resource("organization-members").fields)
        members = w.org_api.list_members(w.owner_h, "Forge")
        self.assertIn("mallory", {m["username"] for m in members["members"]})
        team = w.org_api.create_team(
            w.owner_h, "Forge", {"name": "Builders", "privacy": "visible"})
        self.assertEqual(tuple(team.keys()), get_resource("team").fields)
        w.org_api.add_team_member(w.owner_h, "Forge", "builders",
                                  {"username": "yrsa"})
        team_members = w.org_api.list_team_members(
            w.owner_h, "Forge", "builders")
        self.assertIn("yrsa",
            {m["username"] for m in team_members["members"]})
        linked = w.org_api.link_team_repository(
            w.owner_h, "Forge", "builders",
            {"repository": "anvil", "permission": "write"})
        self.assertEqual(linked["repository"], "Forge/anvil")
        self.assertEqual(tuple(linked.keys()),
                         get_resource("team-repositories").fields)
        default = w.org_api.get_default_permission(w.owner_h, "Forge")
        self.assertEqual(tuple(default.keys()),
            get_resource("organization-default-permission").fields)
        collab = w.org_api.add_collaborator(
            w.owner_h, "volmarr", "pub",
            {"username": "mallory", "role": "read"})
        self.assertEqual(tuple(collab.keys()),
            get_resource("repository-collaborators").fields)
        with self.assertRaises(UsersOrgsTeamsAPIError):
            w.org_api.get_user(None, "ghost")

    # -- S-245 search API ---------------------------------------------
    def test_search_api_finds_and_pages(self):
        w = self.w
        w.ip_api.create_issue(
            w.owner_h, "volmarr", "pub",
            {"title": "Forge gating bug", "body": "forge work"})
        answer = w.search_api.search(w.owner_h, "pub")
        self.assertEqual(tuple(answer.keys()),
                         get_resource("search").fields)
        kinds = {g["type"] for g in answer["groups"]}
        self.assertIn("repositories", kinds)
        page = w.search_api.search_group_page(
            w.owner_h, "pub", "repositories", per_page=5)
        self.assertGreaterEqual(page["total"], 1)
        hidden = w.search_api.search(w.stranger_h, "zorblax")
        for group in hidden["groups"]:
            self.assertEqual(group["total"], 0, group["type"])
        with self.assertRaises(PublicSearchAPIError):
            w.search_api.search_group_page(
                w.owner_h, "pub", "no-such-group")

    # -- S-246 status & checks API -------------------------------------
    def test_checks_api_posts_lists_and_audits(self):
        w = self.w
        record = w.checks_api.post_status(
            w.owner_h, "volmarr", "pub", OID,
            {"state": "passed", "context": "ci/build",
             "description": "build ok",
             "target_url": "https://ci.example/run/1"})
        self.assertEqual(tuple(record.keys()),
                         get_resource("statuses").fields)
        run = w.checks_api.post_check_run(
            w.owner_h, "volmarr", "pub",
            {"oid": OID, "name": "ci/test", "status": "queued"})
        self.assertEqual(tuple(run.keys()),
                         get_resource("check-runs").fields)
        statuses = w.checks_api.list_statuses(None, "volmarr", "pub", OID)
        self.assertGreaterEqual(statuses["total"], 1)
        self.assertIn("ci/build",
            {s["context"] for s in statuses["statuses"]})
        runs = w.checks_api.list_check_runs(None, "volmarr", "pub")
        self.assertEqual(runs["total"], 1)
        actions = {r["action"] for r in w.conn.execute(
            "SELECT action FROM audit_log")}
        self.assertIn("repo.status.post", actions)
        self.assertIn("repo.check_run.post", actions)
        with self.assertRaises(StatusChecksAPIError):
            w.checks_api.post_status(
                w.stranger_h, "volmarr", "priv", OID,
                {"state": "passed", "context": "ci/build"})
        parsed = json.loads(w.checks_api.post_status_json(
            w.owner_h, "volmarr", "pub", OID,
            {"state": "failed", "context": "ci/test"}))
        self.assertEqual(parsed["state"], "failed")

    # -- S-247 webhook taxonomy ----------------------------------------
    def _repo_hook(self, **over):
        kwargs = dict(
            url="https://example.com/hook",
            events=("repo.issue.create",), secret="gate-secret-1")
        kwargs.update(over)
        return self.w.hooks.create_repository_subscription(
            self.w.owner, "volmarr", "pub", **kwargs)

    def test_webhook_taxonomy_audit_and_payload(self):
        audit = audit_webhook_events()
        self.assertEqual(audit.problems, (), audit)
        self.assertGreater(audit.deliverable, 0)
        verbs = all_verbs()
        self.assertIn("repo.issue.create", verbs)
        self.assertTrue(is_deliverable("repo.issue.create"))
        self.assertIn("repo.issue.create", deliverable_verbs())
        payload = webhook_payload(make_event())
        self.assertEqual(payload["event"], "repo.issue.create")
        self.assertEqual(payload["action"], "create")
        self.assertEqual(json.loads(json.dumps(payload)), payload)

    # -- S-248 subscriptions --------------------------------------------
    def test_subscriptions_secret_set_once_never_shown(self):
        sub = self._repo_hook()
        self.assertTrue(sub.active)
        self.assertTrue(sub.has_secret)
        self.assertEqual(sub.events, ("repo.issue.create",))
        self.assertNotIn("gate-secret-1", repr(sub))
        self.assertNotIn("gate-secret-1", sub.words)
        digest = secret_digest("gate-secret-1")
        self.assertTrue(secret_matches(digest, "gate-secret-1"))
        self.assertFalse(secret_matches(digest, "wrong-secret"))
        listed = self.w.hooks.list_repository_subscriptions(
            self.w.owner, "volmarr", "pub")
        self.assertEqual(len(listed), 1)
        org_sub = self.w.hooks.create_organization_subscription(
            self.w.owner, "Forge", "https://example.com/org-hook",
            events=("repo.issue.create",))
        self.assertEqual(org_sub.level, "organization")
        with self.assertRaises(Exception):
            self.w.hooks.create_repository_subscription(
                self.w.stranger, "volmarr", "pub",
                "https://example.com/hook",
                events=("repo.issue.create",))

    def test_subscription_matching_law(self):
        sub = self._repo_hook()
        self.assertTrue(decide_match(
            sub, "repo.issue.create", repo_id=sub.repo_id))
        self.assertFalse(decide_match(
            sub, "repo.push", repo_id=sub.repo_id))
        self.assertFalse(decide_match(
            sub, "repo.issue.create", repo_id=999999))
        quiet = self._repo_hook(url="https://example.com/quiet",
                                active=False)
        self.assertFalse(decide_match(
            quiet, "repo.issue.create", repo_id=quiet.repo_id))

    # -- S-249 signing ----------------------------------------------------
    def test_signing_roundtrip_and_tamper_refused(self):
        body = b'{"event":"repo.issue.create"}'
        header = signature_header(body, "gate-secret-1")
        self.assertTrue(header.startswith("sha256="))
        self.assertEqual(sign_payload(body, "gate-secret-1"),
                         header.split("=", 1)[1])
        self.assertTrue(verify_signature(body, header, "gate-secret-1"))
        self.assertFalse(verify_signature(
            body + b"x", header, "gate-secret-1"))
        self.assertFalse(verify_signature(body, header, "other-secret"))
        self.assertFalse(verify_signature(body, "sha256=zz", "gate-secret-1"))

    # -- S-250 delivery worker ---------------------------------------------
    def _delivery_store(self, transport):
        return WebhookDeliveryStore(
            self.w.conn, self.w.repos, self.w.orgs, self.w.accounts,
            transport=transport, time_fn=self.w.clock,
            jitter_fn=lambda delay: 0.0)

    def test_delivery_success_and_exactly_once_enqueue(self):
        self._repo_hook()
        transport = FakeTransport([200])
        store = self._delivery_store(transport)
        event = make_event()
        found = store.enqueue_event(event)
        self.assertEqual(len(found), 1)
        again = store.enqueue_event(event)
        self.assertEqual(len(again), 1)
        self.assertEqual(again[0].id, found[0].id)
        run = store.run_due(NOW)
        self.assertEqual(run.delivered, 1)
        done = store.deliveries_for_event(event.id)
        self.assertEqual(done[0].status, "delivered")
        self.assertEqual(len(transport.calls), 1)
        url, body, headers, _timeout = transport.calls[0]
        self.assertEqual(url, "https://example.com/hook")
        self.assertIn("X-Samverk-Signature-256", headers)

    def test_delivery_failure_backs_off_then_dead_letters(self):
        self._repo_hook()
        self.assertEqual(backoff_delay(1), 60)
        self.assertLess(backoff_delay(1), backoff_delay(2))
        transport = FakeTransport([500])
        store = self._delivery_store(transport)
        found = store.enqueue_event(make_event(event_id=9))
        run = store.run_due(NOW)
        self.assertEqual(run.delivered, 0)
        pending = store.deliveries_for_event(9)
        self.assertEqual(pending[0].id, found[0].id)
        self.assertNotEqual(pending[0].status, "delivered")
        self.assertEqual(pending[0].attempts, 1)

    # -- S-251 delivery log + redelivery -------------------------------------
    def test_delivery_log_inspection_and_redelivery(self):
        self._repo_hook()
        store = self._delivery_store(FakeTransport([200]))
        found = store.enqueue_event(make_event(event_id=11))
        store.run_due(NOW)
        log = DeliveryLogStore(self.w.conn, self.w.repos, self.w.orgs,
                               self.w.accounts, audit=self.w.audit,
                               time_fn=self.w.clock)
        entries = log.log_for_repository(self.w.owner, "volmarr", "pub")
        self.assertEqual(len(entries), 1)
        entry = log.get_log_entry(self.w.owner, found[0].id)
        self.assertEqual(entry.delivery.status, "delivered")
        self.assertTrue(entry.redeliverable)
        fresh = log.redeliver(self.w.owner, found[0].id)
        self.assertNotEqual(fresh.delivery.id, entry.delivery.id)
        self.assertEqual(fresh.redelivery_of, entry.delivery.id)
        with self.assertRaises(Exception):
            log.get_log_entry(self.w.stranger, found[0].id)

    # -- S-252 ping & test events ----------------------------------------------
    def test_ping_and_test_event_queue_deliveries(self):
        sub = self._repo_hook()
        pings = WebhookPingStore(self.w.conn, self.w.repos, self.w.orgs,
                                 self.w.accounts, audit=self.w.audit,
                                 time_fn=self.w.clock)
        ping = pings.send_repository_ping(
            self.w.owner, "volmarr", "pub", sub.id)
        self.assertTrue(ping.synthetic)
        listed = pings.pings_for_repository(
            self.w.owner, "volmarr", "pub")
        self.assertEqual(len(listed), 1)
        test_event = pings.send_repository_test_event(
            self.w.owner, "volmarr", "pub", sub.id, "repo.issue.create")
        self.assertTrue(test_event.is_test_event)
        store = self._delivery_store(FakeTransport())
        queued = store.deliveries_for_subscription(sub.id)
        self.assertEqual(len(queued), 2)


if __name__ == "__main__":
    unittest.main()
