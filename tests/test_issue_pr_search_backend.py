"""S-206 acceptance battery: issue/PR search backend.

Acceptance (roadmap S-206): Issue/PR search backend —
the qualifier language of S-135/S-161 executed over
FTS + structured fields.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import calendar, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.assignees import AssigneeStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.index_architecture import SearchIndexStore
from samverk.issue_pr_search import (
    IndexRow, IssuePRSearch, SearchBackendError, date_bounds,
    decide_status, fts_match_query, matches_query,
    parse_search_query, render_backend_search_page, review_holds)
from samverk.issue_search import SearchError
from samverk.issues import IssueStore
from samverk.labels import LabelStore
from samverk.milestones import MilestoneStore
from samverk.pull_request_review_assignment import ReviewAssignmentStore
from samverk.pull_request_reviews import PullRequestReviewStore
from samverk.pull_requests import PullRequestStore
from samverk.repositories import RepositoryStore


def git(repo, *args, input_bytes=None):
    env = {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": "/usr/bin:/bin"}
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         capture_output=True, input=input_bytes, env=env)
    assert out.returncode == 0, out.stderr.decode()
    return out.stdout.decode().strip()


def make_commit(repo, parent, files, message):
    lines = []
    for name in sorted(files):
        blob = git(repo, "hash-object", "-w", "--stdin",
                   input_bytes=files[name].encode())
        lines.append(f"100644 blob {blob}\t{name}\n")
    tree = git(repo, "mktree", input_bytes="".join(lines).encode())
    args = ["commit-tree", tree]
    if parent:
        args += ["-p", parent]
    return git(repo, *args, input_bytes=(message + "\n").encode())


def day(year, month, dom, hour=12):
    return calendar.timegm((year, month, dom, hour, 0, 0, 0, 0, 0))


class IssuePRSearchBackendTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.reader = self.accounts.register("yrsa", "correct horse battery")
        self.third = self.accounts.register("tess", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.issues = IssueStore(self.conn, self.repos, self.accounts,
                                 audit=self.audit)
        self.labels = LabelStore(self.conn, self.repos, self.accounts,
                                 self.issues, audit=self.audit)
        self.assignees = AssigneeStore(self.conn, self.repos, self.accounts,
                                       self.issues, audit=self.audit)
        self.milestones = MilestoneStore(self.conn, self.repos,
                                         self.accounts, self.issues,
                                         audit=self.audit)
        self.prs = PullRequestStore(self.conn, self.repos, self.accounts,
                                    self.issues, audit=self.audit)
        self.reviews = PullRequestReviewStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit)
        self.assign = ReviewAssignmentStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit)
        self.index = SearchIndexStore(self.conn, self.repos)
        self.backend = IssuePRSearch(self.conn, self.repos, self.index)
        self.repos.create_repository(self.owner.id, "volmarr", "pub",
                                     visibility="public")
        self.repos.create_repository(self.owner.id, "volmarr", "lab",
                                     visibility="public")
        self.repos.create_repository(self.owner.id, "volmarr", "priv",
                                     visibility="private")
        # pub issues #1..#3
        self.issues.create_issue(self.reader, "volmarr", "pub",
                                 "Crash on startup", "It falls over")
        self.issues.create_issue(self.owner, "volmarr", "pub",
                                 "Add export", "Please add CSV export")
        self.issues.create_issue(self.owner, "volmarr", "pub",
                                 "Crash in export", "Export falls over too")
        self.labels.add_to_issue(self.owner, "volmarr", "pub", 1, "bug")
        self.labels.add_to_issue(self.owner, "volmarr", "pub", 3, "bug")
        self.labels.add_to_issue(self.owner, "volmarr", "pub", 3,
                                 "good first issue")
        self.assignees.assign(self.owner, "volmarr", "pub", 2, "yrsa")
        self.milestones.create_milestone(self.owner, "volmarr", "pub",
                                         "Launch 1")
        self.milestones.set_issue_milestone(self.owner, "volmarr", "pub",
                                            2, "Launch 1")
        self.issues.close_issue(self.owner, "volmarr", "pub", 3)
        # pub pull requests #4..#6
        self.path = self.repos.path_for("volmarr", "pub")
        base = make_commit(self.path, None, {"a.txt": "alpha\n"}, "base")
        git(self.path, "update-ref", "refs/heads/main", base)
        self._base = base
        self.pr1 = self._open_pr("f1", "Fix crash in parser",
                                 "The parser falls over")
        self.pr2 = self._open_pr("f2", "Add export button",
                                 "Please add CSV export")
        self.pr3 = self._open_pr("f3", "Rework settings page",
                                 "Still being designed", draft=True)
        self.reviews.submit_review(self.reader, "volmarr", "pub", 4,
                                   verdict="approve", summary="Good.")
        with self.conn:
            self.conn.execute(
                "UPDATE issues SET state = 'closed' WHERE id = ?",
                (self.pr1.row_id,))
        self.reviews.submit_review(self.reader, "volmarr", "pub", 5,
                                   verdict="approve", summary="Good.")
        self.reviews.submit_review(self.reader, "volmarr", "pub", 5,
                                   verdict="comment", summary="A note.")
        self.reviews.submit_review(self.third, "volmarr", "pub", 5,
                                   verdict="request_changes",
                                   summary="Needs work.")
        self.assign.request_reviewers(self.owner, "volmarr", "pub", 6,
                                      ["@yrsa"])
        repo = self.repos.get_repository("volmarr", "pub")
        bug = self.conn.execute(
            "SELECT id FROM labels WHERE repo_id = ?"
            " AND name_lower = 'bug'", (repo.id,)).fetchone()
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO issue_labels"
                " (issue_id, label_id, created_at) VALUES (?, ?, 0)",
                (self.pr1.row_id, bug[0]))
        # lab + priv items
        self.issues.create_issue(self.owner, "volmarr", "lab",
                                 "Crash in lab", "Broken in the lab")
        self.issues.create_issue(self.owner, "volmarr", "priv",
                                 "Secret crash", "Hidden falls over")
        # Deterministic dates and comment counts.
        dates = {("pub", 1): (day(2026, 1, 5), day(2026, 3, 1)),
                 ("pub", 2): (day(2026, 1, 6), day(2026, 1, 6)),
                 ("pub", 3): (day(2026, 1, 7), day(2026, 1, 7)),
                 ("pub", 4): (day(2026, 2, 1), day(2026, 2, 1)),
                 ("pub", 5): (day(2026, 2, 2), day(2026, 2, 2)),
                 ("pub", 6): (day(2026, 2, 3), day(2026, 2, 3)),
                 ("lab", 1): (day(2026, 1, 5), day(2026, 1, 5)),
                 ("priv", 1): (day(2026, 1, 5), day(2026, 1, 5))}
        repo_ids = {name: self.repos.get_repository("volmarr", name).id
                    for name in ("pub", "lab", "priv")}
        with self.conn:
            for (name, number), (created, updated) in dates.items():
                self.conn.execute(
                    "UPDATE issues SET created_at = ?, updated_at = ?"
                    " WHERE repo_id = ? AND number = ?",
                    (created, updated, repo_ids[name], number))
            for name, number, count in (("pub", 1, 2), ("pub", 3, 3),
                                        ("pub", 5, 1)):
                row_id = self.conn.execute(
                    "SELECT id FROM issues WHERE repo_id = ?"
                    " AND number = ?",
                    (repo_ids[name], number)).fetchone()["id"]
                for _ in range(count):
                    self.conn.execute(
                        "INSERT INTO issue_comments"
                        " (issue_id, author_id, body, created_at,"
                        " updated_at) VALUES (?, ?, 'note', 0, 0)",
                        (row_id, self.owner.id))
        self.backend.index_all()

    def _open_pr(self, branch, title, body, draft=False):
        head = make_commit(self.path, self._base,
                           {"a.txt": f"alpha\n{branch}\n"}, branch)
        git(self.path, "update-ref", f"refs/heads/{branch}", head)
        return self.prs.create_pull_request(
            self.owner, "volmarr", "pub", base_branch="main",
            head_branch=branch, title=title, body=body, draft=draft)

    def numbers(self, query, viewer=None, repo="pub"):
        return [h.number for h in self.backend.search_repository(
            viewer, "volmarr", repo, query)]

    def keys(self, query, viewer=None):
        return [(h.full_name, h.number)
                for h in self.backend.search(viewer, query)]

    # -- pins ---------------------------------------------------
    def test_pins_schema_81_taxonomy_123(self):
        self.assertEqual(schema_version(self.conn), 124)
        self.assertEqual(db.MIGRATIONS[-1][0], 124)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 135)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 89)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        tables = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertIn("issue_pr_fts", tables)

    def test_fresh_database_migrates_to_81(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.init_db(Path(td) / "fresh.db")
            self.assertEqual(db.schema_version(conn), 124)
            conn.close()

    def test_upgrade_from_80_creates_the_fts_table(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "old.db"
            conn = db.connect(path)
            for target, statements in db.MIGRATIONS:
                if target > 80:
                    continue
                with conn:
                    for stmt in statements:
                        conn.execute(stmt)
                    conn.execute(
                        "INSERT OR REPLACE INTO schema_meta"
                        " (key, value) VALUES ('version', ?)",
                        (str(target),))
            self.assertEqual(db.schema_version(conn), 80)
            self.assertEqual(db.migrate(conn), 124)
            names = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")}
            self.assertIn("issue_pr_fts", names)
            conn.close()

    # -- FTS text -------------------------------------------------
    def test_fts_text_matches_tokens_across_kinds(self):
        self.assertEqual(self.numbers("crash"), [1, 3, 4])
        self.assertEqual(self.numbers("export"), [2, 3, 5])
        self.assertEqual(self.numbers("CRASH"), [1, 3, 4])
        self.assertEqual(self.numbers("zebra"), [])

    def test_fts_phrase_and_composition(self):
        self.assertEqual(self.numbers('"falls over"'), [1, 3, 4])
        self.assertEqual(self.numbers("crash is:open"), [1])
        self.assertEqual(self.numbers("export author:volmarr is:pr"),
                         [5])
        self.assertEqual(self.numbers(""), [1, 2, 3, 4, 5, 6])

    def test_fts_match_query_escapes_quotes(self):
        self.assertEqual(fts_match_query(("falls over",)),
                         '"falls over"')
        self.assertEqual(fts_match_query(('a"b', "c")),
                         '"a""b" AND "c"')
        self.assertEqual(fts_match_query(()), "")

    # -- kind, state, structured fields ----------------------------
    def test_kind_and_state_qualifiers(self):
        self.assertEqual(self.numbers("is:issue"), [1, 2, 3])
        self.assertEqual(self.numbers("is:pr"), [4, 5, 6])
        self.assertEqual(self.numbers("is:open"), [1, 2, 5, 6])
        self.assertEqual(self.numbers("is:closed"), [3, 4])
        self.assertEqual(self.numbers("is:draft"), [6])
        self.assertEqual(self.numbers("is:issue is:pr"), [])
        self.assertEqual(self.numbers("is:open is:closed"), [])

    def test_structured_qualifiers(self):
        self.assertEqual(self.numbers("label:bug"), [1, 3, 4])
        self.assertEqual(self.numbers('label:"good first issue"'), [3])
        self.assertEqual(self.numbers("label:bug label:nope"), [])
        self.assertEqual(self.numbers("author:yrsa"), [1])
        self.assertEqual(self.numbers("author:VOLMARR"), [2, 3, 4, 5, 6])
        self.assertEqual(self.numbers("assignee:yrsa"), [2])
        self.assertEqual(self.numbers('milestone:"Launch 1"'), [2])

    def test_review_and_status_are_pull_request_positions(self):
        self.assertEqual(self.numbers("review:approved"), [4])
        self.assertEqual(self.numbers("review:commented"), [5])
        self.assertEqual(self.numbers("review:changes_requested"), [5])
        self.assertEqual(self.numbers("review:changes-requested"), [5])
        self.assertEqual(self.numbers("review:none"), [6])
        self.assertEqual(self.numbers("review:requested"), [6])
        self.assertEqual(self.numbers("review:none review:requested"),
                         [6])
        self.assertEqual(self.numbers("status:open"), [5])
        self.assertEqual(self.numbers("status:draft"), [6])
        self.assertEqual(self.numbers("status:closed"), [4])
        self.assertEqual(self.numbers("status:open status:draft"), [])
        # Issues never satisfy review:/status: — kind honesty.
        self.assertEqual(self.numbers("review:none is:issue"), [])
        self.assertEqual(self.numbers("status:closed is:issue"), [])

    def test_no_qualifier_names_empty_fields(self):
        self.assertEqual(self.numbers("no:label"), [2, 5, 6])
        self.assertEqual(self.numbers("no:assignee"), [1, 3, 4, 5, 6])
        self.assertEqual(self.numbers("no:milestone"), [1, 3, 4, 5, 6])
        self.assertEqual(self.numbers("no:label is:issue"), [2])

    # -- repo scoping ------------------------------------------------
    def test_repo_scope_narrows_and_negates(self):
        self.assertEqual(self.keys("crash"),
                         [("volmarr/lab", 1), ("volmarr/pub", 1),
                          ("volmarr/pub", 3), ("volmarr/pub", 4)])
        self.assertEqual(self.keys("crash repo:volmarr/pub"),
                         [("volmarr/pub", 1), ("volmarr/pub", 3),
                          ("volmarr/pub", 4)])
        self.assertEqual(self.keys("crash -repo:volmarr/pub"),
                         [("volmarr/lab", 1)])
        self.assertEqual(
            self.keys("crash repo:volmarr/pub repo:volmarr/lab"), [])

    # -- dates ---------------------------------------------------------
    def test_date_qualifiers(self):
        self.assertEqual(self.numbers("created:2026-01-05"), [1])
        self.assertEqual(self.numbers("created:>2026-01-05"),
                         [2, 3, 4, 5, 6])
        self.assertEqual(self.numbers("created:>=2026-02-01"),
                         [4, 5, 6])
        self.assertEqual(self.numbers("created:<2026-01-06"), [1])
        self.assertEqual(self.numbers("created:<=2026-01-06"), [1, 2])
        self.assertEqual(self.numbers("created:2026-01-05..2026-01-07"),
                         [1, 2, 3])
        self.assertEqual(self.numbers("updated:2026-03-01"), [1])
        self.assertEqual(
            self.numbers("created:2026-01-05 updated:2026-03-01"), [1])

    def test_date_bounds_pure(self):
        start = day(2026, 1, 5, 0)
        self.assertEqual(date_bounds("2026-01-05", "created"),
                         (start, start + 86400))
        self.assertEqual(date_bounds(">2026-01-05", "created"),
                         (start + 86400, None))
        self.assertEqual(date_bounds("<2026-01-05", "created"),
                         (None, start))
        self.assertEqual(date_bounds("2026-01-05..2026-01-07",
                                     "created"),
                         (start, start + 3 * 86400))

    # -- negation -------------------------------------------------------
    def test_negation_excludes(self):
        self.assertEqual(self.numbers("-label:bug"), [2, 5, 6])
        self.assertEqual(self.numbers("crash -label:bug"), [])
        self.assertEqual(self.numbers("-author:volmarr"), [1])
        self.assertEqual(self.numbers("-is:pr"), [1, 2, 3])
        self.assertEqual(self.numbers("-is:issue"), [4, 5, 6])
        self.assertEqual(self.numbers("is:pr -status:draft"), [4, 5])
        self.assertEqual(self.numbers("-milestone:\"Launch 1\""),
                         [1, 3, 4, 5, 6])

    # -- sorting -----------------------------------------------------------
    def test_sort_qualifiers(self):
        self.assertEqual(self.numbers("sort:created-asc"),
                         [1, 2, 3, 4, 5, 6])
        self.assertEqual(self.numbers("sort:created-desc"),
                         [6, 5, 4, 3, 2, 1])
        self.assertEqual(self.numbers("sort:comments-desc"),
                         [3, 1, 5, 2, 4, 6])
        self.assertEqual(self.numbers("is:issue sort:created-desc"),
                         [3, 2, 1])

    # -- fail-closed ---------------------------------------------------------
    def test_malformed_queries_fail_closed(self):
        bad_queries = (
            "is:banana", "label:", "review:banana", "status:merged",
            "bogus:x", "-bogus:x", "no:banana", "sort:banana",
            "sort:created-asc sort:created-desc",
            "repo:justname", "repo:a/b/c", "repo:/pub",
            "created:banana", "created:2026-02-30",
            "created:2026-13-01", "created:05-01-2026",
            "created:2026-01-07..2026-01-05",
            "updated:2026-01-05..", 'label:"unterminated',
            "-created:2026-01-05", "-sort:created-asc",
            "x" * 501)
        for bad in bad_queries:
            with self.assertRaises(SearchError, msg=bad) as caught:
                parse_search_query(bad)
            self.assertEqual(caught.exception.reason, "query_invalid",
                             msg=bad)
        with self.assertRaises(SearchError):
            parse_search_query(123)

    def test_parse_records_the_full_grammar(self):
        parsed = parse_search_query(
            'is:pr review:approved status:open label:bug '
            'repo:volmarr/pub created:>=2026-01-01 '
            'sort:created-desc -author:tess fix')
        self.assertEqual(parsed.kinds, ("pull_request",))
        self.assertEqual(parsed.reviews, ("approved",))
        self.assertEqual(parsed.statuses, ("open",))
        self.assertEqual(parsed.labels, ("bug",))
        self.assertEqual(parsed.repo_scopes, (("volmarr", "pub"),))
        self.assertEqual(parsed.sort, "created-desc")
        self.assertEqual(parsed.not_authors, ("tess",))
        self.assertEqual(parsed.text_terms, ("fix",))
        self.assertEqual(len(parsed.created_bounds), 1)
        self.assertFalse(parsed.is_empty)
        self.assertTrue(parse_search_query("").is_empty)
        self.assertTrue(parse_search_query("is:draft").draft_only)

    # -- pure deciding law -----------------------------------------------------
    def _row(self, **over):
        base = dict(row_id=1, repo_id=1, number=1, kind="issue",
                    title="t", body="b", state="open",
                    author_lower="volmarr")
        base.update(over)
        return IndexRow(**base)

    def test_pure_law_kind_honesty(self):
        issue = self._row()
        self.assertFalse(decide_status("open", issue))
        self.assertFalse(review_holds("none", issue))
        pr = self._row(kind="pull_request", is_draft=True)
        self.assertTrue(decide_status("draft", pr))
        self.assertFalse(decide_status("open", pr))
        self.assertTrue(review_holds("none", pr))
        parsed = parse_search_query("label:bug -author:tess")
        self.assertTrue(matches_query(
            self._row(labels=("bug",)), parsed))
        self.assertFalse(matches_query(
            self._row(labels=("bug",), author_lower="tess"), parsed))
        self.assertFalse(matches_query(self._row(), parsed))

    # -- permission seam (S-209 builds on it) --------------------------------------
    def test_private_repo_never_leaks_to_strangers(self):
        self.assertNotIn(("volmarr/priv", 1), self.keys("crash"))
        self.assertNotIn(("volmarr/priv", 1),
                         self.keys("crash", viewer=self.reader))
        self.assertIn(("volmarr/priv", 1),
                      self.keys("crash", viewer=self.owner))
        with self.assertRaises(SearchBackendError) as caught:
            self.backend.search_repository(None, "volmarr", "priv",
                                           "crash")
        self.assertEqual(caught.exception.reason, "repo_not_found")
        with self.assertRaises(SearchBackendError):
            self.backend.search_repository(None, "volmarr", "ghost",
                                           "crash")
        self.assertEqual(self.numbers("crash", viewer=self.owner,
                                      repo="priv"), [1])

    # -- index lifecycle ---------------------------------------------------------------
    def test_index_lifecycle_is_honest(self):
        self.issues.create_issue(self.owner, "volmarr", "pub",
                                 "Zebra stripes", "A zebra appears")
        # Not yet indexed: honestly absent.
        self.assertEqual(self.numbers("zebra"), [])
        row = self.backend.index_item("volmarr", "pub", 7)
        self.assertEqual(row.kind, "issue")
        self.assertEqual(self.numbers("zebra"), [7])
        docs = self.index.documents_for("volmarr", "pub", kind="issue")
        self.assertEqual([d.doc_key for d in docs],
                         ["issue:1", "issue:2", "issue:3", "issue:7"])
        with self.conn:
            self.conn.execute(
                "UPDATE issues SET title = 'Giraffe neck'"
                " WHERE repo_id = ? AND number = 7",
                (self.repos.get_repository("volmarr", "pub").id,))
        self.backend.index_item("volmarr", "pub", 7)
        # The title word is gone from the index; the body
        # still honestly carries its own zebra.
        self.assertEqual(self.numbers("stripes"), [])
        self.assertEqual(self.numbers("giraffe"), [7])
        self.assertEqual(self.numbers("zebra"), [7])
        self.assertTrue(self.backend.remove_item("volmarr", "pub", 7))
        self.assertEqual(self.numbers("giraffe"), [])
        self.assertFalse(self.backend.remove_item("volmarr", "pub", 7))
        with self.assertRaises(SearchBackendError) as caught:
            self.backend.index_item("volmarr", "pub", 99)
        self.assertEqual(caught.exception.reason, "item_not_found")
        with self.assertRaises(SearchBackendError) as caught:
            self.backend.index_repository("volmarr", "ghost")
        self.assertEqual(caught.exception.reason, "repo_not_found")

    def test_rebuild_repository_replaces_rows_whole(self):
        with self.conn:
            self.conn.execute(
                "DELETE FROM issue_pr_fts WHERE repo_id = ?",
                (self.repos.get_repository("volmarr", "pub").id,))
        self.assertEqual(self.numbers("crash"), [])
        self.assertEqual(self.backend.rebuild_repository(
            "volmarr", "pub"), 6)
        self.assertEqual(self.numbers("crash"), [1, 3, 4])
        self.assertEqual(self.backend.index_all(), 8)

    def test_search_and_index_write_no_audit_event(self):
        before = self.conn.execute(
            "SELECT COUNT(*) c FROM audit_log").fetchone()["c"]
        self.backend.search(None, "crash label:bug")
        self.backend.index_item("volmarr", "pub", 1)
        after = self.conn.execute(
            "SELECT COUNT(*) c FROM audit_log").fetchone()["c"]
        self.assertEqual(before, after)

    # -- page ----------------------------------------------------------------------------
    def test_page_renders_form_help_results_and_empty_state(self):
        hits = self.backend.search_repository(None, "volmarr", "pub",
                                              "label:bug")
        page = render_backend_search_page("label:bug", hits)
        self.assertIn('value="label:bug"', page)
        self.assertIn("repo:OWNER/NAME", page)
        self.assertIn("no:label", page)
        self.assertIn("volmarr/pub #1 Crash on startup", page)
        self.assertIn("closed pull request", page)
        empty = render_backend_search_page("label:nope", [])
        self.assertIn("No issues or pull requests match", empty)

    def test_page_escapes_hostile_query_and_title(self):
        self.issues.create_issue(self.owner, "volmarr", "pub",
                                 "<script>alert(1)</script>", "x")
        self.backend.index_item("volmarr", "pub", 7)
        hits = self.backend.search_repository(None, "volmarr", "pub",
                                              "script")
        page = render_backend_search_page('"><script>', hits)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)


if __name__ == "__main__":
    unittest.main()
