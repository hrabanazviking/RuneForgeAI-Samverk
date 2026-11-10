"""S-246 acceptance battery: status and checks API.

Acceptance (roadmap S-246): Status and checks API --
external CI posts commit statuses and check runs
(consumed by S-157); identity of the poster is
scoped and audit-logged.

The centre is samverk/api_checks.py: statuses post
through S-157's own record (so the checks panel and
the S-174 gate read what CI posted, with no second
store to drift), check runs keep their own
vocabulary in `check_runs` and fold onto that same
record under their name, every call resolves
through S-238's door and is judged by S-190 with
the token scope as a ceiling, and every successful
post is witnessed in the audit log with its
poster's scoped identity.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import base64, json, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.access_tokens import AccessTokenStore
from samverk.accounts import AccountStore
from samverk.api_checks import (
    CHECK_RUNS_API_PATH, CHECK_RUN_CONCLUSIONS,
    CHECK_RUN_STATUSES, STATUS_API_PATH, StatusChecksAPI,
    StatusChecksAPIError, check_run_to_dict,
    decide_check_run_panel_state, decide_check_run_payload,
    decide_status_payload, error_to_dict,
    render_api_checks_page, status_to_dict)
from samverk.api_contract import (
    PROBLEM_FIELDS, audit_api_contract, get_resource)
from samverk.audit import AuditLog, verify_chain
from samverk.db import schema_version
from samverk.error_shape import is_registered_reason
from samverk.fine_grained_tokens import FineTokenStore
from samverk.issues import IssueStore
from samverk.pull_request_checks import (
    PullRequestChecksStore, render_pull_request_checks)
from samverk.pull_requests import PullRequestStore
from samverk.repositories import RepositoryStore
from test_pull_request_checks import git, make_commit

PW = "correct horse battery"
OID = "a" * 40
OID2 = "b" * 40


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now

    def __call__(self):
        return self.now


def basic(username, credential):
    raw = base64.b64encode(
        f"{username}:{credential}".encode("utf-8"))
    return "Basic " + raw.decode("ascii")


def make_world(root: Path) -> SimpleNamespace:
    conn = db.init_db(root / "samverk.db")
    clock = Clock()
    audit = AuditLog(conn, time_fn=clock)
    accounts = AccountStore(conn, audit=audit, time_fn=clock)
    owner = accounts.register("volmarr", PW)
    reader = accounts.register("yrsa", PW)
    stranger = accounts.register("mallory", PW)
    repos = RepositoryStore(conn, root, accounts, audit=audit)
    issues = IssueStore(conn, repos, accounts, audit=audit,
                        time_fn=clock)
    repos.create_repository(owner.id, "volmarr", "pub",
                            visibility="public")
    repos.create_repository(owner.id, "volmarr", "priv",
                            visibility="private")
    classic = AccessTokenStore(conn, accounts, audit=audit,
                               time_fn=clock)
    fine = FineTokenStore(conn, accounts, audit=audit,
                          time_fn=clock)
    expiry = clock.now + 3600
    _, owner_read = classic.create_token(
        owner.id, "read token", {"repo:read"}, expiry)
    _, owner_write = classic.create_token(
        owner.id, "write token", {"repo:write"}, expiry)
    _, fine_pub = fine.create_token(
        owner.id, "volmarr", "pub", "fine pub",
        {"contents:write", "metadata:read"}, expiry)
    _, fine_priv = fine.create_token(
        owner.id, "volmarr", "priv", "fine priv",
        {"contents:write", "metadata:read"}, expiry)
    api = StatusChecksAPI(conn, accounts, repos, issues,
                          audit=audit, time_fn=clock)
    checks = PullRequestChecksStore(conn, repos, accounts,
                                    issues, time_fn=clock)
    prs = PullRequestStore(conn, repos, accounts, issues,
                           audit=audit, time_fn=clock)
    return SimpleNamespace(
        conn=conn, clock=clock, audit=audit, accounts=accounts,
        owner=owner, reader=reader, stranger=stranger,
        repos=repos, issues=issues, classic=classic, fine=fine,
        owner_read=owner_read, owner_write=owner_write,
        fine_pub=fine_pub, fine_priv=fine_priv, api=api,
        checks=checks, prs=prs)


class ApiChecksTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.w = make_world(Path(self._td.name))
        self.addCleanup(self.w.conn.close)
        self.owner_basic = basic("volmarr", PW)

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(StatusChecksAPIError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    def _audit_actions(self):
        rows = self.w.conn.execute(
            "SELECT action, actor_id, target_id, detail"
            " FROM audit_log ORDER BY seq").fetchall()
        return [(r["action"], r["actor_id"], r["target_id"],
                 json.loads(r["detail"]) if r["detail"] else {})
                for r in rows]

    def _status(self, **over):
        payload = {"state": "passed", "context": "ci/build",
                   "description": "build ok",
                   "target_url": "https://ci.example/run/1"}
        payload.update(over)
        return payload

    # -- pins ------------------------------------------------

    def test_pins_schema_99_taxonomy_131(self):
        self.assertEqual(schema_version(self.w.conn), 100)
        self.assertEqual(db.MIGRATIONS[-1][0], 100)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 131)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 85)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        self.assertIn("repo.status.post", taxonomy.AUDIT_EVENTS)
        self.assertIn("repo.check_run.post", taxonomy.AUDIT_EVENTS)

    def test_contract_marks_both_resources_landed(self):
        statuses = get_resource("statuses")
        self.assertEqual(statuses.standing, "landed")
        self.assertEqual(statuses.slice, "S-246")
        self.assertEqual(statuses.path,
                         "/api/v1/repos/{owner}/{repo}/statuses/{oid}")
        self.assertEqual(
            statuses.fields,
            ("id", "oid", "state", "context", "description",
             "target_url", "poster", "created_at"))
        runs = get_resource("check-runs")
        self.assertEqual(runs.standing, "landed")
        self.assertEqual(runs.slice, "S-246")
        self.assertEqual(
            runs.fields,
            ("id", "oid", "name", "status", "conclusion",
             "poster", "created_at", "updated_at"))
        self.assertEqual(STATUS_API_PATH, statuses.path)
        self.assertEqual(CHECK_RUNS_API_PATH, runs.path)
        audit = audit_api_contract()
        self.assertTrue(audit.ratified, audit)
        self.assertEqual(audit.landed_shapes_checked, 20)

    def test_serialiser_shapes_are_the_contracted_ones(self):
        record = self.w.api.post_status(
            self.owner_basic, "volmarr", "pub", OID, self._status())
        self.assertEqual(tuple(record), get_resource("statuses").fields)
        run = self.w.api.post_check_run(
            self.owner_basic, "volmarr", "pub",
            {"oid": OID, "name": "ci/test", "status": "queued"})
        self.assertEqual(tuple(run), get_resource("check-runs").fields)

    def test_new_reasons_are_registered(self):
        for reason in ("check_name_invalid", "check_status_invalid",
                       "check_conclusion_invalid",
                       "check_state_invalid", "check_context_invalid",
                       "check_head_invalid", "check_url_invalid"):
            self.assertTrue(is_registered_reason(reason), reason)

    # -- pure judgements --------------------------------------

    def test_panel_state_fold_is_pure_and_total(self):
        self.assertEqual(
            decide_check_run_panel_state("queued", ""), "pending")
        self.assertEqual(
            decide_check_run_panel_state("in_progress", ""), "pending")
        for conclusion in CHECK_RUN_CONCLUSIONS:
            state = decide_check_run_panel_state(
                "completed", conclusion)
            self.assertIn(state, ("passed", "failed"))
        self.assertEqual(
            decide_check_run_panel_state("completed", "success"),
            "passed")
        self.assertEqual(
            decide_check_run_panel_state("completed", "failure"),
            "failed")
        self.assertEqual(CHECK_RUN_STATUSES,
                         ("queued", "in_progress", "completed"))

    def test_payload_judgements_are_pure(self):
        self.assertEqual(
            decide_status_payload({"context": "x"})["state"],
            "pending")
        with self.assertRaises(StatusChecksAPIError):
            decide_status_payload({"context": "x", "bogus": 1})
        with self.assertRaises(StatusChecksAPIError):
            decide_status_payload("not-a-dict")
        run = decide_check_run_payload(
            {"oid": OID, "name": "n", "status": "completed",
             "conclusion": "neutral"})
        self.assertEqual(run["panel_state"], "passed")
        with self.assertRaises(StatusChecksAPIError):
            decide_check_run_payload(
                {"oid": OID, "name": "n", "status": "completed"})

    # -- posting statuses -------------------------------------

    def test_post_status_lands_on_the_s157_record(self):
        before = len(self._audit_actions())
        record = self.w.api.post_status(
            self.owner_basic, "volmarr", "pub", OID, self._status())
        self.assertEqual(record["poster"], "volmarr")
        self.assertEqual(record["state"], "passed")
        rows = self.w.checks.checks_for_commit("volmarr", "pub", OID)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].context, "ci/build")
        self.assertEqual(rows[0].state, "passed")
        self.assertEqual(rows[0].target_url, "https://ci.example/run/1")
        actions = self._audit_actions()[before:]
        self.assertEqual(len(actions), 1)
        action, actor, target, detail = actions[0]
        self.assertEqual(action, "repo.status.post")
        self.assertEqual(actor, self.w.owner.id)
        self.assertEqual(target, "volmarr/pub")
        self.assertEqual(detail["poster"], "volmarr")
        self.assertEqual(detail["credential"], "password")
        self.assertEqual(detail["context"], "ci/build")
        ok, bad, _ = verify_chain(self.w.conn)
        self.assertTrue(ok, bad)

    def test_repost_updates_the_row_and_audits_again(self):
        first = self.w.api.post_status(
            self.owner_basic, "volmarr", "pub", OID,
            self._status(state="pending", description="running"))
        self.w.clock.now += 60
        second = self.w.api.post_status(
            self.owner_basic, "volmarr", "pub", OID, self._status())
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["created_at"], second["created_at"])
        rows = self.w.checks.checks_for_commit("volmarr", "pub", OID)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].state, "passed")
        posts = [a for a in self._audit_actions()
                 if a[0] == "repo.status.post"]
        self.assertEqual(len(posts), 2)

    def test_posted_status_is_consumed_by_the_s157_panel(self):
        path = self.w.repos.path_for("volmarr", "pub")
        base = make_commit(path, None, {"a.txt": "alpha\n"}, "base")
        git(path, "update-ref", "refs/heads/main", base)
        head = make_commit(path, base, {"a.txt": "alpha\nbeta\n"},
                           "feature work")
        git(path, "update-ref", "refs/heads/feature", head)
        pr = self.w.prs.create_pull_request(
            self.w.owner, "volmarr", "pub",
            base_branch="main", head_branch="feature")
        self.w.api.post_status(
            self.owner_basic, "volmarr", "pub", head, self._status())
        rows = self.w.checks.checks_for(self.w.owner, "volmarr",
                                        "pub", pr.number)
        self.assertEqual([r.context for r in rows], ["ci/build"])
        page = render_pull_request_checks(rows)
        self.assertIn("ci/build", page)
        self.assertIn("Passed", page)

    def test_status_validation_is_s157s_own_law(self):
        self.assertEqual(
            self._reason(self.w.api.post_status, self.owner_basic,
                         "volmarr", "pub", OID,
                         self._status(state="success")),
            "check_state_invalid")
        self.assertEqual(
            self._reason(self.w.api.post_status, self.owner_basic,
                         "volmarr", "pub", OID,
                         self._status(context="  ")),
            "check_context_invalid")
        self.assertEqual(
            self._reason(self.w.api.post_status, self.owner_basic,
                         "volmarr", "pub", " ",
                         self._status()),
            "check_head_invalid")
        self.assertEqual(
            self._reason(self.w.api.post_status, self.owner_basic,
                         "volmarr", "pub", OID,
                         self._status(
                             target_url="javascript:alert(1)")),
            "check_url_invalid")
        self.assertEqual(
            self.w.checks.checks_for_commit("volmarr", "pub", OID), [])
        self.assertEqual(
            [a for a in self._audit_actions()
             if a[0] == "repo.status.post"], [])

    def test_unknown_payload_key_is_refused_whole(self):
        self.assertEqual(
            self._reason(self.w.api.post_status, self.owner_basic,
                         "volmarr", "pub", OID,
                         self._status(admin=True)),
            "payload_invalid")
        self.assertEqual(
            self._reason(self.w.api.post_check_run, self.owner_basic,
                         "volmarr", "pub",
                         {"oid": OID, "name": "n", "force": True}),
            "payload_invalid")

    # -- the scoped poster ------------------------------------

    def test_anonymous_may_read_public_but_never_post(self):
        self.w.api.post_status(
            self.owner_basic, "volmarr", "pub", OID, self._status())
        listed = self.w.api.list_statuses(
            None, "volmarr", "pub", OID)
        self.assertEqual(listed["total"], 1)
        self.assertEqual(
            self._reason(self.w.api.post_status, None,
                         "volmarr", "pub", OID, self._status()),
            "authentication_required")
        self.assertEqual(
            self._reason(self.w.api.post_status, "Bearer svk_nope",
                         "volmarr", "pub", OID, self._status()),
            "credentials_invalid")

    def test_stranger_cannot_post_to_a_public_repo(self):
        self.assertEqual(
            self._reason(self.w.api.post_status,
                         basic("mallory", PW),
                         "volmarr", "pub", OID, self._status()),
            "repo_not_found")

    def test_private_repo_is_invisible_to_a_stranger(self):
        missing = self._reason(
            self.w.api.list_statuses, basic("mallory", PW),
            "volmarr", "ghost", OID)
        hidden = self._reason(
            self.w.api.list_statuses, basic("mallory", PW),
            "volmarr", "priv", OID)
        self.assertEqual(missing, "repo_not_found")
        self.assertEqual(hidden, "repo_not_found")
        posted = self.w.api.post_status(
            self.owner_basic, "volmarr", "priv", OID, self._status())
        self.assertEqual(posted["context"], "ci/build")

    def test_read_only_token_cannot_post(self):
        self.assertEqual(
            self._reason(self.w.api.post_status,
                         f"Bearer {self.w.owner_read}",
                         "volmarr", "pub", OID, self._status()),
            "insufficient_scope")
        listed = self.w.api.list_statuses(
            f"Bearer {self.w.owner_read}", "volmarr", "pub", OID)
        self.assertEqual(listed["total"], 0)

    def test_write_token_posts_and_is_the_logged_poster(self):
        record = self.w.api.post_status(
            f"Bearer {self.w.owner_write}",
            "volmarr", "pub", OID, self._status())
        self.assertEqual(record["poster"], "volmarr")
        posts = [a for a in self._audit_actions()
                 if a[0] == "repo.status.post"]
        self.assertEqual(posts[-1][3]["credential"], "classic_token")
        self.assertIsNotNone(posts[-1][3]["token_id"])

    def test_fine_token_is_bound_to_its_repository(self):
        record = self.w.api.post_status(
            f"Bearer {self.w.fine_pub}",
            "volmarr", "pub", OID, self._status())
        self.assertEqual(record["poster"], "volmarr")
        self.assertEqual(
            self._reason(self.w.api.post_status,
                         f"Bearer {self.w.fine_priv}",
                         "volmarr", "pub", OID, self._status()),
            "insufficient_scope")
        posted = self.w.api.post_status(
            f"Bearer {self.w.fine_priv}",
            "volmarr", "priv", OID, self._status())
        self.assertEqual(posted["context"], "ci/build")

    # -- check runs -------------------------------------------

    def test_check_run_lifecycle_folds_onto_the_panel(self):
        run = self.w.api.post_check_run(
            self.owner_basic, "volmarr", "pub",
            {"oid": OID, "name": "ci/test", "status": "queued"})
        self.assertEqual(run["conclusion"], "")
        self.assertEqual(run["poster"], "volmarr")
        rows = self.w.checks.checks_for_commit("volmarr", "pub", OID)
        self.assertEqual([(r.context, r.state) for r in rows],
                         [("ci/test", "pending")])
        self.w.clock.now += 30
        done = self.w.api.post_check_run(
            self.owner_basic, "volmarr", "pub",
            {"oid": OID, "name": "ci/test", "status": "completed",
             "conclusion": "failure",
             "target_url": "https://ci.example/run/9"})
        self.assertEqual(done["id"], run["id"])
        self.assertEqual(done["created_at"], run["created_at"])
        self.assertGreater(done["updated_at"], run["updated_at"])
        rows = self.w.checks.checks_for_commit("volmarr", "pub", OID)
        self.assertEqual([(r.context, r.state) for r in rows],
                         [("ci/test", "failed")])
        posts = [a for a in self._audit_actions()
                 if a[0] == "repo.check_run.post"]
        self.assertEqual(len(posts), 2)
        self.assertEqual(posts[-1][3]["conclusion"], "failure")

    def test_check_run_vocabulary_is_refused_whole(self):
        base = {"oid": OID, "name": "ci/test"}
        self.assertEqual(
            self._reason(self.w.api.post_check_run, self.owner_basic,
                         "volmarr", "pub",
                         {**base, "status": "running"}),
            "check_status_invalid")
        self.assertEqual(
            self._reason(self.w.api.post_check_run, self.owner_basic,
                         "volmarr", "pub",
                         {**base, "status": "completed"}),
            "check_conclusion_invalid")
        self.assertEqual(
            self._reason(self.w.api.post_check_run, self.owner_basic,
                         "volmarr", "pub",
                         {**base, "status": "completed",
                          "conclusion": "great"}),
            "check_conclusion_invalid")
        self.assertEqual(
            self._reason(self.w.api.post_check_run, self.owner_basic,
                         "volmarr", "pub",
                         {**base, "status": "queued",
                          "conclusion": "success"}),
            "check_conclusion_invalid")
        self.assertEqual(
            self._reason(self.w.api.post_check_run, self.owner_basic,
                         "volmarr", "pub",
                         {"oid": OID, "name": " ", "status": "queued"}),
            "check_name_invalid")
        self.assertEqual(
            self._reason(self.w.api.post_check_run, self.owner_basic,
                         "volmarr", "pub",
                         {"oid": " ", "name": "n", "status": "queued"}),
            "check_head_invalid")
        listed = self.w.api.list_check_runs(
            self.owner_basic, "volmarr", "pub")
        self.assertEqual(listed["total"], 0)

    def test_check_runs_list_and_filter_by_commit(self):
        self.w.api.post_check_run(
            self.owner_basic, "volmarr", "pub",
            {"oid": OID, "name": "a", "status": "queued"})
        self.w.api.post_check_run(
            self.owner_basic, "volmarr", "pub",
            {"oid": OID2, "name": "b", "status": "completed",
             "conclusion": "success"})
        all_runs = self.w.api.list_check_runs(
            self.owner_basic, "volmarr", "pub")
        self.assertEqual(all_runs["total"], 2)
        one = self.w.api.list_check_runs(
            self.owner_basic, "volmarr", "pub", OID)
        self.assertEqual([r["name"] for r in one["check_runs"]], ["a"])
        self.assertEqual(
            self._reason(self.w.api.list_check_runs,
                         basic("mallory", PW), "volmarr", "priv"),
            "repo_not_found")

    def test_distinct_commits_and_contexts_stay_distinct(self):
        self.w.api.post_status(
            self.owner_basic, "volmarr", "pub", OID, self._status())
        self.w.api.post_status(
            self.owner_basic, "volmarr", "pub", OID2, self._status())
        self.w.api.post_status(
            self.owner_basic, "volmarr", "pub", OID,
            self._status(context="ci/lint"))
        listed = self.w.api.list_statuses(
            self.owner_basic, "volmarr", "pub", OID)
        self.assertEqual(
            [s["context"] for s in listed["statuses"]],
            ["ci/build", "ci/lint"])
        self.assertEqual(listed["statuses"][0]["oid"], OID)

    # -- refusals as problems ---------------------------------

    def test_refusals_render_in_the_one_problem_format(self):
        try:
            self.w.api.post_status(
                None, "volmarr", "pub", OID, self._status())
            self.fail("anonymous post must refuse")
        except StatusChecksAPIError as exc:
            problem = error_to_dict(exc)
            detail = str(exc)
        self.assertEqual(tuple(problem), PROBLEM_FIELDS)
        self.assertEqual(problem["status"], 401)
        self.assertEqual(
            problem["type"],
            "/api/v1/problems/authentication_required")
        self.assertEqual(problem["detail"], detail)

    def test_page_says_the_law_in_words(self):
        page = render_api_checks_page()
        self.assertIn("Status and checks API", page)
        self.assertIn("audit-logged", page)
        self.assertIn("S-157", page)


if __name__ == "__main__":
    unittest.main()
