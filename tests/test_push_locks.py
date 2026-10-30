"""S-092 acceptance battery: concurrent push behaviour.

Acceptance (roadmap S-092): a second push to the same ref
fails fast with a clear message; no torn refs (with S-053).

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db
from samverk.accounts import AccountStore
from samverk.git_http import SmartHttpService, TransportError
from samverk.push_locks import PushBusyError, PushLockManager
from samverk.repositories import RepositoryStore
from test_ssh_upload_routing import FakeRunner, make_world, serve


class LockManagerTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.locks = PushLockManager(self.root)

    def test_second_hold_on_same_ref_fails_fast_with_clear_message(self):
        with self.locks.hold("volmarr/samverk", "refs/heads/main"):
            started = time.monotonic()
            with self.assertRaises(PushBusyError) as caught:
                with self.locks.hold("volmarr/samverk", "refs/heads/main"):
                    pass
            self.assertLess(time.monotonic() - started, 2.0)  # fast, not queued
            message = str(caught.exception)
            self.assertIn("volmarr/samverk", message)
            self.assertIn("refs/heads/main", message)
            self.assertIn("push again", message)
        # Released with the block: the ref is free again.
        with self.locks.hold("volmarr/samverk", "refs/heads/main"):
            pass

    def test_other_refs_and_other_repos_are_unaffected(self):
        with self.locks.hold("volmarr/samverk", "refs/heads/main"):
            with self.locks.hold("volmarr/samverk", "refs/heads/dev"):
                pass
            with self.locks.hold("volmarr/other", "refs/heads/main"):
                pass

    def test_lock_is_released_when_the_push_fails(self):
        with self.assertRaises(RuntimeError):
            with self.locks.hold("volmarr/samverk"):
                raise RuntimeError("push died")
        self.assertFalse(self.locks.is_held("volmarr/samverk"))
        with self.locks.hold("volmarr/samverk"):
            pass

    def test_stale_lock_from_a_dead_holder_heals(self):
        locks = PushLockManager(self.root, stale_after_seconds=60)
        with locks.hold("volmarr/samverk", "refs/heads/main"):
            pass
        # Simulate a crashed holder: recreate its lock file by
        # hand and age it past the stale bound.
        import hashlib
        digest = hashlib.sha256(
            b"volmarr/samverk\nrefs/heads/main").hexdigest()
        path = self.root / "locks" / f"push-{digest}.lock"
        path.write_text("{}")
        old = time.time() - 3600
        os.utime(path, (old, old))
        with locks.hold("volmarr/samverk", "refs/heads/main"):
            pass   # healed: acquired despite the stale file
        self.assertFalse(path.exists())

    def test_concurrent_holders_exactly_one_wins(self):
        locks = PushLockManager(self.root)
        won, lost = [], []

        def attempt(n):
            try:
                with locks.hold("volmarr/samverk", "refs/heads/main"):
                    won.append(n)
                    time.sleep(0.3)
            except PushBusyError:
                lost.append(n)

        first = threading.Thread(target=attempt, args=(1,))
        first.start()
        time.sleep(0.1)   # first holds it before the second tries
        second = threading.Thread(target=attempt, args=(2,))
        second.start()
        first.join(); second.join()
        self.assertEqual(won, [1])
        self.assertEqual(lost, [2])


class TransportWiringTests(unittest.TestCase):
    def test_ssh_receive_fails_fast_while_another_push_holds_the_repo(self):
        runner = FakeRunner()
        w = make_world(self, runner=runner)
        locks = PushLockManager(w["root"])
        w["service"]._push_locks = locks
        with locks.hold("volmarr/samverk"):
            rc, _, err = serve(
                w, w["owner_fp"], "git-receive-pack 'volmarr/samverk'")
            self.assertEqual(rc, 128)
            self.assertIn(b"already in progress", err)
            self.assertEqual(runner.calls, [])
        rc, _, _ = serve(
            w, w["owner_fp"], "git-receive-pack 'volmarr/samverk'")
        self.assertEqual(rc, 0)

    def test_http_receive_fails_fast_while_held(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        conn = db.init_db(root / "samverk.db")
        self.addCleanup(conn.close)
        accounts = AccountStore(conn)
        owner = accounts.register("volmarr", "a long enough passphrase")
        repos = RepositoryStore(conn, root, accounts)
        repos.create_repository(owner.id, "volmarr", "samverk")
        locks = PushLockManager(root)
        service = SmartHttpService(
            conn, root, accounts, repos, push_locks=locks)
        with locks.hold("volmarr/samverk"):
            with self.assertRaises(TransportError) as caught:
                service.receive_pack(owner, "volmarr", "samverk", b"body")
            self.assertEqual(caught.exception.reason, "push_in_progress")
            self.assertIn("already in progress", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
