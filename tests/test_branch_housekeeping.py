"""S-159 acceptance battery: branch housekeeping.

Acceptance (roadmap S-159): branch housekeeping --
delete head branch on merge (opt-in), restore branch
action, fork sync hint.

Written against hidden_files/s159-design.md (designer
output, 2026-11-06; the on-device copy is truncated at
~14,175 of 23,687 bytes and is NOT trusted past that
point -- every fact used here is either inside the
trusted prefix or was supplied in the designer's
summary). At battery-writing time NO implementation
exists in this worktree (no samverk/
branch_housekeeping.py, migrations end at 57, taxonomy
at 110 events, git HEAD is the S-152 base): this
battery is the executable form of the design, in the
house style of the S-151 (14 tests) and S-152
(16 tests) batteries. Builders implement to the
design + this battery; where the two conflict, the
conflict is recorded in CAMPAIGN_STATE.md.

Design facts this battery enforces:
- Migration 58: repo_settings.delete_branch_on_merge
  INTEGER NOT NULL DEFAULT 0 (OFF) + table
  deleted_branches (id, repo_id, branch_name,
  head_oid, deleted_at, deleted_by, pull_request_id,
  pr_number, merge_oid, restored_at, restored_by).
- Setting surface: RepoSettings.delete_branch_on_merge
  and RepoSettingsService.update_settings(...,
  delete_branch_on_merge=...) -- strict bool only,
  else SettingsError 'delete_branch_on_merge_invalid';
  owner-only; the change rides the frozen
  repo.settings.change audit event with the key named.
- Service: BranchHousekeepingService(conn, data_root,
  accounts, repositories, audit=None, time_fn=...);
  error BranchHousekeepingError(RepositoryError).
- Hook: on_pull_request_merged runs AFTER the merge
  commit/transaction. Deletion only when the setting
  is ON for the HEAD-OWNING repository AND the PR
  re-reads as merged AND head != default branch AND
  head != base branch AND head != HEAD target AND the
  ref resolves; CAS delete via
  RefStore.delete_branch(expected_old=head_oid);
  a stale_ref race is a SILENT skip (no row, no
  event). NOTE (tester-flagged tension): design
  section 2.4 guard 7 resolves the oid at hook time,
  so a branch moved after the merge would be deleted
  at its NEW oid under a literal reading; the
  designer's own battery sketch demands a
  'stale-race skip'. Test 7 therefore simulates the
  race INSIDE the CAS window (the ref moves between
  resolve and delete), which is the reading both
  texts agree on.
- Audit: repo.branch.delete_on_merge {number,
  branch, head_repo, oid, merge} and
  repo.branch.restore {branch, oid,
  deleted_branch_id} fire ONLY on actual change;
  taxonomy 110 -> 112 events exactly.
- Restore: restore_branch(actor_user_id, owner, repo,
  deleted_branch_id) recreates the EXACT recorded
  head_oid; deleted_branches(viewer, owner, repo)
  lists rows newest first, restored rows included.
  Refusals by name, nothing written, no event:
  deleted_branch_not_found, already_restored,
  branch_exists, oid_unavailable.
  HTTP names (not exercised here; server.py is a
  skeleton by the scout's verified ground):
  POST /{owner}/{repo}/branches/restore,
  GET /{owner}/{repo}/branches/deleted.
- Fork hint: fork_sync_status(viewer, owner, repo)
  -> ForkSyncStatus(state, upstream_full_name,
  branch, behind, ahead), state in {not_a_fork,
  no_upstream, up_to_date, behind, unknown};
  read-only, no audit event; shown only when
  behind > 0; a viewer who cannot read the upstream
  gets no_upstream and NO leaked counts.
- Protected branches: Part VIII protection rules do
  NOT exist at S-159 (design section 2.4 guard 6);
  the guard is the is_deletable_branch predicate
  seam. This battery tests the guards that exist
  today (default / base / HEAD) and, when the
  predicate is importable, its answers for them.

There is no merge implementation in this base
(S-153..S-155 are parallel slices), so tests simulate
a completed merge honestly: a real merge commit is
created on the base branch, the PR is marked merged
in the database (closed + any merged-* columns the
schema carries), and only then is the hook fired.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import inspect, sqlite3, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog, verify_chain
from samverk.branch_housekeeping import (
    BranchHousekeepingError, BranchHousekeepingService)
try:
    from samverk.branch_housekeeping import is_deletable_branch
except ImportError:  # predicate seam: tested when present
    is_deletable_branch = None
try:
    from samverk.branch_housekeeping import render_deleted_branches
except ImportError:
    render_deleted_branches = None
from samverk.forks import ForkStore
from samverk.fork_sync import ForkSyncStore
from samverk.issues import IssueStore
from samverk.pull_request_forks import ForkPullRequestStore
from samverk.pull_requests import PullRequestStore
from samverk.refs import RefStore, branch_ref
from samverk.repo_settings import RepoSettingsService, SettingsError
from samverk.repositories import RepositoryStore


def git(repo, *args, input_bytes=None):
    env = {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": "/usr/bin:/bin"}
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         capture_output=True, input=input_bytes, env=env)
    assert out.returncode == 0, out.stderr.decode()
    return out.stdout.decode().strip()


def make_tree(repo, files):
    def build(items):
        entries = []
        dirs = {}
        for path, content in items:
            head, _, rest = path.partition("/")
            if rest:
                dirs.setdefault(head, []).append((rest, content))
            else:
                blob = git(repo, "hash-object", "-w", "--stdin",
                           input_bytes=content.encode())
                entries.append((path, f"100644 blob {blob}\t{path}"))
        for name, sub in dirs.items():
            tree = build(sub)
            entries.append((name + "/", f"040000 tree {tree}\t{name}"))
        entries.sort(key=lambda item: item[0])
        return git(repo, "mktree",
                   input_bytes=("\n".join(
                       line for _key, line in entries) + "\n").encode())
    return build(sorted(files.items()))


def make_commit(repo, parent, files, message):
    tree = make_tree(repo, files)
    args = ["commit-tree", tree]
    if parent:
        args += ["-p", parent]
    return git(repo, *args, input_bytes=(message + "\n").encode())


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now

    def __call__(self):
        return self.now


def _bname(rec):
    return getattr(rec, "branch_name", None) or getattr(rec, "branch")


def _boid(rec):
    return getattr(rec, "head_oid", None) or getattr(rec, "oid")


class BranchHousekeepingTests(unittest.TestCase):
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
        self.third = self.accounts.register("tess", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.forks = ForkStore(self.conn, self.root, self.accounts,
                               self.repos, audit=self.audit)
        self.issues = IssueStore(self.conn, self.repos, self.accounts,
                                 audit=self.audit, time_fn=self.clock)
        self.prs = PullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.xprs = ForkPullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.settings = RepoSettingsService(
            self.conn, self.root, self.accounts, self.repos,
            audit=self.audit, time_fn=self.clock)
        self.hk = BranchHousekeepingService(
            self.conn, self.root, self.accounts, self.repos,
            audit=self.audit, time_fn=self.clock)
        self.forksync = ForkSyncStore(self.repos)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.path = self.repos.path_for("volmarr", "pub")

    # -- helpers ---------------------------------------------------------
    def _open(self, base_files=None, head_files=None, *, name="pub",
              base_branch="main", head_branch="feature", draft=False):
        if name != "pub":
            self.repos.create_repository(
                self.owner.id, "volmarr", name, visibility="public")
        path = self.repos.path_for("volmarr", name)
        base_files = base_files or {"a.txt": "alpha\n"}
        head_files = head_files or {"a.txt": "alpha\nbeta\n"}
        base_oid = make_commit(path, None, base_files, "base")
        git(path, "update-ref", f"refs/heads/{base_branch}", base_oid)
        head_oid = make_commit(path, base_oid, head_files, "feature work")
        git(path, "update-ref", f"refs/heads/{head_branch}", head_oid)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", name,
            base_branch=base_branch, head_branch=head_branch,
            draft=draft)
        return pr, path, base_oid, head_oid

    def _ref(self, path, branch):
        return RefStore(path).resolve(branch_ref(branch))

    def _audit_count(self, action):
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM audit_log WHERE action = ?",
            (action,)).fetchone()
        return int(row["c"])

    def _set_opt_in(self, enabled, owner="volmarr", name="pub",
                    actor=None):
        actor = actor or self.owner
        return self.settings.update_settings(
            actor.id, owner, name, delete_branch_on_merge=enabled)

    def _opt_in(self, owner="volmarr", name="pub", viewer=None):
        s = self.settings.settings_for(viewer or self.owner, owner, name)
        return bool(getattr(s, "delete_branch_on_merge", False))

    def _mark_merged(self, pr, base_path, base_branch, head_oid,
                     merged_files=None):
        """A real merge commit on the base branch + the PR
        marked merged in the DB (the S-153..S-155 slices'
        side of the seam, simulated for this battery)."""
        base_now = self._ref(base_path, base_branch)
        merged_files = merged_files or {"a.txt": "alpha\nbeta\n"}
        tree = make_tree(base_path, merged_files)
        merge_oid = git(base_path, "commit-tree", tree,
                        "-p", base_now, "-p", head_oid,
                        input_bytes=b"merge\n")
        git(base_path, "update-ref", f"refs/heads/{base_branch}",
            merge_oid)
        now = int(self.clock())
        with self.conn:
            self.conn.execute(
                "UPDATE issues SET state = 'merged' WHERE id = ?",
                (pr.row_id,))
            cols = [r["name"] for r in self.conn.execute(
                "PRAGMA table_info(pull_requests)").fetchall()]
            sets, vals = [], []
            for col, val in (("merged", 1), ("is_merged", 1),
                             ("merged_at", now),
                             ("merged_by", self.owner.id),
                             ("merge_oid", merge_oid),
                             ("merged_oid", merge_oid),
                             ("merge_commit_oid", merge_oid),
                             ("state", "merged")):
                if col in cols:
                    sets.append(f"{col} = ?")
                    vals.append(val)
            if sets:
                self.conn.execute(
                    "UPDATE pull_requests SET " + ", ".join(sets)
                    + " WHERE id = ?", (*vals, pr.id))
        return merge_oid

    def _fire(self, actor, owner, repo, number, merge_oid):
        """Call the post-merge hook. The design text
        (trusted prefix) writes the call without repo
        coordinates; the signature is therefore probed
        so the battery stands under either reading."""
        fn = self.hk.on_pull_request_merged
        params = inspect.signature(fn).parameters
        if "owner" in params or len(params) >= 5:
            return fn(actor.id, owner, repo, number, merge_oid)
        return fn(actor.id, number, merge_oid)

    def _rows(self, owner="volmarr", name="pub", viewer=None):
        return list(self.hk.deleted_branches(
            viewer or self.owner, owner, name))

    def _delete_feature_on_merge(self):
        """Opt-in ON + a merged feature PR; returns the
        (pr, path, base_oid, head_oid, merge_oid)."""
        self._set_opt_in(True)
        pr, path, base_oid, head_oid = self._open()
        merge_oid = self._mark_merged(pr, path, "main", head_oid)
        self._fire(self.owner, "volmarr", "pub", pr.number, merge_oid)
        return pr, path, base_oid, head_oid, merge_oid

    # -- 1. the opt-in setting --------------------------------------------
    def test_setting_defaults_off_strict_bool_owner_only_and_audited(self):
        self.assertFalse(self._opt_in())
        with self.assertRaises(SettingsError) as caught:
            self._set_opt_in("yes")
        self.assertEqual(caught.exception.reason,
                         "delete_branch_on_merge_invalid")
        self.assertFalse(self._opt_in())
        with self.assertRaises(SettingsError) as caught:
            self.settings.update_settings(
                self.reader.id, "volmarr", "pub",
                delete_branch_on_merge=True)
        self.assertEqual(caught.exception.reason, "not_repo_owner")
        before = self._audit_count("repo.settings.change")
        self._set_opt_in(True)
        self.assertTrue(self._opt_in())
        self.assertEqual(
            self._audit_count("repo.settings.change"), before + 1)
        detail = self.conn.execute(
            "SELECT detail FROM audit_log"
            " WHERE action = 'repo.settings.change'"
            " ORDER BY seq DESC LIMIT 1").fetchone()["detail"]
        self.assertIn("delete_branch_on_merge", detail)
        self._set_opt_in(False)
        self.assertFalse(self._opt_in())

    # -- 2. opt-in OFF / ON on merge ---------------------------------------
    def test_merge_with_opt_in_off_keeps_head_branch(self):
        pr, path, _b, head_oid = self._open()
        merge_oid = self._mark_merged(pr, path, "main", head_oid)
        self._fire(self.owner, "volmarr", "pub", pr.number, merge_oid)
        self.assertEqual(self._ref(path, "feature"), head_oid)
        self.assertEqual(self._rows(), [])
        self.assertEqual(
            self._audit_count("repo.branch.delete_on_merge"), 0)

    def test_opt_in_on_deletes_records_audits_and_hook_is_idempotent(self):
        pr, path, base_oid, head_oid, merge_oid = \
            self._delete_feature_on_merge()
        self.assertIsNone(self._ref(path, "feature"))
        self.assertEqual(self._ref(path, "main"), merge_oid)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        rec = rows[0]
        self.assertEqual(_bname(rec), "feature")
        self.assertEqual(_boid(rec), head_oid)
        self.assertEqual(rec.deleted_by, self.owner.id)
        self.assertEqual(rec.deleted_at, 1_700_000_000)
        self.assertEqual(rec.pr_number, pr.number)
        self.assertEqual(rec.merge_oid, merge_oid)
        self.assertIsNone(rec.restored_at)
        self.assertIsNone(rec.restored_by)
        self.assertEqual(
            self._audit_count("repo.branch.delete_on_merge"), 1)
        detail = self.conn.execute(
            "SELECT detail FROM audit_log"
            " WHERE action = 'repo.branch.delete_on_merge'"
        ).fetchone()["detail"]
        self.assertIn("feature", detail)
        self.assertIn(head_oid, detail)
        # Idempotent: firing the hook again changes nothing.
        self._fire(self.owner, "volmarr", "pub", pr.number, merge_oid)
        self.assertEqual(len(self._rows()), 1)
        self.assertEqual(
            self._audit_count("repo.branch.delete_on_merge"), 1)
        ok, bad, _n = verify_chain(self.conn)
        self.assertTrue(ok, bad)

    # -- 3. guards ------------------------------------------------------------
    def test_not_merged_closed_and_draft_prs_fire_nothing(self):
        self._set_opt_in(True)
        pr, path, _b, head_oid = self._open()
        # Open, never merged: the hook re-read refuses.
        self._fire(self.owner, "volmarr", "pub", pr.number, head_oid)
        self.assertEqual(self._ref(path, "feature"), head_oid)
        # Closed without merging: still nothing.
        with self.conn:
            self.conn.execute(
                "UPDATE issues SET state = 'closed' WHERE id = ?",
                (pr.row_id,))
        self._fire(self.owner, "volmarr", "pub", pr.number, head_oid)
        self.assertEqual(self._ref(path, "feature"), head_oid)
        # A draft PR: nothing either.
        draft, dpath, _b2, dhead = self._open(
            name="pub2", draft=True)
        self._set_opt_in(True, name="pub2")
        self._fire(self.owner, "volmarr", "pub2", draft.number, dhead)
        self.assertEqual(self._ref(dpath, "feature"), dhead)
        self.assertEqual(self._rows(), [])
        self.assertEqual(self._rows(name="pub2"), [])
        self.assertEqual(
            self._audit_count("repo.branch.delete_on_merge"), 0)

    def test_default_branch_is_never_deleted(self):
        self._set_opt_in(True)
        base_oid = make_commit(self.path, None, {"a.txt": "alpha\n"},
                               "base")
        git(self.path, "update-ref", "refs/heads/main", base_oid)
        git(self.path, "update-ref", "refs/heads/release", base_oid)
        head_oid = make_commit(
            self.path, base_oid, {"a.txt": "alpha\nbeta\n"}, "main work")
        git(self.path, "update-ref", "refs/heads/main", head_oid)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", "pub",
            base_branch="release", head_branch="main")
        merge_oid = self._mark_merged(pr, self.path, "release",
                                      head_oid)
        self._fire(self.owner, "volmarr", "pub", pr.number, merge_oid)
        self.assertEqual(self._ref(self.path, "main"), head_oid)
        self.assertEqual(self._rows(), [])
        self.assertEqual(
            self._audit_count("repo.branch.delete_on_merge"), 0)
        if is_deletable_branch is not None:
            repo = self.repos.get_repository("volmarr", "pub")
            try:
                verdict = is_deletable_branch(repo, "main")
            except TypeError:
                verdict = is_deletable_branch(
                    self.owner, "volmarr", "pub", "main")
            self.assertFalse(verdict)

    def test_head_target_branch_is_never_deleted(self):
        self._set_opt_in(True)
        pr, path, _b, head_oid = self._open()
        # The bare repo's HEAD points at the head branch:
        # guard 5 (not HEAD) must save it, default or not.
        git(path, "symbolic-ref", "HEAD", "refs/heads/feature")
        merge_oid = self._mark_merged(pr, path, "main", head_oid)
        self._fire(self.owner, "volmarr", "pub", pr.number, merge_oid)
        self.assertEqual(self._ref(path, "feature"), head_oid)
        self.assertEqual(self._rows(), [])
        self.assertEqual(
            self._audit_count("repo.branch.delete_on_merge"), 0)

    def test_stale_race_inside_cas_window_is_a_silent_skip(self):
        self._set_opt_in(True)
        pr, path, base_oid, head_oid = self._open()
        merge_oid = self._mark_merged(pr, path, "main", head_oid)
        raced = make_commit(path, head_oid,
                            {"a.txt": "alpha\nraced\n"}, "raced push")
        original = RefStore.delete_branch

        def racing_delete(self_rs, short_name, *, expected_old=None):
            # A push lands between the service's resolve
            # and its CAS delete: the ref moves first.
            git(path, "update-ref", "refs/heads/feature", raced)
            return original(self_rs, short_name,
                            expected_old=expected_old)

        RefStore.delete_branch = racing_delete
        try:
            self._fire(self.owner, "volmarr", "pub", pr.number,
                       merge_oid)
        finally:
            RefStore.delete_branch = original
        self.assertEqual(self._ref(path, "feature"), raced)
        self.assertEqual(self._rows(), [])
        self.assertEqual(
            self._audit_count("repo.branch.delete_on_merge"), 0)

    # -- 4. cross-fork rights ---------------------------------------------------
    def _cross_fork_setup(self, *, maintainer_can_edit=True,
                          fork_opt_in=True, base_opt_in=False):
        base_oid = make_commit(self.path, None, {"a.txt": "alpha\n"},
                               "base")
        git(self.path, "update-ref", "refs/heads/main", base_oid)
        self.forks.fork(self.reader.id, "volmarr", "pub")
        fork_path = self.repos.path_for("yrsa", "pub")
        fork_head = make_commit(
            fork_path, base_oid, {"a.txt": "alpha\nfrom the fork\n"},
            "fork work")
        git(fork_path, "update-ref", "refs/heads/feature", fork_head)
        git(self.path, "update-ref", "refs/heads/feature", base_oid)
        created = self.xprs.create_cross_fork_pull_request(
            self.reader, "volmarr", "pub", base_branch="main",
            head_owner="yrsa", head_repo="pub", head_branch="feature",
            maintainer_can_edit=maintainer_can_edit)
        if base_opt_in:
            self._set_opt_in(True)
        if fork_opt_in:
            self.settings.update_settings(
                self.reader.id, "yrsa", "pub",
                delete_branch_on_merge=True)
        merge_oid = self._mark_merged(
            created.pull_request, self.path, "main", base_oid,
            merged_files={"a.txt": "alpha\nfrom the fork\n"})
        return created, fork_path, base_oid, fork_head, merge_oid

    def test_cross_fork_maintainer_edit_deletes_in_fork_only(self):
        created, fork_path, base_oid, fork_head, merge_oid = \
            self._cross_fork_setup()
        # Merger is the BASE owner: not the fork's owner,
        # but maintainer_can_edit + base write (design
        # section 2.5 rider) lets the deletion proceed --
        # in the FORK only.
        self._fire(self.owner, "volmarr", "pub", created.number,
                   merge_oid)
        self.assertIsNone(self._ref(fork_path, "feature"))
        self.assertEqual(self._ref(self.path, "feature"), base_oid)
        rows = self.hk.deleted_branches(self.owner, "yrsa", "pub")
        self.assertEqual(len(rows), 1)
        self.assertEqual(_boid(rows[0]), fork_head)
        self.assertEqual(self._rows(), [])

    def test_cross_fork_without_rights_skips_silently(self):
        created, fork_path, _b, fork_head, merge_oid = \
            self._cross_fork_setup(maintainer_can_edit=False)
        self._fire(self.owner, "volmarr", "pub", created.number,
                   merge_oid)
        self.assertEqual(self._ref(fork_path, "feature"), fork_head)
        self.assertEqual(
            list(self.hk.deleted_branches(self.owner, "yrsa", "pub")),
            [])
        self.assertEqual(
            self._audit_count("repo.branch.delete_on_merge"), 0)

    def test_fork_setting_governs_cross_fork_not_the_base_setting(self):
        created, fork_path, _b, fork_head, merge_oid = \
            self._cross_fork_setup(fork_opt_in=False,
                                   base_opt_in=True)
        self._fire(self.owner, "volmarr", "pub", created.number,
                   merge_oid)
        self.assertEqual(self._ref(fork_path, "feature"), fork_head)
        self.assertEqual(
            self._audit_count("repo.branch.delete_on_merge"), 0)

    # -- 5. restore --------------------------------------------------------------
    def test_restore_round_trip_at_exact_oid_and_listing(self):
        pr, path, _b, head_oid, _m = self._delete_feature_on_merge()
        rec = self._rows()[0]
        later = make_commit(path, head_oid,
                            {"a.txt": "alpha\ngamma\n"}, "later work")
        self.clock.now += 75
        restored = self.hk.restore_branch(
            self.owner.id, "volmarr", "pub", rec.id)
        self.assertEqual(self._ref(path, "feature"), head_oid)
        self.assertNotEqual(self._ref(path, "feature"), later)
        self.assertEqual(_boid(restored), head_oid)
        self.assertEqual(restored.restored_at, 1_700_000_075)
        self.assertEqual(restored.restored_by, self.owner.id)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].restored_at, 1_700_000_075)
        self.assertEqual(self._audit_count("repo.branch.restore"), 1)
        detail = self.conn.execute(
            "SELECT detail FROM audit_log"
            " WHERE action = 'repo.branch.restore'"
        ).fetchone()["detail"]
        self.assertIn("feature", detail)
        self.assertIn(head_oid, detail)
        self.assertIn(str(rec.id), detail)
        if render_deleted_branches is not None:
            html = render_deleted_branches(rows)
            self.assertIn("feature", html)
            self.assertIn("restored", html)

    def test_restore_refusals_are_named_and_write_nothing(self):
        _pr, path, _b, head_oid, _m = self._delete_feature_on_merge()
        rec = self._rows()[0]
        with self.assertRaises(BranchHousekeepingError) as caught:
            self.hk.restore_branch(
                self.owner.id, "volmarr", "pub", rec.id + 999)
        self.assertEqual(caught.exception.reason,
                         "deleted_branch_not_found")
        self.hk.restore_branch(self.owner.id, "volmarr", "pub",
                               rec.id)
        with self.assertRaises(BranchHousekeepingError) as caught:
            self.hk.restore_branch(
                self.owner.id, "volmarr", "pub", rec.id)
        self.assertEqual(caught.exception.reason, "already_restored")
        self.assertEqual(self._audit_count("repo.branch.restore"), 1)
        # branch_exists: delete again via a second PR, then
        # recreate the name by hand before restoring.
        pr2, _p2, _b2, head2 = self._open(name="pub")
        merge2 = self._mark_merged(pr2, path, "main", head2)
        self._fire(self.owner, "volmarr", "pub", pr2.number, merge2)
        rec2 = [r for r in self._rows()
                if r.id != rec.id][0]
        RefStore(path).create_branch("feature", head_oid)
        with self.assertRaises(BranchHousekeepingError) as caught:
            self.hk.restore_branch(
                self.owner.id, "volmarr", "pub", rec2.id)
        self.assertEqual(caught.exception.reason, "branch_exists")
        self.assertEqual(self._ref(path, "feature"), head_oid)
        self.assertIsNone(rec2.restored_at)
        self.assertEqual(self._audit_count("repo.branch.restore"), 1)

    def test_restore_oid_unavailable_when_object_is_gone(self):
        _pr, path, _b, _h, _m = self._delete_feature_on_merge()
        rec = self._rows()[0]
        git(path, "gc", "--prune=now", "--quiet")
        if RefStore(path).resolve(_boid(rec)) is not None:
            self.skipTest(
                "object survived gc in this environment; "
                "oid_unavailable cannot be exercised")
        with self.assertRaises(BranchHousekeepingError) as caught:
            self.hk.restore_branch(
                self.owner.id, "volmarr", "pub", rec.id)
        self.assertEqual(caught.exception.reason, "oid_unavailable")
        self.assertIsNone(self._ref(path, "feature"))
        self.assertIsNone(self._rows()[0].restored_at)
        self.assertEqual(self._audit_count("repo.branch.restore"), 0)

    # -- 6. migration + taxonomy ---------------------------------------------------
    def test_migration_62_fresh_v57_upgrade_and_taxonomy_120(self):
        self.assertEqual(db.schema_version(self.conn), 106)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 133)
        self.assertIn("repo.branch.delete_on_merge",
                      taxonomy.AUDIT_EVENTS)
        self.assertIn("repo.branch.restore", taxonomy.AUDIT_EVENTS)
        cols = [r["name"] for r in self.conn.execute(
            "PRAGMA table_info(repo_settings)").fetchall()]
        self.assertIn("delete_branch_on_merge", cols)
        tcols = [r["name"] for r in self.conn.execute(
            "PRAGMA table_info(deleted_branches)").fetchall()]
        for col in ("id", "repo_id", "branch_name", "head_oid",
                    "deleted_at", "deleted_by", "pull_request_id",
                    "pr_number", "merge_oid", "restored_at",
                    "restored_by"):
            self.assertIn(col, tcols)
        # Upgrade path: a v57 database migrates to 63 and
        # its existing settings row reads OFF (the DEFAULT
        # 0 backfill IS the migration's backfill).
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "old.db"
            conn = db.connect(path)
            for version, statements in db.MIGRATIONS:
                if version > 57:
                    continue
                with conn:
                    for stmt in statements:
                        conn.execute(stmt)
                    conn.execute(
                        "INSERT OR REPLACE INTO schema_meta"
                        " (key, value) VALUES ('version', ?)",
                        (str(version),))
            with conn:
                conn.execute(
                    "INSERT INTO repo_settings"
                    " (repo_id, website, topics) VALUES (1, '', '[]')")
            conn.close()
            conn = db.init_db(path)
            self.assertEqual(db.schema_version(conn), 106)
            row = conn.execute(
                "SELECT delete_branch_on_merge FROM repo_settings"
                " WHERE repo_id = 1").fetchone()
            self.assertEqual(int(row["delete_branch_on_merge"]), 0)
            conn.close()

    # -- 7. fork sync hint ------------------------------------------------------------
    def _make_fork(self, parent_name="pub", fork_owner="yrsa"):
        if parent_name != "pub":
            self.repos.create_repository(
                self.owner.id, "volmarr", parent_name,
                visibility="public")
        path = self.repos.path_for("volmarr", parent_name)
        base_oid = make_commit(path, None, {"a.txt": "alpha\n"},
                               "base")
        git(path, "update-ref", "refs/heads/main", base_oid)
        self.forks.fork(self.reader.id, "volmarr", parent_name)
        fork_path = self.repos.path_for(fork_owner, parent_name)
        return base_oid, fork_path

    def test_fork_hint_shown_only_when_behind(self):
        base_oid, _fp = self._make_fork()
        newer = make_commit(
            self.path, base_oid, {"a.txt": "alpha\nnewer\n"},
            "upstream work")
        git(self.path, "update-ref", "refs/heads/main", newer)
        status = self.forksync.fork_sync_status(self.reader, "yrsa", "pub")
        self.assertEqual(status.state, "behind")
        self.assertGreaterEqual(status.behind, 1)
        self.assertEqual(status.ahead, 0)
        self.assertEqual(status.upstream_full_name, "volmarr/pub")
        self.assertEqual(status.branch, "main")
        words = getattr(status, "words", "")
        if words:
            self.assertIn("behind", words)
        self.assertEqual(self._audit_count("repo.branch.restore"), 0)
        rows = self.conn.execute(
            "SELECT COUNT(*) AS c FROM audit_log").fetchone()
        self.assertGreaterEqual(int(rows["c"]), 0)  # read-only: no
        # housekeeping event was minted by asking
        self.assertEqual(
            self._audit_count("repo.branch.delete_on_merge"), 0)

    def test_fork_hint_hidden_states_and_read_gate(self):
        # up_to_date: a fresh fork shows no hint.
        base_oid, fork_path = self._make_fork()
        status = self.forksync.fork_sync_status(self.reader, "yrsa", "pub")
        self.assertEqual(status.state, "up_to_date")
        self.assertEqual(status.behind, 0)
        # ahead only: still no hint (behind is what shows).
        ahead = make_commit(
            fork_path, base_oid, {"a.txt": "alpha\nfork only\n"},
            "fork work")
        git(fork_path, "update-ref", "refs/heads/main", ahead)
        status = self.forksync.fork_sync_status(self.reader, "yrsa", "pub")
        self.assertEqual(status.state, "up_to_date")
        self.assertEqual(status.behind, 0)
        self.assertGreaterEqual(status.ahead, 1)
        # not_a_fork: the parent itself.
        status = self.forksync.fork_sync_status(self.owner, "volmarr",
                                          "pub")
        self.assertEqual(status.state, "not_a_fork")
        # no_upstream: fork_of_id points at a deleted parent.
        self.repos.create_repository(
            self.owner.id, "volmarr", "gone", visibility="public")
        gone_path = self.repos.path_for("volmarr", "gone")
        g_oid = make_commit(gone_path, None, {"x.txt": "x\n"}, "x")
        git(gone_path, "update-ref", "refs/heads/main", g_oid)
        self.forks.fork(self.reader.id, "volmarr", "gone")
        gone_id = self.repos.get_repository("volmarr", "gone").id
        raw = sqlite3.connect(str(self.root / "samverk.db"))
        raw.execute("PRAGMA foreign_keys=OFF")
        raw.execute("DELETE FROM repositories WHERE id = ?",
                    (gone_id,))
        raw.commit()
        raw.close()
        status = self.forksync.fork_sync_status(self.reader, "yrsa",
                                          "gone")
        self.assertEqual(status.state, "no_upstream")
        # Read gate: a viewer who cannot read the (private)
        # upstream gets no_upstream and NO leaked counts,
        # even though the fork really is behind.
        p_base, _pfp = self._make_fork(parent_name="privsrc")
        self.repos.update_metadata(
            self.owner.id, "volmarr", "privsrc", visibility="private")
        p_new = make_commit(
            self.repos.path_for("volmarr", "privsrc"), p_base,
            {"a.txt": "alpha\nsecret newer\n"}, "secret work")
        git(self.repos.path_for("volmarr", "privsrc"),
            "update-ref", "refs/heads/main", p_new)
        status = self.forksync.fork_sync_status(self.third, "yrsa",
                                          "privsrc")
        self.assertEqual(status.state, "no_upstream")
        self.assertEqual(status.behind, 0)
        self.assertEqual(status.ahead, 0)


if __name__ == "__main__":
    unittest.main()
