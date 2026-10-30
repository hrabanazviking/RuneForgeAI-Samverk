"""S-144 acceptance battery: pull request conversation.

Acceptance (roadmap S-144): PR conversation — comments,
timeline merged with review events, closing-keyword
display from S-127.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.issue_timeline import TimelineStore
from samverk.issues import IssueStore
from samverk.pull_request_conversation import (
    PullRequestConversationStore, render_closing_notice,
    render_conversation, render_pr_timeline)
from samverk.pull_request_drafts import PullRequestDraftStore
from samverk.pull_requests import PullRequestError, PullRequestStore
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


class Clock:
    """One shared, settable clock: every store in the
    harness reads the same time, so ordering across
    comments, audit rows, and the PR row is exact."""

    def __init__(self, now=1_700_000_000):
        self.now = now

    def __call__(self):
        return self.now

    def set(self, now):
        self.now = now


class PullRequestConversationTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, time_fn=self.clock)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.reader = self.accounts.register("yrsa", "correct horse battery")
        self.third = self.accounts.register("tess", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.issues = IssueStore(self.conn, self.repos, self.accounts,
                                 audit=self.audit, time_fn=self.clock)
        self.prs = PullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.drafts = PullRequestDraftStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.convo = PullRequestConversationStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.timeline = TimelineStore(
            self.conn, self.repos, self.accounts, self.issues)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        base_path = self.repos.path_for("volmarr", "pub")
        self.base_oid = make_commit(
            base_path, None, {"a.txt": "base\n"}, "base commit")
        git(base_path, "update-ref", "refs/heads/main", self.base_oid)
        feature_oid = make_commit(
            base_path, self.base_oid,
            {"a.txt": "base\nfeature\n"}, "feature work")
        git(base_path, "update-ref", "refs/heads/feature", feature_oid)
        feature2_oid = make_commit(
            base_path, self.base_oid,
            {"a.txt": "base\nother\n"}, "other work")
        git(base_path, "update-ref", "refs/heads/feature2", feature2_oid)
        self.issue = self.issues.create_issue(
            self.owner, "volmarr", "pub", "The thing to fix")

    def _audit_count(self, action):
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM audit_log WHERE action = ?",
            (action,)).fetchone()
        return int(row["c"])

    def _open(self, body="", draft=False, head="feature"):
        return self.prs.create_pull_request(
            self.owner, "volmarr", "pub", base_branch="main",
            head_branch=head, body=body, draft=draft)

    # -- comments ---------------------------------------------------------
    def test_comments_live_on_the_pull_request(self):
        pr = self._open()
        self.clock.set(1_700_000_100)
        comment = self.convo.add_comment(
            self.reader, "volmarr", "pub", pr.number,
            "This looks right to me.")
        self.assertEqual(comment.number, pr.number)
        self.assertEqual(comment.author_id, self.reader.id)
        listed = self.convo.list_comments(
            self.third, "volmarr", "pub", pr.number)
        self.assertEqual([c.body for c in listed],
                         ["This looks right to me."])
        self.assertEqual(
            self._audit_count("repo.pull_request.comment"), 1)
        with self.assertRaises(PullRequestError) as caught:
            self.convo.add_comment(
                self.reader, "volmarr", "pub", pr.number, "   ")
        self.assertEqual(caught.exception.reason, "comment_required")

    def test_comment_edit_history_and_delete_tombstone(self):
        pr = self._open()
        comment = self.convo.add_comment(
            self.reader, "volmarr", "pub", pr.number, "first words")
        with self.assertRaises(PullRequestError) as caught:
            self.convo.edit_comment(
                self.third, "volmarr", "pub", pr.number,
                comment.id, "not my words")
        self.assertEqual(caught.exception.reason, "permission_denied")
        edited = self.convo.edit_comment(
            self.reader, "volmarr", "pub", pr.number,
            comment.id, "better words")
        self.assertTrue(edited.was_edited)
        history = self.convo.edits_for(
            self.owner, "volmarr", "pub", pr.number, comment.id)
        self.assertEqual([h.previous_body for h in history],
                         ["first words"])
        self.assertEqual(
            self._audit_count("repo.pull_request.comment_edit"), 1)
        # The repository's admin may delete another's comment;
        # the tombstone remains readable as deleted.
        deleted = self.convo.delete_comment(
            self.owner, "volmarr", "pub", pr.number, comment.id)
        self.assertTrue(deleted.is_deleted)
        self.assertEqual(self.convo.list_comments(
            self.owner, "volmarr", "pub", pr.number), [])
        fetched = self.convo.get_comment(
            self.owner, "volmarr", "pub", pr.number, comment.id)
        self.assertTrue(fetched.is_deleted)
        self.assertEqual(
            self._audit_count("repo.pull_request.comment_delete"), 1)

    def test_hidden_comments_follow_the_moderation_visibility_law(self):
        pr = self._open()
        comment = self.convo.add_comment(
            self.reader, "volmarr", "pub", pr.number, "rough words")
        # The moderation stamps are S-138's record on the
        # shared comment row; arranging them at the storage
        # layer here tests this slice's reading law.
        with self.conn:
            self.conn.execute(
                "UPDATE issue_comments SET hidden_at = ?, hidden_by = ?,"
                " hide_reason = 'abuse' WHERE id = ?",
                (1_700_000_200, self.owner.id, comment.id))
        self.assertEqual(self.convo.list_comments(
            self.third, "volmarr", "pub", pr.number), [])
        self.assertEqual(len(self.convo.list_comments(
            self.reader, "volmarr", "pub", pr.number)), 1)
        self.assertEqual(len(self.convo.list_comments(
            self.owner, "volmarr", "pub", pr.number)), 1)

    def test_locked_conversation_refuses_like_an_issue(self):
        pr = self._open()
        # Locking itself is S-132's issue-addressed act;
        # the locked state is arranged at the storage
        # layer its seam writes, as in S-143's battery.
        with self.conn:
            self.conn.execute(
                "UPDATE issues SET locked = 1, lock_reason = 'spam'"
                " WHERE id = ?", (pr.row_id,))
        with self.assertRaises(PullRequestError) as caught:
            self.convo.add_comment(
                self.reader, "volmarr", "pub", pr.number, "let me in")
        self.assertEqual(caught.exception.reason, "conversation_locked")
        self.assertIn("spam", str(caught.exception))
        mine = self.convo.add_comment(
            self.owner, "volmarr", "pub", pr.number, "writers still can")
        self.assertEqual(mine.body, "writers still can")

    # -- timeline + the merged conversation --------------------------------
    def test_timeline_merges_the_pull_requests_own_events(self):
        self.clock.set(1_700_000_000)
        pr = self._open(draft=True)
        self.clock.set(1_700_000_100)
        self.drafts.mark_ready(self.owner, "volmarr", "pub", pr.number)
        self.clock.set(1_700_000_200)
        self.drafts.convert_to_draft(
            self.owner, "volmarr", "pub", pr.number)
        events = self.convo.timeline_for(
            self.reader, "volmarr", "pub", pr.number)
        self.assertEqual([e.kind for e in events],
                         ["created", "marked_ready", "converted_to_draft"])
        page = render_pr_timeline(events)
        self.assertIn("opened this pull request", page)
        self.assertIn("marked this pull request ready for review", page)
        self.assertIn("converted this pull request back to a draft", page)

    def test_conversation_interleaves_comments_and_events_by_time(self):
        self.clock.set(1_700_000_000)
        pr = self._open(draft=True)
        self.clock.set(1_700_000_100)
        self.convo.add_comment(
            self.reader, "volmarr", "pub", pr.number, "starting review")
        self.clock.set(1_700_000_200)
        self.drafts.mark_ready(self.owner, "volmarr", "pub", pr.number)
        self.clock.set(1_700_000_300)
        self.convo.add_comment(
            self.owner, "volmarr", "pub", pr.number, "ready now")
        items = self.convo.conversation_for(
            self.third, "volmarr", "pub", pr.number)
        self.assertEqual([i.kind for i in items],
                         ["created", "comment", "marked_ready", "comment"])
        self.assertEqual(
            [i.comment.body for i in items if i.is_comment],
            ["starting review", "ready now"])
        page = render_conversation(items)
        self.assertIn("yrsa commented", page)
        self.assertIn("starting review", page)
        self.assertIn("marked this pull request ready for review", page)

    # -- closing-keyword display ---------------------------------------------
    def test_closing_keywords_in_the_body_are_shown_before_merge(self):
        pr = self._open(body=f"Fixes #{self.issue.number}")
        closing = self.convo.closing_references(
            self.reader, "volmarr", "pub", pr.number)
        self.assertEqual(
            [(c.target_repo, c.target_number, c.target_kind)
             for c in closing],
            [("volmarr/pub", self.issue.number, "issue")])
        notice = self.convo.closing_notice(
            self.reader, "volmarr", "pub", pr.number)
        self.assertEqual(
            notice,
            [f"Will close volmarr/pub#{self.issue.number} on merge."])
        page = render_closing_notice(notice)
        self.assertIn("Will close volmarr/pub#", page)

    def test_plain_references_do_not_close_and_comments_can_close(self):
        pr = self._open(body=f"See #{self.issue.number} for context",
                        head="feature2")
        self.assertEqual(self.convo.closing_references(
            self.owner, "volmarr", "pub", pr.number), [])
        empty_page = render_closing_notice(self.convo.closing_notice(
            self.owner, "volmarr", "pub", pr.number))
        self.assertIn("will not close any issue", empty_page)
        self.convo.add_comment(
            self.reader, "volmarr", "pub", pr.number,
            f"This now resolves #{self.issue.number}")
        closing = self.convo.closing_references(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual([c.target_number for c in closing],
                         [self.issue.number])
        # A reference to a number that does not exist closes nothing.
        self.convo.add_comment(
            self.reader, "volmarr", "pub", pr.number,
            "Fixes #999")
        self.assertEqual([c.target_number for c in self.convo
                          .closing_references(
                              self.owner, "volmarr", "pub", pr.number)],
                         [self.issue.number])

    def test_synced_references_join_both_timelines(self):
        pr = self._open(body=f"Fixes #{self.issue.number}")
        recorded = self.convo.sync_references(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(len(recorded), 1)
        self.assertTrue(recorded[0].is_closing)
        events = self.convo.timeline_for(
            self.owner, "volmarr", "pub", pr.number)
        referenced = [e for e in events if e.kind == "referenced"]
        self.assertEqual(len(referenced), 1)
        self.assertTrue(referenced[0].is_closing)
        self.assertEqual(referenced[0].target_number, self.issue.number)
        # And the issue gains its back-reference, through
        # S-131's own stream.
        issue_events = self.timeline.timeline_for(
            self.owner, "volmarr", "pub", self.issue.number)
        mentioned = [e for e in issue_events if e.kind == "mentioned"]
        self.assertEqual(len(mentioned), 1)
        self.assertEqual(mentioned[0].source_number, pr.number)

    # -- rendering + permissions ----------------------------------------------
    def test_rendering_escapes_and_says_everything_in_words(self):
        pr = self._open(body=f"Fixes #{self.issue.number}")
        self.convo.add_comment(
            self.reader, "volmarr", "pub", pr.number,
            "<script>alert(1)</script>")
        page = render_conversation(self.convo.conversation_for(
            self.owner, "volmarr", "pub", pr.number))
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("yrsa commented", page)

    def test_private_repository_answers_uniformly(self):
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        priv_path = self.repos.path_for("volmarr", "priv")
        priv_base = make_commit(priv_path, None, {"s.txt": "s\n"}, "one")
        git(priv_path, "update-ref", "refs/heads/main", priv_base)
        priv_head = make_commit(
            priv_path, priv_base, {"s.txt": "s\nmore\n"}, "two")
        git(priv_path, "update-ref", "refs/heads/feature", priv_head)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", "priv", base_branch="main",
            head_branch="feature")
        for call in (
                lambda: self.convo.add_comment(
                    self.reader, "volmarr", "priv", pr.number, "hello"),
                lambda: self.convo.list_comments(
                    self.reader, "volmarr", "priv", pr.number),
                lambda: self.convo.timeline_for(
                    self.reader, "volmarr", "priv", pr.number),
                lambda: self.convo.conversation_for(
                    self.reader, "volmarr", "priv", pr.number),
                lambda: self.convo.closing_notice(
                    self.reader, "volmarr", "priv", pr.number)):
            with self.assertRaises(PullRequestError) as caught:
                call()
            self.assertEqual(
                caught.exception.reason, "pull_request_not_found")


if __name__ == "__main__":
    unittest.main()
