"""S-205 acceptance battery: index architecture.

Acceptance (roadmap S-205): Index architecture — what
is indexed (issues, PRs, commits, code), when (on
push, on mutation), and how rebuilds work; written in
research file 18.

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
from samverk.index_architecture import (
    INDEX_KINDS, KIND_SPECS, MAX_ATTEMPTS, MAX_CODE_BLOB_BYTES,
    SearchIndexError, SearchIndexStore, decide_code_disposition,
    plan_mutation, plan_push, render_index_architecture_page,
    render_index_state_page, spec_for)
from samverk.repositories import RepositoryStore

ZERO = "0" * 40
OID_A = "a" * 40
OID_B = "b" * 40


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


class IndexArchitectureTests(unittest.TestCase):
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
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.index = SearchIndexStore(self.conn, self.repos, time_fn=self.clock)
        self.anvil = self._repo("volmarr", "anvil", "public")
        self.vault = self._repo("volmarr", "vault", "private")

    def _repo(self, owner, name, visibility):
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO repositories (owner, owner_lower, name, name_lower, created_by, created_at, description, visibility) VALUES (?, ?, ?, ?, ?, ?, '', ?)",
                (owner, owner.lower(), name, name.lower(), self.owner.id, 1_700_000_000, visibility))
        return int(cur.lastrowid)

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(SearchIndexError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    def _audit_count(self):
        return self.conn.execute("SELECT COUNT(*) c FROM audit_log").fetchone()["c"]

    def _push(self, ref, old, new):
        return RefUpdate(ref=ref, old_oid=old, new_oid=new)

    # -- pins ------------------------------------------------
    def test_pins_schema_80_taxonomy_123(self):
        self.assertEqual(schema_version(self.conn), 109)
        self.assertEqual(db.MIGRATIONS[-1][0], 109)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 133)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 87)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        tables = {r["name"] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertIn("index_jobs", tables)
        self.assertIn("index_state", tables)
        self.assertIn("index_documents", tables)

    def test_fresh_database_migrates_to_80(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.init_db(Path(td) / "fresh.db")
            self.assertEqual(db.schema_version(conn), 109)
            conn.close()

    # -- the catalog -------------------------------------------
    def test_catalog_names_exactly_four_kinds(self):
        self.assertEqual(INDEX_KINDS, ("issue", "pull_request", "commit", "code"))
        self.assertEqual(set(KIND_SPECS), set(INDEX_KINDS))
        code = spec_for("code")
        self.assertEqual(code.key_fields, ("repo_id", "commit_oid", "path", "digest"))
        self.assertEqual(code.triggers, ("push",))
        self.assertEqual(spec_for("issue").triggers, ("mutation",))
        self.assertIn("title", spec_for("pull_request").fields)
        self.assertIn("message", spec_for("commit").fields)
        self.assertEqual(self._reason(spec_for, "wiki"), "kind_invalid")
        self.assertEqual(self._reason(spec_for, None), "kind_invalid")

    # -- the trigger law ----------------------------------------
    def test_plan_push_branch_move_enqueues_commit_only(self):
        plans = plan_push("main", [self._push("refs/heads/topic", ZERO, OID_A)])
        self.assertEqual([(p.kind, p.trigger) for p in plans], [("commit", "push")])

    def test_plan_push_default_move_enqueues_commit_and_code(self):
        plans = plan_push("main", [self._push("refs/heads/main", OID_A, OID_B)])
        self.assertEqual([p.kind for p in plans], ["commit", "code"])

    def test_plan_push_tags_and_deletion_law(self):
        self.assertEqual(plan_push("main", [self._push("refs/tags/v1", ZERO, OID_A)]), ())
        self.assertEqual(plan_push("main", []), ())
        plans = plan_push("main", [self._push("refs/heads/main", OID_A, ZERO)])
        self.assertEqual([p.kind for p in plans], ["commit", "code"])

    def test_plan_mutation_law(self):
        plans = plan_mutation("issue", "issue:12")
        self.assertEqual([(p.kind, p.trigger, p.target) for p in plans], [("issue", "mutation", "issue:12")])
        self.assertEqual(self._reason(plan_mutation, "commit", "commit:abc"), "kind_invalid")
        self.assertEqual(self._reason(plan_mutation, "code", "code:x"), "kind_invalid")
        self.assertEqual(self._reason(plan_mutation, "issue", "  "), "target_invalid")
        self.assertEqual(self._reason(plan_mutation, "nope", "x:1"), "kind_invalid")

    # -- the coverage law -----------------------------------------
    def test_code_disposition_matrix(self):
        self.assertEqual(decide_code_disposition(size=10), ("index", "indexed"))
        self.assertEqual(decide_code_disposition(size=MAX_CODE_BLOB_BYTES), ("index", "indexed"))
        self.assertEqual(decide_code_disposition(size=MAX_CODE_BLOB_BYTES + 1), ("skip", "oversized"))
        self.assertEqual(decide_code_disposition(size=0), ("skip", "empty"))
        self.assertEqual(decide_code_disposition(size=10, is_binary=True), ("skip", "binary"))
        self.assertEqual(decide_code_disposition(size=10, is_submodule=True), ("skip", "submodule"))
        self.assertEqual(decide_code_disposition(size=10, is_ignored=True), ("skip", "ignored"))
        self.assertEqual(decide_code_disposition(size=10, is_lfs_pointer=True), ("index_pointer", "lfs_pointer"))
        self.assertEqual(decide_code_disposition(size=10, is_lfs_pointer=True, is_binary=True), ("index_pointer", "lfs_pointer"))
        self.assertEqual(decide_code_disposition(size=None), ("skip", "size_unknown"))
        self.assertEqual(decide_code_disposition(size=-1), ("skip", "size_unknown"))

    # -- enqueueing ------------------------------------------------
    def test_enqueue_push_creates_jobs_and_queued_state(self):
        jobs = self.index.enqueue_push("volmarr", "anvil", [self._push("refs/heads/main", OID_A, OID_B)])
        self.assertEqual([j.kind for j in jobs], ["commit", "code"])
        self.assertTrue(all(j.status == "pending" for j in jobs))
        state = self.index.state_for("volmarr", "anvil", "code")
        self.assertEqual(state.status, "queued")
        self.assertEqual(state.generation, 0)
        self.assertFalse(state.is_current)
        self.assertEqual(self.index.state_for("volmarr", "anvil", "issue").status, "never")

    def test_enqueue_push_without_branch_move_queues_nothing(self):
        jobs = self.index.enqueue_push("volmarr", "anvil", [self._push("refs/tags/v1", ZERO, OID_A)])
        self.assertEqual(jobs, ())
        self.assertEqual(self.index.queue_snapshot().pending, 0)

    def test_enqueue_coalesces_waiting_work(self):
        first = self.index.enqueue_mutation("volmarr", "anvil", kind="issue", target="issue:7")
        second = self.index.enqueue_mutation("volmarr", "anvil", kind="issue", target="issue:7")
        self.assertEqual(first.id, second.id)
        other = self.index.enqueue_mutation("volmarr", "anvil", kind="issue", target="issue:8")
        self.assertNotEqual(first.id, other.id)
        self.assertEqual(self.index.queue_snapshot().pending, 2)

    def test_enqueue_refusals_write_nothing(self):
        audits = self._audit_count()
        self.assertEqual(self._reason(self.index.enqueue, "volmarr", "anvil", kind="issue", trigger="push"), "trigger_invalid")
        self.assertEqual(self._reason(self.index.enqueue, "volmarr", "anvil", kind="code", trigger="mutation", target="code:1"), "trigger_invalid")
        self.assertEqual(self._reason(self.index.enqueue, "volmarr", "anvil", kind="issue", trigger="mutation", target=""), "target_invalid")
        self.assertEqual(self._reason(self.index.enqueue, "volmarr", "ghost", kind="code", trigger="push"), "repo_not_found")
        self.assertEqual(self._reason(self.index.enqueue, "volmarr", "anvil", kind="wiki", trigger="push"), "kind_invalid")
        self.assertEqual(self.index.queue_snapshot().pending, 0)
        self.assertEqual(self._audit_count(), audits)

    def test_enqueueing_writes_no_audit_event(self):
        audits = self._audit_count()
        self.index.enqueue_push("volmarr", "anvil", [self._push("refs/heads/main", OID_A, OID_B)])
        self.index.enqueue_mutation("volmarr", "anvil", kind="pull_request", target="pull_request:3")
        self.assertEqual(self._audit_count(), audits)

    # -- the worker road ---------------------------------------------
    def test_claim_complete_lifecycle_and_high_water(self):
        self.index.enqueue_push("volmarr", "anvil", [self._push("refs/heads/main", OID_A, OID_B)])
        job = self.index.claim_next()
        self.assertEqual(job.kind, "commit")
        self.assertEqual(job.status, "running")
        self.assertEqual(job.attempts, 1)
        self.assertEqual(self.index.state_for("volmarr", "anvil", "commit").status, "indexing")
        done = self.index.complete_job(job.id, high_water=OID_B)
        self.assertEqual(done.status, "done")
        state = self.index.state_for("volmarr", "anvil", "commit")
        self.assertEqual(state.status, "current")
        self.assertTrue(state.is_current)
        self.assertEqual(state.high_water, OID_B)
        self.assertEqual(self._reason(self.index.complete_job, job.id), "job_not_running")
        self.assertEqual(self._reason(self.index.complete_job, 99999), "job_not_found")

    def test_claim_next_on_empty_queue_is_none(self):
        self.assertIsNone(self.index.claim_next())

    def test_failure_retries_then_rests_dead_with_error_kept(self):
        self.index.enqueue_mutation("volmarr", "anvil", kind="issue", target="issue:9")
        for attempt in (1, 2):
            job = self.index.claim_next()
            self.assertEqual(job.attempts, attempt)
            failed = self.index.fail_job(job.id, "boom")
            self.assertEqual(failed.status, "pending")
            self.assertEqual(failed.last_error, "boom")
            self.assertEqual(self.index.state_for("volmarr", "anvil", "issue").status, "stale")
        job = self.index.claim_next()
        self.assertEqual(job.attempts, MAX_ATTEMPTS)
        dead = self.index.fail_job(job.id, "still boom")
        self.assertEqual(dead.status, "dead")
        state = self.index.state_for("volmarr", "anvil", "issue")
        self.assertEqual(state.status, "failed")
        self.assertEqual(state.last_error, "still boom")
        self.assertEqual(self.index.queue_snapshot().dead, 1)
        self.assertIsNone(self.index.claim_next())

    # -- the document registry ----------------------------------------
    def test_documents_put_replace_remove_and_kind_isolation(self):
        doc = self.index.put_document("volmarr", "anvil", kind="issue", doc_key="issue:1")
        self.assertEqual(doc.generation, 0)
        self.index.put_document("volmarr", "anvil", kind="issue", doc_key="issue:1", commit_oid=OID_A)
        docs = self.index.documents_for("volmarr", "anvil", kind="issue")
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].commit_oid, OID_A)
        self.assertEqual(self.index.documents_for("volmarr", "anvil", kind="code"), ())
        self.assertEqual(self.index.state_for("volmarr", "anvil", "issue").document_count, 1)
        self.assertTrue(self.index.remove_document("volmarr", "anvil", kind="issue", doc_key="issue:1"))
        self.assertFalse(self.index.remove_document("volmarr", "anvil", kind="issue", doc_key="issue:1"))
        self.assertEqual(self._reason(self.index.put_document, "volmarr", "anvil", kind="issue", doc_key=" "), "target_invalid")

    def test_code_document_key_carries_research_18_shape(self):
        doc = self.index.put_document("volmarr", "anvil", kind="code", doc_key="code:src/main.py", commit_oid=OID_B, path="src/main.py", digest="deadbeef")
        self.assertEqual((doc.commit_oid, doc.path, doc.digest), (OID_B, "src/main.py", "deadbeef"))

    # -- rebuilds --------------------------------------------------------
    def test_rebuild_serves_old_generation_until_completion_flips(self):
        self.index.put_document("volmarr", "anvil", kind="code", doc_key="code:a.py", commit_oid=OID_A, path="a.py", digest="d1")
        jobs = self.index.request_rebuild("volmarr", "anvil", kind="code")
        self.assertEqual(len(jobs), 1)
        rebuild = jobs[0]
        self.assertEqual(rebuild.trigger, "rebuild")
        self.assertEqual(rebuild.generation, 1)
        self.assertEqual(self.index.state_for("volmarr", "anvil", "code").status, "stale")
        self.assertEqual(self.index.state_for("volmarr", "anvil", "code").generation, 0)
        served = self.index.documents_for("volmarr", "anvil", kind="code")
        self.assertEqual([d.doc_key for d in served], ["code:a.py"])
        claimed = self.index.claim_next()
        self.assertEqual(claimed.id, rebuild.id)
        self.index.put_document("volmarr", "anvil", kind="code", doc_key="code:b.py", commit_oid=OID_B, path="b.py", digest="d2", generation=claimed.generation)
        served_mid = self.index.documents_for("volmarr", "anvil", kind="code")
        self.assertEqual([d.doc_key for d in served_mid], ["code:a.py"])
        done = self.index.complete_job(claimed.id, high_water=OID_B)
        self.assertEqual(done.status, "done")
        state = self.index.state_for("volmarr", "anvil", "code")
        self.assertEqual(state.status, "current")
        self.assertEqual(state.generation, 1)
        self.assertEqual(state.document_count, 1)
        served_after = self.index.documents_for("volmarr", "anvil", kind="code")
        self.assertEqual([d.doc_key for d in served_after], ["code:b.py"])
        rows = self.conn.execute("SELECT COUNT(*) c FROM index_documents WHERE kind = 'code'").fetchone()["c"]
        self.assertEqual(rows, 1)

    def test_rebuild_all_kinds_and_supersedes_waiting_work(self):
        self.index.enqueue_mutation("volmarr", "anvil", kind="issue", target="issue:5")
        jobs = self.index.request_rebuild("volmarr", "anvil")
        self.assertEqual([j.kind for j in jobs], list(INDEX_KINDS))
        snap = self.index.queue_snapshot()
        self.assertEqual(snap.pending, 4)
        self.assertEqual(self._reason(self.index.request_rebuild, "volmarr", "ghost"), "repo_not_found")
        self.assertEqual(self._reason(self.index.request_rebuild, "volmarr", "anvil", kind="wiki"), "kind_invalid")

    def test_rebuild_after_crash_converges_without_duplicates(self):
        self.index.put_document("volmarr", "anvil", kind="issue", doc_key="issue:1")
        first = self.index.request_rebuild("volmarr", "anvil", kind="issue")[0]
        claimed = self.index.claim_next()
        self.assertEqual(claimed.id, first.id)
        self.index.fail_job(claimed.id, "worker died")
        again = self.index.claim_next()
        self.index.put_document("volmarr", "anvil", kind="issue", doc_key="issue:1", generation=again.generation)
        self.index.put_document("volmarr", "anvil", kind="issue", doc_key="issue:2", generation=again.generation)
        self.index.complete_job(again.id)
        docs = self.index.documents_for("volmarr", "anvil", kind="issue")
        self.assertEqual([d.doc_key for d in docs], ["issue:1", "issue:2"])

    # -- queue health and purge -------------------------------------------
    def test_queue_snapshot_counts_and_lag(self):
        self.index.enqueue_mutation("volmarr", "anvil", kind="issue", target="issue:1")
        self.clock.now += 90
        snap = self.index.queue_snapshot()
        self.assertEqual(snap.pending, 1)
        self.assertEqual(snap.lag_seconds, 90)
        self.assertEqual(snap.oldest_pending_at, 1_700_000_000)
        job = self.index.claim_next()
        self.index.complete_job(job.id)
        snap = self.index.queue_snapshot()
        self.assertEqual((snap.pending, snap.done, snap.lag_seconds), (0, 1, 0))

    def test_purge_repo_erases_every_trace(self):
        self.index.enqueue_push("volmarr", "vault", [self._push("refs/heads/main", OID_A, OID_B)])
        self.index.put_document("volmarr", "vault", kind="code", doc_key="code:x.py", path="x.py")
        self.index.purge_repo("volmarr", "vault")
        for table in ("index_jobs", "index_state", "index_documents"):
            count = self.conn.execute(f"SELECT COUNT(*) c FROM {table} WHERE repo_id = ?", (self.vault,)).fetchone()["c"]
            self.assertEqual(count, 0, table)
        self.assertEqual(self.index.state_for("volmarr", "vault", "code").status, "never")

    def test_states_for_repo_covers_catalog_in_order(self):
        states = self.index.states_for_repo("volmarr", "anvil")
        self.assertEqual([s.kind for s in states], list(INDEX_KINDS))
        self.assertTrue(all(s.status == "never" for s in states))

    # -- pages ----------------------------------------------------------------
    def test_architecture_page_says_what_when_and_coverage(self):
        page = render_index_architecture_page()
        for needle in ("Issues", "Pull requests", "Commits", "Code", "on push", "on mutation", "rebuild", "LFS", "default branch"):
            self.assertIn(needle, page)
        self.assertIn(str(MAX_CODE_BLOB_BYTES), page)

    def test_state_page_says_freshness_in_words_and_escapes(self):
        self.index.enqueue_mutation("volmarr", "anvil", kind="issue", target="issue:1")
        page = render_index_state_page("volmarr/<script>", self.index.states_for_repo("volmarr", "anvil"), self.index.queue_snapshot())
        self.assertIn("waiting to be indexed", page)
        self.assertIn("never indexed", page)
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)


if __name__ == "__main__":
    unittest.main()
