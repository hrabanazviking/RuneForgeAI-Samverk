"""S-245 acceptance battery: search API, public contract.

Acceptance (roadmap S-245): Search API -- S-216
lands as a public contract here.

The centre is samverk/api_search.py: S-216's
search face ratified under /api/v1/search --
every call resolved through S-238's door, the
whole search delegated to S-216's own face over
S-213's engine, and one group at a time crawled
by S-239's cursor engine over the five banked
group executors, each judged through S-190 and
permission-filtered per S-209, with refusals in
S-240's one problem format.

The planted secret is S-216's own bait, reused:
a private repository (`vault`) whose
description, only commit, only code file, and
only issue all carry the unique word `zorblax`,
so any leak channel -- a group paged without
its S-209 filtering, a cursor replayed across
viewers, a count tallied past the permission
boundary -- moves a string or a number this
battery watches.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import base64, json, sys, tempfile, time, unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.access_tokens import AccessTokenStore
from samverk.api_contract import (
    PROBLEM_FIELDS, SEARCH_PAGE_FIELDS, SEARCH_RESULT_FIELDS,
    audit_api_contract, get_resource)
from samverk.api_search import (
    GROUP_LIMIT, SEARCH_API_PATH, PublicSearchAPI,
    PublicSearchAPIError, error_to_dict, group_page_to_dict,
    render_search_api_page, to_json)
from samverk.db import schema_version
from samverk.error_shape import registered_reasons
from samverk.global_search import GROUP_ORDER
from samverk.index_architecture import SearchIndexStore
from samverk.issue_pr_search import IssuePRSearch
from test_search_api import PW, make_world

ISSUE_COUNT = 25


def basic(username, credential):
    raw = base64.b64encode(f"{username}:{credential}".encode("utf-8"))
    return "Basic " + raw.decode("ascii")


def make_api(w):
    return PublicSearchAPI(w.conn, w.accounts, w.repos, w.orgs)


def add_many_issues(w):
    """Twenty-five public issues carrying the word
    forge, indexed through S-206's own backend --
    a group large enough to crawl in pages."""
    w.repos.create_repository(
        w.owner.id, "volmarr", "many", visibility="public",
        description="A hall of many small jobs")
    for number in range(1, ISSUE_COUNT + 1):
        w.issues.create_issue(
            w.owner, "volmarr", "many",
            f"Forge item {number:02d}", "small forge work")
    backend = IssuePRSearch(
        w.conn, w.repos, SearchIndexStore(w.conn, w.repos))
    backend.index_all()


def crawl(api, header, query, group, *, per_page=7):
    """Every page of one group, following only the
    payload's own next cursors."""
    pages = []
    cursor = None
    while True:
        page = api.search_group_page(
            header, query, group, per_page=per_page, cursor=cursor)
        pages.append(page)
        if page["next_cursor"] is None:
            return pages
        cursor = page["next_cursor"]


class ApiSearchTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.w = make_world(self.root, with_secret=True)
        self.addCleanup(self.w.conn.close)
        self.api = make_api(self.w)
        self.owner_basic = basic("volmarr", PW)

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(PublicSearchAPIError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    def _group(self, payload, kind):
        for group in payload["groups"]:
            if group["type"] == kind:
                return group
        self.fail(f"no {kind} group in payload")

    # -- pins ------------------------------------------------
    def test_pins_schema_99_taxonomy_133(self):
        self.assertEqual(schema_version(self.w.conn), 119)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 134)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 88)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)

    def test_contract_ratifies_search_under_s245(self):
        resource = get_resource("search")
        self.assertEqual(resource.standing, "landed")
        self.assertEqual(resource.slice, "S-245")
        self.assertEqual(resource.fields, SEARCH_RESULT_FIELDS)
        audit = audit_api_contract()
        self.assertTrue(audit.ratified, audit)
        self.assertEqual(audit.landed_shapes_checked, 20)

    def test_path_and_group_limit_are_the_stated_ones(self):
        self.assertEqual(SEARCH_API_PATH, "/api/search")
        self.assertEqual(GROUP_LIMIT, 500)

    def test_page_shape_is_the_contracted_one(self):
        page = SimpleNamespace(
            returned=2, complete=True, total=2, per_page=30,
            has_next=False, has_previous=False,
            next_cursor=None, previous_cursor=None)
        payload = group_page_to_dict("forge", "issues", page, 2, [])
        self.assertEqual(tuple(payload), SEARCH_PAGE_FIELDS)
        code = group_page_to_dict(
            "forge", "code", page, 2, [],
            total_matches=5, total_matched_lines=9)
        self.assertEqual(
            tuple(code),
            SEARCH_PAGE_FIELDS + ("total_matches", "total_matched_lines"))
        self.assertEqual(code["total_matches"], 5)

    def test_complete_flag_never_claims_past_the_crawl_bound(self):
        page = SimpleNamespace(
            returned=500, complete=True, total=500, per_page=100,
            has_next=False, has_previous=True,
            next_cursor=None, previous_cursor="x")
        payload = group_page_to_dict("forge", "issues", page, 600, [])
        self.assertFalse(payload["complete"])
        self.assertEqual(payload["total"], 600)

    # -- the whole search, through the door -------------------
    def test_anonymous_whole_search_is_s216s_payload(self):
        self.assertEqual(
            self.api.search(None, "forge"),
            self.w.api.search(None, "forge"))

    def test_signed_in_whole_search_is_s216s_payload(self):
        self.assertEqual(
            self.api.search(self.owner_basic, "forge"),
            self.w.api.search(self.w.owner, "forge"))
        self.assertEqual(
            self.api.search(self.owner_basic, "zorblax"),
            self.w.api.search(self.w.owner, "zorblax"))

    def test_token_caller_searches_as_its_owner(self):
        store = AccessTokenStore(self.w.conn, self.w.accounts)
        _, raw = store.create_token(
            self.w.owner.id, "script", {"issues:read"},
            int(time.time()) + 3600)
        self.assertEqual(
            self.api.search("Bearer " + raw, "forge"),
            self.w.api.search(self.w.owner, "forge"))

    def test_bad_credential_is_refused_never_downgraded(self):
        reason = self._reason(
            self.api.search, "Bearer svk_not-a-real-token", "forge")
        self.assertEqual(reason, "credentials_invalid")
        problem = error_to_dict(PublicSearchAPIError(
            "credentials_invalid", "probe"))
        self.assertEqual(tuple(problem), PROBLEM_FIELDS)
        self.assertEqual(problem["status"], 401)

    def test_wrong_scheme_is_refused_verbatim(self):
        self.assertEqual(
            self._reason(self.api.search, "Digest abc", "forge"),
            "scheme_unsupported")

    def test_engine_refusals_ride_verbatim(self):
        self.assertEqual(
            self._reason(self.api.search, None, "type:code"),
            "query_invalid")
        self.assertEqual(
            self._reason(self.api.search, None, "foo:bar forge"),
            "query_invalid")
        self.assertEqual(
            self._reason(
                self.api.search, None, "forge", per_group_limit=0),
            "query_invalid")

    def test_search_json_is_the_wire_form(self):
        text = self.api.search_json(self.owner_basic, "forge")
        self.assertIsInstance(text, str)
        self.assertEqual(
            json.loads(text), self.api.search(self.owner_basic, "forge"))
        self.assertEqual(
            to_json(self.api.search(None, "forge")),
            self.api.search_json(None, "forge"))

    def test_api_search_records_no_recents(self):
        before = self.w.conn.execute(
            "SELECT COUNT(*) FROM recent_searches").fetchone()[0]
        self.api.search(self.owner_basic, "forge")
        crawl(self.api, self.owner_basic, "forge", "issues")
        after = self.w.conn.execute(
            "SELECT COUNT(*) FROM recent_searches").fetchone()[0]
        self.assertEqual(before, after)

    # -- one group, paged --------------------------------------
    def test_crawl_covers_a_group_without_repeats_or_gaps(self):
        add_many_issues(self.w)
        pages = crawl(self.api, self.owner_basic, "forge", "issues",
                      per_page=7)
        hits = [hit for page in pages for hit in page["results"]]
        self.assertEqual(len(hits), ISSUE_COUNT + 2)
        keys = [(h["repository"], h["number"]) for h in hits]
        self.assertEqual(len(set(keys)), len(keys))
        for page in pages:
            self.assertEqual(page["total"], ISSUE_COUNT + 2)
            self.assertEqual(page["per_page"], 7)
        self.assertTrue(pages[-1]["complete"])
        self.assertFalse(pages[-1]["has_next"])
        self.assertIsNone(pages[-1]["next_cursor"])
        self.assertTrue(pages[0]["has_previous"] is False)

    def test_crawl_agrees_with_the_whole_search_group(self):
        add_many_issues(self.w)
        pages = crawl(self.api, self.owner_basic, "forge", "issues",
                      per_page=7)
        crawled = [hit for page in pages for hit in page["results"]]
        whole = self._group(
            self.api.search(
                self.owner_basic, "forge", per_group_limit=100),
            "issues")
        self.assertEqual(crawled, whole["results"])
        self.assertEqual(whole["total"], ISSUE_COUNT + 2)

    def test_first_page_is_the_whole_search_groups_prefix(self):
        page = self.api.search_group_page(None, "forge", "code",
                                          per_page=1)
        whole = self._group(self.api.search(None, "forge"), "code")
        self.assertEqual(page["results"], whole["results"][:1])
        self.assertEqual(page["total"], whole["total"])
        self.assertEqual(page["total_matches"], whole["total_matches"])
        self.assertEqual(
            page["total_matched_lines"], whole["total_matched_lines"])

    def test_cursor_contexts_never_cross(self):
        add_many_issues(self.w)
        first = self.api.search_group_page(
            self.owner_basic, "forge", "issues", per_page=7)
        cursor = first["next_cursor"]
        self.assertIsNotNone(cursor)
        self.assertEqual(
            self._reason(self.api.search_group_page,
                         self.owner_basic, "forge", "code",
                         per_page=7, cursor=cursor),
            "cursor_invalid")
        self.assertEqual(
            self._reason(self.api.search_group_page,
                         self.owner_basic, "bellows", "issues",
                         per_page=7, cursor=cursor),
            "cursor_invalid")
        self.assertEqual(
            self._reason(self.api.search_group_page,
                         None, "forge", "issues",
                         per_page=7, cursor=cursor),
            "cursor_invalid")
        self.assertEqual(
            self._reason(self.api.search_group_page,
                         self.owner_basic, "forge", "issues",
                         per_page=7, cursor="not-a-cursor"),
            "cursor_invalid")

    def test_page_size_bounds_are_s239s(self):
        self.assertEqual(
            self._reason(self.api.search_group_page,
                         None, "forge", "issues", per_page=0),
            "page_size_invalid")
        self.assertEqual(
            self._reason(self.api.search_group_page,
                         None, "forge", "issues", per_page=101),
            "page_size_invalid")

    def test_group_names_aliases_and_refusals(self):
        page = self.api.search_group_page(None, "forge", "repo")
        self.assertEqual(page["type"], "repositories")
        self.assertEqual(
            self._reason(self.api.search_group_page,
                         None, "forge", "wiki2"),
            "query_invalid")
        self.assertEqual(
            self._reason(self.api.search_group_page,
                         None, "forge", None),
            "query_invalid")

    def test_empty_query_pages_an_empty_group(self):
        page = self.api.search_group_page(None, "", "issues")
        self.assertEqual(page["total"], 0)
        self.assertEqual(page["results"], [])
        self.assertTrue(page["complete"])
        self.assertEqual(page["returned"], 0)

    def test_words_less_query_is_refused_on_the_page(self):
        self.assertEqual(
            self._reason(self.api.search_group_page,
                         None, "type:issues", "issues"),
            "query_invalid")

    def test_every_group_pages_in_the_fixed_order_universe(self):
        for kind in GROUP_ORDER:
            page = self.api.search_group_page(
                self.owner_basic, "forge", kind, per_page=2)
            whole = self._group(
                self.api.search(self.owner_basic, "forge"), kind)
            self.assertEqual(page["type"], kind)
            self.assertEqual(page["total"], whole["total"], kind)
            self.assertEqual(
                page["results"], whole["results"][:2], kind)

    # -- leakage: S-209 over the paged face ---------------------
    def test_stranger_paged_answers_equal_the_secret_free_world(self):
        other_td = tempfile.TemporaryDirectory()
        self.addCleanup(other_td.cleanup)
        clean = make_world(Path(other_td.name), with_secret=False)
        self.addCleanup(clean.conn.close)
        clean_api = make_api(clean)
        for kind in GROUP_ORDER:
            mine = crawl(self.api, None, "zorblax", kind, per_page=1)
            theirs = crawl(clean_api, None, "zorblax", kind, per_page=1)
            self.assertEqual(
                [p["results"] for p in mine],
                [p["results"] for p in theirs], kind)
            self.assertEqual(
                [p["total"] for p in mine],
                [p["total"] for p in theirs], kind)
            self.assertEqual(mine[0]["total"], 0, kind)

    def test_owner_finds_the_secret_on_the_paged_face(self):
        for kind in ("repositories", "commits", "code", "issues"):
            page = self.api.search_group_page(
                self.owner_basic, "zorblax", kind)
            self.assertGreaterEqual(page["total"], 1, kind)
        page = self.api.search_group_page(
            self.owner_basic, "zorblax", "people")
        self.assertEqual(page["total"], 0)

    def test_stranger_whole_search_still_hides_the_secret(self):
        payload = self.api.search(None, "zorblax")
        for group in payload["groups"]:
            self.assertEqual(group["total"], 0, group["type"])
            self.assertEqual(group["results"], [], group["type"])

    # -- refusals and the page ----------------------------------
    def test_every_reason_is_registered_in_the_problem_registry(self):
        for reason in ("query_invalid", "cursor_invalid",
                       "page_size_invalid", "ordering_invalid",
                       "credentials_invalid", "scheme_unsupported",
                       "authentication_required"):
            self.assertIn(reason, registered_reasons())

    def test_render_page_says_the_contract_in_plain_words(self):
        page = render_search_api_page()
        self.assertIn("Search API", page)
        self.assertIn("/api/v1", page)
        self.assertIn("cursor", page)
        self.assertIn("query_invalid", page)
        self.assertIn("permission filtering", page)


if __name__ == "__main__":
    unittest.main()
