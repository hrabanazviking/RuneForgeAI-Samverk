"""S-222 acceptance battery: watch and star.

Acceptance (roadmap S-222): watch a repo (all /
releases-only / ignore), star as bookmark-plus-
signal; counts are real actions (wires S-119).

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
from samverk.event_store import EventStore
from samverk.repo_header import RepoHeaderService
from samverk.repositories import RepositoryStore
from samverk.watch_star import (
    COUNTED_WATCH_MODES, WATCH_MODES, WatchStarError,
    WatchStarStore, decide_star, decide_watch,
    render_watch_star, validate_watch_mode)


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


class WatchStarTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, audit=self.audit, time_fn=self.clock)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.reader = self.accounts.register("yrsa", "correct horse battery")
        self.stranger = self.accounts.register("mallory", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts, audit=self.audit)
        self.ws = WatchStarStore(self.conn, self.repos, self.accounts, audit=self.audit, time_fn=self.clock)
        self.repos.create_repository(self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(self.owner.id, "volmarr", "priv", visibility="private")

    def _audit_actions(self):
        rows = self.conn.execute("SELECT action FROM audit_log ORDER BY seq").fetchall()
        return [r["action"] for r in rows]

    def _watch_rows(self):
        return self.conn.execute("SELECT COUNT(*) AS n FROM repo_watches").fetchone()["n"]

    def _star_rows(self):
        return self.conn.execute("SELECT COUNT(*) AS n FROM repo_stars").fetchone()["n"]

    # -- pins -------------------------------------------------
    def test_pins_schema_98_taxonomy_131(self):
        self.assertEqual(schema_version(self.conn), 98)
        self.assertEqual(db.MIGRATIONS[-1][0], 98)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 131)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 85)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        for verb in ("repo.watch", "repo.unwatch", "repo.star", "repo.unstar"):
            self.assertIn(verb, taxonomy.AUDIT_EVENTS)
        tables = {r["name"] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("repo_watches", tables); self.assertIn("repo_stars", tables)

    # -- pure decide ------------------------------------------
    def test_pure_decide_and_validate(self):
        self.assertTrue(decide_watch(None, "all"))
        self.assertTrue(decide_watch("all", "ignore"))
        self.assertFalse(decide_watch("all", "all"))
        self.assertTrue(decide_star(False, True)); self.assertTrue(decide_star(True, False))
        self.assertFalse(decide_star(True, True)); self.assertFalse(decide_star(False, False))
        self.assertEqual(validate_watch_mode("releases_only"), "releases_only")
        self.assertEqual(set(WATCH_MODES), {"all", "releases_only", "ignore"})
        self.assertEqual(COUNTED_WATCH_MODES, ("all", "releases_only"))
        for bad in ("everything", "", None, 3, True):
            with self.assertRaises(WatchStarError) as cm:
                validate_watch_mode(bad)
            self.assertEqual(cm.exception.reason, "watch_mode_invalid")

    # -- watch --------------------------------------------------
    def test_set_watch_all_counts_and_audits(self):
        s = self.ws.set_watch(self.reader, "volmarr", "pub", "all")
        self.assertEqual(s.watch_count, 1); self.assertEqual(s.my_watch_mode, "all")
        self.assertEqual(self._watch_rows(), 1)
        self.assertIn("repo.watch", self._audit_actions())
        row = self.conn.execute("SELECT detail FROM audit_log WHERE action='repo.watch'").fetchone()
        import json as _json
        self.assertEqual(_json.loads(row["detail"]), {"mode": "all", "previous": None})

    def test_watch_transitions_and_ignore_not_counted(self):
        self.ws.set_watch(self.reader, "volmarr", "pub", "all")
        s = self.ws.set_watch(self.reader, "volmarr", "pub", "releases_only")
        self.assertEqual(s.watch_count, 1); self.assertEqual(s.my_watch_mode, "releases_only")
        self.assertEqual(self._watch_rows(), 1)
        s = self.ws.set_watch(self.reader, "volmarr", "pub", "ignore")
        self.assertEqual(s.watch_count, 0); self.assertEqual(s.my_watch_mode, "ignore")
        self.assertEqual(self.ws.list_watchers(self.owner, "volmarr", "pub"), ())
        watches = [a for a in self._audit_actions() if a == "repo.watch"]
        self.assertEqual(len(watches), 3)

    def test_watch_same_mode_retry_is_quiet_noop(self):
        self.ws.set_watch(self.reader, "volmarr", "pub", "all")
        before = len(self._audit_actions())
        s = self.ws.set_watch(self.reader, "volmarr", "pub", "all")
        self.assertEqual(s.watch_count, 1)
        self.assertEqual(len(self._audit_actions()), before)
        self.assertEqual(self._watch_rows(), 1)

    def test_clear_watch_audits_once_and_retry_quiet(self):
        self.ws.set_watch(self.reader, "volmarr", "pub", "ignore")
        s = self.ws.clear_watch(self.reader, "volmarr", "pub")
        self.assertIsNone(s.my_watch_mode); self.assertEqual(self._watch_rows(), 0)
        self.assertEqual(self._audit_actions().count("repo.unwatch"), 1)
        before = len(self._audit_actions())
        self.ws.clear_watch(self.reader, "volmarr", "pub")
        self.assertEqual(len(self._audit_actions()), before)

    def test_invalid_mode_refused_and_emits_nothing(self):
        before = len(self._audit_actions())
        with self.assertRaises(WatchStarError) as cm:
            self.ws.set_watch(self.reader, "volmarr", "pub", "everything")
        self.assertEqual(cm.exception.reason, "watch_mode_invalid")
        self.assertEqual(self._watch_rows(), 0)
        self.assertEqual(len(self._audit_actions()), before)

    def test_list_watchers_names_counted_only_in_order(self):
        self.ws.set_watch(self.reader, "volmarr", "pub", "all")
        self.ws.set_watch(self.stranger, "volmarr", "pub", "releases_only")
        self.ws.set_watch(self.owner, "volmarr", "pub", "ignore")
        self.assertEqual(self.ws.list_watchers(self.owner, "volmarr", "pub"),
                         (("yrsa", "all"), ("mallory", "releases_only")))
        s = self.ws.summary(self.owner, "volmarr", "pub")
        self.assertEqual(s.watch_count, 2)

    # -- star ------------------------------------------------------
    def test_star_unstar_counts_and_audit(self):
        s = self.ws.star(self.reader, "volmarr", "pub")
        self.assertEqual(s.star_count, 1); self.assertTrue(s.my_starred)
        s = self.ws.star(self.stranger, "volmarr", "pub")
        self.assertEqual(s.star_count, 2); self.assertEqual(self._star_rows(), 2)
        s = self.ws.unstar(self.reader, "volmarr", "pub")
        self.assertEqual(s.star_count, 1); self.assertFalse(s.my_starred)
        actions = self._audit_actions()
        self.assertEqual(actions.count("repo.star"), 2)
        self.assertEqual(actions.count("repo.unstar"), 1)

    def test_star_retries_are_quiet_noops(self):
        self.ws.star(self.reader, "volmarr", "pub")
        before = len(self._audit_actions())
        self.ws.star(self.reader, "volmarr", "pub")
        self.ws.unstar(self.stranger, "volmarr", "pub")
        self.assertEqual(len(self._audit_actions()), before)
        self.assertEqual(self._star_rows(), 1)

    def test_unstar_only_takes_your_own(self):
        self.ws.star(self.reader, "volmarr", "pub")
        self.ws.unstar(self.stranger, "volmarr", "pub")
        self.assertTrue(self.ws.is_starred(self.reader, "volmarr", "pub"))
        self.assertEqual(self.ws.summary(self.owner, "volmarr", "pub").star_count, 1)

    # -- permission / visibility law ------------------------------
    def test_private_repo_stranger_uniform_not_found(self):
        before = len(self._audit_actions())
        calls = [
            lambda: self.ws.set_watch(self.stranger, "volmarr", "priv", "all"),
            lambda: self.ws.clear_watch(self.stranger, "volmarr", "priv"),
            lambda: self.ws.star(self.stranger, "volmarr", "priv"),
            lambda: self.ws.unstar(self.stranger, "volmarr", "priv"),
            lambda: self.ws.summary(self.stranger, "volmarr", "priv"),
            lambda: self.ws.list_watchers(self.stranger, "volmarr", "priv"),
            lambda: self.ws.watch_mode_for(self.stranger, "volmarr", "priv"),
            lambda: self.ws.summary(self.stranger, "volmarr", "missing"),
        ]
        for call in calls:
            with self.assertRaises(WatchStarError) as cm:
                call()
            self.assertEqual(cm.exception.reason, "repo_not_found")
        self.assertEqual(self._watch_rows(), 0); self.assertEqual(self._star_rows(), 0)
        self.assertEqual(len(self._audit_actions()), before)

    def test_private_repo_owner_can_watch_and_star(self):
        s = self.ws.set_watch(self.owner, "volmarr", "priv", "all")
        self.assertEqual(s.watch_count, 1)
        s = self.ws.star(self.owner, "volmarr", "priv")
        self.assertEqual(s.star_count, 1)

    def test_anonymous_reads_counts_but_cannot_act(self):
        self.ws.star(self.reader, "volmarr", "pub")
        self.ws.set_watch(self.reader, "volmarr", "pub", "all")
        s = self.ws.summary(None, "volmarr", "pub")
        self.assertEqual(s.watch_count, 1); self.assertEqual(s.star_count, 1)
        self.assertIsNone(s.my_watch_mode); self.assertFalse(s.my_starred)
        self.assertIsNone(self.ws.watch_mode_for(None, "volmarr", "pub"))
        self.assertFalse(self.ws.is_starred(None, "volmarr", "pub"))
        before = len(self._audit_actions())
        for call in (lambda: self.ws.set_watch(None, "volmarr", "pub", "all"),
                     lambda: self.ws.star(None, "volmarr", "pub"),
                     lambda: self.ws.unstar(None, "volmarr", "pub"),
                     lambda: self.ws.clear_watch(None, "volmarr", "pub")):
            with self.assertRaises(WatchStarError) as cm:
                call()
            self.assertEqual(cm.exception.reason, "login_required")
        self.assertEqual(len(self._audit_actions()), before)
        with self.assertRaises(WatchStarError) as cm:
            self.ws.summary(None, "volmarr", "priv")
        self.assertEqual(cm.exception.reason, "repo_not_found")

    # -- S-119 wiring: counts are real in the header ---------------
    def test_header_counts_become_real_via_seam(self):
        headers = RepoHeaderService(self.conn, self.repos,
                                    watch_counter=self.ws.watch_count,
                                    star_counter=self.ws.star_count)
        h = headers.header(self.reader, "volmarr", "pub")
        self.assertEqual(h.watch_count, 0); self.assertEqual(h.star_count, 0)
        self.ws.set_watch(self.reader, "volmarr", "pub", "all")
        self.ws.set_watch(self.stranger, "volmarr", "pub", "ignore")
        self.ws.star(self.reader, "volmarr", "pub")
        self.ws.star(self.stranger, "volmarr", "pub")
        h = headers.header(self.reader, "volmarr", "pub")
        self.assertEqual(h.watch_count, 1); self.assertEqual(h.star_count, 2)
        bare = RepoHeaderService(self.conn, self.repos)
        h2 = bare.header(self.reader, "volmarr", "pub")
        self.assertIsNone(h2.watch_count); self.assertIsNone(h2.star_count)

    # -- S-221 wiring: mutations land in the canonical store --------
    def test_events_materialise_for_watch_and_star(self):
        self.ws.set_watch(self.reader, "volmarr", "pub", "all")
        self.ws.star(self.reader, "volmarr", "pub")
        events = EventStore(self.conn, self.repos, self.accounts)
        verbs = [e.verb for e in events.list_for_repo(self.owner, "volmarr", "pub")]
        self.assertIn("repo.watch", verbs); self.assertIn("repo.star", verbs)

    # -- starred list visibility --------------------------------------
    def test_list_starred_repos_filters_private(self):
        self.ws.star(self.owner, "volmarr", "pub")
        self.ws.star(self.owner, "volmarr", "priv")
        self.assertEqual(self.ws.list_starred_repos(self.owner, "volmarr"),
                         ("volmarr/pub", "volmarr/priv"))
        self.assertEqual(self.ws.list_starred_repos(self.stranger, "volmarr"),
                         ("volmarr/pub",))
        self.assertEqual(self.ws.list_starred_repos(None, "volmarr"),
                         ("volmarr/pub",))
        with self.assertRaises(WatchStarError) as cm:
            self.ws.list_starred_repos(self.owner, "ghost")
        self.assertEqual(cm.exception.reason, "no_such_user")

    # -- renderer -------------------------------------------------------
    def test_render_names_counts_and_own_state_in_words(self):
        self.ws.set_watch(self.reader, "volmarr", "pub", "releases_only")
        self.ws.star(self.reader, "volmarr", "pub")
        out = render_watch_star(self.ws.summary(self.reader, "volmarr", "pub"))
        self.assertIn("Watchers: 1", out); self.assertIn("releases only", out)
        self.assertIn("Stars: 1", out); self.assertIn("starred by you", out)
        out2 = render_watch_star(self.ws.summary(self.stranger, "volmarr", "pub"))
        self.assertIn("not watching", out2); self.assertIn("not starred by you", out2)


if __name__ == "__main__":
    unittest.main()
