"""S-310 acceptance battery: security advisories (private).

Acceptance (roadmap S-310): Security advisories
(private) -- maintainers draft an advisory in
private, coordinate a fix, then publish with the
alert linkage.

The centre is samverk/security_advisories.py: an
advisory born draft and visible to the repository's
admin/maintain rungs alone (the uniform
advisory_not_found to everyone else, on public and
private repositories alike), coordinated in draft
(edits, a fix reference, links to standing alerts
of the three families in the same repository only),
published by the pure decide_publish (state, then
rung, then completeness -- the alert linkage or the
affected dependency named), its linkage frozen at
publication, and withdrawn only with a stated
reason, staying readable in that state. Migration
128 (schema 127 -> 128); taxonomy unmoved at 135
(33 auth / 89 repo / 13 admin) -- the advisory's
witness is its own events record, and the battery
proves the audit log does not move.

Counted with: python3 -m unittest tests.test_security_advisories
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.repositories import RepositoryStore
from samverk.security_advisories import (
    AdvisoryError, SecurityAdvisoryStore,
    audit_security_advisories, decide_publish,
    decide_visibility, render_advisories_page,
    render_advisory_page, advisory_to_dict)

PW = "correct horse battery"
T0 = 1_700_000_000


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


class PureLawTests(unittest.TestCase):
    def test_visibility(self):
        self.assertTrue(decide_visibility(state="draft", role="admin"))
        self.assertTrue(decide_visibility(state="draft", role="maintain"))
        for role in ("write", "triage", "read", None):
            self.assertFalse(decide_visibility(state="draft", role=role))
        for state in ("published", "withdrawn"):
            self.assertTrue(decide_visibility(state=state, role="read"))
            self.assertFalse(decide_visibility(state=state, role=None))
        self.assertFalse(decide_visibility(state="bogus", role="admin"))

    def _publish(self, **kw):
        base = dict(state="draft", role="admin", actor="volmarr",
                    full_name="volmarr/pub", title="A flaw",
                    summary="It is bad.", severity="high",
                    linked_count=1, dependency_name="")
        base.update(kw)
        return decide_publish(**base)

    def test_publish_complete_with_linkage(self):
        self.assertTrue(self._publish().may_publish)
        self.assertTrue(
            self._publish(linked_count=0,
                          dependency_name="pyyaml").may_publish)

    def test_publish_state_first(self):
        d = self._publish(state="published")
        self.assertEqual(d.code, "advisory_already_published")
        d = self._publish(state="withdrawn")
        self.assertEqual(d.code, "advisory_withdrawn")
        # State is judged before the rung: even a
        # reader hears the state refusal.
        d = self._publish(state="published", role="read")
        self.assertEqual(d.code, "advisory_already_published")

    def test_publish_rung(self):
        for role in ("write", "triage", "read", None):
            d = self._publish(role=role)
            self.assertEqual(d.code, "advisory_not_permitted")

    def test_publish_completeness(self):
        d = self._publish(linked_count=0, dependency_name="")
        self.assertEqual(d.code, "advisory_incomplete")
        d = self._publish(summary="")
        self.assertEqual(d.code, "advisory_incomplete")
        d = self._publish(title="")
        self.assertEqual(d.code, "advisory_incomplete")
        d = self._publish(severity="severe")
        self.assertEqual(d.code, "advisory_incomplete")


def seed_dependency_alert(conn, repo_id, n=1):
    conn.execute(
        "INSERT INTO dependency_alerts (repo_id,"
        " dependency_id, ecosystem, dependency_name,"
        " name_key, manifest_path, specifier, basis,"
        " pinned_version, advisory_id, severity, affected,"
        " fixed_version, summary, snapshot_date, state,"
        " created_at, updated_at, resolution,"
        " resolved_by_id, resolved_by, resolved_at,"
        " resolution_reason) VALUES (?, NULL, 'python',"
        " 'pyyaml', 'pyyaml', 'requirements.txt', '==1.0',"
        " 'pinned', '1.0', 'CVE-T-0001', 'high', '<2.0',"
        " '2.0', 'seeded summary', '2023-11-10', 'open',"
        " ?, ?, '', NULL, '', NULL, '')",
        (repo_id, T0, T0))
    conn.commit()
    return conn.execute(
        "SELECT last_insert_rowid() AS id").fetchone()["id"]


def seed_secret_alert(conn, repo_id, n=1):
    conn.execute(
        "INSERT INTO secret_alerts (repo_id, scan_id,"
        " commit_oid, path, blob_oid, source, detector_id,"
        " line, column, redacted, fingerprint, state,"
        " created_at) VALUES (?, 1, ?, 'src/keys.py', ?,"
        " 'push', 'github_pat', 1, 1, 'ghp_...1234', ?,"
        " 'open', ?)",
        (repo_id, "a" * 40, "b" * 40, f"fp-{n}", T0))
    conn.commit()
    return conn.execute(
        "SELECT last_insert_rowid() AS id").fetchone()["id"]


class AdvisoryTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(
            self.conn, audit=self.audit, time_fn=self.clock)
        self.owner = self.accounts.register("volmarr", PW)
        self.stranger = self.accounts.register("mallory", PW)
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts)
        self.pub = self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.priv = self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        self.store = SecurityAdvisoryStore(
            self.conn, self.repos, self.accounts,
            time_fn=self.clock)

    def _draft(self, repo="pub", **kw):
        base = dict(title="PyYAML loads arbitrary objects",
                    summary="Unsafe load of untrusted YAML.",
                    severity="high", ecosystem="python",
                    dependency_name="pyyaml", affected="<5.4",
                    fixed_version="5.4")
        base.update(kw)
        return self.store.create_advisory(
            self.owner, "volmarr", repo, **base)

    def _audit_count(self):
        return self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]

    # -- schema / taxonomy -------------------------------------------

    def test_schema_and_taxonomy_stand(self):
        self.assertEqual(schema_version(self.conn), 128)
        self.assertEqual(db.MIGRATIONS[-1][0], 128)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 135)

    # -- creation and the private door ---------------------------------

    def test_create_draft(self):
        adv = self._draft()
        self.assertEqual(adv.state, "draft")
        self.assertTrue(adv.is_draft)
        self.assertEqual(adv.advisory_key, "SAMVERK-ADV-0001")
        self.assertEqual(adv.severity, "high")
        self.assertEqual(adv.fixed_version, "5.4")
        self.assertEqual(adv.fixed_words(), "fixed in 5.4")
        self.assertEqual(adv.created_by, "volmarr")
        self.assertEqual(adv.links, ())

    def test_create_validation(self):
        with self.assertRaises(AdvisoryError) as ctx:
            self._draft(title="  ")
        self.assertEqual(ctx.exception.reason, "title_required")
        with self.assertRaises(AdvisoryError) as ctx:
            self._draft(severity="severe")
        self.assertEqual(ctx.exception.reason, "severity_invalid")
        with self.assertRaises(AdvisoryError) as ctx:
            self._draft(title="x" * 201)
        self.assertEqual(ctx.exception.reason, "title_too_long")

    def test_fix_unknown_is_honest(self):
        adv = self._draft(fixed_version=None)
        self.assertIsNone(adv.fixed_version)
        self.assertEqual(adv.fixed_words(), "fix unknown")
        self.assertIn("fix unknown", adv.words())
        self.assertIsNone(advisory_to_dict(adv)["fixed_version"])

    def test_draft_invisible_to_non_maintainers(self):
        adv = self._draft()
        for viewer in (self.stranger, None):
            with self.assertRaises(AdvisoryError) as ctx:
                self.store.get_advisory(viewer, "volmarr", "pub", adv.id)
            self.assertEqual(ctx.exception.reason, "advisory_not_found")
            listed = self.store.list_advisories(
                viewer, "volmarr", "pub")
            self.assertEqual(listed, ())
            counts = self.store.count_advisories(
                viewer, "volmarr", "pub")
            self.assertEqual(counts["draft"], 0)
            self.assertEqual(counts["total"], 0)
        got = self.store.get_advisory(self.owner, "volmarr", "pub", adv.id)
        self.assertEqual(got.id, adv.id)

    def test_stranger_cannot_create_or_publish(self):
        with self.assertRaises(AdvisoryError) as ctx:
            self.store.create_advisory(
                self.stranger, "volmarr", "pub", title="x",
                severity="low")
        self.assertEqual(ctx.exception.reason, "advisory_not_permitted")
        with self.assertRaises(AdvisoryError) as ctx:
            self.store.create_advisory(
                None, "volmarr", "pub", title="x", severity="low")
        self.assertEqual(ctx.exception.reason, "advisory_not_permitted")
        adv = self._draft()
        # At the publish door a draft does not even
        # exist to a non-maintainer.
        with self.assertRaises(AdvisoryError) as ctx:
            self.store.publish_advisory(
                self.stranger, "volmarr", "pub", adv.id)
        self.assertEqual(ctx.exception.reason, "advisory_not_found")

    def test_private_repo_stranger_gets_repo_not_found(self):
        adv = self._draft(repo="priv")
        self.store.publish_advisory(self.owner, "volmarr", "priv", adv.id)
        for viewer in (self.stranger, None):
            with self.assertRaises(AdvisoryError) as ctx:
                self.store.get_advisory(viewer, "volmarr", "priv", adv.id)
            self.assertEqual(ctx.exception.reason, "repo_not_found")
        got = self.store.get_advisory(
            self.owner, "volmarr", "priv", adv.id)
        self.assertEqual(got.state, "published")

    def test_missing_repo_and_advisory(self):
        with self.assertRaises(AdvisoryError) as ctx:
            self.store.get_advisory(self.owner, "volmarr", "nope", 1)
        self.assertEqual(ctx.exception.reason, "repo_not_found")
        with self.assertRaises(AdvisoryError) as ctx:
            self.store.get_advisory(self.owner, "volmarr", "pub", 999)
        self.assertEqual(ctx.exception.reason, "advisory_not_found")

    # -- coordination in draft ------------------------------------------

    def test_update_draft_and_fix_reference(self):
        adv = self._draft(fix_reference="")
        updated = self.store.update_advisory(
            self.owner, "volmarr", "pub", adv.id,
            fix_reference="PR #42", summary="Sharper summary.")
        self.assertEqual(updated.fix_reference, "PR #42")
        self.assertEqual(updated.summary, "Sharper summary.")
        with self.assertRaises(AdvisoryError) as ctx:
            self.store.update_advisory(
                self.owner, "volmarr", "pub", adv.id)
        self.assertEqual(ctx.exception.reason, "update_empty")
        with self.assertRaises(AdvisoryError) as ctx:
            self.store.update_advisory(
                self.stranger, "volmarr", "pub", adv.id,
                title="hijack")
        self.assertEqual(ctx.exception.reason, "advisory_not_permitted")

    def test_link_alerts(self):
        dep_id = seed_dependency_alert(self.conn, self.pub.id)
        sec_id = seed_secret_alert(self.conn, self.pub.id)
        adv = self._draft(dependency_name="", ecosystem="")
        linked = self.store.link_alert(
            self.owner, "volmarr", "pub", adv.id,
            family="dependency", alert_id=dep_id)
        self.assertEqual(len(linked.links), 1)
        self.assertEqual(linked.links[0].family, "dependency")
        linked = self.store.link_alert(
            self.owner, "volmarr", "pub", adv.id,
            family="secret", alert_id=sec_id)
        self.assertEqual(len(linked.links), 2)
        with self.assertRaises(AdvisoryError) as ctx:
            self.store.link_alert(
                self.owner, "volmarr", "pub", adv.id,
                family="dependency", alert_id=dep_id)
        self.assertEqual(ctx.exception.reason, "alert_already_linked")
        unlinked = self.store.unlink_alert(
            self.owner, "volmarr", "pub", adv.id,
            family="secret", alert_id=sec_id)
        self.assertEqual(len(unlinked.links), 1)
        with self.assertRaises(AdvisoryError) as ctx:
            self.store.unlink_alert(
                self.owner, "volmarr", "pub", adv.id,
                family="secret", alert_id=sec_id)
        self.assertEqual(ctx.exception.reason, "link_not_found")

    def test_link_refusals(self):
        other_dep = seed_dependency_alert(self.conn, self.priv.id)
        adv = self._draft()
        # Another repository's alert can never be claimed.
        with self.assertRaises(AdvisoryError) as ctx:
            self.store.link_alert(
                self.owner, "volmarr", "pub", adv.id,
                family="dependency", alert_id=other_dep)
        self.assertEqual(ctx.exception.reason, "alert_not_found")
        with self.assertRaises(AdvisoryError) as ctx:
            self.store.link_alert(
                self.owner, "volmarr", "pub", adv.id,
                family="dependency", alert_id=999)
        self.assertEqual(ctx.exception.reason, "alert_not_found")
        with self.assertRaises(AdvisoryError) as ctx:
            self.store.link_alert(
                self.owner, "volmarr", "pub", adv.id,
                family="wiki", alert_id=1)
        self.assertEqual(ctx.exception.reason, "family_invalid")

    # -- publication -------------------------------------------------------

    def test_publish_freezes_linkage_and_opens_reads(self):
        dep_id = seed_dependency_alert(self.conn, self.pub.id)
        adv = self._draft(dependency_name="", ecosystem="")
        self.store.link_alert(
            self.owner, "volmarr", "pub", adv.id,
            family="dependency", alert_id=dep_id)
        published = self.store.publish_advisory(
            self.owner, "volmarr", "pub", adv.id)
        self.assertEqual(published.state, "published")
        self.assertEqual(published.published_by, "volmarr")
        self.assertEqual(published.published_at, T0)
        # Anyone may now read it on the public repo.
        for viewer in (self.stranger, None, self.owner):
            got = self.store.get_advisory(
                viewer, "volmarr", "pub", adv.id)
            self.assertEqual(got.state, "published")
            self.assertEqual(len(got.links), 1)
        # The linkage and the facts are frozen now.
        with self.assertRaises(AdvisoryError) as ctx:
            self.store.link_alert(
                self.owner, "volmarr", "pub", adv.id,
                family="dependency", alert_id=dep_id)
        self.assertEqual(ctx.exception.reason, "advisory_not_editable")
        with self.assertRaises(AdvisoryError) as ctx:
            self.store.update_advisory(
                self.owner, "volmarr", "pub", adv.id, title="new")
        self.assertEqual(ctx.exception.reason, "advisory_not_editable")
        with self.assertRaises(AdvisoryError) as ctx:
            self.store.publish_advisory(
                self.owner, "volmarr", "pub", adv.id)
        self.assertEqual(
            ctx.exception.reason, "advisory_already_published")

    def test_publish_incomplete_stays_draft(self):
        adv = self._draft(
            title="Unnamed flaw", summary="",
            dependency_name="", ecosystem="")
        with self.assertRaises(AdvisoryError) as ctx:
            self.store.publish_advisory(
                self.owner, "volmarr", "pub", adv.id)
        self.assertEqual(ctx.exception.reason, "advisory_incomplete")
        got = self.store.get_advisory(self.owner, "volmarr", "pub", adv.id)
        self.assertEqual(got.state, "draft")
        # Completing it (summary + dependency) lets it publish.
        self.store.update_advisory(
            self.owner, "volmarr", "pub", adv.id,
            summary="Now said in words.", dependency_name="pyyaml")
        published = self.store.publish_advisory(
            self.owner, "volmarr", "pub", adv.id)
        self.assertEqual(published.state, "published")

    def test_list_and_counts_respect_privacy(self):
        a1 = self._draft(title="Draft one")
        a2 = self._draft(title="Published one")
        self.store.publish_advisory(self.owner, "volmarr", "pub", a2.id)
        mine = self.store.list_advisories(self.owner, "volmarr", "pub")
        self.assertEqual(len(mine), 2)
        theirs = self.store.list_advisories(
            self.stranger, "volmarr", "pub")
        self.assertEqual(len(theirs), 1)
        self.assertEqual(theirs[0].id, a2.id)
        only_drafts = self.store.list_advisories(
            self.stranger, "volmarr", "pub", state="draft")
        self.assertEqual(only_drafts, ())
        counts = self.store.count_advisories(
            self.owner, "volmarr", "pub")
        self.assertEqual(
            counts, {"draft": 1, "published": 1,
                     "withdrawn": 0, "total": 2})
        with self.assertRaises(AdvisoryError) as ctx:
            self.store.list_advisories(
                self.owner, "volmarr", "pub", state="bogus")
        self.assertEqual(ctx.exception.reason, "state_invalid")
        self.assertEqual(a1.state, "draft")

    # -- withdrawal -------------------------------------------------------

    def test_withdraw_published(self):
        adv = self._draft()
        self.store.publish_advisory(self.owner, "volmarr", "pub", adv.id)
        with self.assertRaises(AdvisoryError) as ctx:
            self.store.withdraw_advisory(
                self.owner, "volmarr", "pub", adv.id, reason=" ")
        self.assertEqual(ctx.exception.reason, "reason_required")
        withdrawn = self.store.withdraw_advisory(
            self.owner, "volmarr", "pub", adv.id,
            reason="The report was a duplicate.")
        self.assertEqual(withdrawn.state, "withdrawn")
        self.assertEqual(
            withdrawn.withdrawn_reason, "The report was a duplicate.")
        # Still readable, in its withdrawn state, by anyone.
        got = self.store.get_advisory(
            self.stranger, "volmarr", "pub", adv.id)
        self.assertEqual(got.state, "withdrawn")
        self.assertIn("duplicate", got.words())
        with self.assertRaises(AdvisoryError) as ctx:
            self.store.publish_advisory(
                self.owner, "volmarr", "pub", adv.id)
        self.assertEqual(ctx.exception.reason, "advisory_withdrawn")
        with self.assertRaises(AdvisoryError) as ctx:
            self.store.withdraw_advisory(
                self.owner, "volmarr", "pub", adv.id,
                reason="again")
        self.assertEqual(ctx.exception.reason, "advisory_withdrawn")

    def test_withdraw_draft(self):
        adv = self._draft()
        withdrawn = self.store.withdraw_advisory(
            self.owner, "volmarr", "pub", adv.id,
            reason="Not a vulnerability after all.")
        self.assertEqual(withdrawn.state, "withdrawn")

    # -- the record ---------------------------------------------------------

    def test_events_record_and_audit_silence(self):
        before = self._audit_count()
        dep_id = seed_dependency_alert(self.conn, self.pub.id)
        adv = self._draft(dependency_name="", ecosystem="")
        self.store.update_advisory(
            self.owner, "volmarr", "pub", adv.id,
            fix_reference="commit abc")
        self.store.link_alert(
            self.owner, "volmarr", "pub", adv.id,
            family="dependency", alert_id=dep_id)
        self.store.publish_advisory(self.owner, "volmarr", "pub", adv.id)
        self.store.withdraw_advisory(
            self.owner, "volmarr", "pub", adv.id,
            reason="Superseded by a fuller report.")
        events = self.store.events_for(
            self.stranger, "volmarr", "pub", adv.id)
        self.assertEqual(
            [e.action for e in events],
            ["create", "update", "link", "publish", "withdraw"])
        self.assertTrue(all(e.actor_username == "volmarr"
                            for e in events))
        self.assertEqual(events[-1].from_state, "published")
        self.assertEqual(events[-1].to_state, "withdrawn")
        # Unwitnessed in the taxonomy: the audit log
        # does not move across the whole life.
        self.assertEqual(self._audit_count(), before)

    def test_events_of_draft_hidden_from_strangers(self):
        adv = self._draft()
        with self.assertRaises(AdvisoryError) as ctx:
            self.store.events_for(self.stranger, "volmarr", "pub", adv.id)
        self.assertEqual(ctx.exception.reason, "advisory_not_found")
        events = self.store.events_for(self.owner, "volmarr", "pub", adv.id)
        self.assertEqual([e.action for e in events], ["create"])

    # -- rendering -----------------------------------------------------------

    def test_rendering_escapes_and_speaks(self):
        adv = self._draft(title="<script>alert(1)</script>")
        page = render_advisory_page(adv)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("draft", page)
        listing = render_advisories_page("volmarr/pub", (adv,))
        self.assertIn("SAMVERK-ADV-0001", listing)
        self.assertIn("&lt;script&gt;", listing)
        empty = render_advisories_page("volmarr/pub", ())
        self.assertIn("No security advisories", empty)

    def test_to_dict_shape(self):
        dep_id = seed_dependency_alert(self.conn, self.pub.id)
        adv = self._draft(dependency_name="", ecosystem="")
        self.store.link_alert(
            self.owner, "volmarr", "pub", adv.id,
            family="dependency", alert_id=dep_id)
        data = advisory_to_dict(
            self.store.get_advisory(self.owner, "volmarr", "pub", adv.id))
        self.assertEqual(data["advisory_key"], "SAMVERK-ADV-0001")
        self.assertEqual(data["state"], "draft")
        self.assertEqual(len(data["links"]), 1)
        self.assertEqual(data["links"][0]["family"], "dependency")
        self.assertEqual(data["links"][0]["alert_id"], dep_id)

    # -- the audit re-proof ----------------------------------------------------

    def test_audit_clean_and_dirty(self):
        dep_id = seed_dependency_alert(self.conn, self.pub.id)
        adv = self._draft(dependency_name="", ecosystem="")
        self.store.link_alert(
            self.owner, "volmarr", "pub", adv.id,
            family="dependency", alert_id=dep_id)
        self.store.publish_advisory(self.owner, "volmarr", "pub", adv.id)
        self.assertEqual(audit_security_advisories(self.conn), [])
        self.conn.execute(
            "UPDATE security_advisories SET severity = 'severe'"
            " WHERE id = ?", (adv.id,))
        self.conn.execute(
            "INSERT INTO security_advisory_alerts ("
            " advisory_id, repo_id, family, alert_id,"
            " created_by_id, created_by, created_at)"
            " VALUES (?, ?, 'dependency', 999, ?, 'volmarr', ?)",
            (adv.id, self.pub.id, self.owner.id, T0))
        self.conn.commit()
        problems = audit_security_advisories(self.conn)
        self.assertTrue(any("severity" in p for p in problems))
        self.assertTrue(any("does not stand" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
