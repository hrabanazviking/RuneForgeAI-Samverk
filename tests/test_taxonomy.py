"""S-008 acceptance battery: audit event taxonomy v1.

Acceptance (roadmap S-008): taxonomy doc + emitter tests — emitters
can only use taxonomy names, and the doc and the code agree exactly.

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk import db, taxonomy
from samverk.audit import AuditLog


class TaxonomyTests(unittest.TestCase):
    def test_taxonomy_size_and_families(self):
        # 37 at the S-008 freeze; append-only additions since:
        # S-026 added auth.email.verify + admin.user.approve;
        # S-029 added auth.profile.update;
        # S-037 added auth.recovery.generate + auth.recovery.use;
        # S-039 added auth.passkey.add/remove/login;
        # S-041 added auth.signin.notify;
        # S-042 added auth.username.change;
        # S-043 added auth.deletion.request/cancel/execute;
        # S-044 added admin.user.suspend/unsuspend;
        # S-045 added auth.identity.link/unlink.
        # S-055 added repo.fork; S-094 added repo.fetch.
        # S-122 added repo.issue.create/update.
        # S-123 added repo.issue.comment/comment_edit/comment_delete.
        # S-124 added repo.label.create/update/delete and
        # repo.issue.label_add/label_remove.
        # S-125 added repo.milestone.create/update/delete and
        # repo.issue.milestone.
        # S-126 added repo.issue.assign/unassign.
        # S-128 added repo.issue.reaction_add/reaction_remove.
        # S-129 added repo.issue_template.create/update/delete.
        # S-130 added repo.issue.close/reopen.
        # S-132 added repo.issue.lock/unlock/pin/unpin.
        # S-133 added repo.issue.transfer_out/transfer_in.
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 85)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 29)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 44)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 12)

    def test_names_are_well_formed(self):
        pattern = re.compile(r"^(auth|repo|admin)(\.[a-z0-9_]+)+$")
        for name in taxonomy.AUDIT_EVENTS:
            self.assertRegex(name, pattern)

    def test_doc_and_code_agree_exactly(self):
        doc = (Path(__file__).resolve().parent.parent
               / "docs" / "AUDIT_TAXONOMY.md").read_text(encoding="utf-8")
        in_doc = set(re.findall(r"`((?:auth|repo|admin)(?:\.[a-z0-9_]+)+)`", doc))
        self.assertEqual(in_doc, set(taxonomy.AUDIT_EVENTS))


class EmitterTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.conn = db.init_db(Path(self._td.name) / "samverk.db")
        self.log = AuditLog(self.conn)

    def tearDown(self):
        self.conn.close()
        self._td.cleanup()

    def test_every_taxonomy_event_can_be_emitted(self):
        for name in sorted(taxonomy.AUDIT_EVENTS):
            seq = self.log.append(
                actor_kind="system", action=name,
                target_kind="instance", outcome="success")
            self.assertGreaterEqual(seq, 1)

    def test_unknown_event_is_refused(self):
        for bad in ("auth.login.sucess", "repo.explode", "user.ban", ""):
            with self.assertRaises(ValueError, msg=bad):
                self.log.append(actor_kind="user", action=bad,
                                target_kind="user", outcome="success")

    def test_refused_event_enters_nothing(self):
        with self.assertRaises(ValueError):
            self.log.append(actor_kind="user", action="repo.explode",
                            target_kind="repo", outcome="success")
        count = self.conn.execute("SELECT COUNT(*) c FROM audit_log").fetchone()["c"]
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
