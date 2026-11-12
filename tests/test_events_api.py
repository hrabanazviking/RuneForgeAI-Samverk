"""S-231 acceptance battery: events API.

Acceptance (roadmap S-231): Events API -- the feed
as a Part XII resource with the same permission
filtering.

The centre is the agreement proof: for the same
reader and the same bound, the API's event ids are
S-229's feed event ids in the same order, on every
face -- the API delegates its filtering to the feed
store, and this battery holds it to that claim.
The planted private repository (`priv`, carrying
the unique target only its owner may see) is the
leak bait in the S-209 shape: a stranger's payload
over a world WITH it must equal, event for event,
the same payload over a world where it was never
created.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import json, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.activity_feeds import PUBLIC_FEED_SCOPE, ActivityFeedStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.event_store import EventStore, event_payload
from samverk.events_api import (
    DEFAULT_LIMIT, MAX_LIMIT, EventsAPI, EventsAPIError,
    error_to_dict, event_to_dict, feed_to_dict)
from samverk.issue_comments import IssueCommentStore
from samverk.issues import IssueStore
from samverk.organizations import OrganizationStore
from samverk.repositories import RepositoryStore

PW = "correct horse battery"


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


def make_world(root: Path, with_secret: bool) -> SimpleNamespace:
    conn = db.init_db(root / "samverk.db")
    clock = Clock()
    audit = AuditLog(conn, time_fn=clock)
    accounts = AccountStore(conn, audit=audit, time_fn=clock)
    owner = accounts.register("volmarr", PW)
    reader = accounts.register("yrsa", PW)
    stranger = accounts.register("mallory", PW)
    with conn:
        conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (owner.id,))
    admin = accounts.get_by_id(owner.id)
    repos = RepositoryStore(conn, root, accounts, audit=audit)
    issues = IssueStore(conn, repos, accounts, audit=audit)
    comments = IssueCommentStore(conn, repos, accounts, issues, audit=audit)
    events = EventStore(conn, repos, accounts)
    feeds = ActivityFeedStore(conn, repos, accounts, events=events)
    w = SimpleNamespace(
        conn=conn, clock=clock, audit=audit, accounts=accounts,
        owner=owner, reader=reader, stranger=stranger, admin=admin,
        repos=repos, issues=issues, comments=comments,
        events=events, feeds=feeds,
        api=EventsAPI(conn, repos, accounts, events=events, feeds=feeds))
    repos.create_repository(owner.id, "volmarr", "pub", visibility="public")
    repos.create_repository(owner.id, "volmarr", "int", visibility="internal")
    issues.create_issue(reader, "volmarr", "pub", "Crash on startup")
    comments.add_comment(owner, "volmarr", "pub", 1, "Looking now")
    issues.close_issue(owner, "volmarr", "pub", 1)
    issues.create_issue(owner, "volmarr", "int", "Crew notes")
    if with_secret:
        repos.create_repository(owner.id, "volmarr", "priv", visibility="private")
        issues.create_issue(owner, "volmarr", "priv", "Secret plans")
    return w


def signature(payload):
    """One feed payload's identity for the leakage
    equivalence proof: kind, subject, filtered total,
    and each event's verb + target, in order."""
    return (payload["kind"], payload["subject"], payload["total"],
            [(e["event"], e["target"]) for e in payload["events"]])


class EventsAPITests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.w = make_world(Path(self._td.name), with_secret=True)
        self.addCleanup(self.w.conn.close)

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(EventsAPIError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    def _audit_count(self):
        return self.w.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]

    # -- pins ------------------------------------------------
    def test_pins_schema_and_taxonomy(self):
        self.assertEqual(schema_version(self.w.conn), 122)
        self.assertEqual(db.MIGRATIONS[-1][0], 122)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 88)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 134)

    # -- the event shape --------------------------------------
    def test_event_dict_agrees_with_s221_payload(self):
        event = self.w.events.list_for_repo(self.w.owner, "volmarr", "pub")[0]
        data = event_to_dict(event)
        payload = event_payload(event)
        for key in ("delivery_id", "event", "action", "actor", "target",
                    "repository", "number", "refs", "detail", "occurred_at"):
            self.assertEqual(data[key], payload[key], key)
        self.assertEqual(data["id"], event.id)
        self.assertEqual(data["actor_id"], event.actor_id)
        self.assertEqual(data["actor_kind"], event.actor_kind)
        self.assertEqual(data["target_kind"], event.target_kind)
        self.assertEqual(data["outcome"], event.outcome)
        self.assertEqual(json.loads(json.dumps(data)), data)

    def test_feed_payload_is_json_safe_and_wire_stable(self):
        payload = self.w.api.user_events(self.w.owner, self.w.owner)
        self.assertEqual(json.loads(json.dumps(payload)), payload)
        wire = self.w.api.user_events_json(self.w.owner, self.w.owner)
        self.assertEqual(json.loads(wire), payload)
        self.assertEqual(wire, self.w.api.user_events_json(
            self.w.owner, self.w.owner))

    # -- the user feed as data ---------------------------------
    def test_user_events_show_only_own_actions_newest_first(self):
        payload = self.w.api.user_events(self.w.reader, self.w.reader)
        self.assertEqual(payload["kind"], "user")
        self.assertEqual(payload["subject"], "yrsa")
        self.assertTrue(payload["events"])
        self.assertTrue(all(
            e["actor_id"] == self.w.reader.id for e in payload["events"]))
        verbs = [e["event"] for e in payload["events"]]
        self.assertIn("repo.issue.create", verbs)
        self.assertNotIn("repo.issue.comment", verbs)
        ids = [e["id"] for e in payload["events"]]
        self.assertEqual(ids, sorted(ids, reverse=True))

    def test_user_events_agree_with_s229_feed(self):
        for viewer in (self.w.admin, self.w.owner, self.w.stranger, None):
            feed = self.w.feeds.user_feed(viewer, self.w.owner, limit=500)
            payload = self.w.api.user_events(viewer, self.w.owner, limit=500)
            self.assertEqual([e["id"] for e in payload["events"]],
                             [e.id for e in feed.events])
            self.assertEqual(payload["total"], feed.count)
            self.assertEqual(payload["scope"], feed.scope)

    def test_user_events_self_sees_own_private_actions(self):
        payload = self.w.api.user_events(self.w.owner, self.w.owner)
        targets = [e["target"] for e in payload["events"]]
        self.assertIn("volmarr/priv#1", targets)

    def test_user_events_stranger_hides_private_member_sees_internal(self):
        payload = self.w.api.user_events(self.w.stranger, self.w.owner)
        targets = [e["target"] or "" for e in payload["events"]]
        self.assertTrue(any(t.startswith("volmarr/pub") for t in targets))
        self.assertTrue(any(t.startswith("volmarr/int") for t in targets))
        self.assertFalse(any("priv" in t for t in targets))
        wire = self.w.api.user_events_json(self.w.stranger, self.w.owner)
        self.assertNotIn("volmarr/priv", wire)
        self.assertNotIn("Secret plans", wire)

    def test_user_events_anonymous_sees_public_only(self):
        payload = self.w.api.user_events(None, self.w.owner)
        targets = [e["target"] or "" for e in payload["events"]]
        self.assertTrue(any(t.startswith("volmarr/pub") for t in targets))
        self.assertFalse(any("priv" in t or "/int" in t for t in targets))

    def test_user_events_org_events_are_public_facts(self):
        orgs = OrganizationStore(self.w.conn, self.w.accounts, audit=self.w.audit)
        orgs.create_organization(self.w.owner.id, "crew")
        payload = self.w.api.user_events(self.w.stranger, self.w.owner)
        self.assertIn("auth.organization.create",
                      [e["event"] for e in payload["events"]])

    def test_unknown_actor_refused_with_store_reason(self):
        for actor in ("ghost", 99999):
            self.assertEqual(
                self._reason(self.w.api.user_events, self.w.owner, actor),
                "no_such_user")

    # -- the repository feed as data ----------------------------
    def test_repo_events_agree_with_s229_feed(self):
        feed = self.w.feeds.repo_feed(self.w.stranger, "volmarr", "pub")
        payload = self.w.api.repo_events(self.w.stranger, "volmarr", "pub")
        self.assertEqual(payload["kind"], "repository")
        self.assertEqual(payload["subject"], "volmarr/pub")
        self.assertEqual([e["id"] for e in payload["events"]],
                         [e.id for e in feed.events])
        self.assertEqual(payload["total"], feed.count)
        self.assertEqual(
            [e["event"] for e in payload["events"]],
            ["repo.issue.close", "repo.issue.comment",
             "repo.issue.create", "repo.create"])

    def test_repo_events_private_denied_uniformly(self):
        for viewer in (self.w.stranger, self.w.reader, None):
            self.assertEqual(
                self._reason(self.w.api.repo_events,
                             viewer, "volmarr", "priv"),
                "repo_not_found")
        self.assertEqual(
            self._reason(self.w.api.repo_events,
                         self.w.owner, "volmarr", "missing"),
            "repo_not_found")
        payload = self.w.api.repo_events(self.w.owner, "volmarr", "priv")
        self.assertIn("repo.issue.create",
                      [e["event"] for e in payload["events"]])

    def test_repo_events_internal_member_reads_anonymous_denied(self):
        payload = self.w.api.repo_events(self.w.stranger, "volmarr", "int")
        self.assertIn("repo.issue.create",
                      [e["event"] for e in payload["events"]])
        self.assertEqual(
            self._reason(self.w.api.repo_events, None, "volmarr", "int"),
            "repo_not_found")

    # -- the public feed as data ---------------------------------
    def test_public_events_agree_with_s229_feed(self):
        feed = self.w.feeds.public_feed(viewer=self.w.admin)
        payload = self.w.api.public_events(viewer=self.w.admin)
        self.assertEqual(payload["kind"], "public")
        self.assertEqual(payload["subject"], "public")
        self.assertEqual(payload["scope"], PUBLIC_FEED_SCOPE)
        self.assertEqual([e["id"] for e in payload["events"]],
                         [e.id for e in feed.events])
        self.assertTrue(all(
            e["repository"] == "volmarr/pub" for e in payload["events"]))

    def test_public_events_same_for_admin_anonymous_and_actor(self):
        seen = [signature(self.w.api.public_events(viewer=v))
                for v in (self.w.admin, None, self.w.reader)]
        self.assertEqual(seen[0], seen[1])
        self.assertEqual(seen[0], seen[2])
        self.assertFalse(any(
            "priv" in (e["target"] or "") or "/int" in (e["target"] or "")
            for e in self.w.api.public_events(viewer=self.w.admin)["events"]))

    def test_public_events_exclude_non_repo_events(self):
        orgs = OrganizationStore(self.w.conn, self.w.accounts, audit=self.w.audit)
        orgs.create_organization(self.w.owner.id, "crew")
        payload = self.w.api.public_events()
        self.assertTrue(all(
            e["repository"] is not None for e in payload["events"]))
        self.assertNotIn("auth.organization.create",
                         [e["event"] for e in payload["events"]])

    # -- counts, caps, and filters --------------------------------
    def test_totals_count_only_shown_and_tally_before_cap(self):
        own = self.w.api.user_events(self.w.owner, self.w.owner)
        stranger = self.w.api.user_events(self.w.stranger, self.w.owner)
        self.assertEqual(own["total"], len(own["events"]))
        self.assertEqual(own["returned"], len(own["events"]))
        self.assertTrue(own["complete"])
        self.assertLess(stranger["total"], own["total"])
        capped = self.w.api.user_events(self.w.owner, self.w.owner, limit=2)
        self.assertEqual(capped["total"], own["total"])
        self.assertEqual(capped["returned"], 2)
        self.assertFalse(capped["complete"])
        self.assertEqual([e["id"] for e in capped["events"]],
                         [e["id"] for e in own["events"][:2]])

    def test_limit_bounds_are_the_contracts_own(self):
        self.assertEqual(DEFAULT_LIMIT, 100)
        self.assertEqual(MAX_LIMIT, 500)
        one = self.w.api.public_events(limit=1)
        self.assertEqual(one["returned"], 1)
        self.assertEqual(one["limit"], 1)
        for bad in (0, 501, -1, "10", 1.5, True, None):
            self.assertEqual(
                self._reason(self.w.api.public_events, limit=bad),
                "limit_invalid")

    def test_verb_prefix_filters_after_permission(self):
        payload = self.w.api.user_events(
            self.w.owner, self.w.owner, verb_prefix="repo.issue.")
        self.assertTrue(payload["events"])
        self.assertTrue(all(
            e["event"].startswith("repo.issue.") for e in payload["events"]))
        stranger = self.w.api.user_events(
            self.w.stranger, self.w.owner, verb_prefix="repo.issue.")
        self.assertFalse(any(
            "priv" in (e["target"] or "") for e in stranger["events"]))
        self.assertLess(stranger["total"], payload["total"])
        empty = self.w.api.user_events(
            self.w.owner, self.w.owner, verb_prefix="admin.")
        self.assertEqual(empty["total"], 0)
        self.assertEqual(empty["events"], [])
        self.assertTrue(empty["complete"])
        for bad in ("", 123):
            self.assertEqual(
                self._reason(self.w.api.user_events,
                             self.w.owner, self.w.owner, verb_prefix=bad),
                "filter_invalid")

    def test_error_to_dict_is_the_refusal_shape(self):
        try:
            self.w.api.user_events(self.w.owner, "ghost")
        except EventsAPIError as exc:
            shape = error_to_dict(exc)
        else:
            self.fail("expected a refusal")
        self.assertEqual(shape["type"], "/api/v1/problems/no_such_user")
        self.assertEqual(shape["status"], 404)
        self.assertTrue(shape["detail"])

    # -- the single event ------------------------------------------
    def test_get_event_round_trips_a_feed_entry(self):
        payload = self.w.api.repo_events(self.w.owner, "volmarr", "pub")
        first = payload["events"][0]
        got = self.w.api.get_event(self.w.stranger, first["id"])
        self.assertEqual(got, first)
        self.assertEqual(
            json.loads(self.w.api.get_event_json(
                self.w.stranger, first["id"])), first)

    def test_get_event_invisible_is_uniformly_not_found(self):
        mine = self.w.api.repo_events(self.w.owner, "volmarr", "priv")
        secret_id = mine["events"][0]["id"]
        for viewer in (self.w.stranger, None):
            self.assertEqual(
                self._reason(self.w.api.get_event, viewer, secret_id),
                "event_not_found")
        self.assertEqual(
            self._reason(self.w.api.get_event, self.w.owner, 99999),
            "event_not_found")
        self.assertEqual(
            self._reason(self.w.api.get_event, self.w.owner, "1"),
            "event_not_found")
        got = self.w.api.get_event(self.w.owner, secret_id)
        self.assertEqual(got["repository"], "volmarr/priv")

    # -- the leakage equivalence ------------------------------------
    def test_leakage_equivalence_over_the_payload(self):
        with tempfile.TemporaryDirectory() as td:
            other = make_world(Path(td), with_secret=False)
            try:
                for viewer_name in ("stranger", "reader"):
                    mine = signature(self.w.api.user_events(
                        getattr(self.w, viewer_name), self.w.owner, limit=500))
                    theirs = signature(other.api.user_events(
                        getattr(other, viewer_name), other.owner, limit=500))
                    self.assertEqual(mine, theirs)
                mine = signature(self.w.api.public_events(limit=500))
                theirs = signature(other.api.public_events(limit=500))
                self.assertEqual(mine, theirs)
            finally:
                other.conn.close()

    # -- statelessness and freshness ---------------------------------
    def test_api_reads_audit_nothing(self):
        self.w.api.public_events()  # materialise once, as the feeds do
        rows = self.w.conn.execute(
            "SELECT COUNT(*) AS n FROM events").fetchone()["n"]
        audits = self._audit_count()
        self.w.api.user_events(self.w.stranger, self.w.owner)
        self.w.api.repo_events(self.w.owner, "volmarr", "pub")
        self.w.api.public_events(viewer=self.w.admin)
        first = self.w.api.repo_events(self.w.owner, "volmarr", "pub")
        self.w.api.get_event(self.w.owner, first["events"][0]["id"])
        self.assertEqual(self._audit_count(), audits)
        self.assertEqual(
            self.w.conn.execute(
                "SELECT COUNT(*) AS n FROM events").fetchone()["n"], rows)

    def test_api_reads_are_never_stale(self):
        before = self.w.api.repo_events(self.w.owner, "volmarr", "pub")
        self.assertNotIn("repo.issue.reopen",
                         [e["event"] for e in before["events"]])
        self.w.issues.reopen_issue(self.w.owner, "volmarr", "pub", 1)
        after = self.w.api.repo_events(self.w.owner, "volmarr", "pub")
        self.assertEqual(after["events"][0]["event"], "repo.issue.reopen")
        self.assertEqual(after["total"], before["total"] + 1)

    def test_empty_feed_is_said_as_data(self):
        newbie = self.w.accounts.register("newbie", PW)
        payload = self.w.api.user_events(self.w.stranger, newbie)
        self.assertEqual(payload["total"], 0)
        self.assertEqual(payload["returned"], 0)
        self.assertEqual(payload["events"], [])
        self.assertTrue(payload["complete"])
        built = feed_to_dict("user", "newbie", payload["scope"], [],
                             limit=DEFAULT_LIMIT)
        self.assertEqual(built["total"], 0)
        self.assertEqual(built["events"], [])


if __name__ == "__main__":
    unittest.main()
