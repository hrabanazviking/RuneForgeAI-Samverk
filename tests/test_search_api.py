"""S-216 acceptance battery: search API.

Acceptance (roadmap S-216): Search API — the same
engine behind Part XII endpoints with identical
permission filtering.

The planted secret is deliberate bait, in the S-209 /
S-213 shape: a private repository (`vault`) whose
description, only commit, only code file, and only
issue all carry the unique word `zorblax`, so any
leak channel — a group serialised without its S-209
filtering, a count tallied across groups, a recent
search recorded by an API call — moves a string or a
number this battery watches. The centre is the
equivalence proof over the payload itself: a
stranger's per-group hits and counts over a world
WITH the private repository equal, exactly, the same
search over a world where it was never created.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.code_indexing import CodeIndexer
from samverk.db import schema_version
from samverk.global_search import GROUP_ORDER, GlobalSearch, RecentSearchStore
from samverk.index_architecture import SearchIndexStore
from samverk.issue_pr_search import IssuePRSearch
from samverk.issues import IssueStore
from samverk.organizations import OrganizationStore
from samverk.repositories import RepositoryStore
from samverk.search_api import (
    SearchAPI, SearchAPIError, error_to_dict, results_to_dict)
from test_repo_home import GIT_ENV, run_git

PW = "correct horse battery"
THOR = ("A U Thor", "a@example.com")
SIGRUN = ("Sigrun Halvorsen", "sigrun@example.com")
KEEPER = ("Zorblax Keeper", "keeper@example.com")


def commit(work, filename, text, subject, body, author, when):
    path = work / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    run_git(work, "add", "-A")
    env = dict(os.environ); env.update(GIT_ENV)
    env["GIT_AUTHOR_NAME"], env["GIT_AUTHOR_EMAIL"] = author
    env["GIT_COMMITTER_NAME"], env["GIT_COMMITTER_EMAIL"] = author
    env["GIT_AUTHOR_DATE"] = str(when)
    env["GIT_COMMITTER_DATE"] = str(when)
    out = subprocess.run(
        ["git", "commit", "-m", subject, "-m", body],
        cwd=work, capture_output=True, env=env)
    if out.returncode != 0:
        raise AssertionError(out.stderr.decode())
    return run_git(work, "rev-parse", "HEAD")


class Clock:
    def __init__(self):
        self.t = 1000

    def __call__(self):
        self.t += 1
        return self.t


def make_world(root: Path, with_secret: bool) -> SimpleNamespace:
    conn = db.init_db(root / "samverk.db")
    accounts = AccountStore(conn)
    orgs = OrganizationStore(conn, accounts)
    owner = accounts.register("volmarr", PW)
    other = accounts.register("sigrun", PW)
    stranger = accounts.register("mallory", PW)
    repos = RepositoryStore(conn, root, accounts)
    audit = AuditLog(conn)
    issues = IssueStore(conn, repos, accounts, audit=audit)
    indexer = CodeIndexer(conn, repos)
    clock = Clock()
    recents = RecentSearchStore(conn, time_fn=clock)
    w = SimpleNamespace(
        conn=conn, accounts=accounts, orgs=orgs, owner=owner,
        other=other, stranger=stranger, repos=repos, issues=issues,
        recents=recents, clock=clock,
        web=GlobalSearch(conn, repos, orgs, recents=recents),
        api=SearchAPI(conn, repos, orgs))

    def profile(user, display, bio):
        conn.execute(
            "INSERT INTO profiles (user_id, display_name, bio,"
            " updated_at) VALUES (?, ?, ?, 0)",
            (user.id, display, bio))
        conn.commit()

    profile(owner, "Volmarr Wyrd", "Forge keeper and hall skald")
    profile(other, "Sigrun Halvorsen", "Weaver of the great hall")
    profile(stranger, "Mallory Quinn", "Wandering cartographer")
    orgs.create_organization(
        owner.id, "ForgeGuild", display_name="The Forge Guild",
        bio="Smiths and builders of the hall")

    def workdir(name):
        d = root / ("work-" + name); d.mkdir()
        run_git(d, "init", "-b", "main")
        return d

    repos.create_repository(
        owner.id, "volmarr", "anvil", visibility="public",
        description="Forge tools for the hall")
    bare = repos.path_for("volmarr", "anvil")
    work = workdir("anvil")
    commit(work, "main.py", "print('forge one')\nforge again\n",
           "Forge the anvil frame", "Hammer work begins",
           THOR, 1700000100)
    commit(work, "lib.py", "VALUE = 'forge'\n",
           "Forge the bellows", "Air for the forge",
           SIGRUN, 1700000200)
    run_git(work, "push", str(bare), "main")
    indexer.index_repository("volmarr", "anvil")
    issues.create_issue(owner, "volmarr", "anvil",
                        "Forge door sticks", "the forge door drags")
    issues.create_issue(owner, "volmarr", "anvil",
                        "Forge <b>markup</b> check", "escape me")

    if with_secret:
        repos.create_repository(
            owner.id, "volmarr", "vault", visibility="private",
            description="zorblax vault plans")
        bare = repos.path_for("volmarr", "vault")
        work = workdir("vault")
        commit(work, "secret.py", "zorblax = 'zorblax'\n",
               "zorblax secret plans", "hidden zorblax body",
               KEEPER, 1700000500)
        run_git(work, "push", str(bare), "main")
        indexer.index_repository("volmarr", "vault")
        issues.create_issue(owner, "volmarr", "vault",
                            "Zorblax master plan", "zorblax secrets")

    backend = IssuePRSearch(conn, repos, SearchIndexStore(conn, repos))
    backend.index_all()
    return w


def payload_signature(payload):
    """Per-group identity + totals from a payload, for
    the leakage equivalence proof: groups in order,
    each group's hit identities and its own total —
    never summed."""
    out = []
    for group in payload["groups"]:
        kind = group["type"]
        if kind == "repositories":
            ids = [h["repository"] for h in group["results"]]
        elif kind == "people":
            ids = [(h["kind"], h["handle"]) for h in group["results"]]
        elif kind == "commits":
            ids = [(h["repository"], h["subject"])
                   for h in group["results"]]
        elif kind == "code":
            ids = [(h["repository"], h["path"])
                   for h in group["results"]]
        else:
            ids = [(h["repository"], h["number"], h["title"])
                   for h in group["results"]]
        out.append((kind, ids, group["total"],
                    group.get("total_matches"),
                    group.get("total_matched_lines")))
    return out


class SearchAPITests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.w = make_world(self.root, with_secret=True)
        self.addCleanup(self.w.conn.close)

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(SearchAPIError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    def _group(self, payload, kind):
        for group in payload["groups"]:
            if group["type"] == kind:
                return group
        self.fail(f"no {kind} group in payload")

    # -- pins ------------------------------------------------
    def test_pins_schema_98_taxonomy_131(self):
        self.assertEqual(schema_version(self.w.conn), 98)
        self.assertEqual(db.MIGRATIONS[-1][0], 98)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 131)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 85)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)

    # -- the payload shape ------------------------------------
    def test_payload_is_json_safe_and_ordered(self):
        payload = self.w.api.search(self.w.stranger, "forge")
        self.assertEqual(payload["query"], "forge")
        self.assertEqual([g["type"] for g in payload["groups"]],
                         list(GROUP_ORDER))
        text = json.dumps(payload)
        self.assertEqual(json.loads(text), payload)
        wire = self.w.api.search_json(self.w.stranger, "forge")
        self.assertEqual(json.loads(wire), payload)

    def test_totals_are_per_group_never_summed(self):
        payload = self.w.api.search(self.w.stranger, "forge")
        self.assertNotIn("total", payload)
        for group in payload["groups"]:
            self.assertEqual(group["returned"],
                             len(group["results"]))
            self.assertEqual(group["complete"],
                             group["total"] <= group["returned"])

    def test_repository_hit_carries_the_pages_facts(self):
        group = self._group(
            self.w.api.search(self.w.stranger, "forge"), "repositories")
        self.assertEqual(group["total"], 1)
        hit = group["results"][0]
        self.assertEqual(hit["repository"], "volmarr/anvil")
        self.assertEqual(hit["owner"], "volmarr")
        self.assertEqual(hit["name"], "anvil")
        self.assertEqual(hit["visibility"], "public")
        self.assertEqual(hit["description"], "Forge tools for the hall")
        self.assertEqual(hit["topics"], [])
        self.assertIn("description", hit["matched_fields"])

    def test_people_hit_carries_profile_card_facts(self):
        group = self._group(
            self.w.api.search(self.w.stranger, "forge"), "people")
        by_handle = {h["handle"]: h for h in group["results"]}
        self.assertIn("ForgeGuild", by_handle)
        org = by_handle["ForgeGuild"]
        self.assertEqual(org["kind"], "org")
        # No membership rows exist in this world
        # (creation seeds none; S-186 seeds on touch).
        self.assertEqual(org["member_count"], 0)
        person = self._group(
            self.w.api.search(self.w.stranger, "volmarr"), "people")
        hit = person["results"][0]
        self.assertEqual(hit["kind"], "user")
        self.assertEqual(hit["handle"], "volmarr")
        self.assertEqual(hit["display_name"], "Volmarr Wyrd")
        self.assertIsNone(hit["avatar"])

    def test_commit_hit_carries_authorship(self):
        group = self._group(
            self.w.api.search(self.w.stranger, "forge"), "commits")
        subjects = [h["subject"] for h in group["results"]]
        self.assertIn("Forge the anvil frame", subjects)
        hit = group["results"][subjects.index("Forge the anvil frame")]
        self.assertEqual(hit["repository"], "volmarr/anvil")
        self.assertEqual(hit["author_name"], "A U Thor")
        self.assertEqual(hit["author_email"], "a@example.com")
        self.assertEqual(hit["author_time"], 1700000100)
        self.assertEqual(len(hit["oid"]), 40)

    def test_code_hit_carries_snippets_and_totals(self):
        group = self._group(
            self.w.api.search(self.w.stranger, "forge"), "code")
        self.assertGreaterEqual(group["total"], 1)
        self.assertGreaterEqual(group["total_matches"], 1)
        self.assertGreaterEqual(group["total_matched_lines"], 1)
        hit = [h for h in group["results"] if h["path"] == "main.py"][0]
        self.assertEqual(hit["repository"], "volmarr/anvil")
        self.assertFalse(hit["is_pointer"])
        self.assertGreaterEqual(hit["match_count"], 1)
        lines = [line for snippet in hit["snippets"]
                 for line in snippet["lines"]]
        self.assertTrue(any(line["is_match"] for line in lines))
        for line in lines:
            self.assertIsInstance(line["spans"], list)

    def test_issue_hit_carries_state_in_words(self):
        group = self._group(
            self.w.api.search(self.w.stranger, "forge"), "issues")
        titles = [h["title"] for h in group["results"]]
        self.assertIn("Forge door sticks", titles)
        hit = group["results"][titles.index("Forge door sticks")]
        self.assertEqual(hit["repository"], "volmarr/anvil")
        self.assertEqual(hit["kind"], "issue")
        self.assertEqual(hit["state_words"], "open")
        self.assertEqual(hit["author"], "volmarr")
        # Data carries raw values — S-010 escaping is the page's law.
        self.assertIn("Forge <b>markup</b> check", titles)

    def test_pure_serialiser_agrees_with_the_face(self):
        results = self.w.web.search(self.w.stranger, "forge")
        self.assertEqual(
            results_to_dict(results),
            self.w.api.search(self.w.stranger, "forge"))

    # -- the grammar and its refusals ---------------------------
    def test_type_selection_and_aliases_ride_the_engine(self):
        payload = self.w.api.search(
            self.w.stranger, "forge", types=["code"])
        self.assertEqual([g["type"] for g in payload["groups"]],
                         ["code"])
        payload = self.w.api.search(self.w.stranger,
                                    "forge type:repo")
        self.assertEqual([g["type"] for g in payload["groups"]],
                         ["repositories"])

    def test_refusals_carry_the_engines_reason_verbatim(self):
        self.assertEqual(
            self._reason(self.w.api.search, self.w.stranger,
                         "forge", types=["wiki"]),
            "query_invalid")
        self.assertEqual(
            self._reason(self.w.api.search, self.w.stranger,
                         "forge author:thor"),
            "query_invalid")
        self.assertEqual(
            self._reason(self.w.api.search, self.w.stranger,
                         "type:code"),
            "query_invalid")
        self.assertEqual(
            self._reason(self.w.api.search, self.w.stranger,
                         "forge", per_group_limit=0),
            "query_invalid")
        self.assertEqual(
            self._reason(self.w.api.search, self.w.stranger,
                         "forge", per_group_limit=101),
            "query_invalid")

    def test_error_to_dict_is_the_refusal_shape(self):
        try:
            self.w.api.search(self.w.stranger, "type:code")
        except SearchAPIError as exc:
            shape = error_to_dict(exc)
        else:
            self.fail("expected a refusal")
        self.assertEqual(shape["type"], "/api/v1/problems/query_invalid")
        self.assertEqual(shape["status"], 400)
        self.assertTrue(shape["detail"])

    def test_empty_query_is_the_landing_said_as_data(self):
        payload = self.w.api.search(self.w.stranger, "")
        self.assertEqual(payload, {"query": "", "groups": []})

    def test_cap_truncation_is_said_by_complete(self):
        payload = self.w.api.search(self.w.owner, "forge",
                                    per_group_limit=1)
        for group in payload["groups"]:
            self.assertLessEqual(group["returned"], 1)
            self.assertEqual(group["complete"],
                             group["total"] <= 1)

    # -- identical permission filtering -------------------------
    def test_stranger_payload_never_names_the_secret(self):
        wire = self.w.api.search_json(self.w.stranger, "zorblax")
        # The payload echoes the query as typed — the searcher's
        # own word, not a leak. The leak check judges the groups.
        groups_wire = json.dumps(json.loads(wire)["groups"])
        self.assertNotIn("zorblax", groups_wire.lower())
        self.assertNotIn("vault", groups_wire)
        payload = json.loads(wire)
        for group in payload["groups"]:
            self.assertEqual(group["total"], 0)
            self.assertEqual(group["results"], [])

    def test_owner_sees_the_secret_through_the_same_api(self):
        payload = self.w.api.search(self.w.owner, "zorblax")
        self.assertEqual(
            self._group(payload, "repositories")["total"], 1)
        self.assertEqual(self._group(payload, "issues")["total"], 1)
        self.assertGreaterEqual(
            self._group(payload, "code")["total"], 1)
        self.assertGreaterEqual(
            self._group(payload, "commits")["total"], 1)

    def test_anonymous_search_is_public_only(self):
        payload = self.w.api.search(None, "zorblax",
                                    types=["repositories"])
        self.assertEqual(payload["groups"][0]["total"], 0)
        payload = self.w.api.search(None, "forge",
                                    types=["repositories"])
        self.assertEqual(payload["groups"][0]["total"], 1)

    def test_leakage_equivalence_over_the_payload(self):
        with tempfile.TemporaryDirectory() as td:
            other = make_world(Path(td), with_secret=False)
            try:
                mine = payload_signature(
                    self.w.api.search(self.w.stranger, "forge"))
                theirs = payload_signature(
                    other.api.search(other.stranger, "forge"))
            finally:
                other.conn.close()
        self.assertEqual(mine, theirs)

    # -- statelessness -------------------------------------------
    def test_api_search_records_no_recents_and_audits_nothing(self):
        def recent_count():
            return self.w.conn.execute(
                "SELECT COUNT(*) AS c FROM recent_searches"
            ).fetchone()["c"]

        def audit_count():
            return self.w.conn.execute(
                "SELECT COUNT(*) AS c FROM audit_log"
            ).fetchone()["c"]

        audits_before = audit_count()
        self.w.api.search(self.w.owner, "forge")
        self.assertEqual(recent_count(), 0)
        self.assertEqual(audit_count(), audits_before)
        # The contrast: the web engine, built with its
        # store, does remember — the API's silence is
        # its own construction, not the world's.
        self.w.web.search(self.w.owner, "forge")
        self.assertEqual(recent_count(), 1)


if __name__ == "__main__":
    unittest.main()
