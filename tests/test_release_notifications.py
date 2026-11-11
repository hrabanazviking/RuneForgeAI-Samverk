"""S-262 acceptance battery: release notifications.

Acceptance (roadmap S-262): Release notifications —
watchers (releases-only watchers of S-222 included)
notified on publish, not on draft saves.

The centre is samverk/release_notifications.py:
ReleaseNotificationStore over migration 103's
release_notification_deliveries ledger (schema 102
to 103), deriving deliveries from the standing
repo.release.publish audit witness alone (S-257)
and materialising each into an ordinary S-223
notification under reason `subscribed`. Draft
creations and draft edits witness nothing, so they
notify nobody by construction; publishing a draft
writes the one witness row and notifies then.
Taxonomy stands at 131 — no new event.

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
from samverk.notification_reasons import (
    NOTIFICATION_REASONS, NotificationStore)
from samverk.releases import NOTES_FILE, ReleaseStore
from samverk.release_notifications import (
    PUBLISH_VERB, REASON, ReleaseDelivery,
    ReleaseNotificationError, ReleaseNotificationStore,
    decide_release_notify, decide_release_recipients,
    delivery_to_dict, render_release_notifications)
from samverk.repositories import RepositoryStore
from samverk.watch_star import WatchStarStore
from test_repo_home import run_git

PW = "correct horse battery"
T0 = 1_700_000_000


class Clock:
    def __init__(self, now=T0):
        self.now = now
    def __call__(self):
        return self.now


class ReleaseNotificationTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.clock = Clock()
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(
            self.conn, audit=self.audit, time_fn=self.clock)
        self.owner = self.accounts.register("volmarr", PW)
        self.allw = self.accounts.register("allw", PW)
        self.relw = self.accounts.register("relw", PW)
        self.ignw = self.accounts.register("ignw", PW)
        self.plain = self.accounts.register("plainw", PW)
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.releases = ReleaseStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.watches = WatchStarStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.notes = NotificationStore(
            self.conn, self.accounts, time_fn=self.clock)
        self.store = ReleaseNotificationStore(
            self.conn, self.repos, self.accounts,
            releases=self.releases, audit=self.audit,
            time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.bare = self.repos.path_for("volmarr", "pub")
        self.work = self.root / "work"; self.work.mkdir()
        run_git(self.work, "init", "-b", "main")
        self._write("app.py", "print('hi')\n")
        self.c1 = self._commit("first")
        run_git(self.work, "tag", "v1.0")
        run_git(self.work, "push", str(self.bare), "v1.0")
        self._write(NOTES_FILE, "# Anvil 1.1\n\nFirst **stable** cut.\n")
        self._write("app.py", "print('ho')\n")
        self.c2 = self._commit("second")
        for tag in ("v1.1", "v1.3", "v1.4", "v1.5"):
            run_git(self.work, "tag", tag)
            run_git(self.work, "push", str(self.bare), tag)

    def _write(self, rel, text):
        p = self.work / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def _commit(self, msg):
        run_git(self.work, "add", "-A")
        run_git(self.work, "commit", "-m", msg)
        run_git(self.work, "push", str(self.bare), "main")
        return run_git(self.work, "rev-parse", "HEAD")

    def _watch_all_three(self):
        self.watches.set_watch(self.allw, "volmarr", "pub", "all")
        self.watches.set_watch(
            self.relw, "volmarr", "pub", "releases_only")
        self.watches.set_watch(self.ignw, "volmarr", "pub", "ignore")

    def _reason(self, fn, *a, **k):
        with self.assertRaises(ReleaseNotificationError) as ctx:
            fn(*a, **k)
        return ctx.exception.reason

    def _publish(self, tag="v1.0", **kw):
        return self.releases.create_release(
            self.owner, "volmarr", "pub", tag,
            f"Anvil {tag}", "Notes.", **kw)

    # -- pure law ---------------------------------------
    def test_decide_release_notify_modes(self):
        self.assertTrue(decide_release_notify("all"))
        self.assertTrue(decide_release_notify("releases_only"))
        self.assertFalse(decide_release_notify("ignore"))
        self.assertFalse(decide_release_notify(None))
        self.assertFalse(decide_release_notify("bogus"))
        self.assertFalse(decide_release_notify(7))

    def test_decide_release_recipients_filters(self):
        watchers = [(11, "ignore"), (12, "all"), (13, "releases_only"),
                    (12, "all"), (14, "releases_only")]
        self.assertEqual(
            decide_release_recipients(watchers, actor_id=14),
            ((12, "all"), (13, "releases_only")))
        self.assertEqual(
            decide_release_recipients(watchers, actor_id=None),
            ((12, "all"), (13, "releases_only"),
             (14, "releases_only")))
        self.assertEqual(decide_release_recipients([], 1), ())

    # -- pins ---------------------------------------------
    def test_pins_schema_104_taxonomy_133(self):
        self.assertEqual(schema_version(self.conn), 106)
        self.assertEqual(db.MIGRATIONS[-1][0], 106)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 133)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 87)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        self.assertIn(PUBLISH_VERB, taxonomy.REPO_EVENTS)
        self.assertEqual(REASON, "subscribed")
        self.assertIn(REASON, NOTIFICATION_REASONS)
        tables = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("release_notification_deliveries", tables)

    def test_upgrade_from_102_creates_ledger(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "old.db"
            conn = db.connect(path)
            for target, statements in db.MIGRATIONS:
                if target > 102:
                    continue
                with conn:
                    for stmt in statements:
                        conn.execute(stmt)
                    conn.execute(
                        "INSERT OR REPLACE INTO schema_meta"
                        " (key, value) VALUES ('version', ?)",
                        (str(target),))
            self.assertEqual(schema_version(conn), 102)
            db.migrate(conn)
            self.assertEqual(schema_version(conn), 106)
            tables = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("release_notification_deliveries", tables)
            conn.close()

    # -- the core: publish notifies, drafts do not --------
    def test_publish_notifies_all_and_releases_only(self):
        self._watch_all_three()
        self._publish("v1.0")
        self.assertEqual(self.store.sync_repo("volmarr", "pub"), 2)
        self.assertEqual(self.store.count_for_recipient(self.allw), 1)
        self.assertEqual(self.store.count_for_recipient(self.relw), 1)
        self.assertEqual(self.store.count_for_recipient(self.ignw), 0)
        self.assertEqual(self.store.count_for_recipient(self.plain), 0)

    def test_publisher_not_notified_even_when_watching(self):
        self.watches.set_watch(self.owner, "volmarr", "pub", "all")
        self._publish("v1.0")
        self.assertEqual(self.store.sync_repo("volmarr", "pub"), 0)
        self.assertEqual(self.store.count_for_recipient(self.owner), 0)
        self.assertEqual(
            self.notes.list_for_recipient(self.owner), [])

    def test_notification_is_s223_subscribed(self):
        self._watch_all_three()
        self._publish("v1.0")
        self.store.sync_all()
        rows = self.notes.list_for_recipient(
            self.relw, reason="subscribed")
        self.assertEqual(len(rows), 1)
        note = rows[0]
        self.assertEqual(note.verb, PUBLISH_VERB)
        self.assertEqual(note.target_kind, "release")
        self.assertEqual(note.target_id, "volmarr/pub")
        self.assertEqual(note.detail["repo"], "volmarr/pub")
        self.assertEqual(note.detail["tag"], "v1.0")
        self.assertEqual(note.detail["watch_mode"], "releases_only")
        self.assertEqual(note.actor, "volmarr")
        self.assertTrue(note.unread)

    def test_draft_create_notifies_nobody(self):
        self._watch_all_three()
        self._publish("v1.3", draft=True)
        self.assertEqual(self.store.sync_repo("volmarr", "pub"), 0)
        self.assertEqual(self.store.count_for_recipient(self.allw), 0)
        self.assertEqual(
            self.notes.list_for_recipient(self.relw), [])

    def test_draft_edit_notifies_nobody(self):
        self._watch_all_three()
        self._publish("v1.3", draft=True)
        self.releases.update_release(
            self.owner, "volmarr", "pub", "v1.3",
            title="Anvil 1.3 renamed", notes="Edited in draft.")
        self.assertEqual(self.store.sync_all(), 0)
        self.assertEqual(self.store.count_for_recipient(self.relw), 0)

    def test_publish_draft_notifies(self):
        self._watch_all_three()
        self._publish("v1.3", draft=True)
        self.assertEqual(self.store.sync_all(), 0)
        self.releases.publish_release(
            self.owner, "volmarr", "pub", "v1.3")
        self.assertEqual(self.store.sync_repo("volmarr", "pub"), 2)
        got = self.store.deliveries_for_recipient(self.relw)
        self.assertEqual([d.tag for d in got], ["v1.3"])

    def test_publish_draft_prerelease_notifies(self):
        self._watch_all_three()
        self._publish("v1.4", draft=True, prerelease=True)
        self.assertEqual(self.store.sync_all(), 0)
        published = self.releases.publish_release(
            self.owner, "volmarr", "pub", "v1.4")
        self.assertTrue(published.prerelease)
        self.assertEqual(self.store.sync_repo("volmarr", "pub"), 2)

    def test_prerelease_create_notifies(self):
        self._watch_all_three()
        self._publish("v1.5", prerelease=True)
        self.assertEqual(self.store.sync_repo("volmarr", "pub"), 2)
        self.assertEqual(self.store.count_for_recipient(self.allw), 1)

    def test_resync_exactly_once(self):
        self._watch_all_three()
        self._publish("v1.0")
        self.assertEqual(self.store.sync_repo("volmarr", "pub"), 2)
        self.assertEqual(self.store.sync_repo("volmarr", "pub"), 0)
        self.assertEqual(self.store.sync_all(), 0)
        self.assertEqual(self.store.count_for_recipient(self.relw), 1)
        self.assertEqual(
            len(self.notes.list_for_recipient(self.relw)), 1)

    def test_sync_all_counts(self):
        self._watch_all_three()
        self._publish("v1.0")
        self._publish("v1.4")
        self.assertEqual(self.store.sync_all(), 4)
        self.assertEqual(self.store.sync_all(), 0)

    def test_tag_push_door_notifies(self):
        self._watch_all_three()
        made = self.releases.create_release_from_tag_push(
            self.owner, "volmarr", "pub", "v1.1")
        self.assertEqual(made.tag, "v1.1")
        self.assertEqual(self.store.sync_repo("volmarr", "pub"), 2)

    def test_api_door_notifies(self):
        self._watch_all_three()
        self.releases.create_release_from_api(
            self.owner, "volmarr", "pub",
            {"tag": "v1.0", "title": "Anvil 1.0", "notes": "Via API."})
        self.assertEqual(self.store.sync_repo("volmarr", "pub"), 2)

    def test_two_publications_two_deliveries_ordered(self):
        self._watch_all_three()
        self._publish("v1.0")
        self._publish("v1.4")
        self.store.sync_all()
        got = self.store.deliveries_for_recipient(self.relw)
        self.assertEqual([d.tag for d in got], ["v1.0", "v1.4"])
        self.assertTrue(all(
            d.watch_mode == "releases_only" for d in got))

    def test_unwatch_before_sync_no_delivery(self):
        self._watch_all_three()
        self._publish("v1.0")
        self.watches.clear_watch(self.relw, "volmarr", "pub")
        self.assertEqual(self.store.sync_repo("volmarr", "pub"), 1)
        self.assertEqual(self.store.count_for_recipient(self.relw), 0)
        self.assertEqual(self.store.count_for_recipient(self.allw), 1)

    def test_watch_after_publish_before_sync_delivers(self):
        self._publish("v1.0")
        self.watches.set_watch(
            self.relw, "volmarr", "pub", "releases_only")
        self.assertEqual(self.store.sync_repo("volmarr", "pub"), 1)
        self.assertEqual(self.store.count_for_recipient(self.relw), 1)

    def test_visibility_flip_blocks_delivery(self):
        self._watch_all_three()
        self.repos.update_metadata(
            self.owner.id, "volmarr", "pub", visibility="private")
        self._publish("v1.0")
        self.assertEqual(self.store.sync_repo("volmarr", "pub"), 0)
        self.assertEqual(self.store.count_for_recipient(self.relw), 0)

    # -- reads ----------------------------------------------
    def test_deliveries_for_recipient_requires_login(self):
        self.assertEqual(
            self._reason(self.store.deliveries_for_recipient, None),
            "authentication_required")
        self.assertEqual(
            self._reason(self.store.count_for_recipient, None),
            "authentication_required")

    def test_deliveries_for_recipient_only_own(self):
        self._watch_all_three()
        self._publish("v1.0")
        mine = self.store.deliveries_for_recipient(self.allw)
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0].recipient, "allw")
        self.assertEqual(mine[0].repository, "volmarr/pub")
        self.assertEqual(
            self.store.deliveries_for_recipient(self.plain), [])

    def test_count_for_recipient(self):
        self._watch_all_three()
        self._publish("v1.0")
        self._publish("v1.4")
        self.assertEqual(self.store.count_for_recipient(self.allw), 2)
        self.assertEqual(self.store.count_for_recipient(self.ignw), 0)

    def test_deliveries_for_release_listing(self):
        self._watch_all_three()
        made = self._publish("v1.0")
        rows = self.store.deliveries_for_release(
            self.owner, "volmarr", "pub", "v1.0")
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            {d.watch_mode for d in rows}, {"all", "releases_only"})
        self.assertTrue(all(d.release_id == made.id for d in rows))
        self.assertTrue(all(d.tag == "v1.0" for d in rows))

    def test_deliveries_for_release_gates(self):
        self._publish("v1.3", draft=True)
        self.assertEqual(
            self._reason(self.store.deliveries_for_release,
                         self.allw, "volmarr", "pub", "v1.3"),
            "release_not_found")
        self.assertEqual(
            self._reason(self.store.deliveries_for_release,
                         self.owner, "volmarr", "pub", "v9.9"),
            "release_not_found")
        self.assertEqual(
            self._reason(self.store.sync_repo, "volmarr", "nope"),
            "repo_not_found")
        # the writer may list the draft's (empty) deliveries
        self.assertEqual(
            self.store.deliveries_for_release(
                self.owner, "volmarr", "pub", "v1.3"), [])

    def test_delivery_words_and_dict(self):
        self._watch_all_three()
        self._publish("v1.0")
        got = self.store.deliveries_for_recipient(self.relw)[0]
        self.assertIn("volmarr published release v1.0", got.words)
        self.assertIn("volmarr/pub", got.words)
        self.assertIn("you are subscribed", got.words)
        self.assertEqual(got.reason_words, "you are subscribed")
        as_dict = delivery_to_dict(got)
        self.assertEqual(as_dict["repository"], "volmarr/pub")
        self.assertEqual(as_dict["tag"], "v1.0")
        self.assertEqual(as_dict["watch_mode"], "releases_only")
        self.assertEqual(as_dict["reason"], "subscribed")
        self.assertEqual(as_dict["verb"], PUBLISH_VERB)
        self.assertEqual(
            as_dict["notification_id"], got.notification_id)

    def test_render_plain_words_and_escaping(self):
        self._watch_all_three()
        self._publish("v1.0")
        got = self.store.deliveries_for_recipient(self.relw)
        page = render_release_notifications(got)
        self.assertIn("published release v1.0", page)
        self.assertIn("you are subscribed", page)
        crafted = ReleaseDelivery(
            id=1, notification_id=1, audit_seq=1, repo_id=1,
            repository="volmarr/pub", release_id=1,
            tag="<b>v9</b>", recipient_id=2, recipient="relw",
            actor_id=1, actor="volmarr", watch_mode="all",
            reason="subscribed", created_at=T0)
        evil = render_release_notifications([crafted])
        self.assertIn("&lt;b&gt;v9&lt;/b&gt;", evil)
        self.assertNotIn("<b>v9</b>", evil)
        empty = render_release_notifications([])
        self.assertIn("Drafts are saved silently", empty)

    def test_deleted_release_delivery_stays_honest(self):
        self._watch_all_three()
        self._publish("v1.0")
        self.store.sync_all()
        self.releases.delete_release(
            self.owner, "volmarr", "pub", "v1.0")
        got = self.store.deliveries_for_recipient(self.relw)
        self.assertEqual([d.tag for d in got], ["v1.0"])
        self.assertIn("v1.0", got[0].words)


if __name__ == "__main__":
    unittest.main()
