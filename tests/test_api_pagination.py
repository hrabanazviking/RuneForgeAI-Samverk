"""S-239 acceptance battery: pagination and
conditional requests.

Acceptance (roadmap S-239): Pagination and
conditional requests -- cursor pagination, `Link`
headers, ETag/`If-None-Match`; a full crawl of a
large repo uses bounded requests.

The centre is the crawl proof over S-231's events
face: a repository with well over one page of
events is walked cursor by cursor, every request
bounded, the pages together exactly the unpaged
feed in order, and a row inserted mid-crawl moves
nothing already passed. Around it, the pure law:
cursors are positions scoped to their context,
never credentials; page sizes are bounded or
refused, never clamped; Link headers walk first /
prev / next / last; and a held ETag ends an
unchanged re-check at 304 while a changed payload
answers 200 in full.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import base64, json, re, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.activity_feeds import ActivityFeedStore
from samverk.api_contract import (
    CURRENT_ERROR_FIELDS, audit_api_contract, get_rule)
from samverk.api_pagination import (
    CURSOR_VERSION, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE,
    PAGINATION_PATH, ApiPaginationError, check_page_size,
    conditional_response, decode_cursor, encode_cursor,
    error_to_dict, etag_for, etag_for_text,
    if_none_match_matches, link_header, page_to_dict,
    page_url, paginate, parse_if_none_match,
    render_api_pagination_page)
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.event_store import EventStore
from samverk.events_api import EventsAPI, EventsAPIError
from samverk.issues import IssueStore
from samverk.repositories import RepositoryStore

PW = "correct horse battery"
CRAWL_ISSUES = 125


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
    reader = accounts.register("yrsa", PW)
    stranger = accounts.register("mallory", PW)
    repos = RepositoryStore(conn, root, accounts, audit=audit)
    issues = IssueStore(conn, repos, accounts, audit=audit)
    events = EventStore(conn, repos, accounts)
    feeds = ActivityFeedStore(conn, repos, accounts, events=events)
    api = EventsAPI(conn, repos, accounts, events=events, feeds=feeds)
    repos.create_repository(
        owner.id, "volmarr", "pub", visibility="public")
    repos.create_repository(
        owner.id, "volmarr", "priv", visibility="private")
    issues.create_issue(owner, "volmarr", "priv", "Secret plans")
    for number in range(1, CRAWL_ISSUES + 1):
        issues.create_issue(
            owner, "volmarr", "pub", f"Crawl issue {number}")
    return SimpleNamespace(
        conn=conn, clock=clock, audit=audit, accounts=accounts,
        owner=owner, reader=reader, stranger=stranger,
        repos=repos, issues=issues, events=events, feeds=feeds,
        api=api)


def crafted_cursor(payload) -> str:
    raw = json.dumps(payload).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


class PurePaginationTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.conn = db.init_db(Path(self._td.name) / "samverk.db")
        self.addCleanup(self.conn.close)

    # -- pins ------------------------------------------------
    def test_pins_schema_taxonomy_and_bounds(self):
        self.assertEqual(schema_version(self.conn), 101)
        self.assertEqual(db.MIGRATIONS[-1][0], 101)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 85)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 131)
        self.assertEqual(PAGINATION_PATH, "/api/pagination")
        self.assertEqual(DEFAULT_PAGE_SIZE, 30)
        self.assertEqual(MAX_PAGE_SIZE, 100)
        self.assertEqual(CURSOR_VERSION, 1)

    def test_error_dict_matches_s237_current_shape(self):
        exc = ApiPaginationError("cursor_invalid", "nope")
        rendered = error_to_dict(exc)
        self.assertEqual(tuple(rendered.keys()), CURRENT_ERROR_FIELDS)
        self.assertEqual(
            rendered["type"], "/api/v1/problems/cursor_invalid")
        self.assertEqual(rendered["status"], 400)
        self.assertEqual(json.loads(json.dumps(rendered)), rendered)

    def test_contract_rule_now_records_s239_landed(self):
        rule = get_rule("cursor-pagination")
        self.assertIn("S-239", rule.statement)
        self.assertIn("api_pagination", rule.statement)
        self.assertTrue(audit_api_contract().ratified)

    # -- cursors ----------------------------------------------
    def test_cursor_roundtrips_int_and_str_keys(self):
        for key in (1, 987654, "volmarr/pub", "a"):
            token = encode_cursor(key, "feed:x")
            self.assertEqual(decode_cursor(token, "feed:x"), key)
        self.assertNotIn("volmarr", encode_cursor("volmarr/pub", "c"))

    def test_cursor_refuses_keys_it_cannot_name(self):
        for bad in (True, None, 1.5, "", b"bytes", ["x"]):
            with self.assertRaises(ApiPaginationError) as ctx:
                encode_cursor(bad, "c")
            self.assertEqual(ctx.exception.reason, "cursor_invalid")

    def test_cursor_failures_are_one_refusal(self):
        good = encode_cursor(5, "feed:x")
        bad_tokens = [
            "not a cursor", "", "!!!", good[:-3], 42, None,
            crafted_cursor({"v": 99, "ctx": "feed:x", "k": 5}),
            crafted_cursor({"v": 1, "ctx": "feed:x"}),
            crafted_cursor({"v": 1, "ctx": "feed:x", "k": True}),
            crafted_cursor({"v": 1, "ctx": "feed:x", "k": 5, "x": 1}),
            crafted_cursor(["v", 1]),
        ]
        for token in bad_tokens:
            with self.assertRaises(ApiPaginationError) as ctx:
                decode_cursor(token, "feed:x")
            self.assertEqual(
                ctx.exception.reason, "cursor_invalid", repr(token))

    def test_cursor_contexts_never_cross(self):
        token = encode_cursor(5, "feed:one")
        with self.assertRaises(ApiPaginationError) as ctx:
            decode_cursor(token, "feed:two")
        self.assertEqual(ctx.exception.reason, "cursor_invalid")
        with self.assertRaises(ApiPaginationError):
            decode_cursor(token, "feed:one", key_type=str)

    # -- the engine -------------------------------------------
    def _numbers(self, count=95):
        return list(range(count, 0, -1))

    def test_first_page_bounds_and_walking_facts(self):
        page = paginate(self._numbers(), key=lambda n: n, per_page=10)
        self.assertEqual(list(page.items), list(range(95, 85, -1)))
        self.assertEqual(page.total, 95)
        self.assertEqual(page.returned, 10)
        self.assertFalse(page.complete)
        self.assertTrue(page.has_next)
        self.assertFalse(page.has_previous)
        self.assertIsNotNone(page.next_cursor)
        self.assertIsNone(page.previous_cursor)

    def test_page_size_bounds_refused_never_clamped(self):
        for bad in (0, -1, MAX_PAGE_SIZE + 1, True, "10", 10.5, None):
            with self.assertRaises(ApiPaginationError) as ctx:
                check_page_size(bad)
            self.assertEqual(
                ctx.exception.reason, "page_size_invalid", repr(bad))
        self.assertEqual(check_page_size(1), 1)
        self.assertEqual(check_page_size(MAX_PAGE_SIZE), MAX_PAGE_SIZE)
        with self.assertRaises(ApiPaginationError):
            paginate(self._numbers(5), key=lambda n: n, per_page=0)

    def test_default_page_size_is_the_documented_one(self):
        page = paginate(self._numbers(95), key=lambda n: n)
        self.assertEqual(page.per_page, DEFAULT_PAGE_SIZE)
        self.assertEqual(page.returned, DEFAULT_PAGE_SIZE)

    def test_walking_every_page_covers_once_in_order(self):
        seen, cursor, pages = [], None, 0
        while True:
            page = paginate(
                self._numbers(), key=lambda n: n,
                per_page=10, cursor=cursor, context="n")
            seen.extend(page.items)
            pages += 1
            if not page.has_next:
                break
            cursor = page.next_cursor
        self.assertEqual(seen, self._numbers())
        self.assertEqual(pages, 10)
        self.assertTrue(page.complete)

    def test_exact_multiple_ends_cleanly(self):
        first = paginate(self._numbers(20), key=lambda n: n, per_page=10)
        last = paginate(
            self._numbers(20), key=lambda n: n, per_page=10,
            cursor=first.next_cursor)
        self.assertEqual(last.returned, 10)
        self.assertFalse(last.has_next)
        self.assertIsNone(last.next_cursor)
        self.assertTrue(last.complete)

    def test_empty_collection_pages_to_nothing(self):
        page = paginate([], key=lambda n: n, per_page=10)
        self.assertEqual(page.total, 0)
        self.assertEqual(page.returned, 0)
        self.assertTrue(page.complete)
        self.assertIsNone(page.next_cursor)
        self.assertIsNone(page.previous_cursor)

    def test_ascending_order_and_str_keys(self):
        names = ["birch", "elm", "oak", "pine", "yew"]
        first = paginate(
            names, key=lambda s: s, per_page=2, descending=False)
        self.assertEqual(list(first.items), ["birch", "elm"])
        second = paginate(
            names, key=lambda s: s, per_page=2,
            cursor=first.next_cursor, descending=False)
        self.assertEqual(list(second.items), ["oak", "pine"])
        self.assertEqual(second.previous_cursor, None)
        self.assertTrue(second.has_previous)

    def test_unstable_order_is_refused_not_trusted(self):
        for rows in ([3, 1, 2], [5, 5, 4], [1, 2, 3]):
            with self.assertRaises(ApiPaginationError) as ctx:
                paginate(rows, key=lambda n: n, per_page=2)
            self.assertEqual(
                ctx.exception.reason, "ordering_invalid", rows)

    def test_keyset_page_ignores_rows_inserted_ahead(self):
        rows = self._numbers(50)
        first = paginate(rows, key=lambda n: n, per_page=10)
        grown = [999, 998] + rows  # inserted at the head, mid-crawl
        second = paginate(
            grown, key=lambda n: n, per_page=10,
            cursor=first.next_cursor)
        self.assertEqual(list(second.items), list(range(40, 30, -1)))

    def test_previous_cursor_walks_back_to_the_first_page(self):
        rows = self._numbers(50)
        first = paginate(rows, key=lambda n: n, per_page=10)
        second = paginate(
            rows, key=lambda n: n, per_page=10,
            cursor=first.next_cursor)
        third = paginate(
            rows, key=lambda n: n, per_page=10,
            cursor=second.next_cursor)
        back = paginate(
            rows, key=lambda n: n, per_page=10,
            cursor=third.previous_cursor)
        self.assertEqual(list(back.items), list(second.items))
        first_again = paginate(
            rows, key=lambda n: n, per_page=10,
            cursor=back.previous_cursor)
        self.assertEqual(list(first_again.items), list(first.items))

    def test_page_to_dict_shape_and_json_safety(self):
        page = paginate(self._numbers(25), key=lambda n: n, per_page=10)
        data = page_to_dict(page, [{"n": n} for n in page.items])
        self.assertEqual(
            tuple(data.keys()),
            ("total", "returned", "complete", "per_page",
             "has_next", "has_previous", "next_cursor",
             "previous_cursor", "items"))
        self.assertEqual(json.loads(json.dumps(data)), data)

    # -- Link headers ------------------------------------------
    def test_page_url_replaces_paging_params_keeps_the_rest(self):
        url = page_url(
            "/api/v1/events?verb=repo.&per_page=5&cursor=old",
            cursor="new", per_page=10)
        self.assertIn("verb=repo.", url)
        self.assertIn("per_page=10", url)
        self.assertIn("cursor=new", url)
        self.assertNotIn("cursor=old", url)
        first = page_url("/api/v1/events", per_page=10)
        self.assertNotIn("cursor", first)

    def test_link_header_walks_first_prev_next_last(self):
        rows = self._numbers(95)
        base = "/api/v1/repos/volmarr/pub/events"
        first = paginate(rows, key=lambda n: n, per_page=10)
        header = link_header(base, first)
        self.assertIn('rel="first"', header)
        self.assertIn('rel="next"', header)
        self.assertIn('rel="last"', header)
        self.assertNotIn('rel="prev"', header)
        self.assertIn("per_page=10", header)
        middle = paginate(
            rows, key=lambda n: n, per_page=10,
            cursor=first.next_cursor)
        header = link_header(base, middle)
        for rel in ("first", "prev", "next", "last"):
            self.assertIn(f'rel="{rel}"', header)
        cursor = first.next_cursor
        page = first
        while page.has_next:
            page = paginate(
                rows, key=lambda n: n, per_page=10, cursor=cursor)
            cursor = page.next_cursor
        header = link_header(base, page)
        self.assertIn('rel="first"', header)
        self.assertIn('rel="prev"', header)
        self.assertNotIn('rel="next"', header)
        self.assertNotIn('rel="last"', header)

    # -- ETags and conditional requests ------------------------
    def test_etag_is_strong_stable_and_order_insensitive(self):
        tag = etag_for({"b": 1, "a": [1, 2, {"z": "þ"}]})
        self.assertEqual(tag, etag_for({"a": [1, 2, {"z": "þ"}], "b": 1}))
        self.assertRegex(tag, r'^"[0-9a-f]{64}"$')
        self.assertNotEqual(tag, etag_for({"a": [1, 2], "b": 1}))
        self.assertEqual(
            etag_for_text('{"a":1}'), etag_for_text('{"a":1}'))
        self.assertNotEqual(
            etag_for_text('{"a":1}'), etag_for_text('{"a":2}'))

    def test_etag_refuses_what_json_cannot_carry(self):
        with self.assertRaises(ApiPaginationError) as ctx:
            etag_for({"x": object()})
        self.assertEqual(ctx.exception.reason, "payload_not_json")

    def test_if_none_match_weak_list_star_and_misses(self):
        tag = etag_for({"a": 1})
        self.assertTrue(if_none_match_matches(tag, tag))
        self.assertTrue(if_none_match_matches("W/" + tag, tag))
        self.assertTrue(
            if_none_match_matches('"other", ' + tag, tag))
        self.assertTrue(if_none_match_matches("*", tag))
        self.assertFalse(if_none_match_matches(None, tag))
        self.assertFalse(if_none_match_matches('"other"', tag))
        self.assertFalse(if_none_match_matches("garbage, ", tag))
        self.assertEqual(parse_if_none_match(None), (False, ()))
        with self.assertRaises(ApiPaginationError) as ctx:
            parse_if_none_match(42)
        self.assertEqual(ctx.exception.reason, "header_invalid")

    def test_conditional_response_304_carries_no_payload(self):
        payload = {"total": 3, "events": [1, 2, 3]}
        fresh = conditional_response(payload)
        self.assertEqual(fresh.status, 200)
        self.assertEqual(fresh.payload, payload)
        self.assertFalse(fresh.not_modified)
        held = conditional_response(payload, fresh.etag)
        self.assertEqual(held.status, 304)
        self.assertTrue(held.not_modified)
        self.assertIsNone(held.payload)
        self.assertEqual(held.etag, fresh.etag)
        changed = conditional_response(
            {"total": 4, "events": [1, 2, 3, 4]}, fresh.etag)
        self.assertEqual(changed.status, 200)

    # -- the help page ------------------------------------------
    def test_page_renders_the_law_and_escapes_values(self):
        page = render_api_pagination_page(
            link='<x>; rel="next"', etag='"abc"')
        self.assertIn("API pagination and conditional requests", page)
        self.assertIn("304", page)
        self.assertIn("&lt;x&gt;", page)
        self.assertNotIn("<x>", page)


class EventsCrawlTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.w = make_world(Path(self._td.name))
        self.addCleanup(self.w.conn.close)

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(EventsAPIError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    def _audit_count(self):
        return self.w.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]

    def _crawl_repo(self, per_page):
        pages, cursor = [], None
        while True:
            payload = self.w.api.repo_events_page(
                self.w.owner, "volmarr", "pub",
                per_page=per_page, cursor=cursor)
            pages.append(payload)
            if not payload["has_next"]:
                return pages
            cursor = payload["next_cursor"]

    # -- the acceptance crawl -----------------------------------
    def test_full_crawl_of_a_large_repo_uses_bounded_requests(self):
        whole = self.w.api.repo_events(
            self.w.owner, "volmarr", "pub", limit=500)
        total = whole["total"]
        self.assertGreater(total, 100)
        pages = self._crawl_repo(per_page=10)
        self.assertEqual(len(pages), -(-total // 10))
        for payload in pages:
            self.assertLessEqual(payload["returned"], 10)
            self.assertEqual(payload["total"], total)
            self.assertEqual(
                json.loads(json.dumps(payload)), payload)
        crawled = [
            event["id"] for payload in pages
            for event in payload["events"]]
        expected = [event["id"] for event in whole["events"]]
        self.assertEqual(crawled, expected)
        self.assertEqual(len(set(crawled)), len(crawled))
        self.assertTrue(pages[-1]["complete"])
        self.assertFalse(pages[0]["complete"])

    def test_crawl_is_undisturbed_by_a_row_inserted_mid_crawl(self):
        whole = self.w.api.repo_events(
            self.w.owner, "volmarr", "pub", limit=500)
        expected = [event["id"] for event in whole["events"]]
        first = self.w.api.repo_events_page(
            self.w.owner, "volmarr", "pub", per_page=10)
        self.w.issues.create_issue(
            self.w.owner, "volmarr", "pub", "Late arrival")
        seen = [event["id"] for event in first["events"]]
        cursor = first["next_cursor"]
        while cursor is not None:
            payload = self.w.api.repo_events_page(
                self.w.owner, "volmarr", "pub",
                per_page=10, cursor=cursor)
            seen.extend(event["id"] for event in payload["events"])
            cursor = payload["next_cursor"]
        self.assertEqual(seen, expected)

    def test_first_page_agrees_with_the_capped_feed(self):
        capped = self.w.api.repo_events(
            self.w.owner, "volmarr", "pub", limit=10)
        page = self.w.api.repo_events_page(
            self.w.owner, "volmarr", "pub", per_page=10)
        self.assertEqual(
            [e["id"] for e in page["events"]],
            [e["id"] for e in capped["events"]])
        self.assertEqual(page["kind"], "repository")
        self.assertEqual(page["subject"], "volmarr/pub")
        self.assertEqual(page["per_page"], 10)

    def test_user_and_public_pages_carry_the_same_law(self):
        mine = self.w.api.user_events_page(
            self.w.owner, self.w.owner, per_page=10)
        capped = self.w.api.user_events(
            self.w.owner, self.w.owner, limit=10)
        self.assertEqual(
            [e["id"] for e in mine["events"]],
            [e["id"] for e in capped["events"]])
        seen, cursor = [], None
        while True:
            payload = self.w.api.public_events_page(
                self.w.stranger, per_page=25, cursor=cursor)
            seen.extend(payload["events"])
            if not payload["has_next"]:
                break
            cursor = payload["next_cursor"]
        self.assertTrue(seen)
        for event in seen:
            self.assertEqual(event["repository"], "volmarr/pub")

    # -- refusals ride the face's own error ----------------------
    def test_paged_refusals_are_the_faces_own_reasons(self):
        self.assertEqual(
            self._reason(
                self.w.api.repo_events_page,
                self.w.owner, "volmarr", "pub", cursor="junk!!"),
            "cursor_invalid")
        self.assertEqual(
            self._reason(
                self.w.api.repo_events_page,
                self.w.owner, "volmarr", "pub", per_page=0),
            "page_size_invalid")
        self.assertEqual(
            self._reason(
                self.w.api.repo_events_page,
                self.w.owner, "volmarr", "pub",
                per_page=MAX_PAGE_SIZE + 1),
            "page_size_invalid")
        self.assertEqual(
            self._reason(
                self.w.api.repo_events_page,
                self.w.stranger, "volmarr", "priv"),
            "repo_not_found")

    def test_a_cursor_never_crosses_feeds(self):
        page = self.w.api.repo_events_page(
            self.w.owner, "volmarr", "pub", per_page=10)
        self.assertEqual(
            self._reason(
                self.w.api.user_events_page,
                self.w.owner, self.w.owner,
                cursor=page["next_cursor"]),
            "cursor_invalid")
        self.assertEqual(
            self._reason(
                self.w.api.public_events_page,
                self.w.owner, cursor=page["next_cursor"]),
            "cursor_invalid")

    # -- conditional requests on the face -------------------------
    def test_single_event_conditional_round_trip(self):
        event_id = self.w.api.repo_events(
            self.w.owner, "volmarr", "pub", limit=1)["events"][0]["id"]
        fresh = self.w.api.get_event_conditional(
            self.w.owner, event_id)
        self.assertEqual(fresh.status, 200)
        self.assertEqual(fresh.payload["id"], event_id)
        self.assertEqual(fresh.etag, etag_for(fresh.payload))
        held = self.w.api.get_event_conditional(
            self.w.owner, event_id, if_none_match=fresh.etag)
        self.assertEqual(held.status, 304)
        self.assertIsNone(held.payload)
        stale = self.w.api.get_event_conditional(
            self.w.owner, event_id, if_none_match='"0000"')
        self.assertEqual(stale.status, 200)

    def test_feed_page_etag_changes_when_the_feed_does(self):
        payload = self.w.api.repo_events_page(
            self.w.owner, "volmarr", "pub", per_page=10)
        held = conditional_response(payload, etag_for(payload))
        self.assertEqual(held.status, 304)
        self.w.issues.create_issue(
            self.w.owner, "volmarr", "pub", "Fresh news")
        changed = self.w.api.repo_events_page(
            self.w.owner, "volmarr", "pub", per_page=10)
        self.assertNotEqual(etag_for(changed), etag_for(payload))
        self.assertEqual(
            conditional_response(changed, etag_for(payload)).status,
            200)

    def test_paged_reads_write_no_audit_row(self):
        before = self._audit_count()
        self._crawl_repo(per_page=50)
        self.w.api.public_events_page(self.w.stranger, per_page=10)
        self.w.api.user_events_page(
            self.w.owner, self.w.owner, per_page=10)
        self.assertEqual(self._audit_count(), before)


if __name__ == "__main__":
    unittest.main()
