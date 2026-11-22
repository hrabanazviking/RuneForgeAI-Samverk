"""Upgrades (S-357).

Roadmap S-357: **documented procedure: export (S-341)
-> stop -> migrate -> start -> verify counts; a failed
migration rolls back to the export, rehearsed in the
drill.**

This slice composes the standing seams into the one
upgrade procedure, as judged code plus the written
procedure in docs/UPGRADES.md (the battery pins the
document's steps to the code's steps, in order):

1. **export** -- a whole-instance export (S-341) of the
   instance as it stands, before anything changes.
2. **verify_export** -- the archive is re-verified
   against its own manifest (S-341 ``verify_export``);
   an unverified export is never the rollback point.
3. **stop** -- an operator step in the document and a
   judged precondition in code: the caller must state
   the instance is stopped. This slice stops no real
   service; if the stop is not confirmed, the procedure
   aborts before any change and says so plainly.
4. **migrate** -- pending migrations are applied
   (``db.migrate`` by default; a rehearsal may supply
   its own migration step, applied to that instance
   only). Each real migration already runs in its own
   transaction (S-001 law), and any failure here --
   or later -- triggers the rollback below.
5. **start** -- likewise an operator step / judged
   precondition: the caller confirms the instance is
   started again before counts are trusted.
6. **verify_counts** -- users, repository rows,
   repositories on disk, and LFS objects after the
   migration are judged against the export manifest
   (users against the count taken at export time) by
   the pure ``compare_upgrade_counts``; every mismatch
   is named.

**Rollback.** Any failure at migrate, start, or
verify_counts rolls the instance back to the export:
the data root is cleared and the archive is restored
onto it through the S-342 restore drill (which itself
re-verifies the archive, restores the database
snapshot, rebuilds repositories from their bundles,
re-stores LFS objects, and proves a restored user can
sign in). The report says in plain words that the
upgrade failed and the instance was rolled back -- a
half-migrated instance is never claimed as upgraded.
If the rollback itself fails, that too is named, with
the drill's problems, and the export archive is kept:
it is the operator's road back.

The export destination must stand outside the data
root: a rollback clears the data root, and an archive
inside it would be cleared with it.

No migration of this slice's own and no new taxonomy
event: the schema stands at 140 and the taxonomy
stands at 142 (coordinator pin sweep at S-357 banking:
S-355 landed migration 140 and four taxonomy events
after this slice was built). The rehearsed stand-in migration in
the battery raises a *scratch* database to a pretend
141; no such migration ships.
"""
from __future__ import annotations
import json, shutil, sqlite3, time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from . import db
from .accounts import AccountStore
from .config import Config
from .db import schema_version
from .escaping import escape_html_text
from .refs import RefStore
from .repositories import RepositoryStore
from .secrets import Secrets
from .whole_instance_export import WholeInstanceExportService, verify_export

__all__ = ["STEP_GUIDE", "STEP_IDS", "StepGuide", "StepResult",
    "ObservedUpgradeCounts", "UpgradeReport", "UpgradeError",
    "compare_upgrade_counts", "decide_rollback", "decide_start",
    "decide_stop", "export_dest_problem", "plan_upgrade",
    "UpgradeProcedure", "render_upgrade_report"]

@dataclass(frozen=True)
class StepGuide:
    step_id: str; title: str; failure_mode: str; remedy: str

STEP_GUIDE = (
 StepGuide("export", "Export the whole instance (S-341)",
  "export_failed: the export is refused (not an admin, no exportable repository, an LFS object that no longer hashes to its oid, or a destination that already holds an export) -- there is no rollback point, so the upgrade must not begin.",
  "Fix the named cause and re-run from the export step; never start an upgrade without a completed export outside the data root."),
 StepGuide("verify_export", "Verify the export against its manifest",
  "export_unverified: a member is missing, resized, or hashes differently than the manifest -- the archive could not restore the instance, so it cannot be the rollback point.",
  "Discard the bad archive, find why it is corrupt (disk, interrupted write), take a fresh export, and verify it before proceeding."),
 StepGuide("stop", "Stop the instance (operator step, judged precondition)",
  "not_stopped: the operator has not confirmed the instance is stopped -- migrating a live instance could race its writes, so the procedure aborts before changing anything.",
  "Stop the instance by the operator's own road (the service manager or the serve process), confirm it, and re-run; this procedure never stops or starts a real service itself."),
 StepGuide("migrate", "Apply pending migrations",
  "migration_failed: a migration raised mid-way -- the database may hold a half-applied change, so the procedure rolls back to the export and reports the failure in plain words.",
  "Read the named migration error, fix the migration or the data it tripped on, and start the whole procedure again from a fresh export; never hand-finish a half migration."),
 StepGuide("start", "Start the instance (operator step, judged precondition)",
  "not_started: the operator has not confirmed the instance started again after migration -- counts taken against a stopped instance would prove nothing about the serving instance, so the procedure rolls back.",
  "Start the instance by the operator's own road; if it will not start, the rollback has already restored the pre-upgrade instance -- start that and read its logs."),
 StepGuide("verify_counts", "Verify counts against the export manifest",
  "counts_mismatch: users, repository rows, repositories on disk, or LFS objects after migration differ from the export manifest -- the migration changed content it should not have, so the procedure rolls back.",
  "Read the named mismatches; they are the migration's unintended effects. Fix the migration and start again from a fresh export."),
)
STEP_IDS = tuple(g.step_id for g in STEP_GUIDE)
_GUIDE = {g.step_id: g for g in STEP_GUIDE}

class UpgradeError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message); self.reason = reason

@dataclass(frozen=True)
class StepResult:
    step_id: str; ok: bool; detail: str; elapsed_seconds: float = 0.0; state: str = ""
    @property
    def failure_mode(self) -> str: return _GUIDE[self.step_id].failure_mode
    @property
    def remedy(self) -> str: return _GUIDE[self.step_id].remedy

def plan_upgrade() -> tuple[str, ...]:
    """The procedure's steps, in order. Pure."""
    return STEP_IDS

def decide_stop(stopped: object) -> tuple[bool, str]:
    if stopped is True: return True, "instance confirmed stopped by the operator"
    return False, "not_stopped: the instance has not been confirmed stopped; the upgrade aborts before changing anything"

def decide_start(started: object) -> tuple[bool, str]:
    if started is True: return True, "instance confirmed started by the operator"
    return False, "not_started: the instance has not been confirmed started after migration"

def decide_rollback(failed_step: str | None) -> bool:
    """Pure: a failure at or after migrate rolls back;
    a failure before it changed nothing, so there is
    nothing to roll back (the export is kept)."""
    return failed_step in ("migrate", "start", "verify_counts")

def export_dest_problem(data_root: Path, dest_dir: Path) -> str | None:
    """Pure judgement on plain paths: the export must
    stand outside the data root, because a rollback
    clears the data root."""
    root, dest = Path(data_root).resolve(), Path(dest_dir).resolve()
    if dest == root or root in dest.parents:
        return ("export_inside_data_root: the export destination is "
                "inside the data root; a rollback clears the data "
                "root and would destroy the rollback point itself")
    return None

@dataclass(frozen=True)
class ObservedUpgradeCounts:
    repos: int; repos_in_db: int; lfs_objects: int; users: int; schema: int

def compare_upgrade_counts(manifest: dict, observed: ObservedUpgradeCounts,
                           expected_users: int,
                           expected_schema: int) -> list[str]:
    """Judge post-upgrade counts against the export
    manifest. Pure. Users judge against the count taken
    at export time (the manifest carries no user count);
    schema judges against the version the migration
    step reported. Every mismatch is named."""
    problems: list[str] = []
    want_repos = len(manifest.get("repos_included", []))
    if observed.repos != want_repos:
        problems.append(f"repos: manifest includes {want_repos}, the upgraded instance holds {observed.repos} on disk")
    want_rows = want_repos + len(manifest.get("repos_excluded", []))
    if observed.repos_in_db != want_rows:
        problems.append(f"repos_in_db: manifest accounts for {want_rows} repository rows, the upgraded database holds {observed.repos_in_db}")
    want_lfs = int(manifest.get("lfs_objects", 0))
    if observed.lfs_objects != want_lfs:
        problems.append(f"lfs_objects: manifest says {want_lfs}, the upgraded instance holds {observed.lfs_objects}")
    if observed.users != expected_users:
        problems.append(f"users: the export was taken with {expected_users} users, the upgraded database holds {observed.users}")
    if observed.schema != expected_schema:
        problems.append(f"schema: migration reported {expected_schema}, the upgraded database is {observed.schema}")
    return problems

@dataclass
class UpgradeReport:
    ok: bool
    steps: list[StepResult] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    failed_step: str | None = None
    rolled_back: bool = False
    rollback_problems: list[str] = field(default_factory=list)
    archive_path: Path | None = None
    manifest_path: Path | None = None
    schema_before: int = 0
    schema_after: int = 0
    elapsed_seconds: float = 0.0
    def step(self, step_id: str) -> StepResult | None:
        for s in self.steps:
            if s.step_id == step_id: return s
        return None
    @property
    def headline(self) -> str:
        if self.ok:
            return (f"upgrade complete: export verified, migrations "
                    f"applied (schema {self.schema_before} -> "
                    f"{self.schema_after}), counts match the export manifest")
        if self.rolled_back:
            return (f"upgrade FAILED at the {self.failed_step} step and "
                    f"the instance was rolled back to the export: it "
                    f"stands exactly as it stood before the upgrade, "
                    f"not half-migrated ({'; '.join(self.problems[:2])})")
        if self.rollback_problems:
            return (f"upgrade FAILED at the {self.failed_step} step and "
                    f"the rollback did NOT complete: the export archive "
                    f"is kept and is the operator's road back "
                    f"({'; '.join(self.rollback_problems[:2])})")
        return (f"upgrade did not proceed: it stopped at the "
                f"{self.failed_step} step before changing anything "
                f"({'; '.join(self.problems[:2])})")

class UpgradeProcedure:
    """Run the S-357 procedure once over one instance.
    The stop/start steps are judged preconditions only:
    this class stops and starts no real service."""
    def __init__(self, conn: sqlite3.Connection, data_root: Path,
                 accounts: AccountStore, repositories: RepositoryStore,
                 config: Config | None = None,
                 secrets: Secrets | None = None,
                 time_fn: Callable[[], float] = time.time):
        self._conn = conn; self._data_root = Path(data_root)
        self._accounts = accounts; self._repos = repositories
        self._config = config; self._secrets = secrets; self._now = time_fn
    @property
    def conn(self) -> sqlite3.Connection: return self._conn
    @property
    def accounts(self) -> AccountStore: return self._accounts
    @property
    def repositories(self) -> RepositoryStore: return self._repos

    def _observed(self, manifest: dict) -> ObservedUpgradeCounts:
        repos_on_disk = 0; lfs = 0
        for full in manifest.get("repos_included", []):
            owner, name = full.split("/", 1)
            path = self._repos.path_for(owner, name)
            if path.is_dir() and RefStore(path).list_refs():
                repos_on_disk += 1
            objects = path / "lfs" / "objects"
            if objects.is_dir():
                lfs += sum(1 for p in objects.rglob("*") if p.is_file())
        users = int(self._conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])
        rows = int(self._conn.execute("SELECT COUNT(*) FROM repositories").fetchone()[0])
        return ObservedUpgradeCounts(repos=repos_on_disk, repos_in_db=rows,
            lfs_objects=lfs, users=users, schema=schema_version(self._conn))

    def _rollback(self, archive_path: Path, username: str | None,
                  password: str | None) -> list[str]:
        """Restore the export onto the data root through
        the S-342 drill. Returns named problems; an empty
        list means the instance stands as exported."""
        from .restore_drill import RestoreDrill, RestoreDrillError
        try: self._conn.close()
        except Exception: pass
        root = self._data_root
        for child in list(root.iterdir()):
            if child.is_dir() and not child.is_symlink(): shutil.rmtree(child)
            else: child.unlink()
        try:
            report = RestoreDrill(time_fn=self._now).run(
                archive_path, root, username, password)
        except RestoreDrillError as exc:
            return [f"{exc.reason}: {exc}"]
        self._conn = db.connect(root / "samverk.db")
        self._accounts = AccountStore(self._conn)
        self._repos = RepositoryStore(self._conn, root, self._accounts)
        if not report.ok: return list(report.problems)
        return []

    def run(self, actor_user_id: int, export_dest: Path, *,
            stopped: bool = False, started: bool = False,
            migration_fn: Callable[[sqlite3.Connection], int | None] | None = None,
            signin_username: str | None = None,
            signin_password: str | None = None) -> UpgradeReport:
        total_start = self._now()
        report = UpgradeReport(ok=False, schema_before=schema_version(self._conn),
                               schema_after=schema_version(self._conn))
        def record(step_id, ok, detail, state=""):
            report.steps.append(StepResult(step_id, ok, detail, 0.0, state))
            if not ok and report.failed_step is None:
                report.failed_step = step_id; report.problems.append(detail)
            return ok
        def finish() -> UpgradeReport:
            report.elapsed_seconds = round(self._now() - total_start, 4)
            report.schema_after = schema_version(self._conn)
            return report
        def fail_and_maybe_roll_back() -> UpgradeReport:
            if decide_rollback(report.failed_step):
                assert report.archive_path is not None
                problems = self._rollback(report.archive_path,
                    signin_username, signin_password)
                if problems: report.rollback_problems = problems
                else: report.rolled_back = True
            return finish()
        # export
        problem = export_dest_problem(self._data_root, Path(export_dest))
        if problem is not None:
            record("export", False, problem, "export_inside_data_root"); return finish()
        service = WholeInstanceExportService(self._conn, self._data_root,
            self._accounts, self._repos, config=self._config,
            secrets=self._secrets, time_fn=self._now)
        try:
            export = service.export_instance(actor_user_id, Path(export_dest))
        except Exception as exc:
            reason = getattr(exc, "reason", type(exc).__name__)
            record("export", False, f"{reason}: {exc}", str(reason)); return finish()
        report.archive_path = export.archive_path; report.manifest_path = export.manifest_path
        record("export", True, export.headline)
        manifest = json.loads(export.manifest_path.read_text(encoding="utf-8"))
        expected_users = int(self._conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])
        # verify export
        verdict = verify_export(export.archive_path)
        if not record("verify_export", verdict.ok, verdict.headline,
                      "" if verdict.ok else "export_unverified"):
            return finish()
        # stop (judged precondition only; no service action)
        ok, detail = decide_stop(stopped)
        if not record("stop", ok, detail, "" if ok else "not_stopped"):
            return finish()
        # migrate
        try:
            result = migration_fn(self._conn) if migration_fn is not None else db.migrate(self._conn)
            new_schema = int(result) if result is not None else schema_version(self._conn)
        except Exception as exc:
            record("migrate", False, f"migration_failed: {type(exc).__name__}: {exc}", "migration_failed")
            return fail_and_maybe_roll_back()
        record("migrate", True, f"migrations applied; schema {report.schema_before} -> {new_schema}")
        # start (judged precondition only)
        ok, detail = decide_start(started)
        if not record("start", ok, detail, "" if ok else "not_started"):
            return fail_and_maybe_roll_back()
        # verify counts
        problems = compare_upgrade_counts(manifest, self._observed(manifest),
                                          expected_users, new_schema)
        if problems:
            record("verify_counts", False, "counts_mismatch: " + "; ".join(problems), "counts_mismatch")
            report.problems = problems
            return fail_and_maybe_roll_back()
        record("verify_counts", True, "counts match the export manifest exactly")
        report.ok = True
        return finish()

def render_upgrade_report(report: UpgradeReport) -> str:
    lines = ["<h1>Upgrade</h1>", f"<p>{escape_html_text(report.headline)}.</p>"]
    for s in report.steps:
        mark = "ok" if s.ok else "FAILED"
        lines.append(f"<p>[{mark}] {escape_html_text(_GUIDE[s.step_id].title)}: {escape_html_text(s.detail)}</p>")
        if not s.ok:
            lines.append(f"<p>Failure: {escape_html_text(s.failure_mode)}</p>")
            lines.append(f"<p>Remedy: {escape_html_text(s.remedy)}</p>")
    if report.archive_path is not None:
        lines.append(f"<p>Export archive: {escape_html_text(report.archive_path.name)} (kept).</p>")
    return "\n".join(lines)
