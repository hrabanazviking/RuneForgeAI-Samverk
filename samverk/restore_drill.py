"""Restore drill (S-342).

Roadmap S-342: **export restored onto a scratch instance;
repos clone, users sign in, counts match the manifest;
the drill is a test, not a hope.**

S-341 exports the whole instance into one verified archive
(``samverk-instance-export/1``). This slice proves the
other half of that promise: the archive actually restores.

The drill, end to end against real seams:

1. The archive is re-verified with S-341's ``verify_export``
   before a single byte is trusted; an unverified archive
   restores nothing.
2. The database snapshot lands in a *fresh* scratch data
   root (the drill refuses a non-empty destination: a
   restore over a live instance is not a drill) and is
   opened there; its schema must equal the manifest's.
3. Every included repository is rebuilt from its S-074
   bundle through the S-014 local-clone seam, and its LFS
   objects are re-stored through the S-060 store, which
   re-hashes every object on the way in.
4. Proof, not hope: every restored repository is cloned
   *again* from the restored instance and its default-
   branch tip must equal the tip recorded in the S-074
   metadata inside the archive; a restored user signs in
   through the real S-027 ``LoginService`` and the session
   must resolve back to that user.
5. Counts are compared exactly -- repositories restored,
   LFS objects restored, users in the restored database
   against users counted in the archive's own database
   snapshot, repository rows, and archive members against
   the manifest's entries. Every mismatch is reported
   *by name*; nothing is rounded away.

Secrets are the honest remainder. S-341 deliberately
excludes secret values and the TLS private key, so a
restored instance cannot invent them: the drill report
names each one as an operator step (re-provide this secret,
re-provision that key file) from the manifest's exclusions
and the exported config's secret *names* -- names only,
never values, never silently invented.

The judgements are pure. ``compare_drill_counts`` judges
plain counts against a manifest and writes nothing;
``operator_steps`` turns a manifest plus its exported
config document into the named re-provisioning steps and
writes nothing. The service acts on the judgements.
No migration and no new taxonomy event: the schema stands
at 139 and the taxonomy stands at 138.
"""
from __future__ import annotations
import io, json, sqlite3, tarfile, time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from .accounts import AccountStore
from .db import connect, schema_version
from .escaping import escape_html_text
from .lfs_store import LFSError, LFSStore
from .login import LoginFailed, LoginService
from .proc import run_git_clone_local
from .refs import RefStore
from .repositories import RepositoryStore
from .sessions import SessionStore
from .whole_instance_export import MANIFEST_NAME, verify_export

class RestoreDrillError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message); self.reason = reason

@dataclass(frozen=True)
class ObservedCounts:
    repos: int; lfs_objects: int; users: int; members: int; repos_in_db: int

def compare_drill_counts(manifest: dict, observed: ObservedCounts,
                         expected_users: int) -> list[str]:
    """Judge observed restore counts against the manifest.
    Pure. Every mismatch is a named problem; an empty list
    is the only pass. Users are judged against the count
    taken from the archive's own database snapshot (the
    manifest carries no user count, so the snapshot -- a
    manifest-verified member -- is the honest source)."""
    problems: list[str] = []
    want_repos = len(manifest.get("repos_included", []))
    if observed.repos != want_repos:
        problems.append(f"repos: manifest includes {want_repos}, "
                        f"the restore holds {observed.repos}")
    want_lfs = int(manifest.get("lfs_objects", 0))
    if observed.lfs_objects != want_lfs:
        problems.append(f"lfs_objects: manifest says {want_lfs}, "
                        f"the restore holds {observed.lfs_objects}")
    if observed.users != expected_users:
        problems.append(f"users: the archive database snapshot holds "
                        f"{expected_users}, the restore holds {observed.users}")
    want_rows = want_repos + len(manifest.get("repos_excluded", []))
    if observed.repos_in_db != want_rows:
        problems.append(f"repos_in_db: manifest accounts for {want_rows} "
                        f"repository rows, the restored database "
                        f"holds {observed.repos_in_db}")
    want_members = len(manifest.get("entries", [])) + 1
    if observed.members != want_members:
        problems.append(f"members: manifest lists "
                        f"{len(manifest.get('entries', []))} entries plus "
                        f"itself ({want_members}), the archive holds "
                        f"{observed.members}")
    return problems

def operator_steps(manifest: dict, config_doc: dict | None) -> list[str]:
    """The named re-provisioning steps a restored instance
    needs, judged purely from the manifest's exclusions and
    the exported config's secret *names*. S-341 never
    exports secret values or the TLS private key, so the
    drill names what an operator must re-provide -- it
    never invents a value and never stays silent."""
    steps: list[str] = []
    def add(step: str):
        if step not in steps: steps.append(step)
    for entry in manifest.get("excluded", []):
        name, reason = entry.get("name", ""), entry.get("reason", "")
        if reason == "tls_private_key_never_exported":
            add(f"Re-provision the TLS private key ({name.removeprefix('config:')}) "
                f"on the restored instance; the key was never exported.")
        elif reason == "secret_file_values_never_exported":
            add(f"Re-provide the secrets file ({name.removeprefix('config:')}) "
                f"on the restored instance; its values were never exported.")
    cfg = config_doc or {}
    for name in cfg.get("secret_names", []):
        add(f"Re-provide secret {name} on the restored instance; "
            f"only its name was exported, never its value.")
    if cfg.get("tls_key_file") and not any("TLS private key" in s for s in steps):
        add(f"Re-provision the TLS private key ({cfg['tls_key_file']}) "
            f"on the restored instance; the key was never exported.")
    return steps

@dataclass
class DrillReport:
    ok: bool
    archive_path: Path
    scratch_root: Path
    problems: list[str] = field(default_factory=list)
    repos_restored: int = 0
    lfs_objects: int = 0
    users: int = 0
    members_checked: int = 0
    clones: dict = field(default_factory=dict)
    signed_in_as: str | None = None
    operator_steps: tuple = ()
    @property
    def headline(self) -> str:
        if self.ok:
            return (f"restore drill passed: {self.repos_restored} "
                    f"repositories cloned, {self.lfs_objects} LFS objects, "
                    f"{self.users} users, {self.members_checked} manifest "
                    f"members -- all counts match the manifest exactly")
        return (f"restore drill FAILED: {len(self.problems)} problems "
                f"({'; '.join(self.problems[:3])})")

def _read_members(archive_path: Path) -> dict[str, bytes]:
    with tarfile.open(archive_path, "r:gz") as tar:
        return {m.name: tar.extractfile(m).read()
                for m in tar.getmembers() if m.isfile()}

def _snapshot_counts(db_bytes: bytes, tmp: Path) -> tuple[int, int]:
    snap = tmp / "snapshot.db"; snap.write_bytes(db_bytes)
    conn = sqlite3.connect(str(snap))
    try:
        users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        repos = conn.execute("SELECT COUNT(*) FROM repositories").fetchone()[0]
    finally: conn.close()
    return int(users), int(repos)

class RestoreDrill:
    """Restore one S-341 archive onto a scratch instance
    and prove it: clones, sign-in, exact counts."""
    def __init__(self, time_fn: Callable[[], float] = time.time):
        self._now = time_fn

    def run(self, archive_path: Path, scratch_root: Path,
            signin_username: str | None = None,
            signin_password: str | None = None) -> DrillReport:
        archive_path, scratch = Path(archive_path), Path(scratch_root)
        verdict = verify_export(archive_path)
        if not verdict.ok:
            raise RestoreDrillError(
                "export_unverified",
                "The archive does not verify against its own manifest "
                f"({'; '.join(verdict.problems[:3])}); restoring it "
                "would be a hope, not a drill.")
        if scratch.exists() and any(scratch.iterdir()):
            raise RestoreDrillError(
                "scratch_not_empty",
                "The scratch destination already holds files; a drill "
                "restores onto a fresh instance, never over one.")
        scratch.mkdir(parents=True, exist_ok=True)
        members = _read_members(archive_path)
        manifest = json.loads(members[MANIFEST_NAME].decode("utf-8"))
        problems: list[str] = []
        tmp = scratch / ".drill-tmp"; tmp.mkdir()
        db_bytes = members.get("database/samverk.db")
        if db_bytes is None:
            raise RestoreDrillError("no_database", "The archive holds "
                                    "no database member to restore.")
        expected_users, _ = _snapshot_counts(db_bytes, tmp)
        (scratch / "samverk.db").write_bytes(db_bytes)
        conn = connect(scratch / "samverk.db")
        try:
            if schema_version(conn) != int(manifest.get("schema_version", -1)):
                problems.append(
                    f"schema: manifest says {manifest.get('schema_version')}, "
                    f"the restored database is {schema_version(conn)}")
            accounts = AccountStore(conn)
            repos_store = RepositoryStore(conn, scratch, accounts)
            included = list(manifest.get("repos_included", []))
            meta: dict[str, dict] = {}
            for full in included:
                owner, name = full.split("/", 1)
                stem = f"{owner.lower()}-{name.lower()}"
                raw = members.get(f"repos/{stem}.json")
                if raw is not None:
                    meta[full] = json.loads(raw.decode("utf-8"))
                bundle_bytes = members.get(f"repos/{stem}.bundle")
                if bundle_bytes is None:
                    problems.append(f"{full}: listed as included but its "
                                    "bundle is missing from the archive")
                    continue
                bundle_file = tmp / f"{stem}.bundle"
                bundle_file.write_bytes(bundle_bytes)
                dest = repos_store.path_for(owner, name)
                dest.parent.mkdir(parents=True, exist_ok=True)
                result = run_git_clone_local(bundle_file.resolve(),
                                             dest.resolve())
                if result.returncode != 0:
                    problems.append(f"{full}: bundle clone failed: " + result.stderr.decode("utf-8", "replace").strip()[:200])
            lfs_restored = 0
            for entry in manifest.get("entries", []):
                if entry.get("kind") != "lfs_object": continue
                arc = entry["archive_path"]
                stem, oid = arc.split("/")[1], arc.rsplit("/", 1)[-1]
                full = next((f for f in included if f"{f.split('/',1)[0].lower()}-{f.split('/',1)[1].lower()}" == stem), None)
                if full is None:
                    problems.append(f"{arc}: LFS object names no included repository"); continue
                owner, name = full.split("/", 1)
                try:
                    LFSStore(repos_store.path_for(owner, name)).put(oid, members[arc])
                    lfs_restored += 1
                except LFSError as exc:
                    problems.append(f"{arc}: LFS restore refused: {exc}")
            cfg_doc = None
            if "config/config.json" in members:
                cfg_doc = json.loads(members["config/config.json"].decode("utf-8"))
                (scratch / "config.json").write_bytes(members["config/config.json"])
            repos_on_disk = 0; clones: dict[str, str] = {}
            for full in included:
                owner, name = full.split("/", 1)
                path = repos_store.path_for(owner, name)
                if not (path.is_dir() and RefStore(path).list_refs()): continue
                repos_on_disk += 1
                clone_dest = tmp / f"clone-{owner.lower()}-{name.lower()}"
                result = run_git_clone_local(path.resolve(), clone_dest.resolve())
                if result.returncode != 0:
                    problems.append(f"{full}: clone from the restored instance failed"); continue
                branch = meta.get(full, {}).get("default_branch", "main")
                want = meta.get(full, {}).get("refs", {}).get(f"refs/heads/{branch}")
                got = RefStore(clone_dest).resolve(f"refs/heads/{branch}")
                if want is None or got != want:
                    problems.append(f"{full}: cloned tip {got} does not match the archived tip {want}")
                else: clones[full] = got
            users = int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])
            rows = int(conn.execute("SELECT COUNT(*) FROM repositories").fetchone()[0])
            observed = ObservedCounts(repos=repos_on_disk, lfs_objects=lfs_restored,
                                      users=users, members=len(members), repos_in_db=rows)
            problems.extend(compare_drill_counts(manifest, observed, expected_users))
            signed_in_as = None
            if signin_username is None:
                problems.append("sign-in: not attempted -- no credentials supplied, so no restored user was proven to sign in")
            else:
                login = LoginService(conn, accounts, SessionStore(conn), time_fn=self._now)
                try:
                    token = login.login(signin_username, signin_password or "")
                    uid = login.authenticate_session(token)
                    user = accounts.get_by_username(signin_username)
                    if user is not None and uid == user.id:
                        signed_in_as = user.username
                    else:
                        problems.append(f"sign-in: session for {signin_username} did not resolve to that user")
                except LoginFailed:
                    problems.append(f"sign-in: restored user {signin_username} could not sign in")
        finally:
            conn.close()
            import shutil; shutil.rmtree(tmp, ignore_errors=True)
        return DrillReport(ok=not problems, archive_path=archive_path,
            scratch_root=scratch, problems=problems, repos_restored=repos_on_disk,
            lfs_objects=lfs_restored, users=users, members_checked=len(members),
            clones=clones, signed_in_as=signed_in_as,
            operator_steps=tuple(operator_steps(manifest, cfg_doc)))

def render_restore_drill_page(report: DrillReport) -> str:
    parts = ["<h1>Restore drill</h1>", f"<p>{escape_html_text(report.headline)}.</p>"]
    if report.signed_in_as:
        parts.append(f"<p>Restored user {escape_html_text(report.signed_in_as)} signed in on the restored instance.</p>")
    for step in report.operator_steps:
        parts.append(f"<p>Operator step: {escape_html_text(step)}</p>")
    for problem in report.problems:
        parts.append(f"<p>Problem: {escape_html_text(problem)}</p>")
    return "\n".join(parts)
