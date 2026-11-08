"""S-212 acceptance battery: commit search.

Acceptance (roadmap S-212): Commit search — by
message and author across permitted repos.

The planted secret is deliberate bait, in the
S-209 shape: a private repository (`vault`) whose
only commit carries the unique word `zorblax` in
its subject, its body, and its author's name, so
any leak channel — history read before filtering,
a count tallied before filtering, a page rendered
from unfiltered hits — moves a string or a number
this battery watches. The centre is the
equivalence proof: a stranger's hits and counts
over a world WITH the private repository equal,
exactly, the same search over a world where it
was never created.

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
from samverk.commit_list import CommitSummary
from samverk.commit_search import (
    CommitHit, CommitSearch, CommitSearchError, commit_matches_query,
    matched_fields, parse_commit_query, render_commit_search_page)
from samverk.db import schema_version
from samverk.repositories import RepositoryStore
from test_repo_home import GIT_ENV, run_git

PW = "correct horse battery"
THOR = ("A U Thor", "a@example.com")
SIGRUN = ("Sigrun Halvorsen", "sigrun@example.com")
KEEPER = ("Zorblax Keeper", "keeper@example.com")
EVE = ("Eve Markup", "eve@example.com")


def commit(work, filename, text, subject, body, author, when):
    (work / filename).write_text(text, encoding="utf-8")
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


def make_world(root: Path, with_secret: bool) -> SimpleNamespace:
    conn = db.init_db(root / "samverk.db")
    accounts = AccountStore(conn)
    owner = accounts.register("volmarr", PW)
    other = accounts.register("sigrun", PW)
    stranger = accounts.register("mallory", PW)
    admin = accounts.register("admina", PW)
    conn.execute(
        "UPDATE users SET is_admin = 1 WHERE username_lower = 'admina'")
    conn.commit()
    admin = accounts.get_by_id(admin.id)
    repos = RepositoryStore(conn, root, accounts)
    w = SimpleNamespace(
        conn=conn, accounts=accounts, owner=owner, other=other,
        stranger=stranger, admin=admin, repos=repos,
        search=CommitSearch(conn, repos), oids={})

    def workdir(name):
        d = root / ("work-" + name); d.mkdir()
        run_git(d, "init", "-b", "main")
        return d

    repos.create_repository(
        owner.id, "volmarr", "anvil", visibility="public")
    bare = repos.path_for("volmarr", "anvil")
    work = workdir("anvil")
    w.oids["anvil-1"] = commit(
        work, "f1.txt", "one\n", "Forge the anvil frame",
        "Hammer work begins", THOR, 1700000100)
    run_git(work, "checkout", "-b", "side")
    w.oids["anvil-side"] = commit(
        work, "s1.txt", "side\n", "Side branch experiment",
        "Off the main line", THOR, 1700000400)
    run_git(work, "push", str(bare), "side")
    run_git(work, "checkout", "main")
    w.oids["anvil-2"] = commit(
        work, "f2.txt", "two\n", "Temper the steel <carefully>",
        "Quench in oil", SIGRUN, 1700000200)
    w.oids["anvil-3"] = commit(
        work, "f3.txt", "three\n", "Polish the horn",
        "Final shine for the forge", THOR, 1700000300)
    w.oids["anvil-5"] = commit(
        work, "f5.txt", "five\n", "Markup in the message <b>bold</b>",
        "Body with <i>tags</i>", EVE, 1700000700)
    run_git(work, "push", str(bare), "main")

    repos.create_repository(
        owner.id, "volmarr", "attic", visibility="private")
    bare = repos.path_for("volmarr", "attic")
    work = workdir("attic")
    w.oids["attic-1"] = commit(
        work, "m.txt", "maps\n", "Store old maps",
        "Charts of the north", THOR, 1700000050)
    run_git(work, "push", str(bare), "main")

    if with_secret:
        repos.create_repository(
            owner.id, "volmarr", "vault", visibility="private")
        bare = repos.path_for("volmarr", "vault")
        work = workdir("vault")
        w.oids["vault-1"] = commit(
            work, "v.txt", "secret\n", "zorblax secret plans",
            "hidden zorblax body", KEEPER, 1700000500)
        run_git(work, "push", str(bare), "main")

    repos.create_repository(
        other.id, "sigrun", "loom", visibility="internal")
    bare = repos.path_for("sigrun", "loom")
    work = workdir("loom")
    w.oids["loom-1"] = commit(
        work, "l.txt", "loom\n", "Weave the loom pattern",
        "Warp and weft", SIGRUN, 1700000600)
    run_git(work, "push", str(bare), "main")

    repos.create_repository(
        owner.id, "volmarr", "empty", visibility="public")
    return w


def subjects(hits):
    return [h.subject for h in hits]


def signature(hits):
    return [(h.full_name, h.subject, h.author_email) for h in hits]


class PureLawTests(unittest.TestCase):
    def test_parse_terms_and_qualifiers(self):
        q = parse_commit_query(
            "forge author:Thor repo:Volmarr/Anvil sort:oldest")
        self.assertEqual(q.terms, ("forge",))
        self.assertEqual(q.authors, ("thor",))
        self.assertEqual(q.repo_scope, ("volmarr", "anvil"))
        self.assertEqual(q.sort, "oldest")
        self.assertFalse(q.is_empty)

    def test_parse_quoted_phrase_and_quoted_author(self):
        q = parse_commit_query('"anvil frame" author:"A U Thor"')
        self.assertEqual(q.terms, ("anvil frame",))
        self.assertEqual(q.authors, ("a u thor",))

    def test_parse_negated_and_repeated_author(self):
        q = parse_commit_query("forge -author:mallory")
        self.assertEqual(q.terms, ("forge",))
        self.assertEqual(q.not_authors, ("mallory",))
        q = parse_commit_query("author:a author:b")
        self.assertEqual(q.authors, ("a", "b"))

    def test_parse_empty_shapes(self):
        self.assertTrue(parse_commit_query("").is_empty)
        self.assertTrue(parse_commit_query(None).is_empty)
        self.assertFalse(parse_commit_query("repo:a/b").is_empty)
        self.assertFalse(parse_commit_query("author:thor").is_empty)
        self.assertFalse(parse_commit_query("-author:thor").is_empty)

    def test_parse_unknown_qualifier_refused_by_name(self):
        with self.assertRaises(CommitSearchError) as ctx:
            parse_commit_query("hello language:python")
        self.assertEqual(ctx.exception.reason, "query_invalid")
        self.assertIn("language", str(ctx.exception))

    def test_parse_bad_values_refused(self):
        for bad in ("author:", "repo:", "repo:justname", "repo:a/b/c",
                    "repo:a/b repo:c/d", "sort:size",
                    "sort:newest sort:oldest", "-repo:a/b",
                    "-sort:newest", "-forge", '"unterminated'):
            with self.assertRaises(CommitSearchError) as ctx:
                parse_commit_query(bad)
            self.assertEqual(ctx.exception.reason, "query_invalid", bad)

    def test_parse_overlong_control_and_nonstr_refused(self):
        for bad in ("x" * 501, "a\x01b", 42):
            with self.assertRaises(CommitSearchError) as ctx:
                parse_commit_query(bad)
            self.assertEqual(ctx.exception.reason, "query_invalid")

    def test_matches_and_fields_pure(self):
        summary = CommitSummary(
            oid="abc", parents=(), author_name="A U Thor",
            author_email="a@example.com", author_time=1,
            subject="Forge the frame", body="Hammer work")
        self.assertTrue(commit_matches_query(
            summary, parse_commit_query("forge")))
        self.assertEqual(matched_fields(
            summary, parse_commit_query("forge")), ("message",))
        self.assertEqual(matched_fields(
            summary, parse_commit_query("thor")), ("author",))
        both = parse_commit_query("hammer thor")
        self.assertTrue(commit_matches_query(summary, both))
        self.assertEqual(matched_fields(summary, both),
                         ("message", "author"))
        self.assertFalse(commit_matches_query(
            summary, parse_commit_query("forge quench")))
        self.assertTrue(commit_matches_query(
            summary, parse_commit_query("author:a@example.com")))
        self.assertFalse(commit_matches_query(
            summary, parse_commit_query("author:sigrun")))
        self.assertFalse(commit_matches_query(
            summary, parse_commit_query("-author:thor")))
        self.assertEqual(matched_fields(
            summary, parse_commit_query("author:thor")), ())

    def test_matched_fields_both_when_term_in_both(self):
        summary = CommitSummary(
            oid="abc", parents=(), author_name="Thor",
            author_email="t@example.com", author_time=1,
            subject="Thor hammers", body="")
        self.assertEqual(matched_fields(
            summary, parse_commit_query("thor")),
            ("message", "author"))

    def test_hit_properties(self):
        hit = CommitHit(
            repo_id=1, owner="volmarr", repo="anvil", oid="abc",
            parents=(), author_name="A U Thor",
            author_email="a@example.com", author_time=1,
            subject="Subject", body="Body")
        self.assertEqual(hit.full_name, "volmarr/anvil")
        self.assertEqual(hit.message, "Subject\n\nBody")
        bare = CommitHit(
            repo_id=1, owner="volmarr", repo="anvil", oid="abc",
            parents=(), author_name="A U Thor",
            author_email="a@example.com", author_time=1,
            subject="Subject", body="")
        self.assertEqual(bare.message, "Subject")


class CommitSearchTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.a = make_world(Path(self._td.name), with_secret=True)
        self.addCleanup(self.a.conn.close)

    # -- pins ---------------------------------------------------
    def test_pins_schema_88_taxonomy_127(self):
        self.assertEqual(schema_version(self.a.conn), 88)
        self.assertEqual(db.MIGRATIONS[-1][0], 88)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 127)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 31)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 83)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)

    # -- message and author --------------------------------------
    def test_search_by_message_subject_and_body(self):
        w = self.a
        hits = w.search.search(w.owner, "temper")
        self.assertEqual(subjects(hits), ["Temper the steel <carefully>"])
        self.assertEqual(hits[0].matched_fields, ("message",))
        hits = w.search.search(w.owner, "quench")
        self.assertEqual(subjects(hits), ["Temper the steel <carefully>"])

    def test_search_by_author_free_text(self):
        w = self.a
        hits = w.search.search(w.owner, "sigrun@example.com")
        self.assertEqual(subjects(hits), ["Temper the steel <carefully>"])
        self.assertEqual(hits[0].matched_fields, ("author",))

    def test_search_by_author_qualifier(self):
        w = self.a
        hits = w.search.search(w.owner, "author:sigrun")
        self.assertEqual(subjects(hits), ["Temper the steel <carefully>"])
        hits = w.search.search(w.owner, "author:thor author:a@example")
        self.assertEqual(len(hits), 4)
        hits = w.search.search(w.other, "author:sigrun")
        self.assertEqual(
            subjects(hits),
            ["Weave the loom pattern", "Temper the steel <carefully>"])

    def test_terms_compose_by_and_across_fields(self):
        w = self.a
        self.assertEqual(
            subjects(w.search.search(w.owner, "forge polish")),
            ["Polish the horn"])
        self.assertEqual(w.search.search(w.owner, "forge quench"), [])
        self.assertEqual(
            subjects(w.search.search(w.owner, "anvil thor")),
            ["Forge the anvil frame"])

    def test_phrase_search(self):
        w = self.a
        self.assertEqual(
            subjects(w.search.search(w.owner, '"anvil frame"')),
            ["Forge the anvil frame"])
        self.assertEqual(w.search.search(w.owner, '"frame anvil"'), [])

    def test_side_branch_commit_is_found(self):
        w = self.a
        hits = w.search.search(w.owner, "experiment")
        self.assertEqual(subjects(hits), ["Side branch experiment"])
        self.assertEqual(hits[0].full_name, "volmarr/anvil")
        self.assertEqual(hits[0].parents, (w.oids["anvil-1"],))

    # -- ordering, scope, keywords --------------------------------
    def test_newest_first_default_and_oldest_sort(self):
        w = self.a
        newest = ["Side branch experiment", "Polish the horn",
                  "Forge the anvil frame", "Store old maps"]
        self.assertEqual(subjects(w.search.search(w.owner, "thor")),
                         newest)
        self.assertEqual(
            subjects(w.search.search(w.owner, "thor sort:oldest")),
            list(reversed(newest)))
        self.assertEqual(
            subjects(w.search.search(
                w.owner, "thor sort:oldest", sort="newest")), newest)

    def test_repo_scope_qualifier_and_kwarg_override(self):
        w = self.a
        hits = w.search.search(w.owner, "forge repo:volmarr/anvil")
        self.assertEqual(len(hits), 2)
        self.assertTrue(all(h.full_name == "volmarr/anvil" for h in hits))
        self.assertEqual(
            w.search.search(w.owner, "forge repo:volmarr/attic"), [])
        hits = w.search.search(
            w.owner, "repo:volmarr/attic forge",
            owner="volmarr", repo="anvil")
        self.assertEqual(len(hits), 2)
        hits = w.search.search_repository(
            w.owner, "volmarr", "anvil", "forge")
        self.assertEqual(len(hits), 2)

    def test_scope_only_and_author_only_are_searches(self):
        w = self.a
        res = w.search.search_counted(w.owner, "repo:volmarr/anvil")
        self.assertEqual(res.total, 5)
        self.assertEqual(
            subjects(w.search.search(w.owner, "author:keeper")),
            ["zorblax secret plans"])

    def test_empty_search_and_bad_limit_refused(self):
        w = self.a
        for query in ("", "   ", None):
            with self.assertRaises(CommitSearchError) as ctx:
                w.search.search(w.owner, query)
            self.assertEqual(ctx.exception.reason, "query_invalid")
        with self.assertRaises(CommitSearchError):
            w.search.search(w.owner, "", author="")
        for kwargs in ({"limit": 0}, {"limit": 501}, {"limit": "3"},
                       {"sort": "size"}, {"author": 7}):
            with self.assertRaises(CommitSearchError) as ctx:
                w.search.search(w.owner, "forge", **kwargs)
            self.assertEqual(ctx.exception.reason, "query_invalid", kwargs)

    def test_negated_author_qualifier(self):
        w = self.a
        self.assertEqual(
            w.search.search(w.owner, "forge -author:thor"), [])
        self.assertEqual(
            subjects(w.search.search(w.owner, "shine -author:sigrun")),
            ["Polish the horn"])
        self.assertEqual(
            subjects(w.search.search(w.owner, "-author:thor")),
            ["Markup in the message <b>bold</b>",
             "zorblax secret plans", "Temper the steel <carefully>"])

    def test_explicit_author_kwarg_ands_with_text(self):
        w = self.a
        self.assertEqual(w.search.search(w.owner, "forge", author="sigrun"),
                         [])
        self.assertEqual(len(w.search.search(w.owner, "", author="thor")), 4)
        self.assertEqual(
            subjects(w.search.search(w.owner, "forge", author="thor")),
            ["Polish the horn", "Forge the anvil frame"])

    # -- counts -----------------------------------------------------
    def test_limit_caps_display_never_the_count(self):
        w = self.a
        res = w.search.search_counted(w.owner, "thor", limit=2)
        self.assertEqual(len(res.hits), 2)
        self.assertEqual(res.total, 4)
        self.assertEqual(w.search.count(w.owner, "thor"), 4)
        counted = w.search.search_counted(w.owner, "thor")
        self.assertEqual(list(counted.hits), w.search.search(w.owner, "thor"))
        self.assertEqual(counted.total, 4)

    # -- hit facts ----------------------------------------------------
    def test_hit_record_carries_the_commit_facts(self):
        w = self.a
        hit = w.search.search(w.owner, "temper")[0]
        repo = w.repos.get_repository("volmarr", "anvil")
        self.assertEqual(hit.repo_id, repo.id)
        self.assertEqual(hit.owner, "volmarr")
        self.assertEqual(hit.repo, "anvil")
        self.assertEqual(hit.full_name, "volmarr/anvil")
        self.assertEqual(hit.oid, w.oids["anvil-2"])
        self.assertEqual(hit.parents, (w.oids["anvil-1"],))
        self.assertEqual(hit.author_name, "Sigrun Halvorsen")
        self.assertEqual(hit.author_email, "sigrun@example.com")
        self.assertEqual(hit.author_time, 1700000200)
        self.assertEqual(hit.subject, "Temper the steel <carefully>")
        self.assertEqual(hit.body, "Quench in oil")
        self.assertEqual(
            hit.message, "Temper the steel <carefully>\n\nQuench in oil")
        self.assertEqual(hit.matched_fields, ("message",))

    # -- permission law (S-209) ---------------------------------------
    def test_scoped_missing_and_unreadable_are_uniform(self):
        w = self.a
        reasons = []
        for call in (
                lambda: w.search.search(
                    w.stranger, "secret repo:volmarr/vault"),
                lambda: w.search.search(
                    w.stranger, "secret", owner="volmarr", repo="vault"),
                lambda: w.search.search(w.owner, "x repo:volmarr/nope"),
                lambda: w.search.search_repository(
                    w.owner, "volmarr", "nope", "x"),
                lambda: w.search.search(
                    None, "secret repo:volmarr/vault")):
            with self.assertRaises(CommitSearchError) as ctx:
                call()
            reasons.append(ctx.exception.reason)
        self.assertEqual(reasons, ["repo_not_found"] * 5)

    def test_scoped_empty_repo_answers_empty(self):
        w = self.a
        self.assertEqual(
            w.search.search(w.owner, "author:thor repo:volmarr/empty"), [])
        self.assertEqual(
            w.search.search_repository(w.owner, "volmarr", "empty", "thor"),
            [])

    def test_internal_repo_follows_the_s054_gate(self):
        w = self.a
        self.assertEqual(w.search.search(w.owner, "weave"), [])
        self.assertEqual(w.search.search(w.stranger, "weave"), [])
        self.assertEqual(
            subjects(w.search.search(w.other, "weave")),
            ["Weave the loom pattern"])
        self.assertEqual(
            subjects(w.search.search(w.admin, "weave")),
            ["Weave the loom pattern"])

    def test_private_repo_of_owner_and_admin_visibility(self):
        w = self.a
        self.assertEqual(subjects(w.search.search(w.owner, "maps")),
                         ["Store old maps"])
        self.assertEqual(w.search.search(None, "maps"), [])
        self.assertEqual(w.search.search(w.stranger, "maps"), [])
        self.assertEqual(subjects(w.search.search(w.admin, "maps")),
                         ["Store old maps"])
        self.assertEqual(
            subjects(w.search.search(None, "forge")),
            ["Polish the horn", "Forge the anvil frame"])

    def test_secret_invisible_to_stranger_and_anon(self):
        for viewer in (self.a.stranger, None):
            for query in ("zorblax", "secret", "keeper", "hidden"):
                self.assertEqual(self.a.search.search(viewer, query), [])
                self.assertEqual(self.a.search.count(viewer, query), 0)

    def test_equivalence_with_and_without_secret_repo(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        b = make_world(Path(td.name), with_secret=False)
        self.addCleanup(b.conn.close)
        for query in ("forge", "zorblax", "secret", "thor",
                      "keeper", "maps"):
            for viewer_a, viewer_b in (
                    (self.a.stranger, b.stranger), (None, None)):
                ha = self.a.search.search_counted(viewer_a, query)
                hb = b.search.search_counted(viewer_b, query)
                self.assertEqual(signature(ha.hits), signature(hb.hits),
                                 query)
                self.assertEqual(ha.total, hb.total, query)
        owner = self.a.search.search_counted(self.a.owner, "zorblax")
        self.assertEqual(owner.total, 1)
        self.assertEqual(owner.hits[0].full_name, "volmarr/vault")
        self.assertEqual(b.search.search(b.owner, "zorblax"), [])

    # -- rendering ------------------------------------------------------
    def test_rendered_pages_carry_no_secret(self):
        w = self.a
        page = render_commit_search_page(
            "secret", w.search.search(w.stranger, "secret"),
            total=w.search.count(w.stranger, "secret"))
        self.assertNotIn("zorblax", page)
        self.assertNotIn("vault", page)
        self.assertNotIn("Zorblax Keeper", page)
        self.assertIn("0 commits match", page)
        owner_page = render_commit_search_page(
            "zorblax", w.search.search(w.owner, "zorblax"))
        self.assertIn("volmarr/vault", owner_page)
        self.assertIn("zorblax secret plans", owner_page)

    def test_pages_say_the_facts_in_words(self):
        w = self.a
        page = render_commit_search_page(
            "steel", w.search.search(w.owner, "steel"), total=1)
        self.assertIn("volmarr/anvil", page)
        self.assertIn("Temper the steel", page)
        self.assertIn("Sigrun Halvorsen", page)
        self.assertIn("sigrun@example.com", page)
        self.assertIn("2023-11-14", page)
        self.assertIn("Matched in: message", page)
        self.assertIn("1 commit matches", page)
        self.assertIn("author:NAME", page)
        empty = render_commit_search_page(
            "zzzz", w.search.search(w.owner, "zzzz"), total=0)
        self.assertIn("No commits match.", empty)

    def test_stored_markup_renders_as_text(self):
        w = self.a
        page = render_commit_search_page(
            "steel", w.search.search(w.owner, "steel"))
        self.assertIn("&lt;carefully&gt;", page)
        self.assertNotIn("<carefully>", page)
        page = render_commit_search_page(
            "markup", w.search.search(w.owner, "markup"))
        self.assertIn("Markup in the message &lt;b&gt;bold&lt;/b&gt;", page)
        self.assertNotIn("<b>bold</b>", page)
        page = render_commit_search_page('a"b', [])
        self.assertIn("&quot;", page)

    # -- searching writes nothing ---------------------------------------
    def test_searches_write_nothing(self):
        w = self.a
        before = (
            w.conn.execute("SELECT COUNT(*) c FROM audit_log").fetchone()["c"],
            w.conn.execute("SELECT COUNT(*) c FROM repositories").fetchone()["c"])
        w.search.search_counted(w.owner, "forge")
        w.search.search(w.stranger, "thor")
        w.search.count(None, "zorblax")
        w.search.search_repository(w.owner, "volmarr", "anvil", "steel")
        after = (
            w.conn.execute("SELECT COUNT(*) c FROM audit_log").fetchone()["c"],
            w.conn.execute("SELECT COUNT(*) c FROM repositories").fetchone()["c"])
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
