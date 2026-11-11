"""S-243 acceptance battery: issues and PRs API.

Acceptance (roadmap S-243): Issues and PRs API --
full lifecycle incl. reviews and merge;
acceptance: a script drives an entire PR from
open to merge.

The centre is samverk/api_issues_pulls.py: the
contract's issues and pulls families delegating
every act to the web's own stores (S-122/S-130
issues, S-123 comments, S-124 labels, S-125
assignees, S-126 milestones, S-141 pull creation,
S-144 pull conversation, S-143 drafts, S-148
reviews, S-153 merge), judged through S-238's
door and S-190's engine alone, with refusals in
S-240's one problem format. The planted private
repository (`priv`) is the leak bait in the
S-209 shape: a stranger's answers over a world
WITH it must equal the same answers over a world
where it was never created.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import base64, json, subprocess, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.access_tokens import AccessTokenStore
from samverk.accounts import AccountStore
from samverk.api_contract import PROBLEM_FIELDS, get_resource
from samverk.api_issues_pulls import (
    ISSUES_PULLS_API_PATH, IssuesPullsAPI, IssuesPullsAPIError,
    comment_to_dict, error_to_dict, issue_to_dict, pull_to_dict,
    render_issues_pulls_api_page, review_to_dict)
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.fine_grained_tokens import FineTokenStore
from samverk.issues import IssueStore
from samverk.labels import LabelStore
from samverk.milestones import MilestoneStore
from samverk.pull_requests import PullRequestStore
from samverk.repositories import RepositoryStore

PW = "correct horse battery"


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


def basic(username, credential):
    raw = base64.b64encode(f"{username}:{credential}".encode("utf-8"))
    return "Basic " + raw.decode("ascii")


def git(repo, *args, input_bytes=None):
    env = {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": "/usr/bin:/bin"}
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         capture_output=True, input=input_bytes, env=env)
    assert out.returncode == 0, out.stderr.decode()
    return out.stdout.decode().strip()


def build_tree(repo, mapping):
    lines = []
    for name in sorted(mapping):
        value = mapping[name]
        if isinstance(value, dict):
            oid = build_tree(repo, value)
            lines.append(f"040000 tree {oid}\t{name}")
        else:
            oid = git(repo, "hash-object", "-w", "--stdin",
                      input_bytes=value)
            lines.append(f"100644 blob {oid}\t{name}")
    return git(repo, "mktree",
               input_bytes=("\n".join(lines) + "\n").encode())


def commit_tree(repo, tree, message, parent=None):
    args = ["commit-tree", tree]
    if parent:
        args += ["-p", parent]
    return git(repo, *args, input_bytes=(message + "\n").encode())


def make_world(root: Path, with_secret: bool = True) -> SimpleNamespace:
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
    labels = LabelStore(conn, repos, accounts, issues, audit=audit,
                        time_fn=clock)
    milestones = MilestoneStore(conn, repos, accounts, issues,
                                audit=audit, time_fn=clock)
    prs = PullRequestStore(conn, repos, accounts, issues,
                           audit=audit, time_fn=clock)
    api = IssuesPullsAPI(conn, accounts, repos, audit=audit,
                         time_fn=clock)
    w = SimpleNamespace(
        conn=conn, clock=clock, audit=audit, accounts=accounts,
        owner=owner, reader=reader, stranger=stranger,
        repos=repos, issues=issues, labels=labels,
        milestones=milestones, prs=prs, api=api, root=root)
    pub = repos.create_repository(
        owner.id, "volmarr", "pub", visibility="public")
    path = repos.path_for("volmarr", "pub")
    tree1 = build_tree(path, {"hello.txt": b"hello world\n"})
    c1 = commit_tree(path, tree1, "first")
    git(path, "update-ref", "refs/heads/main", c1)
    tree2 = build_tree(path, {"hello.txt": b"hello world\n",
                              "feature.txt": b"new work\n"})
    c2 = commit_tree(path, tree2, "feature work", parent=c1)
    git(path, "update-ref", "refs/heads/feature", c2)
    w.pub, w.c1, w.c2, w.path = pub, c1, c2, path
    if with_secret:
        repos.create_repository(
            owner.id, "volmarr", "priv", visibility="private")
        issues.create_issue(owner, "volmarr", "priv",
                            "Secret zorblax plans")
    # The repository's seeded defaults (S-124) already
    # carry "bug" and "documentation"; the battery
    # works with those, as a script on the web would.
    milestones.create_milestone(owner, "volmarr", "pub", "v1.0",
                                "First release", None)
    classic = AccessTokenStore(conn, accounts, audit=audit,
                               time_fn=clock)
    fine = FineTokenStore(conn, accounts, audit=audit, time_fn=clock)
    expiry = clock.now + 3600
    _, w.owner_issues = classic.create_token(
        owner.id, "issues", {"issues:write"}, expiry)
    _, w.owner_pulls = classic.create_token(
        owner.id, "pulls", {"repo:write"}, expiry)
    _, w.owner_readonly = classic.create_token(
        owner.id, "ro", {"issues:read", "repo:read"}, expiry)
    _, w.fine_pub = fine.create_token(
        owner.id, "volmarr", "pub", "fine pub",
        {"issues:write", "pull_requests:write", "metadata:read"},
        expiry)
    return w


class IssuesPullsAPITests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.w = make_world(Path(self._td.name))
        self.addCleanup(self.w.conn.close)
        self.owner_h = basic("volmarr", PW)
        self.reader_h = basic("yrsa", PW)
        self.stranger_h = basic("mallory", PW)

    def _error(self, fn, *args, **kwargs):
        with self.assertRaises(IssuesPullsAPIError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception

    def _open_issue(self, title="First bug", body="It broke."):
        return self.w.api.create_issue(
            self.owner_h, "volmarr", "pub",
            {"title": title, "body": body})

    def _open_pull(self, **overrides):
        payload = {"base": "main", "head": "feature",
                   "title": "Add the feature", "body": "For review."}
        payload.update(overrides)
        return self.w.api.create_pull(
            self.owner_h, "volmarr", "pub", payload)

    # -- pins ------------------------------------------------
    def test_pins_schema_and_taxonomy(self):
        self.assertEqual(schema_version(self.w.conn), 106)
        self.assertEqual(db.MIGRATIONS[-1][0], 106)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 87)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 133)
        self.assertEqual(ISSUES_PULLS_API_PATH, "/api/issues-pulls")

    def test_contract_now_lands_the_family(self):
        for rid in ("issues", "issue", "issue-comments", "pulls",
                    "pull", "pull-merge", "pull-reviews"):
            self.assertEqual(get_resource(rid).standing, "landed", rid)
            self.assertEqual(get_resource(rid).slice, "S-243", rid)
        issue = self._open_issue()
        self.assertEqual(
            tuple(issue.keys()), get_resource("issues").fields)
        pull = self._open_pull()
        self.assertEqual(
            tuple(pull.keys()), get_resource("pulls").fields)

    def test_serialiser_shapes_match_the_contract(self):
        issue = self.w.issues.create_issue(
            self.w.owner, "volmarr", "pub", "Shaped")
        rendered = issue_to_dict(issue, "volmarr/pub", "volmarr",
                                 [], [], None)
        self.assertEqual(
            tuple(rendered.keys()), get_resource("issue").fields)
        comment = self.w.api.add_issue_comment(
            self.owner_h, "volmarr", "pub", issue.number,
            {"body": "A note."})
        self.assertEqual(
            tuple(comment.keys()),
            get_resource("issue-comments").fields)

    def test_error_dict_is_the_one_problem_format(self):
        exc = self._error(self.w.api.get_issue, None,
                          "volmarr", "priv", 1)
        rendered = error_to_dict(exc)
        self.assertEqual(tuple(rendered.keys()), PROBLEM_FIELDS)
        self.assertEqual(
            rendered["type"], "/api/v1/problems/repo_not_found")
        self.assertEqual(rendered["status"], 404)
        self.assertEqual(json.loads(json.dumps(rendered)), rendered)

    # -- issues: lifecycle -------------------------------------
    def test_issue_full_lifecycle(self):
        created = self._open_issue()
        self.assertEqual(created["number"], 1)
        self.assertEqual(created["state"], "open")
        self.assertEqual(created["author"], "volmarr")
        self.assertEqual(created["repository"], "volmarr/pub")
        self.assertEqual(created["labels"], [])
        read = self.w.api.get_issue(None, "volmarr", "pub", 1)
        self.assertEqual(read["title"], "First bug")
        edited = self.w.api.update_issue(
            self.owner_h, "volmarr", "pub", 1,
            {"title": "First bug, renamed",
             "labels": ["bug"], "assignees": ["yrsa"],
             "milestone": "v1.0"})
        self.assertEqual(edited["title"], "First bug, renamed")
        self.assertEqual(edited["labels"], ["bug"])
        self.assertEqual(edited["assignees"], ["yrsa"])
        self.assertEqual(edited["milestone"], "v1.0")
        swapped = self.w.api.update_issue(
            self.owner_h, "volmarr", "pub", 1,
            {"labels": ["documentation"], "assignees": [],
             "milestone": None})
        self.assertEqual(swapped["labels"], ["documentation"])
        self.assertEqual(swapped["assignees"], [])
        self.assertIsNone(swapped["milestone"])
        closed = self.w.api.update_issue(
            self.owner_h, "volmarr", "pub", 1,
            {"state": "closed", "reason": "not_planned"})
        self.assertEqual(closed["state"], "closed")
        reopened = self.w.api.update_issue(
            self.owner_h, "volmarr", "pub", 1, {"state": "open"})
        self.assertEqual(reopened["state"], "open")
        stored = self.w.issues.get_issue(
            self.w.owner, "volmarr", "pub", 1)
        self.assertEqual(stored.state, "open")

    def test_issue_list_envelope_and_state_filter(self):
        self._open_issue("One")
        second = self._open_issue("Two")
        self.w.api.update_issue(
            self.owner_h, "volmarr", "pub", second["number"],
            {"state": "closed"})
        all_issues = self.w.api.list_issues(None, "volmarr", "pub")
        self.assertEqual(all_issues["total"], 2)
        self.assertEqual(all_issues["repository"], "volmarr/pub")
        open_only = self.w.api.list_issues(
            None, "volmarr", "pub", state="open")
        self.assertEqual(
            [i["title"] for i in open_only["issues"]], ["One"])
        capped = self.w.api.list_issues(
            None, "volmarr", "pub", limit=1)
        self.assertEqual(capped["returned"], 1)
        self.assertFalse(capped["complete"])
        exc = self._error(self.w.api.list_issues, None,
                          "volmarr", "pub", state="sideways")
        self.assertEqual(exc.reason, "state_invalid")
        exc = self._error(self.w.api.list_issues, None,
                          "volmarr", "pub", limit=0)
        self.assertEqual(exc.reason, "limit_invalid")

    def test_issue_comments_lifecycle(self):
        issue = self._open_issue()
        added = self.w.api.add_issue_comment(
            self.reader_h, "volmarr", "pub", issue["number"],
            {"body": "I can reproduce this."})
        self.assertEqual(added["author"], "yrsa")
        self.assertEqual(added["issue"], issue["number"])
        listed = self.w.api.list_issue_comments(
            None, "volmarr", "pub", issue["number"])
        self.assertEqual(listed["total"], 1)
        self.assertEqual(
            listed["comments"][0]["body"], "I can reproduce this.")
        exc = self._error(self.w.api.add_issue_comment,
                          self.reader_h, "volmarr", "pub",
                          issue["number"], {"body": "  "})
        self.assertEqual(exc.reason, "comment_required")
        exc = self._error(self.w.api.add_issue_comment, None,
                          "volmarr", "pub", issue["number"],
                          {"body": "anon"})
        self.assertEqual(exc.reason, "authentication_required")

    def test_issue_write_law_matches_the_web(self):
        issue = self._open_issue()
        # A stranger who can read the public repo still may
        # not edit another person's issue.
        exc = self._error(self.w.api.update_issue,
                          self.stranger_h, "volmarr", "pub",
                          issue["number"], {"title": "Hijacked"})
        self.assertEqual(exc.reason, "permission_denied")
        # The author may edit their own issue.
        mine = self.w.api.create_issue(
            self.reader_h, "volmarr", "pub", {"title": "Mine"})
        edited = self.w.api.update_issue(
            self.reader_h, "volmarr", "pub", mine["number"],
            {"title": "Mine, edited"})
        self.assertEqual(edited["title"], "Mine, edited")

    def test_issue_payload_law(self):
        exc = self._error(self.w.api.create_issue, self.owner_h,
                          "volmarr", "pub", {"name": "nope"})
        self.assertEqual(exc.reason, "payload_invalid")
        exc = self._error(self.w.api.create_issue, self.owner_h,
                          "volmarr", "pub", {"body": "no title"})
        self.assertEqual(exc.reason, "title_required")
        issue = self._open_issue()
        exc = self._error(self.w.api.update_issue, self.owner_h,
                          "volmarr", "pub", issue["number"], {})
        self.assertEqual(exc.reason, "payload_invalid")
        exc = self._error(self.w.api.update_issue, self.owner_h,
                          "volmarr", "pub", issue["number"],
                          {"labels": "bug"})
        self.assertEqual(exc.reason, "payload_invalid")
        exc = self._error(self.w.api.update_issue, self.owner_h,
                          "volmarr", "pub", issue["number"],
                          {"state": "closed", "reason": "whenever"})
        self.assertEqual(exc.reason, "reason_invalid")
        exc = self._error(self.w.api.update_issue, self.owner_h,
                          "volmarr", "pub", issue["number"],
                          {"reason": "completed"})
        self.assertEqual(exc.reason, "payload_invalid")

    def test_issue_not_found_is_uniform(self):
        exc = self._error(self.w.api.get_issue, None,
                          "volmarr", "pub", 99)
        self.assertEqual(exc.reason, "issue_not_found")
        self.assertEqual(str(exc), "No such issue.")
        issue = self._open_issue()
        pull = self._open_pull()
        exc = self._error(self.w.api.get_issue, None,
                          "volmarr", "pub", pull["number"])
        self.assertEqual(exc.reason, "issue_not_found")
        exc = self._error(self.w.api.get_pull, None,
                          "volmarr", "pub", issue["number"])
        self.assertEqual(exc.reason, "pull_request_not_found")

    # -- pulls: the acceptance drive ------------------------------
    def test_script_drives_a_pull_from_open_to_merge(self):
        # Open, through the API alone.
        pull = self._open_pull()
        number = pull["number"]
        self.assertEqual(pull["state"], "open")
        self.assertEqual(pull["head"], "feature")
        self.assertEqual(pull["base"], "main")
        self.assertFalse(pull["merged"])
        # Converse, through the API alone.
        said = self.w.api.add_pull_comment(
            self.reader_h, "volmarr", "pub", number,
            {"body": "Looking now."})
        self.assertEqual(said["pull"], number)
        thread = self.w.api.list_pull_comments(
            None, "volmarr", "pub", number)
        self.assertEqual(thread["total"], 1)
        # Review: a change request, then an approval,
        # through the API alone.
        asked = self.w.api.submit_review(
            self.reader_h, "volmarr", "pub", number,
            {"verdict": "request_changes",
             "summary": "Please note the new file."})
        self.assertEqual(asked["state"], "changes_requested")
        self.assertEqual(
            tuple(asked.keys()),
            get_resource("pull-reviews").fields)
        approved = self.w.api.submit_review(
            self.reader_h, "volmarr", "pub", number,
            {"verdict": "approve", "summary": "Noted. Ship it."})
        self.assertEqual(approved["state"], "approved")
        self.assertEqual(approved["author"], "yrsa")
        reviews = self.w.api.list_reviews(
            None, "volmarr", "pub", number)
        self.assertEqual(reviews["total"], 2)
        # Merge, through the API alone.
        landed = self.w.api.merge_pull(
            self.owner_h, "volmarr", "pub", number)
        self.assertTrue(landed["merged"])
        self.assertEqual(
            tuple(landed.keys()),
            get_resource("pull-merge").fields)
        base_tip = git(self.w.path, "rev-parse", "refs/heads/main")
        self.assertEqual(base_tip, landed["oid"])
        parents = git(self.w.path, "show", "-s", "--format=%P",
                      landed["oid"]).split()
        self.assertEqual(parents, [self.w.c1, self.w.c2])
        after = self.w.api.get_pull(None, "volmarr", "pub", number)
        self.assertEqual(after["state"], "closed")
        self.assertTrue(after["merged"])
        exc = self._error(self.w.api.merge_pull, self.owner_h,
                          "volmarr", "pub", number)
        self.assertEqual(exc.reason, "pull_request_closed")

    def test_pull_creation_law_matches_the_web(self):
        exc = self._error(self.w.api.create_pull, self.owner_h,
                          "volmarr", "pub",
                          {"base": "main", "head": "main"})
        self.assertEqual(exc.reason, "same_branch")
        exc = self._error(self.w.api.create_pull, self.owner_h,
                          "volmarr", "pub",
                          {"base": "main", "head": "ghost"})
        self.assertEqual(exc.reason, "head_not_found")
        exc = self._error(self.w.api.create_pull, self.reader_h,
                          "volmarr", "pub",
                          {"base": "main", "head": "feature"})
        self.assertEqual(exc.reason, "repo_not_found")
        self._open_pull()
        exc = self._error(self._open_pull)
        self.assertEqual(exc.reason, "already_exists")

    def test_pull_draft_round_trip(self):
        pull = self._open_pull(draft=True)
        number = pull["number"]
        exc = self._error(self.w.api.merge_pull, self.owner_h,
                          "volmarr", "pub", number)
        self.assertEqual(exc.reason, "pull_request_draft")
        ready = self.w.api.update_pull(
            self.owner_h, "volmarr", "pub", number,
            {"draft": False})
        self.assertEqual(ready["number"], number)
        back = self.w.api.update_pull(
            self.owner_h, "volmarr", "pub", number,
            {"draft": True})
        self.assertEqual(back["number"], number)
        exc = self._error(self.w.api.update_pull, self.owner_h,
                          "volmarr", "pub", number,
                          {"title": "No back doors"})
        self.assertEqual(exc.reason, "payload_invalid")

    def test_review_law_matches_the_web(self):
        pull = self._open_pull()
        number = pull["number"]
        exc = self._error(self.w.api.submit_review, self.owner_h,
                          "volmarr", "pub", number,
                          {"verdict": "approve", "summary": "Mine"})
        self.assertEqual(exc.reason, "self_review")
        exc = self._error(self.w.api.submit_review, self.reader_h,
                          "volmarr", "pub", number,
                          {"verdict": "request_changes"})
        self.assertEqual(exc.reason, "summary_required")
        exc = self._error(self.w.api.submit_review, self.reader_h,
                          "volmarr", "pub", number,
                          {"verdict": "shrug"})
        self.assertEqual(exc.reason, "verdict_invalid")
        noted = self.w.api.submit_review(
            self.owner_h, "volmarr", "pub", number,
            {"verdict": "comment", "summary": "Author's note."})
        self.assertEqual(noted["state"], "commented")

    def test_merge_requires_a_writer(self):
        pull = self._open_pull()
        exc = self._error(self.w.api.merge_pull, self.reader_h,
                          "volmarr", "pub", pull["number"])
        self.assertEqual(exc.reason, "repo_not_found")
        stored = self.w.prs.get_pull_request(
            self.w.owner, "volmarr", "pub", pull["number"])
        self.assertEqual(stored.state, "open")

    # -- auth, scope, and the leak law ------------------------------
    def test_anonymous_reads_public_and_never_private(self):
        self._open_issue()
        listed = self.w.api.list_issues(None, "volmarr", "pub")
        self.assertEqual(listed["total"], 1)
        exc = self._error(self.w.api.list_issues, None,
                          "volmarr", "priv")
        self.assertEqual(exc.reason, "repo_not_found")
        exc = self._error(self.w.api.create_issue, None,
                          "volmarr", "pub", {"title": "Anon"})
        self.assertEqual(exc.reason, "authentication_required")
        exc = self._error(self.w.api.list_issues,
                          "Bearer svk_nope", "volmarr", "pub")
        self.assertEqual(exc.reason, "credentials_invalid")

    def test_leak_equivalence_for_a_stranger(self):
        def snapshot(api, header):
            out = {}
            for fn, args in (
                    ("list_issues", ("volmarr", "priv")),
                    ("get_issue", ("volmarr", "priv", 1)),
                    ("list_pulls", ("volmarr", "priv"))):
                try:
                    data = getattr(api, fn)(header, *args)
                    out[fn] = ("ok", data["total"])
                except IssuesPullsAPIError as exc:
                    out[fn] = ("error", exc.reason, str(exc))
            return out
        with_world = snapshot(self.w.api, self.stranger_h)
        td2 = tempfile.TemporaryDirectory()
        self.addCleanup(td2.cleanup)
        bare = make_world(Path(td2.name), with_secret=False)
        self.addCleanup(bare.conn.close)
        without_world = snapshot(bare.api, basic("mallory", PW))
        self.assertEqual(with_world, without_world)
        self.assertEqual(
            with_world["get_issue"],
            ("error", "repo_not_found", "No such repository."))

    def test_token_scope_is_a_ceiling(self):
        ro = "Bearer " + self.w.owner_readonly
        exc = self._error(self.w.api.create_issue, ro,
                          "volmarr", "pub", {"title": "Scoped out"})
        self.assertEqual(exc.reason, "insufficient_scope")
        issues_tok = "Bearer " + self.w.owner_issues
        made = self.w.api.create_issue(
            issues_tok, "volmarr", "pub", {"title": "By token"})
        self.assertEqual(made["author"], "volmarr")
        exc = self._error(self.w.api.create_pull, issues_tok,
                          "volmarr", "pub",
                          {"base": "main", "head": "feature"})
        self.assertEqual(exc.reason, "insufficient_scope")
        pulls_tok = "Bearer " + self.w.owner_pulls
        pull = self.w.api.create_pull(
            pulls_tok, "volmarr", "pub",
            {"base": "main", "head": "feature"})
        self.assertEqual(pull["author"], "volmarr")
        fine = "Bearer " + self.w.fine_pub
        noted = self.w.api.add_issue_comment(
            fine, "volmarr", "pub", made["number"],
            {"body": "Fine-grained hello."})
        self.assertEqual(noted["author"], "volmarr")

    def test_writes_are_witnessed_by_the_stores(self):
        def count(action):
            return self.w.conn.execute(
                "SELECT COUNT(*) AS n FROM audit_log"
                " WHERE action = ?", (action,)).fetchone()["n"]
        before = count("repo.issue.create")
        issue = self._open_issue()
        self.assertEqual(count("repo.issue.create"), before + 1)
        self.w.api.add_issue_comment(
            self.reader_h, "volmarr", "pub", issue["number"],
            {"body": "Witnessed."})
        self.assertEqual(count("repo.issue.comment"), 1)
        pull = self._open_pull()
        self.assertEqual(count("repo.pull_request.create"), 1)
        self.w.api.submit_review(
            self.reader_h, "volmarr", "pub", pull["number"],
            {"verdict": "approve"})
        self.assertEqual(
            count("repo.pull_request.review_submit"), 1)
        self.w.api.merge_pull(
            self.owner_h, "volmarr", "pub", pull["number"])
        self.assertEqual(count("repo.pull_request.merge"), 1)

    def test_page_says_the_family_in_plain_words(self):
        page = render_issues_pulls_api_page()
        self.assertIn("Issues and pull requests API", page)
        self.assertIn("open to merge", page)


if __name__ == "__main__":
    unittest.main()
