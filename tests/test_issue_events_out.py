"""S-139 acceptance battery: issue events out.

Acceptance (roadmap S-139): every mutation emits
Part XI events and Part XII webhooks (here: the
outbound store + payload shape those parts consume).

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.assignees import AssigneeStore
from samverk.audit import AuditLog
from samverk.issue_comments import IssueCommentStore
from samverk.issue_events_out import (
    ISSUE_EVENT_VERBS, IssueEventOutError, IssueEventOutbox,
    payload_json, webhook_payload)
from samverk.issues import IssueStore
from samverk.labels import LabelStore
from samverk.repositories import RepositoryStore


class IssueEventsOutTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.reader = self.accounts.register("yrsa", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.issues = IssueStore(self.conn, self.repos, self.accounts, audit=self.audit)
        self.comments = IssueCommentStore(
            self.conn, self.repos, self.accounts, self.issues, audit=self.audit)
        self.labels = LabelStore(
            self.conn, self.repos, self.accounts, self.issues, audit=self.audit)
        self.assignees = AssigneeStore(
            self.conn, self.repos, self.accounts, self.issues, audit=self.audit)
        self.outbox = IssueEventOutbox(self.conn, self.repos, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "pub", visibility="public")

    def _mutate(self):
        self.issues.create_issue(self.reader, "volmarr", "pub", "Crash on startup")
        self.comments.add_comment(self.owner, "volmarr", "pub", 1, "Looking now")
        self.labels.add_to_issue(self.owner, "volmarr", "pub", 1, "bug")
        self.assignees.assign(self.owner, "volmarr", "pub", 1, "yrsa")
        self.issues.close_issue(self.owner, "volmarr", "pub", 1)

    def test_every_mutation_emits_exactly_once(self):
        self._mutate()
        emitted = self.outbox.sync_repo("volmarr", "pub")
        self.assertEqual(emitted, 5)
        events = self.outbox.list_events(self.owner, "volmarr", "pub")
        self.assertEqual(
            [e.verb for e in events],
            ["repo.issue.create", "repo.issue.comment",
             "repo.issue.label_add", "repo.issue.assign",
             "repo.issue.close"])
        self.assertTrue(all(e.number == 1 for e in events))
        self.assertEqual(events[0].actor, "yrsa")
        self.assertEqual(events[-1].detail.get("reason"), "completed")
        # Exactly-once: re-syncing (directly or through a read) emits 0.
        self.assertEqual(self.outbox.sync_repo("volmarr", "pub"), 0)
        self.assertEqual(self.outbox.sync_all(), 0)
        self.assertEqual(len(self.outbox.list_events(
            self.owner, "volmarr", "pub")), 5)

    def test_quiet_retries_emit_nothing(self):
        self.issues.create_issue(self.owner, "volmarr", "pub", "Once only")
        self.issues.close_issue(self.owner, "volmarr", "pub", 1)
        self.issues.close_issue(self.owner, "volmarr", "pub", 1)  # no-op
        verbs = [e.verb for e in
                 self.outbox.list_events(self.owner, "volmarr", "pub")]
        self.assertEqual(verbs, ["repo.issue.create", "repo.issue.close"])

    def test_non_issue_events_never_leak_in(self):
        # setUp already audited a signup pair + repo.create;
        # none of them are issue-family events.
        self.assertEqual(self.outbox.sync_all(), 0)
        self.assertNotIn("repo.create", ISSUE_EVENT_VERBS)
        self.assertNotIn("repo.push", ISSUE_EVENT_VERBS)
        self.assertNotIn("repo.issue_template.create", ISSUE_EVENT_VERBS)

    def test_verb_set_covers_the_part_vi_family(self):
        for verb in ("repo.issue.create", "repo.issue.comment",
                     "repo.issue.close", "repo.issue.lock",
                     "repo.issue.pin", "repo.issue.assign",
                     "repo.issue.label_add", "repo.issue.milestone",
                     "repo.issue.reaction_add", "repo.issue.transfer_out",
                     "repo.issue.convert", "repo.issue.comment_hide",
                     "repo.issue.comment_remove",
                     "repo.label.create", "repo.milestone.create",
                     "repo.pull_request.create"):
            self.assertIn(verb, ISSUE_EVENT_VERBS)

    def test_webhook_payload_shape(self):
        self._mutate()
        event = self.outbox.list_events(self.owner, "volmarr", "pub")[0]
        payload = webhook_payload(event)
        self.assertEqual(payload["event"], "repo.issue.create")
        self.assertEqual(payload["action"], "create")
        self.assertEqual(payload["repository"], "volmarr/pub")
        self.assertEqual(payload["number"], 1)
        self.assertEqual(payload["actor"], "yrsa")
        self.assertEqual(payload["delivery_id"], f"evt-{event.id}")
        self.assertEqual(payload["occurred_at"], event.created_at)
        self.assertEqual(json.loads(payload_json(event)), payload)

    def test_reads_follow_the_repository_gate(self):
        self._mutate()
        self.repos.create_repository(self.owner.id, "volmarr", "priv",
                                     visibility="private")
        self.issues.create_issue(self.owner, "volmarr", "priv", "Secret work")
        with self.assertRaises(IssueEventOutError) as caught:
            self.outbox.list_events(self.reader, "volmarr", "priv")
        self.assertEqual(caught.exception.reason, "repo_not_found")
        self.assertEqual(
            self.outbox.count_for_repo(self.owner, "volmarr", "priv"), 1)
        # Repositories do not share events.
        self.assertEqual(
            [e.repository for e in
             self.outbox.list_events(self.owner, "volmarr", "pub")],
            ["volmarr/pub"] * 5)


if __name__ == "__main__":
    unittest.main()
