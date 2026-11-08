"""S-215 acceptance battery: index health.

Acceptance (roadmap S-215): Index health — admin-visible
index state, lag, and rebuild trigger; lag is shown,
never hidden.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.hooks import RefUpdate
from samverk.index_architecture import SearchIndexStore
from samverk.index_health import (
    STATUS_ORDER, IndexHealth, IndexHealthError,
    decide_worst_status, lag_seconds_for,
    render_index_health_page, render_repo_index_health_page)
from samverk.repositories import RepositoryStore

ZERO = "0" * 40
OID_A = "a" * 40
OID_B = "b" * 40


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


class IndexHealthTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, time_fn=self.clock)
        self.admin = self.accounts.register("admina", "correct horse battery")
        with self.conn:
            self.conn.execute(
                "UPDATE users SET is_admin = 1 WHERE id = ?", (self.admin.id,))
        self.admin = self.accounts.get_by_id(self.admin.id)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.index = SearchIndexStore(self.conn, self.repos, time_fn=self.clock)
        self.health = IndexHealth(
            self.conn, self.accounts, self.index, self.audit,
            time_fn=self.clock)
        self.anvil = self._repo("volmarr", "anvil", "public")
        self.vault = self._repo("volmarr", "vault", "private")

    def _repo(self, owner, name, visibility):
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO repositories (owner, owner_lower, name, name_lower, created_by, created_at, description, visibility) VALUES (?, ?, ?, ?, ?, ?, '', ?)",
                (owner, owner.lower(), name, name.lower(), self.owner.id, 1_700_000_000, visibility))
        return int(cur.lastrowid)

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(IndexHealthError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    def _audit_rows(self, action=None):
        sql = "SELECT * FROM audit_log"
        args = ()
        if action is not None:
            sql += " WHERE action = ?"
            args = (action,)
        return self.conn.execute(sql + " ORDER BY seq", args).fetchall()

    def _push(self, ref, old, new):
        return RefUpdate(ref=ref, old_oid=old, new_oid=new)

    # -- pins ------------------------------------------------
    def test_pins_schema_87_taxonomy_127(self):
        self.assertEqual(schema_version(self.conn), 87)
        self.assertEqual(db.MIGRATIONS[-1][0], 87)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 127)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 31)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 83)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        self.assertIn("admin.index.rebuild", taxonomy.ADMIN_EVENTS)

    # -- the pure laws -----------------------------------------
    def test_worst_status_folds_by_honesty_order(self):
        self.assertEqual(decide_worst_status(["current", "current"]), "current")
        self.assertEqual(decide_worst_status(["current", "never"]), "never")
        self.assertEqual(decide_worst_status(["never", "queued"]), "queued")
        self.assertEqual(decide_worst_status(["queued", "indexing"]), "indexing")
        self.assertEqual(decide_worst_status(["indexing", "stale"]), "stale")
        self.assertEqual(decide_worst_status(["stale", "failed"]), "failed")
        self.assertEqual(decide_worst_status(["current", "failed", "never"]), "failed")
        self.assertEqual(decide_worst_status([]), "never")
        self.assertEqual(STATUS_ORDER[0], "failed")
        self.assertEqual(STATUS_ORDER[-1], "current")

    def test_lag_law_zero_is_a_number_and_never_negative(self):
        self.assertEqual(lag_seconds_for(None, 1_700_000_100), 0)
        self.assertEqual(lag_seconds_for(1_700_000_000, 1_700_000_100), 100)
        self.assertEqual(lag_seconds_for(1_700_000_200, 1_700_000_100), 0)

    # -- the admin gate -------------------------------------------
    def test_every_face_refuses_non_admins_before_reading(self):
        self.assertEqual(
            self._reason(self.health.repo_health, 99999, "volmarr", "anvil"),
            "no_such_user")
        self.assertEqual(
            self._reason(self.health.repo_health, self.owner.id, "volmarr", "anvil"),
            "not_site_admin")
        self.assertEqual(
            self._reason(self.health.instance_health, self.owner.id),
            "not_site_admin")
        self.assertEqual(
            self._reason(self.health.instance_health, None), "no_such_user")
        self.assertEqual(
            self._reason(self.health.request_rebuild, self.owner.id, "volmarr", "anvil"),
            "not_site_admin")
        # A refused trigger enqueues nothing and audits nothing.
        self.assertEqual(self.index.queue_snapshot().pending, 0)
        self.assertEqual(self._audit_rows("admin.index.rebuild"), [])

    def test_health_reads_write_no_audit(self):
        before = len(self._audit_rows())
        self.health.repo_health(self.admin.id, "volmarr", "anvil")
        self.health.instance_health(self.admin.id)
        self.assertEqual(len(self._audit_rows()), before)

    # -- the per-repository read -------------------------------------
    def test_fresh_repository_reads_never_with_zero_lag(self):
        health = self.health.repo_health(self.admin.id, "volmarr", "anvil")
        self.assertEqual(health.full_name, "volmarr/anvil")
        self.assertEqual(health.repo_id, self.anvil)
        self.assertEqual([s.kind for s in health.states],
                         ["issue", "pull_request", "commit", "code"])
        self.assertTrue(all(s.status == "never" for s in health.states))
        self.assertEqual(health.worst_status, "never")
        self.assertFalse(health.is_current)
        self.assertEqual(health.lag_seconds, 0)
        self.assertEqual((health.pending, health.running, health.dead), (0, 0, 0))
        self.assertEqual(health.document_count, 0)

    def test_unknown_repository_answers_repo_not_found(self):
        self.assertEqual(
            self._reason(self.health.repo_health, self.admin.id, "volmarr", "ghost"),
            "repo_not_found")
        self.assertEqual(
            self._reason(self.health.request_rebuild, self.admin.id, "volmarr", "ghost"),
            "repo_not_found")

    def test_lag_is_the_oldest_waiting_jobs_age_per_repository(self):
        self.index.enqueue_mutation(
            "volmarr", "anvil", kind="issue", target="issue:1")
        self.clock.now += 120
        health = self.health.repo_health(self.admin.id, "volmarr", "anvil")
        self.assertEqual(health.lag_seconds, 120)
        self.assertEqual(health.pending, 1)
        self.assertEqual(health.oldest_pending_at, 1_700_000_000)
        self.assertEqual(health.worst_status, "queued")
        # The other repository's lag is its own: still zero.
        other = self.health.repo_health(self.admin.id, "volmarr", "vault")
        self.assertEqual(other.lag_seconds, 0)
        self.assertEqual(other.worst_status, "never")

    def test_completed_kind_reads_current_in_its_state(self):
        self.index.enqueue_push(
            "volmarr", "anvil", [self._push("refs/heads/main", OID_A, OID_B)])
        job = self.index.claim_next()
        self.index.complete_job(job.id, high_water=OID_B)
        health = self.health.repo_health(self.admin.id, "volmarr", "anvil")
        by_kind = {s.kind: s for s in health.states}
        self.assertEqual(by_kind["commit"].status, "current")
        self.assertEqual(by_kind["commit"].high_water, OID_B)
        # The code job still waits, so the headline stays queued.
        self.assertEqual(by_kind["code"].status, "queued")
        self.assertEqual(health.worst_status, "queued")

    def test_failed_kind_leads_the_headline_with_its_error(self):
        self.index.enqueue_mutation(
            "volmarr", "anvil", kind="issue", target="issue:9")
        for _ in range(3):
            job = self.index.claim_next()
            self.index.fail_job(job.id, "disk gone")
        health = self.health.repo_health(self.admin.id, "volmarr", "anvil")
        self.assertEqual(health.worst_status, "failed")
        self.assertEqual(health.dead, 1)
        by_kind = {s.kind: s for s in health.states}
        self.assertEqual(by_kind["issue"].status, "failed")
        self.assertEqual(by_kind["issue"].last_error, "disk gone")

    def test_document_counts_come_from_the_registry(self):
        self.index.put_document(
            "volmarr", "anvil", kind="issue", doc_key="issue:1")
        self.index.put_document(
            "volmarr", "anvil", kind="issue", doc_key="issue:2")
        health = self.health.repo_health(self.admin.id, "volmarr", "anvil")
        self.assertEqual(health.document_count, 2)

    # -- the instance read ----------------------------------------------
    def test_instance_health_covers_every_repo_in_order(self):
        self.index.enqueue_mutation(
            "volmarr", "vault", kind="issue", target="issue:1")
        self.clock.now += 45
        health = self.health.instance_health(self.admin.id)
        self.assertEqual([r.full_name for r in health.repos],
                         ["volmarr/anvil", "volmarr/vault"])
        # The admin sees the private repository's freshness too.
        self.assertEqual(health.lag_seconds, 45)
        self.assertEqual(health.queue.pending, 1)
        self.assertEqual(health.worst_status, "queued")
        self.assertEqual(health.current_count, 0)
        self.assertEqual(health.behind_count, 0)

    def test_instance_counts_current_and_behind_honestly(self):
        # anvil: fully current (all four kinds completed).
        for kind, target in (("issue", "issue:1"), ("pull_request", "pr:1")):
            self.index.enqueue_mutation("volmarr", "anvil", kind=kind, target=target)
        self.index.enqueue_push(
            "volmarr", "anvil", [self._push("refs/heads/main", OID_A, OID_B)])
        while True:
            job = self.index.claim_next()
            if job is None:
                break
            self.index.complete_job(job.id)
        # vault: one dead kind.
        self.index.enqueue_mutation(
            "volmarr", "vault", kind="issue", target="issue:1")
        for _ in range(3):
            job = self.index.claim_next()
            self.index.fail_job(job.id, "boom")
        health = self.health.instance_health(self.admin.id)
        self.assertEqual(health.current_count, 1)
        self.assertEqual(health.behind_count, 1)
        self.assertEqual(health.worst_status, "failed")

    # -- the rebuild trigger ------------------------------------------------
    def test_rebuild_one_kind_enqueues_and_audits(self):
        jobs = self.health.request_rebuild(
            self.admin.id, "volmarr", "anvil", kind="code")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].kind, "code")
        self.assertEqual(jobs[0].trigger, "rebuild")
        self.assertEqual(jobs[0].generation, 1)
        state = self.index.state_for("volmarr", "anvil", "code")
        self.assertEqual(state.status, "stale")
        rows = self._audit_rows("admin.index.rebuild")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["actor_id"], self.admin.id)
        self.assertEqual(row["target_kind"], "repository")
        self.assertEqual(row["target_id"], "volmarr/anvil")
        self.assertEqual(row["outcome"], "success")
        import json
        detail = json.loads(row["detail"])
        self.assertEqual(detail["kinds"], ["code"])
        self.assertEqual(detail["generations"], [1])
        self.assertEqual(detail["jobs"], [jobs[0].id])

    def test_rebuild_all_kinds_is_one_witnessed_act(self):
        jobs = self.health.request_rebuild(self.admin.id, "volmarr", "anvil")
        self.assertEqual([j.kind for j in jobs],
                         ["issue", "pull_request", "commit", "code"])
        rows = self._audit_rows("admin.index.rebuild")
        self.assertEqual(len(rows), 1)
        import json
        detail = json.loads(rows[0]["detail"])
        self.assertEqual(detail["kinds"],
                         ["issue", "pull_request", "commit", "code"])

    def test_rebuild_without_an_audit_log_fails_closed(self):
        bare = IndexHealth(
            self.conn, self.accounts, self.index, None, time_fn=self.clock)
        self.assertEqual(
            self._reason(bare.request_rebuild, self.admin.id, "volmarr", "anvil"),
            "audit_required")
        self.assertEqual(self.index.queue_snapshot().pending, 0)
        self.assertEqual(
            self.index.state_for("volmarr", "anvil", "code").status, "never")

    def test_rebuild_refusals_enqueue_and_audit_nothing(self):
        self.assertEqual(
            self._reason(self.health.request_rebuild, self.admin.id,
                         "volmarr", "anvil", kind="wiki"),
            "kind_invalid")
        self.assertEqual(self.index.queue_snapshot().pending, 0)
        self.assertEqual(self._audit_rows("admin.index.rebuild"), [])

    def test_triggered_rebuild_completes_through_s205s_law(self):
        self.index.put_document(
            "volmarr", "anvil", kind="code", doc_key="code:a.py",
            commit_oid=OID_A, path="a.py", digest="d1")
        self.health.request_rebuild(self.admin.id, "volmarr", "anvil", kind="code")
        job = self.index.claim_next()
        self.index.put_document(
            "volmarr", "anvil", kind="code", doc_key="code:b.py",
            commit_oid=OID_B, path="b.py", digest="d2",
            generation=job.generation)
        self.index.complete_job(job.id, high_water=OID_B)
        health = self.health.repo_health(self.admin.id, "volmarr", "anvil")
        by_kind = {s.kind: s for s in health.states}
        self.assertEqual(by_kind["code"].status, "current")
        self.assertEqual(by_kind["code"].generation, 1)
        self.assertEqual(by_kind["code"].document_count, 1)

    # -- the pages -------------------------------------------------------------
    def test_repo_page_shows_lag_and_freshness_in_words(self):
        self.index.enqueue_mutation(
            "volmarr", "anvil", kind="issue", target="issue:1")
        self.clock.now += 90
        page = render_repo_index_health_page(
            self.health.repo_health(self.admin.id, "volmarr", "anvil"))
        self.assertIn("volmarr/anvil", page)
        self.assertIn("Index lag: 90 seconds", page)
        self.assertIn("waiting to be indexed", page)
        self.assertIn("never indexed", page)

    def test_instance_page_shows_zero_lag_rather_than_hiding_it(self):
        page = render_index_health_page(
            self.health.instance_health(self.admin.id))
        self.assertIn("Index lag: 0 seconds", page)
        self.assertIn("2 repositories", page)
        self.assertIn("0 behind", page)
        self.assertIn("never indexed", page)

    def test_pages_escape_names_and_errors(self):
        self.index.enqueue_mutation(
            "volmarr", "anvil", kind="issue", target="issue:1")
        for _ in range(3):
            job = self.index.claim_next()
            self.index.fail_job(job.id, "<script>alert(1)</script>")
        page = render_repo_index_health_page(
            self.health.repo_health(self.admin.id, "volmarr", "anvil"))
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)
        instance_page = render_index_health_page(
            self.health.instance_health(self.admin.id))
        self.assertIn("1 behind", instance_page)
        self.assertIn("indexing failed", instance_page)


if __name__ == "__main__":
    unittest.main()
