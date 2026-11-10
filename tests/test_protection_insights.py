"""S-183 acceptance battery: rule insights.

Acceptance (roadmap S-183): a page answering
"why was this push/merge refused?" from the audit
trail, in plain words (user-friendliness law).

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.protection_insights import (
    REFUSAL_OUTCOMES, RuleInsightsStore, explain_refusal,
    render_insight, render_insights_page)
from samverk.repositories import RepositoryStore


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


class RuleInsightsTests(unittest.TestCase):
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
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.store = RuleInsightsStore(self.conn, self.repos, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(self.owner.id, "volmarr", "priv", visibility="private")
        self.repos.create_repository(self.owner.id, "volmarr", "other", visibility="public")

    def _refusal(self, target="volmarr/pub", actor=None,
                 action="repo.pull_request.merge", outcome="denied",
                 detail=None):
        return self.audit.append(
            actor_kind="user" if actor is not None else "anonymous",
            actor_id=actor.id if actor is not None else None,
            action=action, target_kind="repo", target_id=target,
            outcome=outcome, detail=detail)

    # pure explanation
    def test_explain_merge_permission(self):
        words = explain_refusal(
            "repo.pull_request.merge", "denied",
            {"number": 7, "reason": "permission_denied"})
        self.assertIn("pull request merge", words)
        self.assertIn("refused", words)
        self.assertIn("did not have the standing", words)
        self.assertIn("pull request #7", words)

    def test_explain_branch_and_gate(self):
        words = explain_refusal(
            "repo.push", "denied",
            {"branch": "main", "gate": "protection",
             "reason": "status_checks_required"})
        self.assertIn("branch was 'main'", words)
        self.assertIn("protection gate", words)
        self.assertIn("status check was not green", words)

    def test_explain_unknown_reason_humanised(self):
        words = explain_refusal(
            "repo.push", "failure", {"reason": "some_new_code"})
        self.assertIn("some new code", words)

    def test_explain_unknown_action_named_not_guessed(self):
        words = explain_refusal("repo.fork", "denied", None)
        self.assertIn("repo.fork", words)
        self.assertIn("refused", words)

    def test_explain_patterns_and_rules(self):
        words = explain_refusal(
            "repo.protection.bypass", "denied",
            {"patterns": ["main", "release/*"], "rule_ids": [3, 5],
             "reason": "bypass_not_allowed"})
        self.assertIn("main, release/*", words)
        self.assertIn("numbered 3, 5", words)
        self.assertIn("bypass list", words)

    def test_explain_no_detail_still_answers(self):
        words = explain_refusal("repo.push", "denied", None)
        self.assertIn("push", words)
        self.assertIn("refused", words)

    # store reads
    def test_only_refusals_for_this_repo(self):
        self._refusal(detail={"number": 1, "reason": "permission_denied"})
        self._refusal(action="repo.push", outcome="success")
        self._refusal(action="repo.pull_request.merge", outcome="success",
                      detail={"number": 2})
        self._refusal(target="volmarr/other")
        self.audit.append(actor_kind="user", actor_id=self.owner.id,
                          action="auth.login.failure", target_kind="user",
                          target_id=str(self.owner.id), outcome="denied")
        found = self.store.insights_for(self.owner, "volmarr", "pub")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].action, "repo.pull_request.merge")
        self.assertEqual(found[0].detail.get("reason"), "permission_denied")

    def test_newest_first_and_failure_counts(self):
        first = self._refusal(detail={"number": 1})
        second = self._refusal(outcome="failure", detail={"number": 2})
        found = self.store.insights_for(self.owner, "volmarr", "pub")
        self.assertEqual([f.seq for f in found], [second, first])

    def test_limit_clamped(self):
        for n in range(3):
            self._refusal(detail={"number": n})
        self.assertEqual(
            len(self.store.insights_for(self.owner, "volmarr", "pub", limit=2)), 2)
        self.assertEqual(
            len(self.store.insights_for(self.owner, "volmarr", "pub", limit=0)), 1)

    def test_actor_resolved_and_anonymous(self):
        self._refusal(actor=self.reader, detail={"number": 1})
        self._refusal(detail={"number": 2})
        found = self.store.insights_for(self.owner, "volmarr", "pub")
        by_number = {f.detail["number"]: f for f in found}
        self.assertEqual(by_number[1].actor, "yrsa")
        self.assertIsNone(by_number[2].actor)
        self.assertIn("by yrsa", by_number[1].words)
        self.assertIn("unnamed actor", by_number[2].words)

    def test_bad_detail_json_tolerated(self):
        seq = self._refusal(detail={"number": 9})
        self.conn.execute("UPDATE audit_log SET detail = ? WHERE seq = ?",
                          ("{not json", seq))
        found = self.store.insights_for(self.owner, "volmarr", "pub")
        self.assertEqual(len(found), 1)
        self.assertIsNone(found[0].detail)

    def test_latest_refusal(self):
        self.assertIsNone(self.store.latest_refusal(self.owner, "volmarr", "pub"))
        self._refusal(detail={"number": 1})
        newest = self._refusal(detail={"number": 2})
        latest = self.store.latest_refusal(self.owner, "volmarr", "pub")
        self.assertEqual(latest.seq, newest)

    def test_explain_one(self):
        seq = self._refusal(detail={"number": 5})
        other = self._refusal(target="volmarr/other")
        ok_seq = self._refusal(action="repo.push", outcome="success")
        one = self.store.explain_one(self.owner, "volmarr", "pub", seq)
        self.assertIsNotNone(one)
        self.assertIn("pull request #5", one.explanation)
        self.assertIsNone(self.store.explain_one(self.owner, "volmarr", "pub", other))
        self.assertIsNone(self.store.explain_one(self.owner, "volmarr", "pub", ok_seq))
        self.assertIsNone(self.store.explain_one(self.owner, "volmarr", "pub", 99999))

    # guard
    def test_private_stranger_repo_not_found(self):
        self._refusal(target="volmarr/priv")
        with self.assertRaises(Exception) as cm:
            self.store.insights_for(self.reader, "volmarr", "priv")
        self.assertEqual(getattr(cm.exception, "reason", ""), "repo_not_found")
        with self.assertRaises(Exception) as cm:
            self.store.insights_for(None, "volmarr", "priv")
        self.assertEqual(getattr(cm.exception, "reason", ""), "repo_not_found")

    def test_private_owner_and_public_anonymous(self):
        self._refusal(target="volmarr/priv", detail={"number": 1})
        self._refusal(target="volmarr/pub", detail={"number": 2})
        self.assertEqual(
            len(self.store.insights_for(self.owner, "volmarr", "priv")), 1)
        self.assertEqual(
            len(self.store.insights_for(None, "volmarr", "pub")), 1)
        with self.assertRaises(Exception) as cm:
            self.store.insights_for(self.owner, "volmarr", "missing")
        self.assertEqual(getattr(cm.exception, "reason", ""), "repo_not_found")

    # rendering
    def test_render_page_words_and_honesty(self):
        self._refusal(actor=self.owner, detail={"number": 3, "reason": "permission_denied"})
        found = self.store.insights_for(self.owner, "volmarr", "pub")
        page = render_insights_page("volmarr/pub", found)
        self.assertIn("Rule insights", page)
        self.assertIn("plain words", page)
        self.assertIn("cannot appear", page)
        self.assertIn("pull request #3", page)
        self.assertIn("by volmarr", page)

    def test_render_empty_page(self):
        page = render_insights_page("volmarr/pub", ())
        self.assertIn("Nothing has been refused", page)

    def test_render_escapes_detail(self):
        self._refusal(detail={"branch": "<script>alert(1)</script>"})
        found = self.store.insights_for(self.owner, "volmarr", "pub")
        html = render_insight(found[0])
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)
        page = render_insights_page("volmarr/pub", found)
        self.assertNotIn("<script>alert(1)</script>", page)

    def test_refusal_outcomes_constant(self):
        self.assertEqual(REFUSAL_OUTCOMES, frozenset({"denied", "failure"}))

    def test_no_migration_no_taxonomy(self):
        self.assertEqual(schema_version(self.conn), 104)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 131)


if __name__ == "__main__":
    unittest.main()
