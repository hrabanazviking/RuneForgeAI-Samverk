"""S-279 acceptance battery: gist fork and star.

Acceptance (roadmap S-279): Gist fork and star --
forking copies history; stars work as S-222.

Fork (over S-277/S-278's GistStore in
samverk/gists.py): a server-side bare clone through
S-014's local-paths-only seam (`run_git_clone_local`,
the S-055 road) gives the fork its own complete
object store carrying the source's full revision
history -- the same tip, the same commit oids --
while migration 110's `fork_of_id` column records
the direct source as lineage only. The fork is a
new gist owned by the forker, with the source's
description and (by default) its visibility.

Star (migration 110's `gist_stars`): S-222's law
carried to gists -- a star is a stored row, counts
are COUNT(*) at read time, re-starring and
un-starring what was never starred are quiet
no-ops, un-starring removes only the actor's own
row, mutations need a signed-in account
(login_required), and an unknown gist is the
uniform gist_not_found. Reads follow S-278's
visibility law: public and secret alike are
readable (and so starrable and forkable) by link;
secret gists stay unlisted in starred/fork
listings for anyone but their owner.

No new taxonomy event -- 133 stand (33 auth /
87 repo / 13 admin); gist acts unwitnessed, as
S-277's law. Schema 109 -> 110.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.gist_web import GistWeb, GistWebError
from samverk.gists import (
    GistError, GistStore, decide_star, gist_to_dict,
    render_gist_fork_star)

PW = "correct horse battery"
T0 = 1_700_000_000


class Clock:
    def __init__(self, now=T0):
        self.now = now
    def __call__(self):
        return self.now


class GistForkStarTests(unittest.TestCase):
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
        self.other = self.accounts.register("yrsa", PW)
        self.third = self.accounts.register("tess", PW)
        self.gists = GistStore(
            self.conn, self.root, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.web = GistWeb(
            self.conn, self.root, self.accounts,
            gists=self.gists, audit=self.audit,
            time_fn=self.clock)

    def _reason(self, fn, *a, **k):
        with self.assertRaises((GistError, GistWebError)) as ctx:
            fn(*a, **k)
        return ctx.exception.reason

    def _make(self, description="demo gist", visibility="public",
              revisions=3):
        gist = self.gists.create_gist(
            self.owner, description,
            {"hello.py": "print('v1')\n", "notes.md": "# Notes\n"},
            visibility=visibility)
        for n in range(2, revisions + 1):
            gist = self.gists.update_gist(
                self.owner, gist.id,
                files={"hello.py": f"print('v{n}')\n",
                       "notes.md": "# Notes\n"},
                message=f"revision {n}")
        return gist

    # -- schema / taxonomy pins ---------------------------

    def test_schema_and_taxonomy_stand(self):
        self.assertEqual(schema_version(self.conn), 125)
        self.assertEqual(db.MIGRATIONS[-1][0], 125)
        self.assertEqual(db.migrate(self.conn), 125)
        from samverk.taxonomy import AUDIT_EVENTS
        self.assertEqual(len(AUDIT_EVENTS), 135)

    def test_pure_decide_star(self):
        self.assertTrue(decide_star(False, True))
        self.assertTrue(decide_star(True, False))
        self.assertFalse(decide_star(True, True))
        self.assertFalse(decide_star(False, False))

    # -- fork: gates ---------------------------------------

    def test_fork_requires_signed_in(self):
        gist = self._make()
        self.assertEqual(
            self._reason(self.gists.fork_gist, None, gist.id),
            "permission_denied")

    def test_fork_unknown_gist_is_uniform_not_found(self):
        self.assertEqual(
            self._reason(self.gists.fork_gist, self.other, 99999),
            "gist_not_found")
        self.assertEqual(
            self._reason(self.gists.fork_gist, self.other, "x"),
            "gist_not_found")

    # -- fork: history, provenance, ownership ---------------

    def test_fork_copies_full_history(self):
        src = self._make(revisions=3)
        fork = self.gists.fork_gist(self.other, src.id)
        self.assertEqual(fork.revision_count, 3)
        self.assertEqual(fork.head_oid, src.head_oid)
        src_revs = self.gists.list_revisions(self.owner, src.id)
        fork_revs = self.gists.list_revisions(self.other, fork.id)
        self.assertEqual([r.oid for r in fork_revs],
                         [r.oid for r in src_revs])
        self.assertEqual([r.message for r in fork_revs],
                         [r.message for r in src_revs])
        # A file body at an old revision reads in the fork.
        first = fork_revs[-1].oid
        old = self.gists.read_file(
            self.other, fork.id, "hello.py", revision=first)
        self.assertEqual(old.content, "print('v1')\n")
        now = self.gists.read_file(self.other, fork.id, "hello.py")
        self.assertEqual(now.content, "print('v3')\n")

    def test_fork_is_independent_of_source(self):
        src = self._make(revisions=2)
        fork = self.gists.fork_gist(self.other, src.id)
        self.gists.update_gist(
            self.owner, src.id,
            files={"hello.py": "print('v3')\n",
                   "notes.md": "# Notes\n"},
            message="source moves on")
        standing = self.gists.get_gist(self.other, fork.id)
        self.assertEqual(standing.revision_count, 2)
        self.assertEqual(standing.head_oid, fork.head_oid)
        # Deleting the source can never break the fork:
        # the clone owns its object store outright.
        self.gists.delete_gist(self.owner, src.id)
        survivor = self.gists.get_gist(self.other, fork.id)
        self.assertEqual(survivor.revision_count, 2)
        body = self.gists.read_file(self.other, fork.id, "hello.py")
        self.assertEqual(body.content, "print('v2')\n")

    def test_fork_provenance_and_counts(self):
        src = self._make()
        self.assertIsNone(src.fork_of_id)
        self.assertEqual(self.gists.fork_count(src.id), 0)
        self.assertIsNone(self.gists.fork_source(self.owner, src.id))
        fork = self.gists.fork_gist(self.other, src.id)
        self.assertEqual(fork.fork_of_id, src.id)
        self.assertEqual(gist_to_dict(fork)["fork_of_id"], src.id)
        self.assertEqual(self.gists.fork_count(src.id), 1)
        source = self.gists.fork_source(self.other, fork.id)
        self.assertIsNotNone(source)
        self.assertEqual(source.id, src.id)
        # A fork of a fork points at its direct source.
        fork2 = self.gists.fork_gist(self.third, fork.id)
        self.assertEqual(fork2.fork_of_id, fork.id)
        self.assertEqual(self.gists.fork_count(src.id), 1)
        self.assertEqual(self.gists.fork_count(fork.id), 1)
        forks = self.gists.list_forks(None, src.id)
        self.assertEqual([g.id for g in forks], [fork.id])

    def test_fork_ownership_description_visibility(self):
        src = self._make(description="carry me",
                         visibility="secret")
        fork = self.gists.fork_gist(self.other, src.id)
        self.assertEqual(fork.owner, "yrsa")
        self.assertEqual(fork.owner_id, self.other.id)
        self.assertEqual(fork.description, "carry me")
        self.assertEqual(fork.visibility, "secret")
        path = self.root / "gists" / "yrsa" / f"{fork.id}.git"
        self.assertTrue(path.is_dir())
        self.assertEqual(self.gists.gist_path(fork.id), path)
        # The fork stands in the forker's own listing,
        # secret and all; the source owner's list is
        # untouched.
        mine = self.gists.list_gists(self.other, "yrsa")
        self.assertEqual([g.id for g in mine], [fork.id])

    def test_fork_visibility_override_is_judged(self):
        src = self._make(visibility="secret")
        fork = self.gists.fork_gist(
            self.other, src.id, visibility="public")
        self.assertEqual(fork.visibility, "public")
        self.assertEqual(
            self._reason(self.gists.fork_gist, self.other,
                         src.id, visibility="private"),
            "visibility_invalid")

    def test_owner_may_fork_own_gist(self):
        src = self._make()
        fork = self.gists.fork_gist(self.owner, src.id)
        self.assertEqual(fork.owner, "volmarr")
        self.assertNotEqual(fork.id, src.id)
        self.assertEqual(fork.fork_of_id, src.id)

    # -- star: S-222 semantics -------------------------------

    def test_star_unstar_counts_are_live(self):
        gist = self._make()
        self.assertEqual(self.gists.star_count(gist), 0)
        summary = self.gists.star(self.other, gist.id)
        self.assertEqual(summary.star_count, 1)
        self.assertTrue(summary.my_starred)
        self.assertEqual(summary.gist_id, gist.id)
        self.gists.star(self.third, gist.id)
        self.assertEqual(self.gists.star_count(gist), 2)
        summary = self.gists.unstar(self.other, gist.id)
        self.assertEqual(summary.star_count, 1)
        self.assertFalse(summary.my_starred)
        self.assertEqual(self.gists.star_count(gist), 1)

    def test_star_retries_are_quiet_noops(self):
        gist = self._make()
        self.gists.star(self.other, gist.id)
        again = self.gists.star(self.other, gist.id)
        self.assertEqual(again.star_count, 1)
        self.gists.unstar(self.third, gist.id)
        self.assertEqual(self.gists.star_count(gist), 1)
        self.gists.unstar(self.other, gist.id)
        twice = self.gists.unstar(self.other, gist.id)
        self.assertEqual(twice.star_count, 0)

    def test_unstar_only_takes_your_own(self):
        gist = self._make()
        self.gists.star(self.other, gist.id)
        self.gists.unstar(self.third, gist.id)
        self.assertEqual(self.gists.star_count(gist), 1)
        self.assertTrue(self.gists.is_starred(self.other, gist.id))

    def test_star_requires_signed_in(self):
        gist = self._make()
        self.assertEqual(
            self._reason(self.gists.star, None, gist.id),
            "login_required")
        self.assertEqual(
            self._reason(self.gists.unstar, None, gist.id),
            "login_required")
        self.assertEqual(self.gists.star_count(gist), 0)

    def test_star_unknown_gist_is_uniform_not_found(self):
        self.assertEqual(
            self._reason(self.gists.star, self.other, 99999),
            "gist_not_found")
        self.assertEqual(
            self._reason(self.gists.star_summary, None, 99999),
            "gist_not_found")
        self.assertFalse(self.gists.is_starred(None, self._make().id))

    def test_anonymous_reads_star_state(self):
        gist = self._make()
        self.gists.star(self.other, gist.id)
        summary = self.gists.star_summary(None, gist.id)
        self.assertEqual(summary.star_count, 1)
        self.assertEqual(summary.fork_count, 0)
        self.assertFalse(summary.my_starred)
        self.assertFalse(self.gists.is_starred(None, gist.id))

    def test_star_secret_gist_by_link(self):
        # S-278's law: a secret gist is readable by
        # link, so it is starrable and forkable by
        # link too -- it is unlisted, not private.
        gist = self._make(visibility="secret")
        summary = self.gists.star(self.other, gist.id)
        self.assertEqual(summary.star_count, 1)
        fork = self.gists.fork_gist(self.third, gist.id)
        self.assertEqual(fork.fork_of_id, gist.id)
        # ...yet the secret gist stays out of the
        # owner's public listing for strangers.
        listed = self.gists.list_gists(None, "volmarr")
        self.assertEqual(listed, [])

    def test_list_starred_gists_and_secret_filter(self):
        pub = self._make(description="open")
        sec = self.gists.create_gist(
            self.owner, "quiet", {"a.txt": "a"},
            visibility="secret")
        self.gists.star(self.other, pub.id)
        self.gists.star(self.other, sec.id)
        own = self.gists.list_starred_gists(self.other, "yrsa")
        self.assertEqual([g.id for g in own], [pub.id, sec.id])
        # A stranger's view of yrsa's stars: the public
        # gist shows; the secret one she starred does
        # not (it is not hers to list, nor the viewer's).
        stranger = self.gists.list_starred_gists(self.third, "yrsa")
        self.assertEqual([g.id for g in stranger], [pub.id])
        anon = self.gists.list_starred_gists(None, "yrsa")
        self.assertEqual([g.id for g in anon], [pub.id])
        self.assertEqual(
            self._reason(self.gists.list_starred_gists,
                         None, "nobody"),
            "gist_not_found")

    def test_delete_gist_removes_its_stars(self):
        gist = self._make()
        self.gists.star(self.other, gist.id)
        self.gists.delete_gist(self.owner, gist.id)
        rows = self.conn.execute(
            "SELECT COUNT(*) AS c FROM gist_stars"
            " WHERE gist_id = ?", (gist.id,)).fetchone()
        self.assertEqual(int(rows["c"]), 0)
        self.assertEqual(
            self.gists.list_starred_gists(self.other, "yrsa"), [])

    def test_render_names_counts_and_own_state(self):
        gist = self._make()
        self.gists.star(self.other, gist.id)
        self.gists.fork_gist(self.third, gist.id)
        mine = render_gist_fork_star(
            self.gists.star_summary(self.other, gist.id))
        self.assertIn("Stars: 1", mine)
        self.assertIn("starred by you", mine)
        self.assertIn("Forks: 1", mine)
        anon = render_gist_fork_star(
            self.gists.star_summary(None, gist.id))
        self.assertIn("not starred by you", anon)

    # -- web face ---------------------------------------------

    def test_web_fork_star_and_view_counts(self):
        gist = self.web.create_gist(
            self.owner, "via web", "public",
            [("a.txt", "alpha\n")])
        fork = self.web.fork_gist(self.other, gist.id)
        self.assertEqual(fork.owner, "yrsa")
        self.assertEqual(fork.fork_of_id, gist.id)
        self.web.star_gist(self.third, gist.id)
        view = self.web.view_gist(None, gist.id)
        self.assertEqual(view.star_count, 1)
        self.assertEqual(view.fork_count, 1)
        self.assertFalse(view.my_starred)
        mine = self.web.view_gist(self.third, gist.id)
        self.assertTrue(mine.my_starred)
        self.web.unstar_gist(self.third, gist.id)
        self.assertEqual(self.web.view_gist(None, gist.id).star_count, 0)
        self.assertEqual(
            self._reason(self.web.star_gist, self.other, 99999),
            "gist_not_found")


if __name__ == "__main__":
    unittest.main()
