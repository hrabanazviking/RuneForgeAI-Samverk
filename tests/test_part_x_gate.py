"""S-220 — PART X GATE battery: search, assembled.

The whole Part X system struck at once, in the house gate
shape of S-096/S-120/S-140/S-168/S-184/S-204 — no new
production code, only the battery that walks the landed
S-205..S-219 machinery end to end through its public
seams, at the three things the gate names:

- **The leakage suite (S-209's law, every face)** — a
  planted secret bundle carrying the unique word
  `zorblax` across every search surface at once: a
  private repository (its name-adjacent description,
  its S-066 topic, its only code file, its only commit,
  its only issue) plus a suspended account whose
  display name and bio carry the word. The centre is
  the equivalence proof, run face by face: a stranger's
  and an anonymous visitor's hits AND counts over a
  world WITH the secret equal, exactly, the same
  searches over a world where it was never created —
  code (S-208), issues/PRs (S-206), repositories
  (S-210), people (S-211), commits (S-212), the global
  page (S-213) and the API payload itself (S-216).
  The owner and the site admin DO find the secret on
  every face, proving the filter is permission, not
  absence. An internal repository pins the second
  half of the law: in the search faces it is read by
  its owner and the site admin only — S-190's wider
  internal floor is the permission engine's surface,
  not a search surface, exactly as S-210 recorded.
- **The round trips** — S-205's closed index catalog,
  push/mutation trigger plans and code-coverage law;
  S-207 indexing (text indexed, LFS pointers indexed
  as pointers, binary skipped, a push re-indexes the
  change and the removal); S-206's issue index
  following creation; S-213's groups delegating to
  the banked executors; S-214's saved searches
  re-running live and staying private to their owner;
  recents recorded per user by the web face and never
  by the API (S-216).
- **The honesty seams** — S-215 index health is
  admin-only, shows lag in seconds rather than hiding
  it, and its rebuild trigger is audited; S-218's one
  shared language table is the table the highlighter,
  the indexer and the code filter all use, and its
  fail-closed alias law executes through S-208 (the
  alias `py` finds nothing; the canonical `python`
  finds the file); S-217's budgets are stated per
  hardware class and a class that was not measured is
  reported unmeasured — NOT PROVEN — never borrowed
  (this battery measures nothing on Pi-class hardware
  and claims nothing for it); S-219's limits document
  audits honestly against the live engines.

The gate claimed no migration and no taxonomy event:
the assembled system stands at schema 85 with 123
audit events (31 auth / 79 repo / 13 admin), and the
battery proves both pins. The full-suite counted
recount at this gate is recorded in
PROJECT_MEMORY_MAP.md (the gate entry), read back
from its log file after the run finished.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.code_indexing import CodeIndexer
from samverk.code_search import CodeSearch, CodeSearchError
from samverk.commit_search import CommitSearch, CommitSearchError
from samverk.db import schema_version
from samverk.global_search import (
    GROUP_ORDER, GlobalSearch, RecentSearchStore)
from samverk.hooks import RefUpdate
from samverk.index_architecture import (
    KIND_SPECS, SearchIndexError, SearchIndexStore,
    decide_code_disposition, plan_mutation, plan_push, spec_for)
from samverk.index_health import (
    IndexHealth, IndexHealthError, render_repo_index_health_page)
from samverk.issue_pr_search import IssuePRSearch
from samverk.issues import IssueStore
from samverk.language_detection import (
    LANGUAGE_BY_EXTENSION, all_languages, canonical_language,
    detect_language, language_matches)
from samverk.organization_members import OrgMembershipStore
from samverk.organizations import OrganizationStore
from samverk.repo_settings import RepoSettingsService
from samverk.repositories import RepositoryStore
from samverk.repository_search import RepositorySearch
from samverk.saved_searches import (
    SavedSearchError, SavedSearchStore)
from samverk.search_api import SearchAPI
from samverk.search_budgets import (
    HARDWARE_CLASSES, QUERY_KINDS, SearchBudgetError,
    budget_for, budget_report, corpus_spec, judge,
    measure_searches, render_search_budget_page, summarise)
from samverk.search_limits import (
    DOCUMENTED_CAPS, audit_search_limits, get_limit, limit_ids,
    render_search_limits_page)
from samverk.search_permissions import (
    may_read, visible_repositories)
from samverk.user_org_search import PeopleSearch, user_visible_to
from test_repo_home import GIT_ENV, run_git

PW = "correct horse battery"
THOR = ("A U Thor", "a@example.com")
SIGRUN = ("Sigrun Halvorsen", "sigrun@example.com")
KEEPER = ("Zorblax Keeper", "keeper@example.com")
LFS_POINTER = (
    b"version https://git-lfs.github.com/spec/v1\n"
    b"oid sha256:" + b"a" * 64 + b"\nsize 12345\n")


class Clock:
    def __init__(self):
        self.t = 1000

    def __call__(self):
        self.t += 1
        return self.t


def commit(work, filename, text, subject, body, author, when):
    path = work / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")
    run_git(work, "add", "-A")
    env = dict(os.environ)
    env.update(GIT_ENV)
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


def make_world(root: Path, with_secret: bool) -> SimpleNamespace:
    conn = db.init_db(root / "samverk.db")
    # One deterministic clock for every store in the
    # world, shared by both worlds: identical operation
    # sequences then carry identical timestamps, so the
    # API equivalence proof compares payloads whole —
    # a one-second wall-clock drift between the two
    # builds is a fixture artifact, not a leak channel.
    clock = Clock()
    accounts = AccountStore(conn, time_fn=clock)
    orgs = OrganizationStore(conn, accounts, time_fn=clock)
    owner = accounts.register("volmarr", PW)
    other = accounts.register("sigrun", PW)
    stranger = accounts.register("mallory", PW)
    admin = accounts.register("sitemod", PW)
    with conn:
        conn.execute(
            "UPDATE users SET is_admin = 1 WHERE id = ?", (admin.id,))
    admin = accounts.get_by_id(admin.id)
    repos = RepositoryStore(conn, root, accounts, time_fn=clock)
    settings = RepoSettingsService(
        conn, root, accounts, repos, time_fn=clock)
    audit = AuditLog(conn, time_fn=clock)
    issues = IssueStore(conn, repos, accounts, audit=audit,
                        time_fn=clock)
    indexer = CodeIndexer(conn, repos)
    index_store = SearchIndexStore(conn, repos)
    recents = RecentSearchStore(conn, time_fn=clock)
    w = SimpleNamespace(
        conn=conn, accounts=accounts, orgs=orgs, owner=owner,
        other=other, stranger=stranger, admin=admin, repos=repos,
        settings=settings, issues=issues, indexer=indexer,
        index_store=index_store, recents=recents, clock=clock,
        root=root,
        code=CodeSearch(conn, repos),
        backend=IssuePRSearch(conn, repos, index_store),
        repo_search=RepositorySearch(conn, repos),
        people=PeopleSearch(conn, orgs),
        commits=CommitSearch(conn, repos),
        web=GlobalSearch(conn, repos, orgs, recents=recents),
        api=SearchAPI(conn, repos, orgs))
    w.saved = SavedSearchStore(conn, w.web, time_fn=clock)
    w.health = IndexHealth(
        conn, accounts, index_store, audit=audit)

    def profile(user, display, bio):
        with conn:
            conn.execute(
                "INSERT INTO profiles (user_id, display_name, bio,"
                " updated_at) VALUES (?, ?, ?, 0)",
                (user.id, display, bio))

    profile(owner, "Volmarr Wyrd", "Forge keeper and hall skald")
    profile(other, "Sigrun Halvorsen", "Weaver of the great hall")
    profile(stranger, "Mallory Quinn", "Wandering cartographer")
    guild = orgs.create_organization(
        owner.id, "ForgeGuild", display_name="The Forge Guild",
        bio="Smiths and builders of the hall")
    OrgMembershipStore(conn, accounts, audit).add_member(
        owner.id, guild.id, other.id)

    def workdir(name):
        d = root / ("work-" + name)
        d.mkdir()
        run_git(d, "init", "-b", "main")
        return d

    # The public control repository: forge + quill content.
    repos.create_repository(
        owner.id, "volmarr", "anvil", visibility="public",
        description="Forge tools for the hall")
    settings.update_settings(
        owner.id, "volmarr", "anvil", topics=["build", "ci"])
    bare = repos.path_for("volmarr", "anvil")
    work = workdir("anvil")
    commit(work, "main.py",
           "print('forge one')\nquill one\nquill two quill\n",
           "Forge the anvil frame", "Hammer work begins",
           THOR, 1700000100)
    commit(work, "lib.py", "VALUE = 'forge'\n",
           "Forge the bellows", "Air for the forge",
           SIGRUN, 1700000200)
    commit(work, "notes.txt", "forge notes\n",
           "Forge the notes", "Paper for the forge",
           THOR, 1700000300)
    commit(work, "big.bin", LFS_POINTER,
           "Forge the pointer", "A pointer, honestly",
           SIGRUN, 1700000400)
    commit(work, "blob.bin", b"\x00\x01\x02binary\x00forge\n",
           "Forge the blob", "Binary, skipped",
           THOR, 1700000500)
    run_git(work, "push", str(bare), "main")
    w.anvil_work = work
    indexer.index_repository("volmarr", "anvil")
    issues.create_issue(owner, "volmarr", "anvil",
                        "Forge door sticks", "the forge door drags")
    issues.create_issue(owner, "volmarr", "anvil",
                        "Quill failure", "the quill broke")

    # The internal control repository: read, in the search
    # faces, by its owner and the site admin only.
    repos.create_repository(
        other.id, "sigrun", "loom", visibility="internal",
        description="Weaving patterns for the hall")
    bare = repos.path_for("sigrun", "loom")
    work = workdir("loom")
    commit(work, "loom.py", "loom shuttle\n",
           "Loom shuttle rhythm", "Threads for the hall",
           SIGRUN, 1700000600)
    run_git(work, "push", str(bare), "main")
    indexer.index_repository("sigrun", "loom")

    if with_secret:
        # The planted secret bundle: one private repository
        # whose description, topic, code, commit and issue
        # all carry the unique word, plus one suspended
        # account whose card carries it.
        repos.create_repository(
            owner.id, "volmarr", "vault", visibility="private",
            description="zorblax vault plans")
        settings.update_settings(
            owner.id, "volmarr", "vault", topics=["zorblax"])
        bare = repos.path_for("volmarr", "vault")
        work = workdir("vault")
        commit(work, "secret.py", "zorblax quill\nzorblax zorblax\n",
               "zorblax secret plans", "hidden zorblax body",
               KEEPER, 1700000700)
        run_git(work, "push", str(bare), "main")
        indexer.index_repository("volmarr", "vault")
        issues.create_issue(owner, "volmarr", "vault",
                            "Zorblax master plan", "zorblax quill secrets")
        zorkeeper = accounts.register("zorkeeper", PW)
        profile(zorkeeper, "Zorblax Keeper", "zorblax hoard keeper")
        with conn:
            conn.execute(
                "UPDATE users SET status = 'suspended' WHERE id = ?",
                (zorkeeper.id,))
        w.zorkeeper = accounts.get_by_id(zorkeeper.id)

    backend = IssuePRSearch(conn, repos, index_store)
    backend.index_all()
    w.backend = backend
    return w


def global_signature(results):
    """Per-group identity + totals, for the leakage
    equivalence proof (S-213's shape): groups in order,
    each group's hit identities and its own totals —
    never summed across groups."""
    out = []
    for group in results.groups:
        if group.kind == "repositories":
            ids = [h.full_name for h in group.hits]
        elif group.kind == "people":
            ids = [(h.kind, h.handle) for h in group.hits]
        elif group.kind == "commits":
            ids = [(h.full_name, h.subject) for h in group.hits]
        elif group.kind == "code":
            ids = [(h.full_name, h.path) for h in group.hits]
        else:
            ids = [(h.full_name, h.number, h.title)
                   for h in group.hits]
        out.append((group.kind, ids, group.total,
                    group.total_matches, group.total_matched_lines))
    return out


class PartXGateTests(unittest.TestCase):
    def setUp(self):
        self._tds = [tempfile.TemporaryDirectory(),
                     tempfile.TemporaryDirectory()]
        for td in self._tds:
            self.addCleanup(td.cleanup)
        self.a = make_world(Path(self._tds[0].name), with_secret=True)
        self.b = make_world(Path(self._tds[1].name), with_secret=False)
        self.addCleanup(self.a.conn.close)
        self.addCleanup(self.b.conn.close)

    # -- pins ---------------------------------------------------

    def test_pins_schema_99_taxonomy_131(self):
        self.assertEqual(schema_version(self.a.conn), 101)
        self.assertEqual(db.MIGRATIONS[-1][0], 101)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 131)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 85)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)

    # -- S-205: the index architecture --------------------------

    def test_index_catalog_is_closed_and_complete(self):
        self.assertEqual(
            tuple(KIND_SPECS), ("issue", "pull_request", "commit", "code"))
        for kind in KIND_SPECS:
            spec = spec_for(kind)
            self.assertEqual(spec.kind, kind)
            self.assertTrue(spec.fields)
            self.assertTrue(spec.triggers)
            self.assertTrue(spec.key_fields)
        with self.assertRaises(SearchIndexError) as ctx:
            spec_for("wiki")
        self.assertEqual(ctx.exception.reason, "kind_invalid")

    def test_plan_push_law(self):
        zero, one = "0" * 40, "1" * 40
        plans = plan_push("main", (
            RefUpdate("refs/heads/main", zero, one),))
        self.assertEqual(
            [(p.kind, p.trigger) for p in plans],
            [("commit", "push"), ("code", "push")])
        plans = plan_push("main", (
            RefUpdate("refs/heads/side", zero, one),))
        self.assertEqual([p.kind for p in plans], ["commit"])
        self.assertEqual(plan_push("main", (
            RefUpdate("refs/tags/v1", zero, one),)), ())
        self.assertEqual(plan_push("main", ()), ())

    def test_plan_mutation_law(self):
        self.assertEqual(
            [(p.kind, p.target) for p in plan_mutation("issue", "issue:12")],
            [("issue", "issue:12")])
        self.assertEqual(
            [p.kind for p in plan_mutation("pull_request", "pr:3")],
            ["pull_request"])
        for kind in ("commit", "code"):
            with self.assertRaises(SearchIndexError) as ctx:
                plan_mutation(kind, "x:1")
            self.assertEqual(ctx.exception.reason, "kind_invalid")
        with self.assertRaises(SearchIndexError) as ctx:
            plan_mutation("issue", "  ")
        self.assertEqual(ctx.exception.reason, "target_invalid")

    def test_code_disposition_law(self):
        cases = [
            (dict(size=10), ("index", "indexed")),
            (dict(size=10, is_lfs_pointer=True),
             ("index_pointer", "lfs_pointer")),
            (dict(size=10, is_submodule=True), ("skip", "submodule")),
            (dict(size=10, is_ignored=True), ("skip", "ignored")),
            (dict(size=10, is_binary=True), ("skip", "binary")),
            (dict(size=0), ("skip", "empty")),
            (dict(size=1048577), ("skip", "oversized")),
            (dict(size="big"), ("skip", "size_unknown")),
        ]
        for kwargs, expected in cases:
            with self.subTest(kwargs=kwargs):
                self.assertEqual(decide_code_disposition(**kwargs), expected)

    # -- S-207/S-206: indexing round trips ----------------------

    def test_code_index_round_trip(self):
        docs = self.a.indexer.documents_for("volmarr", "anvil")
        self.assertEqual(
            [d.path for d in docs],
            ["big.bin", "lib.py", "main.py", "notes.txt"])
        by_path = {d.path: d for d in docs}
        self.assertEqual(by_path["main.py"].language, "python")
        self.assertEqual(by_path["notes.txt"].language, "text")
        self.assertTrue(by_path["big.bin"].is_pointer)
        self.assertEqual(by_path["big.bin"].lfs_size, 12345)
        # The binary blob was judged and skipped, honestly.
        self.assertNotIn("blob.bin", by_path)
        # A delta pass over the same tip (S-207's index_tip,
        # the push seam) changes nothing and re-reads
        # nothing; index_repository itself is the full
        # rebuild, judged against an empty snapshot.
        tip = run_git(self.a.anvil_work, "rev-parse", "HEAD")
        report = self.a.indexer.index_tip("volmarr", "anvil", tip)
        self.assertEqual(report.changed, 0)
        # All five snapshot files stand unchanged — the
        # four indexed documents plus the binary blob,
        # whose skip judgement also stands unre-read.
        self.assertEqual(report.unchanged, 5)

    def test_code_index_follows_a_push(self):
        w = self.a
        bare = w.repos.path_for("volmarr", "anvil")
        old_tip = run_git(w.anvil_work, "rev-parse", "HEAD")
        new_tip = commit(w.anvil_work, "bellows.py", "zephyr bellows\n",
                         "Forge the zephyr bellows", "New air",
                         SIGRUN, 1700000800)
        run_git(w.anvil_work, "push", str(bare), "main")
        # The push seam itself (S-207's index_push over
        # S-205's plan): only the delta is indexed.
        report = w.indexer.index_push(
            "volmarr", "anvil",
            [RefUpdate("refs/heads/main", old_tip, new_tip)])
        self.assertIsNotNone(report)
        self.assertEqual(report.indexed, 1)
        self.assertEqual(report.changed, 1)
        hits = w.code.search(w.owner, "zephyr")
        self.assertEqual(
            [(h.full_name, h.path) for h in hits],
            [("volmarr/anvil", "bellows.py")])
        # A push that moves only a side branch does not
        # move the code index — index_push answers None.
        self.assertIsNone(w.indexer.index_push(
            "volmarr", "anvil",
            [RefUpdate("refs/heads/side", old_tip, new_tip)]))
        # A file the next push removes leaves the index too.
        run_git(w.anvil_work, "rm", "notes.txt")
        env = dict(os.environ)
        env.update(GIT_ENV)
        out = subprocess.run(
            ["git", "commit", "-m", "Drop the notes"],
            cwd=w.anvil_work, capture_output=True, env=env)
        self.assertEqual(out.returncode, 0, out.stderr.decode())
        drop_tip = run_git(w.anvil_work, "rev-parse", "HEAD")
        run_git(w.anvil_work, "push", str(bare), "main")
        report = w.indexer.index_push(
            "volmarr", "anvil",
            [RefUpdate("refs/heads/main", new_tip, drop_tip)])
        self.assertEqual(report.removed, 1)
        paths = [d.path for d in w.indexer.documents_for("volmarr", "anvil")]
        self.assertNotIn("notes.txt", paths)
        self.assertEqual(w.code.search(w.owner, "forge notes"), [])

    def test_issue_index_round_trip(self):
        w = self.a
        hits = w.backend.search(w.owner, "forge")
        self.assertEqual(
            [h.title for h in hits], ["Forge door sticks"])
        self.assertEqual(
            w.backend.count(w.owner, "forge"), 1)
        self.assertEqual(
            [h.title for h in w.backend.search(w.owner, "quill")],
            ["Quill failure", "Zorblax master plan"])
        # A newly created issue joins the search once the
        # index follows the mutation, and only then.
        w.issues.create_issue(w.owner, "volmarr", "anvil",
                              "Zephyr latch", "a zephyr latch sticks")
        self.assertEqual(w.backend.search(w.owner, "zephyr"), [])
        w.backend.index_all()
        self.assertEqual(
            [h.title for h in w.backend.search(w.owner, "zephyr")],
            ["Zephyr latch"])

    def test_lfs_pointer_is_indexed_as_a_pointer(self):
        hits = self.a.code.search(self.a.owner, "git-lfs")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].path, "big.bin")
        self.assertTrue(hits[0].is_pointer)

    # -- S-208: code search, executed ---------------------------

    def test_code_search_modes_paths_and_scope(self):
        w = self.a
        hits = w.code.search(w.owner, "forge")
        self.assertEqual(
            sorted(h.path for h in hits),
            ["lib.py", "main.py", "notes.txt"])
        regex = w.code.search(w.owner, "f.rge mode:regex")
        self.assertEqual(
            sorted(h.path for h in regex),
            ["lib.py", "main.py", "notes.txt"])
        pathed = w.code.search(w.owner, "forge path:lib.py")
        self.assertEqual([h.path for h in pathed], ["lib.py"])
        # A scoped search of a repository the viewer may
        # not read is the uniform not-found (S-209).
        with self.assertRaises(CodeSearchError) as ctx:
            w.code.search(w.owner, "forge repo:sigrun/loom")
        self.assertEqual(ctx.exception.reason, "repo_not_found")
        scoped = w.code.search(w.other, "shuttle repo:sigrun/loom")
        self.assertEqual([h.path for h in scoped], ["loom.py"])

    def test_language_filter_executes_the_fail_closed_alias_law(self):
        w = self.a
        hits = w.code.search(w.owner, "forge language:python")
        self.assertEqual(
            sorted(h.path for h in hits), ["lib.py", "main.py"])
        # The alias law (S-218): `py` resolves as a name
        # through canonical_language, but inside a filter
        # an alias matches NOTHING — fail closed, never a
        # silent widening to python.
        self.assertEqual(canonical_language("py"), "python")
        self.assertEqual(w.code.search(w.owner, "forge language:py"), [])
        self.assertEqual(
            w.code.search(w.owner, "forge language:klingon"), [])
        for recorded, filt, expected in [
                ("python", "python", True), ("python", "PYTHON", True),
                ("python", "py", False), ("python", "", True),
                ("python", "klingon", False)]:
            self.assertEqual(language_matches(recorded, filt), expected)

    def test_language_table_is_one_shared_table(self):
        from samverk import blob_view, code_indexing
        self.assertIs(
            blob_view.LANGUAGE_BY_EXTENSION, LANGUAGE_BY_EXTENSION)
        self.assertIs(code_indexing.detect_language, detect_language)
        self.assertEqual(detect_language("x.py", b""), "python")
        self.assertEqual(
            detect_language("Makefile", b"#!/usr/bin/env python\n"),
            "make")
        self.assertEqual(detect_language("x.unknownext", b"hi"), "text")
        self.assertIn("python", all_languages())
        self.assertIn("rust", all_languages())
        # The indexer's recorded language IS the table's
        # answer for the same file.
        docs = {d.path: d for d in
                self.a.indexer.documents_for("volmarr", "anvil")}
        self.assertEqual(
            docs["main.py"].language, detect_language("main.py", b""))

    # -- the leakage suite: S-209's law on every face -----------
    # For each face: the stranger's and the anonymous
    # visitor's hits and counts over world A (WITH the
    # secret) equal world B (secret never created).

    def test_leakage_code_face(self):
        for viewer_a, viewer_b in (
                (self.a.stranger, self.b.stranger), (None, None)):
            for query in ("zorblax", "quill"):
                with self.subTest(query=query):
                    ra = self.a.code.search_counted(viewer_a, query)
                    rb = self.b.code.search_counted(viewer_b, query)
                    self.assertEqual(
                        [(h.full_name, h.path) for h in ra.hits],
                        [(h.full_name, h.path) for h in rb.hits])
                    self.assertEqual(
                        (ra.total_files, ra.total_matches,
                         ra.total_matched_lines),
                        (rb.total_files, rb.total_matches,
                         rb.total_matched_lines))
        # The word exists in world A — for its owner.
        res = self.a.code.search_counted(self.a.owner, "zorblax")
        self.assertEqual(res.total_files, 1)
        self.assertGreater(res.total_matches, 0)

    def test_leakage_issue_face(self):
        for viewer_a, viewer_b in (
                (self.a.stranger, self.b.stranger), (None, None)):
            for query in ("zorblax", "quill"):
                with self.subTest(query=query):
                    ha = self.a.backend.search(viewer_a, query)
                    hb = self.b.backend.search(viewer_b, query)
                    self.assertEqual(
                        [(h.full_name, h.number, h.title) for h in ha],
                        [(h.full_name, h.number, h.title) for h in hb])
                    self.assertEqual(
                        self.a.backend.count(viewer_a, query),
                        self.b.backend.count(viewer_b, query))
        self.assertEqual(
            [h.title for h in self.a.backend.search(
                self.a.owner, "zorblax")],
            ["Zorblax master plan"])
        # A scoped search of the vault by a stranger is the
        # uniform not-found — never an empty list that
        # admits the repository exists.
        from samverk.issue_pr_search import SearchBackendError
        with self.assertRaises(SearchBackendError) as ctx:
            self.a.backend.search_repository(
                self.a.stranger, "volmarr", "vault", "zorblax")
        self.assertEqual(ctx.exception.reason, "repo_not_found")

    def test_leakage_repository_face(self):
        for viewer_a, viewer_b in (
                (self.a.stranger, self.b.stranger), (None, None)):
            for query in ("zorblax", "topic:zorblax", "vault"):
                with self.subTest(query=query):
                    ra = self.a.repo_search.search_counted(viewer_a, query)
                    rb = self.b.repo_search.search_counted(viewer_b, query)
                    self.assertEqual(
                        [h.full_name for h in ra.hits],
                        [h.full_name for h in rb.hits])
                    self.assertEqual(ra.total, rb.total)
            self.assertEqual(
                self.a.repo_search.directory_counted(viewer_a).total,
                self.b.repo_search.directory_counted(viewer_b).total)
        hit = self.a.repo_search.search(self.a.owner, "zorblax")
        self.assertEqual([h.full_name for h in hit], ["volmarr/vault"])
        self.assertEqual(hit[0].topics, ("zorblax",))

    def test_leakage_people_face(self):
        for viewer_a, viewer_b in (
                (self.a.stranger, self.b.stranger), (None, None)):
            for query in ("zorblax", "keeper"):
                with self.subTest(query=query):
                    ra = self.a.people.search_counted(viewer_a, query)
                    rb = self.b.people.search_counted(viewer_b, query)
                    self.assertEqual(
                        [(h.kind, h.handle) for h in ra.hits],
                        [(h.kind, h.handle) for h in rb.hits])
                    self.assertEqual(ra.total, rb.total)
        # The visibility law itself: a suspended account is
        # a directory fact only for itself and site admins.
        self.assertFalse(
            user_visible_to(self.a.stranger, self.a.zorkeeper.id,
                            "suspended"))
        self.assertFalse(
            user_visible_to(None, self.a.zorkeeper.id, "suspended"))
        self.assertTrue(
            user_visible_to(self.a.admin, self.a.zorkeeper.id,
                            "suspended"))
        self.assertTrue(
            user_visible_to(self.a.zorkeeper, self.a.zorkeeper.id,
                            "suspended"))
        admin_hits = self.a.people.search(self.a.admin, "zorblax")
        self.assertEqual(
            [(h.kind, h.handle) for h in admin_hits],
            [("user", "zorkeeper")])

    def test_leakage_commit_face(self):
        for viewer_a, viewer_b in (
                (self.a.stranger, self.b.stranger), (None, None)):
            for query in ("zorblax", "author:keeper"):
                with self.subTest(query=query):
                    ra = self.a.commits.search_counted(viewer_a, query)
                    rb = self.b.commits.search_counted(viewer_b, query)
                    self.assertEqual(
                        [(h.full_name, h.subject) for h in ra.hits],
                        [(h.full_name, h.subject) for h in rb.hits])
                    self.assertEqual(ra.total, rb.total)
        self.assertEqual(
            [h.subject for h in self.a.commits.search(
                self.a.owner, "zorblax")],
            ["zorblax secret plans"])
        with self.assertRaises(CommitSearchError) as ctx:
            self.a.commits.search_repository(
                self.a.stranger, "volmarr", "vault", "zorblax")
        self.assertEqual(ctx.exception.reason, "repo_not_found")

    def test_leakage_global_face(self):
        for viewer_a, viewer_b in (
                (self.a.stranger, self.b.stranger), (None, None)):
            for query in ("zorblax", "quill"):
                with self.subTest(query=query):
                    self.assertEqual(
                        global_signature(
                            self.a.web.search(viewer_a, query)),
                        global_signature(
                            self.b.web.search(viewer_b, query)))
        owner_sig = global_signature(
            self.a.web.search(self.a.owner, "zorblax"))
        self.assertEqual(
            [kind for kind, *_ in owner_sig], list(GROUP_ORDER))
        zorblax_groups = {
            kind: total for kind, _, total, *_ in owner_sig}
        self.assertGreater(zorblax_groups["repositories"], 0)
        self.assertGreater(zorblax_groups["commits"], 0)
        self.assertGreater(zorblax_groups["code"], 0)
        self.assertGreater(zorblax_groups["issues"], 0)

    def test_leakage_api_face(self):
        for viewer_a, viewer_b in (
                (self.a.stranger, self.b.stranger), (None, None)):
            for query in ("zorblax", "quill"):
                with self.subTest(query=query):
                    self.assertEqual(
                        self.a.api.search(viewer_a, query),
                        self.b.api.search(viewer_b, query))
        import json
        payload = json.loads(
            self.a.api.search_json(self.a.stranger, "zorblax"))
        payload.pop("query", None)
        self.assertNotIn("zorblax", json.dumps(payload))
        self.assertNotIn("vault", json.dumps(payload))
        owner_payload = self.a.api.search(self.a.owner, "zorblax")
        self.assertIn("vault", str(owner_payload))

    def test_leakage_rendered_pages_carry_no_secret(self):
        from samverk.code_search import render_code_search_page
        from samverk.global_search import render_global_search_page
        from samverk.issue_pr_search import render_backend_search_page
        from samverk.repository_search import (
            render_repository_search_page)
        w = self.a
        pages = [
            render_code_search_page(
                "zorblax", w.code.search(w.stranger, "zorblax")),
            render_backend_search_page(
                "zorblax", w.backend.search(w.stranger, "zorblax")),
            render_repository_search_page(
                "zorblax", w.repo_search.search(w.stranger, "zorblax")),
            render_global_search_page(
                w.web.search(w.stranger, "zorblax")),
        ]
        for page in pages:
            self.assertNotIn("vault", page)
            self.assertNotIn("Zorblax master plan", page)
            self.assertNotIn("secret.py", page)

    def test_internal_repository_gate_on_every_face(self):
        w = self.a
        # Read in the search faces by owner + site admin
        # only (S-054's gate, as S-210 recorded).
        for viewer in (w.stranger, None, w.owner):
            self.assertEqual(w.repo_search.search(viewer, "loom"), [])
            self.assertEqual(w.code.search(viewer, "shuttle"), [])
            self.assertEqual(w.commits.search(viewer, "loom"), [])
        # The global face over world A equals world B for
        # every viewer who may not read the internal repo —
        # the internal repository is not a leak channel.
        for viewer_a, viewer_b in (
                (w.stranger, self.b.stranger), (None, None),
                (w.owner, self.b.owner)):
            self.assertEqual(
                global_signature(w.web.search(viewer_a, "loom")),
                global_signature(self.b.web.search(viewer_b, "loom")))
        loom = w.repos.get_repository("sigrun", "loom")
        self.assertFalse(may_read(w.owner, loom))
        self.assertTrue(may_read(w.other, loom))
        self.assertTrue(may_read(w.admin, loom))
        self.assertEqual(
            [h.full_name for h in w.repo_search.search(w.other, "loom")],
            ["sigrun/loom"])
        self.assertEqual(
            [h.path for h in w.code.search(w.admin, "shuttle")],
            ["loom.py"])
        self.assertEqual(
            [r.name for r in visible_repositories(
                w.conn, w.repos, w.stranger)],
            ["anvil"])

    # -- the faces, walked functionally --------------------------

    def test_repository_search_fields_qualifiers_directory(self):
        w = self.a
        self.assertEqual(
            [h.full_name for h in w.repo_search.search(
                w.stranger, "forge")],
            ["volmarr/anvil"])
        self.assertEqual(
            [h.full_name for h in w.repo_search.search(
                w.stranger, "topic:build")],
            ["volmarr/anvil"])
        self.assertEqual(
            [h.full_name for h in w.repo_search.search(
                w.stranger, "owner:volmarr")],
            ["volmarr/anvil"])
        directory = w.repo_search.directory(w.stranger)
        self.assertEqual(
            [h.full_name for h in directory], ["volmarr/anvil"])
        owner_directory = w.repo_search.directory(w.owner)
        self.assertEqual(
            [h.full_name for h in owner_directory],
            ["volmarr/anvil", "volmarr/vault"])

    def test_people_search_cards_and_kinds(self):
        w = self.a
        hits = w.people.search(w.stranger, "forge")
        self.assertEqual(
            sorted((h.kind, h.handle) for h in hits),
            [("org", "ForgeGuild"), ("user", "volmarr")])
        users_only = w.people.search(w.stranger, "forge", kind="user")
        self.assertEqual(
            [(h.kind, h.handle) for h in users_only],
            [("user", "volmarr")])
        org_hit = [h for h in hits if h.kind == "org"][0]
        self.assertEqual(org_hit.display_name, "The Forge Guild")
        # The creator's own member row plus Sigrun, added
        # in the fixture: the card counts member rows.
        self.assertEqual(org_hit.member_count, 2)
        # No card carries an email, ever.
        for hit in w.people.directory(w.stranger):
            self.assertNotIn("@", hit.handle)
            self.assertFalse(hasattr(hit, "email"))

    def test_commit_search_author_scope_and_order(self):
        w = self.a
        hits = w.commits.search(w.stranger, "forge")
        self.assertEqual(
            [h.subject for h in hits],
            ["Forge the blob", "Forge the pointer",
             "Forge the notes", "Forge the bellows",
             "Forge the anvil frame"])
        thor = w.commits.search(w.stranger, "forge author:thor")
        self.assertEqual(
            sorted(h.subject for h in thor),
            ["Forge the anvil frame", "Forge the blob",
             "Forge the notes"])
        scoped = w.commits.search(
            w.stranger, "forge repo:volmarr/anvil sort:oldest")
        self.assertEqual(scoped[0].subject, "Forge the anvil frame")
        self.assertEqual(scoped[-1].subject, "Forge the blob")

    def test_global_groups_delegate_and_order(self):
        w = self.a
        results = w.web.search(w.owner, "forge")
        self.assertEqual(results.kinds, GROUP_ORDER)
        repos = results.group("repositories")
        self.assertEqual(
            [h.full_name for h in repos.hits], ["volmarr/anvil"])
        code = results.group("code")
        self.assertEqual(
            sorted(h.path for h in code.hits),
            ["lib.py", "main.py", "notes.txt"])
        issues = results.group("issues")
        self.assertEqual(
            [h.title for h in issues.hits], ["Forge door sticks"])
        narrowed = w.web.search(w.owner, "forge type:code")
        self.assertEqual(narrowed.kinds, ("code",))

    def test_recents_are_per_user_and_web_only(self):
        w = self.a
        w.web.search(w.owner, "forge")
        w.web.search(w.stranger, "bellows")
        self.assertEqual(
            [r.query for r in w.recents.list_recent(w.owner)],
            ["forge"])
        self.assertEqual(
            [r.query for r in w.recents.list_recent(w.stranger)],
            ["bellows"])
        # The API records nothing — not even for its caller.
        w.api.search(w.owner, "zephyr-token")
        self.assertEqual(
            [r.query for r in w.recents.list_recent(w.owner)],
            ["forge"])
        # An anonymous search records nothing at all.
        w.web.search(None, "forge")
        self.assertEqual(
            [r.query for r in w.recents.list_recent(w.owner)],
            ["forge"])

    def test_saved_searches_private_and_rerun_live(self):
        w = self.a
        saved = w.saved.save_search(w.owner, "Forge hunt", "forge")
        self.assertEqual(saved.query, "forge")
        self.assertEqual(
            [s.name for s in w.saved.list_searches(w.owner)],
            ["Forge hunt"])
        self.assertEqual(w.saved.list_searches(w.stranger), [])
        with self.assertRaises(SavedSearchError) as ctx:
            w.saved.get_search(w.stranger, "Forge hunt")
        self.assertEqual(ctx.exception.reason, "saved_not_found")
        before = w.saved.run_search(w.owner, "Forge hunt")
        self.assertEqual(before.group("issues").total, 1)
        # The re-run is live: a new indexed issue joins it.
        w.issues.create_issue(w.owner, "volmarr", "anvil",
                              "Forge latch", "the forge latch bends")
        w.backend.index_all()
        after = w.saved.run_search(w.owner, "Forge hunt")
        self.assertEqual(after.group("issues").total, 2)
        # And the saved face inherits the leakage law at
        # run time: the owner's own saved zorblax hunt is
        # the owner's — a stranger cannot even name it.
        w.saved.save_search(w.owner, "Secret hunt", "zorblax")
        run = w.saved.run_search(w.owner, "Secret hunt")
        self.assertGreater(run.group("repositories").total, 0)
        with self.assertRaises(SavedSearchError):
            w.saved.run_search(w.stranger, "Secret hunt")

    # -- S-215: index health, honest about lag -------------------

    def test_index_health_admin_only(self):
        w = self.a
        with self.assertRaises(IndexHealthError) as ctx:
            w.health.instance_health(w.stranger.id)
        self.assertEqual(ctx.exception.reason, "not_site_admin")
        with self.assertRaises(IndexHealthError) as ctx:
            w.health.instance_health(999999)
        self.assertEqual(ctx.exception.reason, "no_such_user")
        with self.assertRaises(IndexHealthError) as ctx:
            w.health.repo_health(w.owner.id, "volmarr", "anvil")
        self.assertEqual(ctx.exception.reason, "not_site_admin")
        health = w.health.instance_health(w.admin.id)
        self.assertEqual(
            [r.full_name for r in health.repos],
            ["sigrun/loom", "volmarr/anvil", "volmarr/vault"])

    def test_index_health_current_after_indexing(self):
        w = self.a
        # The extractor has filled the registry (4 code
        # documents), but no S-205 job has completed, so
        # the state honestly reads `never` — documents and
        # job-currency are different facts, and the health
        # face shows both without confusing them.
        health = w.health.repo_health(w.admin.id, "volmarr", "anvil")
        states = {s.kind: s for s in health.states}
        self.assertEqual(states["code"].document_count, 4)
        self.assertEqual(states["code"].status, "never")
        self.assertEqual(health.pending, 0)
        self.assertEqual(health.lag_seconds, 0)
        page = render_repo_index_health_page(health)
        self.assertIn("Index lag: 0 seconds", page)
        # Walk the queue lifecycle through its public
        # seams: enqueue the push plan, claim and complete
        # each job — now the kinds read current, with the
        # high-water mark at the tip the jobs carried.
        tip = run_git(w.anvil_work, "rev-parse", "HEAD")
        jobs = w.index_store.enqueue_push(
            "volmarr", "anvil",
            [RefUpdate("refs/heads/main", "0" * 40, tip)])
        self.assertEqual(
            sorted(j.kind for j in jobs), ["code", "commit"])
        while True:
            job = w.index_store.claim_next()
            if job is None:
                break
            w.index_store.complete_job(job.id, high_water=tip)
        health = w.health.repo_health(w.admin.id, "volmarr", "anvil")
        states = {s.kind: s for s in health.states}
        self.assertTrue(states["code"].is_current)
        self.assertTrue(states["commit"].is_current)
        self.assertEqual(states["code"].high_water, tip)
        self.assertEqual(states["code"].document_count, 4)

    def test_index_health_lag_is_shown_and_rebuild_audited(self):
        w = self.a
        before = w.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log"
            " WHERE action = 'admin.index.rebuild'").fetchone()["n"]
        jobs = w.health.request_rebuild(w.admin.id, "volmarr", "anvil")
        self.assertTrue(jobs)
        after = w.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log"
            " WHERE action = 'admin.index.rebuild'").fetchone()["n"]
        self.assertEqual(after, before + 1)
        # Read the same repository two hours later: the
        # waiting work is still waiting, and the lag is
        # SAID — in the record and on the page.
        late = IndexHealth(
            w.conn, w.accounts, w.index_store, audit=None,
            time_fn=lambda: time.time() + 7200)
        health = late.repo_health(w.admin.id, "volmarr", "anvil")
        self.assertGreaterEqual(health.pending, 1)
        self.assertGreaterEqual(health.lag_seconds, 7000)
        page = render_repo_index_health_page(health)
        self.assertIn(f"Index lag: {health.lag_seconds} seconds", page)
        with self.assertRaises(IndexHealthError) as ctx:
            w.health.request_rebuild(w.stranger.id, "volmarr", "anvil")
        self.assertEqual(ctx.exception.reason, "not_site_admin")

    # -- S-217/S-219: budgets and limits, stated honestly --------

    def test_budgets_stated_per_class_and_refusals_named(self):
        for hardware in HARDWARE_CLASSES:
            for kind in QUERY_KINDS:
                self.assertGreater(budget_for(hardware, kind), 0)
        with self.assertRaises(SearchBudgetError) as ctx:
            budget_for("pi_class_arm", "semantic")
        self.assertEqual(ctx.exception.reason, "query_kind_unknown")
        with self.assertRaises(SearchBudgetError) as ctx:
            budget_for("quantum", "substring")
        self.assertEqual(ctx.exception.reason, "budget_unknown")
        summary = summarise([10.0, 20.0, 30.0])
        self.assertEqual(summary.count, 3)
        self.assertTrue(judge(summary, 1000.0))
        self.assertFalse(judge(summary, 1.0))

    def test_budget_report_marks_unmeasured_classes_unproven(self):
        w = self.a
        measurements = measure_searches(
            w.code, w.owner, repetitions=2,
            hardware="laptop_x86_64")
        self.assertEqual(len(measurements), 3)
        for m in measurements:
            self.assertEqual(m.hardware_class, "laptop_x86_64")
            self.assertEqual(m.summary.count, 2)
            self.assertEqual(
                m.within_budget, judge(m.summary, m.budget_ms))
        report = budget_report(measurements, corpus_spec())
        self.assertEqual(
            report["classes"]["laptop_x86_64"]["status"], "measured")
        # Pi-class is STATED in S-217 but was not measured
        # by this battery (it runs on a laptop): the report
        # says so, in data and on the page — never borrowed.
        self.assertEqual(
            report["classes"]["pi_class_arm"],
            {"status": "unmeasured", "within_budget": None})
        page = render_search_budget_page(report)
        self.assertIn("pi_class_arm: unmeasured — NOT PROVEN", page)
        self.assertIn("laptop_x86_64", page)

    def test_limits_document_audits_honest_against_the_engines(self):
        audit = audit_search_limits()
        self.assertTrue(audit.honestly_stated)
        self.assertEqual(audit.caps_checked, len(DOCUMENTED_CAPS))
        self.assertEqual(audit.caps_matching, audit.caps_checked)
        self.assertEqual(audit.cap_mismatches, ())
        self.assertEqual(audit.offending_hit_fields, ())
        self.assertFalse(audit.regex_has_timeout)
        ids = limit_ids()
        self.assertEqual(len(ids), 10)
        for limit_id in ids:
            self.assertTrue(get_limit(limit_id).statement)
        page = render_search_limits_page(audit)
        self.assertIn("No meaning search", page)
        self.assertIn("No relevance ranking", page)

    # -- the whole system: searching writes nothing --------------

    def test_searching_writes_nothing(self):
        w = self.a

        def counts():
            return (
                w.conn.execute(
                    "SELECT COUNT(*) AS n FROM audit_log"
                    ).fetchone()["n"],
                w.conn.execute(
                    "SELECT COUNT(*) AS n FROM repositories"
                    ).fetchone()["n"],
                w.conn.execute(
                    "SELECT COUNT(*) AS n FROM users"
                    ).fetchone()["n"],
                w.conn.execute(
                    "SELECT COUNT(*) AS n FROM saved_searches"
                    ).fetchone()["n"])

        before = counts()
        w.code.search(w.owner, "forge")
        w.code.search_counted(w.stranger, "zorblax")
        w.backend.search(w.owner, "forge")
        w.repo_search.search(w.owner, "forge")
        w.repo_search.directory(w.admin)
        w.people.search(w.owner, "forge")
        w.commits.search(w.owner, "forge")
        w.web.search(None, "forge")
        w.api.search(w.owner, "forge")
        w.health.instance_health(w.admin.id)
        self.assertEqual(counts(), before)

    def test_visible_repositories_is_the_one_resolution(self):
        w = self.a
        names = lambda v: [r.name for r in visible_repositories(
            w.conn, w.repos, v)]
        self.assertEqual(names(w.owner), ["anvil", "vault"])
        self.assertEqual(names(w.admin), ["anvil", "loom", "vault"])
        self.assertEqual(names(w.other), ["anvil", "loom"])
        self.assertEqual(names(w.stranger), ["anvil"])
        self.assertEqual(names(None), ["anvil"])
