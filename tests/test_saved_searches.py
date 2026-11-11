"""S-214 acceptance battery: saved searches.

Acceptance (roadmap S-214): Saved searches — beyond
issue filters (S-136): any global query saved and
re-runnable.

The planted secret is deliberate bait, in the S-209 /
S-213 shape: a private repository (`vault`) whose
description, only commit, only code file, and only
issue all carry the unique word `zorblax`. A saved
search stores only its query text, so the centre is
the run-time proof: a stranger who saves `zorblax`
and re-runs it sees exactly what the same saved
search sees in a world where the private repository
was never created — nothing — while its owner finds
it in its groups. Results are never cached: a
repository created after the save appears on the
rerun.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import os, subprocess, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.code_indexing import CodeIndexer
from samverk.db import schema_version
from samverk.global_search import GROUP_ORDER, GlobalSearch
from samverk.index_architecture import SearchIndexStore
from samverk.issue_pr_search import IssuePRSearch
from samverk.issues import IssueStore
from samverk.organizations import OrganizationStore
from samverk.repositories import RepositoryStore
from samverk.saved_searches import (
    NAME_MAX, SAVED_LIMIT, SavedSearchError, SavedSearchStore,
    render_saved_searches)
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
    plain = GlobalSearch(conn, repos, orgs)
    clock = Clock()
    w = SimpleNamespace(
        conn=conn, accounts=accounts, orgs=orgs, owner=owner,
        other=other, stranger=stranger, repos=repos, issues=issues,
        search=plain, clock=clock,
        saved=SavedSearchStore(conn, plain, time_fn=clock))

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


def signature(results):
    """Per-group identity + totals, for the leakage
    equivalence proof (the S-213 shape): groups in
    order, each group's hit identities and its own
    total — never summed."""
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


class PinsTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.conn = db.init_db(Path(self._td.name) / "samverk.db")
        self.addCleanup(self.conn.close)

    def test_pins_schema_99_taxonomy_133(self):
        self.assertEqual(schema_version(self.conn), 109)
        self.assertEqual(db.MIGRATIONS[-1][0], 109)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 133)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 87)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        tables = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertIn("saved_searches", tables)
        self.assertIn("saved_filters", tables)
        self.assertIn("recent_searches", tables)

    def test_fresh_database_migrates_to_93(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.init_db(Path(td) / "fresh.db")
            self.assertEqual(db.schema_version(conn), 109)
            conn.close()

    def test_upgrade_from_83_creates_saved_searches(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "old.db"
            conn = db.connect(path)
            for target, statements in db.MIGRATIONS:
                if target > 83:
                    continue
                with conn:
                    for stmt in statements:
                        conn.execute(stmt)
                    conn.execute(
                        "INSERT OR REPLACE INTO schema_meta"
                        " (key, value) VALUES ('version', ?)",
                        (str(target),))
            self.assertEqual(db.schema_version(conn), 83)
            self.assertEqual(db.migrate(conn), 109)
            names = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")}
            self.assertIn("saved_searches", names)
            conn.close()


class SavedSearchTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.a = make_world(Path(self._td.name), with_secret=True)
        self.addCleanup(self.a.conn.close)

    def test_save_list_in_name_order_and_fields(self):
        store, owner = self.a.saved, self.a.owner
        store.save_search(owner, "beta", "anvil")
        saved = store.save_search(
            owner, "  Alpha  ", "  Forge type:code  ")
        store.save_search(owner, "gamma", "bellows")
        self.assertEqual(saved.name, "Alpha")
        self.assertEqual(saved.query, "Forge type:code")
        self.assertEqual(saved.user_id, owner.id)
        self.assertEqual(saved.created_at, saved.updated_at)
        self.assertEqual(
            [s.name for s in store.list_searches(owner)],
            ["Alpha", "beta", "gamma"])
        got = store.get_search(owner, "ALPHA")
        self.assertEqual(got.id, saved.id)

    def test_names_unique_per_user_case_insensitive(self):
        store = self.a.saved
        store.save_search(self.a.owner, "Mine", "forge")
        with self.assertRaises(SavedSearchError) as ctx:
            store.save_search(self.a.owner, "MINE", "anvil")
        self.assertEqual(ctx.exception.reason, "name_taken")
        # The same name is free for another account.
        store.save_search(self.a.stranger, "mine", "anvil")
        self.assertEqual(
            [s.name for s in store.list_searches(self.a.stranger)],
            ["mine"])

    def test_searches_are_personal_every_face(self):
        store, owner, stranger = (
            self.a.saved, self.a.owner, self.a.stranger)
        store.save_search(owner, "Mine", "forge")
        self.assertEqual(store.list_searches(stranger), [])
        faces = (
            lambda: store.get_search(stranger, "Mine"),
            lambda: store.rename_search(stranger, "Mine", "His"),
            lambda: store.update_search(stranger, "Mine", "anvil"),
            lambda: store.delete_search(stranger, "Mine"),
            lambda: store.run_search(stranger, "Mine"))
        for face in faces:
            with self.assertRaises(SavedSearchError) as ctx:
                face()
            self.assertEqual(ctx.exception.reason, "saved_not_found")
        # The owner's search stands untouched by all of it.
        self.assertEqual(store.get_search(owner, "Mine").query, "forge")

    def test_signed_in_only_every_face(self):
        store = self.a.saved
        store.save_search(self.a.owner, "Mine", "forge")
        for actor in (None, "mallory", 42):
            faces = (
                lambda: store.save_search(actor, "X", "forge"),
                lambda: store.list_searches(actor),
                lambda: store.get_search(actor, "Mine"),
                lambda: store.rename_search(actor, "Mine", "Y"),
                lambda: store.update_search(actor, "Mine", "anvil"),
                lambda: store.delete_search(actor, "Mine"),
                lambda: store.run_search(actor, "Mine"))
            for face in faces:
                with self.assertRaises(SavedSearchError) as ctx:
                    face()
                self.assertEqual(
                    ctx.exception.reason, "auth_required")

    def test_invalid_queries_refused_at_save(self):
        store, owner = self.a.saved, self.a.owner
        bad_queries = (
            "", "   ", None, 42, "type:code",
            "forge type:code -type:code", "x" * 501,
            "a\x01b", '"unterminated')
        for bad in bad_queries:
            with self.assertRaises(SavedSearchError) as ctx:
                store.save_search(owner, "Bad", bad)
            self.assertEqual(ctx.exception.reason, "query_invalid", bad)
        with self.assertRaises(SavedSearchError) as ctx:
            store.save_search(owner, "Bad", "forge author:thor")
        self.assertEqual(ctx.exception.reason, "query_invalid")
        self.assertIn("author", str(ctx.exception))
        self.assertEqual(store.list_searches(owner), [])

    def test_name_refusals(self):
        store, owner = self.a.saved, self.a.owner
        for bad in ("", "   ", None, 42):
            with self.assertRaises(SavedSearchError) as ctx:
                store.save_search(owner, bad, "forge")
            self.assertEqual(ctx.exception.reason, "name_required", bad)
        for bad in ("x" * (NAME_MAX + 1), "a\x01b"):
            with self.assertRaises(SavedSearchError) as ctx:
                store.save_search(owner, bad, "forge")
            self.assertEqual(ctx.exception.reason, "name_invalid", bad)
        self.assertEqual(store.list_searches(owner), [])

    def test_cap_refuses_never_prunes_and_is_per_user(self):
        store, owner = self.a.saved, self.a.owner
        for i in range(SAVED_LIMIT):
            store.save_search(owner, f"q-{i:02d}", "forge")
        self.assertEqual(len(store.list_searches(owner)), SAVED_LIMIT)
        with self.assertRaises(SavedSearchError) as ctx:
            store.save_search(owner, "one-too-many", "forge")
        self.assertEqual(ctx.exception.reason, "saved_limit_reached")
        # Nothing was evicted to make room, and the cap
        # is this user's alone.
        self.assertEqual(len(store.list_searches(owner)), SAVED_LIMIT)
        store.save_search(self.a.stranger, "one-too-many", "forge")
        store.delete_search(owner, "q-00")
        store.save_search(owner, "one-too-many", "forge")
        self.assertEqual(len(store.list_searches(owner)), SAVED_LIMIT)

    def test_rename_keeps_query_and_creation(self):
        store, owner = self.a.saved, self.a.owner
        saved = store.save_search(owner, "Old", "forge")
        store.save_search(owner, "Taken", "anvil")
        renamed = store.rename_search(owner, "old", "New")
        self.assertEqual(renamed.name, "New")
        self.assertEqual(renamed.query, "forge")
        self.assertEqual(renamed.created_at, saved.created_at)
        self.assertGreater(renamed.updated_at, saved.updated_at)
        with self.assertRaises(SavedSearchError) as ctx:
            store.get_search(owner, "Old")
        self.assertEqual(ctx.exception.reason, "saved_not_found")
        # Recasing one's own name is a rename, not a clash.
        recased = store.rename_search(owner, "New", "NEW")
        self.assertEqual(recased.name, "NEW")
        with self.assertRaises(SavedSearchError) as ctx:
            store.rename_search(owner, "NEW", "taken")
        self.assertEqual(ctx.exception.reason, "name_taken")
        with self.assertRaises(SavedSearchError) as ctx:
            store.rename_search(owner, "Missing", "Other")
        self.assertEqual(ctx.exception.reason, "saved_not_found")
        with self.assertRaises(SavedSearchError) as ctx:
            store.rename_search(owner, "NEW", "")
        self.assertEqual(ctx.exception.reason, "name_required")
        self.assertEqual(store.get_search(owner, "new").name, "NEW")

    def test_update_replaces_query_validated(self):
        store, owner = self.a.saved, self.a.owner
        saved = store.save_search(owner, "Hunt", "forge")
        updated = store.update_search(owner, "hunt", "anvil")
        self.assertEqual(updated.query, "anvil")
        self.assertEqual(updated.name, "Hunt")
        self.assertEqual(updated.created_at, saved.created_at)
        self.assertGreater(updated.updated_at, saved.updated_at)
        with self.assertRaises(SavedSearchError) as ctx:
            store.update_search(owner, "Hunt", "forge author:thor")
        self.assertEqual(ctx.exception.reason, "query_invalid")
        # A refused update leaves the stored query whole.
        self.assertEqual(store.get_search(owner, "Hunt").query, "anvil")
        with self.assertRaises(SavedSearchError) as ctx:
            store.update_search(owner, "Missing", "forge")
        self.assertEqual(ctx.exception.reason, "saved_not_found")

    def test_delete_and_missing_refused(self):
        store, owner = self.a.saved, self.a.owner
        store.save_search(owner, "Mine", "forge")
        store.delete_search(owner, "MINE")
        self.assertEqual(store.list_searches(owner), [])
        with self.assertRaises(SavedSearchError) as ctx:
            store.delete_search(owner, "Mine")
        self.assertEqual(ctx.exception.reason, "saved_not_found")

    def test_rerun_executes_the_global_search(self):
        store, owner = self.a.saved, self.a.owner
        store.save_search(owner, "Everything forge", "forge")
        results = store.run_search(owner, "everything forge")
        self.assertEqual(results.kinds, GROUP_ORDER)
        self.assertEqual(results.query, "forge")
        self.assertEqual(
            [h.full_name for h in results.group("repositories").hits],
            ["volmarr/anvil"])
        self.assertEqual(results.group("issues").total, 2)

    def test_rerun_honours_the_saved_type_selection(self):
        store, owner = self.a.saved, self.a.owner
        store.save_search(owner, "Code only", "forge type:code")
        results = store.run_search(owner, "Code only")
        self.assertEqual(results.kinds, ("code",))
        self.assertEqual(results.group("code").total, 2)
        updated = store.update_search(owner, "Code only", "forge")
        self.assertEqual(updated.query, "forge")
        results = store.run_search(owner, "Code only")
        self.assertEqual(results.kinds, GROUP_ORDER)

    def test_rerun_is_live_not_cached(self):
        store, owner = self.a.saved, self.a.owner
        store.save_search(owner, "Repos", "forge type:repositories")
        first = store.run_search(owner, "Repos")
        self.assertEqual(
            [h.full_name for h in first.group("repositories").hits],
            ["volmarr/anvil"])
        # A repository born after the save is found by
        # the rerun: the store held text, not results.
        self.a.repos.create_repository(
            owner.id, "volmarr", "forgeworks", visibility="public",
            description="More forge tools for the hall")
        second = store.run_search(owner, "Repos")
        self.assertEqual(
            sorted(h.full_name
                   for h in second.group("repositories").hits),
            ["volmarr/anvil", "volmarr/forgeworks"])

    def test_saved_searches_write_no_audit(self):
        store, owner = self.a.saved, self.a.owner
        before = self.a.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
        store.save_search(owner, "Mine", "forge")
        store.rename_search(owner, "Mine", "Yours")
        store.update_search(owner, "Yours", "anvil")
        store.run_search(owner, "Yours")
        store.delete_search(owner, "Yours")
        after = self.a.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
        self.assertEqual(before, after)

    def test_render_lists_escaped_rerun_links(self):
        store, owner = self.a.saved, self.a.owner
        store.save_search(owner, "Open <bugs>", "forge type:code")
        html = render_saved_searches(store.list_searches(owner))
        self.assertIn("Open &lt;bugs&gt;", html)
        self.assertNotIn("Open <bugs>", html)
        self.assertIn('href="/search?q=forge+type%3Acode"', html)
        self.assertIn("forge type:code", html)
        self.assertIn("No saved searches yet",
                      render_saved_searches([]))


class LeakageTests(unittest.TestCase):
    def setUp(self):
        self._tds = [tempfile.TemporaryDirectory(),
                     tempfile.TemporaryDirectory()]
        for td in self._tds:
            self.addCleanup(td.cleanup)
        self.a = make_world(Path(self._tds[0].name), with_secret=True)
        self.b = make_world(Path(self._tds[1].name), with_secret=False)
        self.addCleanup(self.a.conn.close)
        self.addCleanup(self.b.conn.close)

    def test_stranger_rerun_invisible_everywhere(self):
        for world in (self.a, self.b):
            world.saved.save_search(
                world.stranger, "Secret hunt", "zorblax")
            results = world.saved.run_search(
                world.stranger, "Secret hunt")
            self.assertEqual(results.kinds, GROUP_ORDER)
            for group in results.groups:
                self.assertEqual(group.hits, (), group.kind)
                self.assertEqual(group.total, 0, group.kind)
                self.assertEqual(group.total_matches, 0, group.kind)

    def test_stranger_rerun_equivalence(self):
        for world in (self.a, self.b):
            world.saved.save_search(
                world.stranger, "Secret hunt", "zorblax")
            world.saved.save_search(
                world.stranger, "Forge hunt", "forge")
        for name in ("Secret hunt", "Forge hunt"):
            left = signature(self.a.saved.run_search(
                self.a.stranger, name))
            right = signature(self.b.saved.run_search(
                self.b.stranger, name))
            self.assertEqual(left, right, name)

    def test_owner_rerun_finds_the_secret(self):
        self.a.saved.save_search(
            self.a.owner, "Secret hunt", "zorblax")
        results = self.a.saved.run_search(
            self.a.owner, "Secret hunt")
        self.assertEqual(
            [h.full_name for h in results.group("repositories").hits],
            ["volmarr/vault"])
        self.assertEqual(
            [h.subject for h in results.group("commits").hits],
            ["zorblax secret plans"])
        self.assertEqual(
            [h.path for h in results.group("code").hits],
            ["secret.py"])
        self.assertEqual(
            [h.title for h in results.group("issues").hits],
            ["Zorblax master plan"])
        self.assertEqual(results.group("people").total, 0)


if __name__ == "__main__":
    unittest.main()
