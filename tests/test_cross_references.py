"""S-127 acceptance battery: cross-references.

Acceptance (roadmap S-127): mentioning `#n` or a commit
links both ways; closing keywords (`closes #n`) parsed
and shown before merge.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.cross_references import (
    CrossReferenceStore, parse_closing_references, parse_references)
from samverk.issue_comments import IssueCommentStore
from samverk.issues import IssueError, IssueStore
from samverk.repositories import RepositoryStore

FULL_OID = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"

class CrossReferenceTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.reader = self.accounts.register("yrsa", "correct horse battery")
        self.other = self.accounts.register("mallory", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.issues = IssueStore(self.conn, self.repos, self.accounts, audit=self.audit)
        self.comments = IssueCommentStore(
            self.conn, self.repos, self.accounts, self.issues, audit=self.audit)
        self.xrefs = CrossReferenceStore(
            self.conn, self.repos, self.accounts, self.issues,
            commit_resolver=lambda o, r, s: FULL_OID if FULL_OID.startswith(s) else None)
        self.repos.create_repository(self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(self.owner.id, "volmarr", "other", visibility="public")
        self.repos.create_repository(self.owner.id, "volmarr", "priv", visibility="private")
        self.target = self.issues.create_issue(self.owner, "volmarr", "pub", "Target")
        self.other_target = self.issues.create_issue(self.owner, "volmarr", "other", "Elsewhere")

    def test_mention_links_both_ways(self):
        source = self.issues.create_issue(
            self.owner, "volmarr", "pub", "Source", "See #1 and also #99.")
        recorded = self.xrefs.sync_issue_references(self.owner, "volmarr", "pub", source.number)
        # #99 was never claimed: prose, not a link, no row.
        self.assertEqual([r.target_number for r in recorded], [1])
        forward = self.xrefs.references_from(None, "volmarr", "pub", source.number)
        self.assertEqual([r.target_number for r in forward], [1])
        backward = self.xrefs.references_to(None, "volmarr", "pub", 1)
        self.assertEqual([(r.source_number, r.source_kind) for r in backward],
                         [(source.number, "issue")])
        # A re-sync is idempotent: no duplicate rows.
        self.xrefs.sync_issue_references(self.owner, "volmarr", "pub", source.number)
        self.assertEqual(len(self.xrefs.references_to(None, "volmarr", "pub", 1)), 1)

    def test_closing_keywords_parsed(self):
        parsed = parse_references("Fixes #3, see also #4. This closes #5.")
        by_number = {r.target_number: r for r in parsed}
        self.assertTrue(by_number[3].is_closing)
        self.assertFalse(by_number[4].is_closing)
        self.assertTrue(by_number[5].is_closing)
        listed = parse_closing_references("Closes volmarr/other#1, #2 and resolves #6")
        self.assertEqual(
            [(r.target_owner, r.target_number) for r in listed],
            [("volmarr", 1), (None, 2), (None, 6)])
        # A mention repeated under a keyword folds to closing.
        folded = parse_references("See #7. Fixes #7")
        self.assertEqual(len(folded), 1)
        self.assertTrue(folded[0].is_closing)

    def test_closing_shown_before_merge(self):
        pr = self.issues.create_issue(
            self.owner, "volmarr", "pub", "The fix", "Fixes #1")
        self.xrefs.sync_issue_references(self.owner, "volmarr", "pub", pr.number)
        closing = self.xrefs.closing_references(None, "volmarr", "pub", pr.number)
        self.assertEqual([r.target_number for r in closing], [1])
        self.assertEqual(
            self.xrefs.closing_notice(None, "volmarr", "pub", pr.number),
            ["Will close volmarr/pub#1 on merge."])

    def test_code_is_not_prose(self):
        source = self.issues.create_issue(
            self.owner, "volmarr", "pub", "Quoting",
            "Real mention of #1.\n\n```\n#2 in a fence\n```\n\nAnd `#1` inline.")
        recorded = self.xrefs.sync_issue_references(self.owner, "volmarr", "pub", source.number)
        self.assertEqual([r.target_number for r in recorded], [1])

    def test_cross_repo_reference(self):
        source = self.issues.create_issue(
            self.owner, "volmarr", "pub", "Pointer",
            "Tracked in volmarr/other#1; volmarr/nope#1 is not a place.")
        recorded = self.xrefs.sync_issue_references(self.owner, "volmarr", "pub", source.number)
        self.assertEqual(len(recorded), 1)
        other_repo = self.repos.get_repository("volmarr", "other")
        self.assertEqual(recorded[0].target_repo_id, other_repo.id)
        backward = self.xrefs.references_to(None, "volmarr", "other", 1)
        self.assertEqual([r.source_number for r in backward], [source.number])

    def test_edit_resync_and_self_reference(self):
        source = self.issues.create_issue(
            self.owner, "volmarr", "pub", "Draft", "Depends on #1.")
        self.xrefs.sync_issue_references(self.owner, "volmarr", "pub", source.number)
        self.assertEqual(len(self.xrefs.references_to(None, "volmarr", "pub", 1)), 1)
        self.issues.update_issue(self.owner, "volmarr", "pub", source.number, body="No deps.")
        self.xrefs.sync_issue_references(self.owner, "volmarr", "pub", source.number)
        self.assertEqual(self.xrefs.references_to(None, "volmarr", "pub", 1), [])
        self_ref = self.issues.create_issue(
            self.owner, "volmarr", "pub", "Self", "This very issue, #3, speaks.")
        self.assertEqual(
            self.xrefs.sync_issue_references(self.owner, "volmarr", "pub", self_ref.number), [])

    def test_comment_references_die_with_the_comment(self):
        host = self.issues.create_issue(self.owner, "volmarr", "pub", "Host")
        comment = self.comments.add_comment(self.reader, "volmarr", "pub", host.number, "See #1")
        recorded = self.xrefs.sync_comment_references(
            self.reader, "volmarr", "pub", host.number, comment.id)
        self.assertEqual([(r.source_kind, r.target_number) for r in recorded],
                         [("comment", 1)])
        back = self.xrefs.references_to(None, "volmarr", "pub", 1)
        self.assertEqual([r.source_comment_id for r in back], [comment.id])
        self.comments.delete_comment(self.reader, "volmarr", "pub", host.number, comment.id)
        self.assertEqual(self.xrefs.sync_comment_references(
            self.reader, "volmarr", "pub", host.number, comment.id), [])
        self.assertEqual(self.xrefs.references_to(None, "volmarr", "pub", 1), [])

    def test_commit_references_both_ways(self):
        recorded = self.xrefs.record_commit_references(
            "volmarr", "pub", FULL_OID, "Fix the thing.\n\nRefs #1. Fixes #2",
            author_id=self.owner.id)
        # #2 was never claimed in pub, so only the proven #1 lands.
        self.assertEqual([(r.target_number, r.is_closing) for r in recorded], [(1, False)])
        back = self.xrefs.references_to(None, "volmarr", "pub", 1)
        self.assertEqual([(r.source_kind, r.source_sha) for r in back],
                         [("commit", FULL_OID)])
        # And the other direction: prose naming the commit, resolver-gated.
        mention = self.issues.create_issue(
            self.owner, "volmarr", "pub", "Bisect", f"Broken by {FULL_OID[:10]}.")
        got = self.xrefs.sync_issue_references(self.owner, "volmarr", "pub", mention.number)
        self.assertEqual([r.target_sha for r in got], [FULL_OID])
        to_commit = self.xrefs.references_to_commit(None, "volmarr", "pub", FULL_OID[:7])
        self.assertEqual([r.source_number for r in to_commit], [mention.number])
        # Without a resolver wired, a SHA mention records nothing.
        bare = CrossReferenceStore(self.conn, self.repos, self.accounts, self.issues)
        fresh = self.issues.create_issue(
            self.owner, "volmarr", "pub", "Bisect 2", f"Also {FULL_OID[:10]}.")
        self.assertEqual(bare.sync_issue_references(
            self.owner, "volmarr", "pub", fresh.number), [])

    def test_private_source_hidden_from_public_target(self):
        secret = self.issues.create_issue(
            self.owner, "volmarr", "priv", "Secret", "Relates to volmarr/pub#1")
        self.xrefs.sync_issue_references(self.owner, "volmarr", "priv", secret.number)
        # The owner, who can read both, sees the back-reference.
        self.assertEqual(
            len(self.xrefs.references_to(self.owner, "volmarr", "pub", 1)), 1)
        # A stranger to the private repo does not learn it exists.
        self.assertEqual(self.xrefs.references_to(self.other, "volmarr", "pub", 1), [])
        self.assertEqual(self.xrefs.references_to(None, "volmarr", "pub", 1), [])
        with self.assertRaises(IssueError) as caught:
            self.xrefs.references_to(self.other, "volmarr", "priv", 1)
        self.assertEqual(caught.exception.reason, "issue_not_found")

if __name__ == "__main__":
    unittest.main()
