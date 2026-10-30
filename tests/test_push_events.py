"""S-090 acceptance battery: post-receive push events.

Acceptance (roadmap S-090): every accepted push emits the
canonical event (Part XI's store) with refs and commit ranges.

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db
from samverk.accounts import AccountStore
from samverk.hooks import HookRunner, RefUpdate
from samverk.push_events import (
    PushEventError,
    PushEventStore,
    diff_refs,
    update_kind,
)
from samverk.repositories import RepositoryStore
from test_git_http_upload import seed_commit

ZERO = "0" * 40
A = "a" * 40
B = "b" * 40


class PushEventStoreTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register(
            "volmarr", "a long enough passphrase")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "samverk")
        self.store = PushEventStore(self.conn, self.repos)

    def record(self, updates, **kw):
        kw.setdefault("actor_kind", "user")
        kw.setdefault("actor_id", self.owner.id)
        kw.setdefault("transport", "http")
        return self.store.record_push("volmarr", "samverk", updates=updates, **kw)

    def test_event_carries_actor_transport_and_ranges(self):
        event = self.record(
            (RefUpdate("refs/heads/main", ZERO, A),
             RefUpdate("refs/heads/dev", A, B)))
        self.assertEqual(event.full_name, "volmarr/samverk")
        self.assertEqual(event.actor_kind, "user")
        self.assertEqual(event.transport, "http")
        self.assertEqual(event.refs, ("refs/heads/main", "refs/heads/dev"))
        self.assertEqual(event.updates[0].old_oid, ZERO)
        listed = self.store.list_for_repo("volmarr", "samverk")
        self.assertEqual([e.id for e in listed], [event.id])
        self.assertEqual(listed[0].updates, event.updates)

    def test_creation_and_deletion_kinds(self):
        self.assertEqual(
            update_kind(RefUpdate("refs/heads/x", ZERO, A)), "created")
        self.assertEqual(
            update_kind(RefUpdate("refs/heads/x", A, ZERO)), "deleted")
        self.assertEqual(
            update_kind(RefUpdate("refs/heads/x", A, B)), "updated")

    def test_unmoved_and_empty_ranges_record_nothing(self):
        with self.assertRaises(PushEventError) as caught:
            self.record((RefUpdate("refs/heads/main", A, A),))
        self.assertEqual(caught.exception.reason, "update_invalid")
        with self.assertRaises(PushEventError) as caught:
            self.record(())
        self.assertEqual(caught.exception.reason, "updates_empty")
        with self.assertRaises(PushEventError):
            self.record((RefUpdate("refs/heads/main", "zz", A),))
        self.assertEqual(self.store.count_for_repo("volmarr", "samverk"), 0)

    def test_unknown_repo_transport_and_actor_are_named(self):
        with self.assertRaises(PushEventError):
            self.store.record_push(
                "volmarr", "nope", actor_kind="user", actor_id=1,
                transport="http",
                updates=(RefUpdate("refs/heads/m", ZERO, A),))
        with self.assertRaises(PushEventError):
            self.record((RefUpdate("refs/heads/m", ZERO, A),),
                        transport="carrier-pigeon")
        with self.assertRaises(PushEventError):
            self.record((RefUpdate("refs/heads/m", ZERO, A),),
                        actor_kind="ghost")

    def test_newest_first_and_limit_clamped(self):
        for i in range(3):
            self.record((RefUpdate("refs/heads/main", A, B),))
        events = self.store.list_for_repo("volmarr", "samverk", limit=2)
        self.assertEqual(len(events), 2)
        self.assertGreater(events[0].id, events[1].id)
        self.assertEqual(self.store.count_for_repo("volmarr", "samverk"), 3)

    def test_diff_refs_computes_creates_updates_deletes(self):
        updates = diff_refs(
            {"refs/heads/main": A, "refs/heads/old": A},
            {"refs/heads/main": B, "refs/heads/new": B})
        by_ref = {u.ref: u for u in updates}
        self.assertEqual(by_ref["refs/heads/main"].old_oid, A)
        self.assertEqual(by_ref["refs/heads/new"].old_oid, ZERO)
        self.assertEqual(by_ref["refs/heads/old"].new_oid, ZERO)
        self.assertEqual(diff_refs({"refs/heads/m": A}, {"refs/heads/m": A}), ())

    def test_post_receive_handler_records_from_hook_context(self):
        runner = HookRunner(timeout_seconds=5)
        runner.register_post_receive(
            "events", self.store.post_receive_handler(transport="ssh"))
        outcomes = runner.run_post_receive(
            "volmarr/samverk",
            updates=(RefUpdate("refs/heads/main", ZERO, A),),
            actor="volmarr", payload={})
        self.assertEqual(outcomes[0].status, "completed")
        events = self.store.list_for_repo("volmarr", "samverk")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].transport, "ssh")
        # An update-less context records nothing, and still passes.
        outcomes = runner.run_post_receive("volmarr/samverk", updates=())
        self.assertEqual(outcomes[0].status, "completed")
        self.assertEqual(self.store.count_for_repo("volmarr", "samverk"), 1)


class HttpTransportEventTests(unittest.TestCase):
    def test_stock_push_over_http_emits_event_with_real_range(self):
        # A stock-git push over real HTTP, through a service
        # with the event store wired, must land exactly one
        # event carrying the true old -> new commit range.
        import os
        import sqlite3
        import subprocess
        from samverk.git_http import SmartHttpService
        from test_git_http_receive import make_full_harness
        from test_git_http_upload import GIT_ENV, git
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        conn = db.init_db(root / "samverk.db")
        self.addCleanup(conn.close)
        accounts = AccountStore(conn)
        owner = accounts.register("volmarr", "a long enough passphrase")
        repos = RepositoryStore(conn, root, accounts)
        repos.create_repository(owner.id, "volmarr", "samverk")
        first = seed_commit(repos, "volmarr", "samverk")
        store = PushEventStore(conn, repos)
        # The harness serves from worker threads: a second,
        # cross-thread service over the same database file
        # (the proven LFS pattern), with the store wired.
        conn2 = sqlite3.connect(
            str(root / "samverk.db"), timeout=5.0,
            check_same_thread=False)
        conn2.row_factory = sqlite3.Row
        self.addCleanup(conn2.close)
        accounts2 = AccountStore(conn2)
        repos2 = RepositoryStore(conn2, root, accounts2)
        service2 = SmartHttpService(
            conn2, root, accounts2, repos2,
            push_events=PushEventStore(conn2, repos2))
        server = make_full_harness(service2, owner)
        self.addCleanup(server.shutdown)
        port = server.server_address[1]
        env = dict(os.environ)
        env.update(GIT_ENV)
        env["HOME"] = str(root)
        work = root / "work"
        out = subprocess.run(
            ["git", "clone", f"http://127.0.0.1:{port}/volmarr/samverk.git",
             str(work)], capture_output=True, env=env)
        self.assertEqual(out.returncode, 0, out.stderr.decode())
        (work / "second.txt").write_bytes(b"eventful\n")
        for args in (["add", "second.txt"], ["commit", "-m", "second"],
                     ["push", "origin", "main"]):
            out = subprocess.run(["git", "-C", str(work), *args],
                                 capture_output=True, env=env)
            self.assertEqual(out.returncode, 0, out.stderr.decode())
        bare = repos.path_for("volmarr", "samverk")
        head = git(bare, "rev-parse", "refs/heads/main")
        self.assertNotEqual(head, first)
        events = store.list_for_repo("volmarr", "samverk")
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.transport, "http")
        self.assertEqual(event.actor_kind, "user")
        self.assertEqual(event.actor_id, owner.id)
        (update,) = event.updates
        self.assertEqual(update.ref, "refs/heads/main")
        self.assertEqual(update.old_oid, first)
        self.assertEqual(update.new_oid, head)


if __name__ == "__main__":
    unittest.main()
