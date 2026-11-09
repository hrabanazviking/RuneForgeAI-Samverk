"""S-240 acceptance battery: error shape.

Acceptance (roadmap S-240): Error shape -- one
problem format (type, title, status, detail,
error id) across all endpoints; the web UI's
refusals match it.

The centre is samverk/error_shape.py: the one
registry every refusal surface derives from.
This battery holds each surface to it -- the
four API faces' `error_to_dict` (S-238 auth,
S-239 pagination, S-231 events, S-216 search),
the server's S-019 body, and S-113's web error
states -- and proves the S-209 leakage law over
the new shape: a private repository's problem
is a missing repository's problem in every
field but the error id every refusal mints.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import http.client, json, sys, tempfile, threading, unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.api_auth import ApiAuthenticator, ApiAuthError
from samverk.api_auth import error_to_dict as auth_error_to_dict
from samverk.api_contract import (
    CURRENT_ERROR_FIELDS, PROBLEM_FIELDS, audit_api_contract)
from samverk.api_pagination import (
    ApiPaginationError, check_page_size)
from samverk.api_pagination import error_to_dict as page_error_to_dict
from samverk.audit import AuditLog
from samverk.config import Config
from samverk.db import schema_version
from samverk.errors import ERROR_CODES, PublicError, public_error_body
from samverk.error_shape import (
    ERROR_SHAPE_PATH, PROBLEM_TYPE_BASE, ErrorShapeError, Problem,
    canonical_public_words, decide_problem_status, is_registered_reason,
    make_problem, problem_for_public_code, problem_from_error,
    problem_title_for, problem_to_dict, problem_type_for,
    registered_reasons, render_error_shape_page, render_problem_page)
from samverk.events_api import EventsAPI, EventsAPIError
from samverk.events_api import error_to_dict as events_error_to_dict
from samverk.event_store import EventStore
from samverk.activity_feeds import ActivityFeedStore
from samverk.issues import IssueStore
from samverk.organizations import OrganizationStore
from samverk.page_states import error_state
from samverk.repositories import RepositoryStore
from samverk.search_api import SearchAPI, SearchAPIError
from samverk.search_api import error_to_dict as search_error_to_dict
from samverk.server import make_server

PW = "correct horse battery"

# Every reason each API face can raise, from the
# faces' own code: their own raises plus the
# reasons they carry verbatim from the stores
# behind them. S-240 registers every one.
FACE_REASONS = {
    "authentication_required", "credentials_invalid",
    "scheme_unsupported", "insufficient_scope",
    "resource_unknown", "role_invalid",
    "cursor_invalid", "page_size_invalid", "header_invalid",
    "ordering_invalid", "payload_not_json",
    "limit_invalid", "filter_invalid", "repo_not_found",
    "event_not_found", "no_such_user",
    "query_invalid", "auth_required", "recent_not_found",
    "rule_unknown", "rate_settings_invalid",
    "payload_invalid", "repo_taken", "repo_path_exists",
    "repo_invalid", "description_invalid", "visibility_invalid",
    "branch_invalid", "not_repo_owner", "git_init_failed",
    "git_head_failed", "git_clone_failed",
    "fork_visibility_escalation", "ref_not_found", "ref_invalid",
    "path_not_found", "path_invalid", "not_a_file",
    "already_pending", "sudo_required", "content_too_large",
    "object_not_found", "wrong_type",
}

EXPECTED_STATUS = {
    "bad_request": 400, "csrf_failed": 403, "internal": 500,
    "method_not_allowed": 405, "not_found": 404,
    "rate_limited": 429, "unauthorized": 401,
    "authentication_required": 401, "credentials_invalid": 401,
    "scheme_unsupported": 400, "insufficient_scope": 403,
    "resource_unknown": 404, "role_invalid": 400,
    "cursor_invalid": 400, "page_size_invalid": 400,
    "header_invalid": 400, "ordering_invalid": 500,
    "payload_not_json": 500, "limit_invalid": 400,
    "filter_invalid": 400, "repo_not_found": 404,
    "event_not_found": 404, "no_such_user": 404,
    "query_invalid": 400, "auth_required": 401,
    "recent_not_found": 404, "rule_unknown": 404,
    "rate_settings_invalid": 400,
    "payload_invalid": 400, "repo_taken": 409,
    "repo_path_exists": 409, "repo_invalid": 400,
    "description_invalid": 400, "visibility_invalid": 400,
    "branch_invalid": 400, "not_repo_owner": 403,
    "git_init_failed": 500, "git_head_failed": 500,
    "git_clone_failed": 500, "fork_visibility_escalation": 400,
    "ref_not_found": 404, "ref_invalid": 400,
    "path_not_found": 404, "path_invalid": 400,
    "not_a_file": 400, "already_pending": 409,
    "sudo_required": 403, "content_too_large": 413,
    "object_not_found": 404, "wrong_type": 400,
}


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
    stranger = accounts.register("mallory", PW)
    repos = RepositoryStore(conn, root, accounts, audit=audit)
    orgs = OrganizationStore(conn, accounts, audit=audit)
    issues = IssueStore(conn, repos, accounts, audit=audit)
    events = EventStore(conn, repos, accounts)
    feeds = ActivityFeedStore(conn, repos, accounts, events=events)
    repos.create_repository(owner.id, "volmarr", "pub",
                            visibility="public")
    repos.create_repository(owner.id, "volmarr", "priv",
                            visibility="private")
    issues.create_issue(owner, "volmarr", "priv", "Secret zorblax plans")
    return SimpleNamespace(
        conn=conn, clock=clock, audit=audit, accounts=accounts,
        owner=owner, stranger=stranger, repos=repos, orgs=orgs,
        issues=issues, events=events, feeds=feeds,
        events_api=EventsAPI(conn, repos, accounts,
                             events=events, feeds=feeds),
        search_api=SearchAPI(conn, repos, orgs),
        auth=ApiAuthenticator(conn, accounts, repos,
                              audit=audit, time_fn=clock))


class ErrorShapeTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.w = make_world(Path(self._td.name))
        self.addCleanup(self.w.conn.close)

    # -- pins ------------------------------------------------
    def test_pins_schema_taxonomy_and_fields(self):
        self.assertEqual(schema_version(self.w.conn), 94)
        self.assertEqual(db.MIGRATIONS[-1][0], 94)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 129)
        families = {}
        for event in taxonomy.AUDIT_EVENTS:
            families[event.split(".")[0]] = (
                families.get(event.split(".")[0], 0) + 1)
        self.assertEqual(families, {"auth": 33, "repo": 83, "admin": 13})
        self.assertEqual(
            PROBLEM_FIELDS,
            ("type", "title", "status", "detail", "error_id"))
        self.assertEqual(CURRENT_ERROR_FIELDS, PROBLEM_FIELDS)
        self.assertEqual(ERROR_SHAPE_PATH, "/api/error-shape")

    def test_contract_audit_ratified_on_the_new_shape(self):
        audit = audit_api_contract()
        self.assertTrue(audit.ratified, audit)
        self.assertTrue(audit.error_shape_ok)

    # -- the format itself -----------------------------------
    def test_problem_dict_is_exactly_the_five_fields_in_order(self):
        problem = make_problem("repo_not_found", "No such repository.")
        rendered = problem_to_dict(problem)
        self.assertEqual(tuple(rendered.keys()), PROBLEM_FIELDS)
        self.assertEqual(rendered["type"], "/api/v1/problems/repo_not_found")
        self.assertEqual(rendered["title"], "No such repository")
        self.assertEqual(rendered["status"], 404)
        self.assertEqual(rendered["detail"], "No such repository.")
        self.assertEqual(json.loads(json.dumps(rendered)), rendered)

    def test_type_is_the_reasons_stable_address(self):
        for reason in registered_reasons():
            self.assertEqual(
                problem_type_for(reason), PROBLEM_TYPE_BASE + reason)

    def test_error_ids_are_opaque_unique_and_fresh(self):
        ids = {make_problem("not_found").error_id for _ in range(200)}
        self.assertEqual(len(ids), 200)
        for error_id in ids:
            self.assertEqual(len(error_id), 16)
            int(error_id, 16)  # hex, encoding nothing else
        held = make_problem("not_found", error_id="0123456789abcdef")
        self.assertEqual(held.error_id, "0123456789abcdef")

    def test_every_face_reason_is_registered(self):
        self.assertTrue(FACE_REASONS <= set(registered_reasons()))
        for reason in FACE_REASONS:
            self.assertTrue(is_registered_reason(reason), reason)

    def test_status_mapping_is_the_registry_table(self):
        self.assertEqual(
            set(EXPECTED_STATUS), set(registered_reasons()))
        for reason, status in EXPECTED_STATUS.items():
            self.assertEqual(decide_problem_status(reason), status, reason)
            self.assertEqual(make_problem(reason).status, status, reason)
            self.assertTrue(problem_title_for(reason), reason)

    def test_unregistered_reasons_fall_back_by_suffix_law(self):
        self.assertEqual(decide_problem_status("widget_not_found"), 404)
        self.assertEqual(decide_problem_status("widget_invalid"), 400)
        self.assertEqual(decide_problem_status("permission_denied"), 403)
        self.assertEqual(decide_problem_status("not_repo_owner"), 403)
        self.assertEqual(decide_problem_status("widget_taken"), 409)
        self.assertEqual(decide_problem_status("already_member"), 409)
        self.assertEqual(decide_problem_status("widget_exploded"), 400)
        problem = make_problem("widget_not_found", "No such widget.")
        self.assertEqual(problem.status, 404)
        self.assertEqual(problem.title, "That could not be found")
        self.assertFalse(is_registered_reason("widget_not_found"))

    def test_unshapeable_reasons_raise(self):
        for bad in ("", "Repo Not Found", "repo not found", None, 404):
            with self.assertRaises(ErrorShapeError):
                make_problem(bad)

    def test_explicit_status_wins_over_the_registry(self):
        problem = make_problem("not_found", status=404)
        self.assertEqual(problem.status, 404)
        moved = problem_from_error(PublicError("unauthorized", 401))
        self.assertEqual(moved.status, 401)
        self.assertEqual(moved.title, "Sign-in needed")
        self.assertEqual(
            moved.detail, canonical_public_words("unauthorized")[2])

    # -- the four faces emit it -------------------------------
    def test_auth_face_refusals_are_problems(self):
        with self.assertRaises(ApiAuthError) as ctx:
            self.w.auth.authenticate(None)
        rendered = auth_error_to_dict(ctx.exception)
        self.assertEqual(tuple(rendered.keys()), PROBLEM_FIELDS)
        self.assertEqual(
            rendered["type"], "/api/v1/problems/authentication_required")
        self.assertEqual(rendered["status"], 401)
        self.assertEqual(rendered["title"], "Sign-in needed")
        self.assertTrue(rendered["detail"])

    def test_pagination_face_refusals_are_problems(self):
        rendered = page_error_to_dict(
            ApiPaginationError("cursor_invalid", "nope"))
        self.assertEqual(tuple(rendered.keys()), PROBLEM_FIELDS)
        self.assertEqual(rendered["status"], 400)
        with self.assertRaises(ApiPaginationError) as ctx:
            check_page_size(0)
        rendered = page_error_to_dict(ctx.exception)
        self.assertEqual(
            rendered["type"], "/api/v1/problems/page_size_invalid")

    def test_events_face_refusals_are_problems(self):
        with self.assertRaises(EventsAPIError) as ctx:
            self.w.events_api.user_events(self.w.owner, "ghost")
        rendered = events_error_to_dict(ctx.exception)
        self.assertEqual(tuple(rendered.keys()), PROBLEM_FIELDS)
        self.assertEqual(rendered["type"], "/api/v1/problems/no_such_user")
        self.assertEqual(rendered["status"], 404)

    def test_search_face_refusals_are_problems(self):
        with self.assertRaises(SearchAPIError) as ctx:
            self.w.search_api.search(self.w.stranger, "type:code")
        rendered = search_error_to_dict(ctx.exception)
        self.assertEqual(tuple(rendered.keys()), PROBLEM_FIELDS)
        self.assertEqual(rendered["type"], "/api/v1/problems/query_invalid")
        self.assertEqual(rendered["status"], 400)

    def test_same_reason_same_problem_on_every_face(self):
        """repo_not_found raised through three faces
        is one problem in type, title, status and
        detail -- only the error id differs."""
        problems = []
        with self.assertRaises(ApiAuthError) as ctx:
            self.w.auth.authorize(None, "volmarr", "priv")
        problems.append(auth_error_to_dict(ctx.exception))
        with self.assertRaises(EventsAPIError) as ctx:
            self.w.events_api.repo_events(
                self.w.stranger, "volmarr", "priv")
        problems.append(events_error_to_dict(ctx.exception))
        for rendered in problems:
            self.assertEqual(
                rendered["type"], "/api/v1/problems/repo_not_found")
            self.assertEqual(rendered["title"], "No such repository")
            self.assertEqual(rendered["status"], 404)
            self.assertEqual(rendered["detail"], "No such repository.")
        self.assertNotEqual(
            problems[0]["error_id"], problems[1]["error_id"])

    # -- leakage (S-209 law over the new shape) ---------------
    def test_private_and_missing_repos_are_one_problem(self):
        def problem_for(owner, repo):
            with self.assertRaises(EventsAPIError) as ctx:
                self.w.events_api.repo_events(self.w.stranger, owner, repo)
            return events_error_to_dict(ctx.exception)
        private = problem_for("volmarr", "priv")
        missing = problem_for("volmarr", "nevermade")
        for field in ("type", "title", "status", "detail"):
            self.assertEqual(private[field], missing[field], field)
        blob = json.dumps(private)
        for leaked in ("zorblax", "Secret", "priv"):
            self.assertNotIn(leaked, blob)

    def test_problems_carry_no_internals(self):
        rendered = problem_to_dict(problem_from_error(
            ApiPaginationError("cursor_invalid", "That cursor failed.")))
        blob = json.dumps(rendered)
        for leaked in ("Traceback", "/home/", "samverk/", ".py"):
            self.assertNotIn(leaked, blob)

    # -- success is unchanged ----------------------------------
    def test_successful_responses_are_unchanged(self):
        feed = self.w.events_api.public_events(self.w.stranger)
        self.assertEqual(
            tuple(feed.keys()),
            ("kind", "subject", "scope", "total", "returned",
             "complete", "limit", "events"))
        empty = self.w.search_api.search(self.w.stranger, "")
        self.assertEqual(empty, {"query": "", "groups": []})
        found = self.w.events_api.repo_events(
            self.w.owner, "volmarr", "pub")
        self.assertNotIn("error_id", found)

    def test_shaping_a_refusal_writes_and_audits_nothing(self):
        before = self.w.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
        for reason in registered_reasons():
            problem_to_dict(make_problem(reason, "detail"))
        after = self.w.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
        self.assertEqual(before, after)

    # -- the web UI matches -------------------------------------
    def test_server_body_is_the_problem_format(self):
        for code in sorted(ERROR_CODES):
            status, title, detail = canonical_public_words(code)
            body = public_error_body(code)
            self.assertEqual(tuple(body.keys()), PROBLEM_FIELDS, code)
            self.assertEqual(body["type"], PROBLEM_TYPE_BASE + code, code)
            self.assertEqual(body["title"], title, code)
            self.assertEqual(body["status"], status, code)
            self.assertEqual(body["detail"], detail, code)
            self.assertEqual(len(body["error_id"]), 16, code)

    def test_web_error_states_speak_the_canonical_words(self):
        for code in sorted(ERROR_CODES):
            _status, title, detail = canonical_public_words(code)
            state = error_state(code)
            self.assertEqual(state.title, title, code)
            self.assertEqual(state.message, detail, code)

    def test_problem_page_matches_the_wire(self):
        problem = problem_for_public_code(
            "not_found", 404, error_id="0123456789abcdef")
        page = render_problem_page(problem)
        self.assertIn("That page could not be found", page)
        self.assertIn("Status: 404", page)
        self.assertIn(problem.detail, page)
        self.assertIn("0123456789abcdef", page)
        self.assertIn("/api/v1/problems/not_found", page)
        self.assertNotIn("<script", page)

    def test_problem_page_escapes_its_detail(self):
        problem = make_problem(
            "query_invalid", "<script>alert(1)</script>")
        page = render_problem_page(problem)
        self.assertNotIn("<script>alert", page)
        self.assertIn("&lt;script&gt;", page)

    def test_help_page_states_the_format_and_registry(self):
        page = render_error_shape_page()
        for field in PROBLEM_FIELDS:
            self.assertIn(field, page)
        self.assertIn("/api/v1/problems/repo_not_found", page)
        self.assertIn("No such repository", page)

    # -- the live server speaks it --------------------------------
    def _serve(self) -> int:
        httpd = make_server(Config(
            host="127.0.0.1", port=0, data_root=Path(self._td.name)))
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        return httpd.server_address[1]

    def _request(self, port, method, path):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request(method, path)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        return resp.status, json.loads(raw) if raw else {}

    def test_live_404_and_403_are_problems(self):
        port = self._serve()
        status, body = self._request(port, "GET", "/missing")
        self.assertEqual(status, 404)
        self.assertEqual(tuple(body.keys()), PROBLEM_FIELDS)
        self.assertEqual(body["type"], "/api/v1/problems/not_found")
        self.assertEqual(body["title"], "That page could not be found")
        self.assertEqual(body["status"], 404)
        status, body = self._request(port, "POST", "/healthz")
        self.assertEqual(status, 403)
        self.assertEqual(body["type"], "/api/v1/problems/csrf_failed")
        self.assertEqual(body["status"], 403)

    def test_live_success_is_not_a_problem(self):
        port = self._serve()
        status, body = self._request(port, "GET", "/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        self.assertNotIn("error_id", body)


if __name__ == "__main__":
    unittest.main()
