"""Whole-instance export (S-341).

Roadmap S-341: **one archive: all bare repos, LFS store,
database, and config, with a manifest and checksums
(built on S-074).**

S-074 exports one repository (a verified git bundle plus
its metadata JSON). This slice exports the whole instance
into a single ``.tar.gz`` archive:

- **Repositories** ride S-074 unchanged: every repository
  with refs becomes a verified bundle plus its S-074
  metadata JSON inside the archive. A repository that
  cannot be bundled honestly -- empty (git bundle refuses
  an empty bundle) or missing on disk (the S-071 drift) --
  is never faked: it is named in the manifest's
  ``excluded`` list with its reason, and the export still
  succeeds for the rest. An instance with no exportable
  repository at all is refused outright: an archive of
  nothing is not a backup.
- **The LFS store** (S-060) does not ride git bundles, so
  every LFS object of every exported repository is copied
  in under ``lfs/<owner>-<repo>/<oid>`` and re-hashed on
  the way in: an object whose bytes no longer hash to its
  oid fails the whole export rather than shipping corrupt.
- **The database** is a consistent snapshot taken through
  SQLite's backup API, never a raw copy of a live file.
- **Config** is exported as values, never secrets: the
  boot configuration (S-002) is written as JSON, the
  instance config file is included when one sits in the
  data root, and a TLS certificate (public material) is
  included when configured. What the S-003 law holds back
  is named in ``excluded``, never silently dropped and
  never exported in plaintext: the secrets file (only the
  *names* of loaded secrets are listed, never a value),
  the TLS private key, and any ``secrets.env`` in the
  data root.
- **The manifest** (``manifest.json``, also written as a
  sidecar beside the archive) lists exactly what went in:
  every archive member with its kind, byte count, and
  SHA-256, plus every exclusion with its reason, plus the
  instance counts. ``verify_export`` re-opens an archive
  and checks every member against the manifest: a missing,
  extra, resized, or re-hashed member is a named problem,
  never a quiet pass.

The gate is the S-074 gate, widened to the instance: an
admin only. A whole-instance archive carries every
repository's entire content, so no lesser gate is honest.

The judgements are pure. ``is_secret_name`` judges one
file name against the S-003 hold-back law;
``plan_instance_export`` chooses included and excluded
repositories from plain facts and writes nothing;
``verify_manifest`` judges a manifest against the bytes
actually present and writes nothing. The service acts on
the judgements. No migration and no new audit event: the
schema stands at 138 and the taxonomy stands at 138.
"""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import tarfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .accounts import AccountStore
from .config import Config
from .db import schema_version
from .escaping import escape_html_text
from .lfs_store import oid_for
from .refs import RefStore
from .repo_backup import BackupError, RepoBackup
from .repositories import Repository, RepositoryStore
from .secrets import Secrets

FORMAT = "samverk-instance-export/1"
MANIFEST_NAME = "manifest.json"

KIND_BUNDLE = "repo_bundle"
KIND_REPO_META = "repo_metadata"
KIND_LFS = "lfs_object"
KIND_DATABASE = "database"
KIND_CONFIG = "config"
KIND_CERT = "tls_certificate"

# Names the S-003 law never lets into an archive, judged
# purely by name: secret material is identified by what
# it is called before any byte of it is read.
_SECRET_SUFFIXES = (".key", ".pem.key")
_SECRET_NAMES = frozenset({"secrets.env", "secret.env", "secrets"})


class WholeInstanceExportError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_secret_name(name: object) -> bool:
    """One file name judged purely against the S-003
    hold-back law: secrets files and private-key files
    are never archive material, whatever directory they
    were found in. Certificates (``.crt``/``.pem`` without
    the key marker) are public material and pass."""
    if not isinstance(name, str) or not name:
        return False
    base = name.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if base in _SECRET_NAMES:
        return True
    if base.endswith(_SECRET_SUFFIXES):
        return True
    return "private" in base and base.endswith(".pem")


@dataclass(frozen=True)
class RepoFact:
    """The plain facts the plan judges for one repo."""
    full_name: str
    owner: str
    name: str
    on_disk: bool
    has_refs: bool


@dataclass(frozen=True)
class ExportPlan:
    included: tuple[RepoFact, ...]
    excluded: tuple[tuple[str, str], ...]  # (full_name, reason)


def plan_instance_export(facts: list[RepoFact]) -> ExportPlan:
    """Choose the export's repositories from plain facts.
    Pure. A repository takes part only when it stands on
    disk with at least one ref (the S-074 bundle law);
    every other repository is excluded *by name*, with
    the reason a restore operator needs. Name order, so
    the manifest reads the same on every run."""
    included, excluded = [], []
    for fact in sorted(facts, key=lambda f: f.full_name.lower()):
        if not fact.on_disk:
            excluded.append((fact.full_name, "repo_missing_on_disk"))
        elif not fact.has_refs:
            excluded.append((fact.full_name, "repo_empty"))
        else:
            included.append(fact)
    return ExportPlan(tuple(included), tuple(excluded))


@dataclass(frozen=True)
class ManifestEntry:
    archive_path: str
    kind: str
    sha256: str
    size: int
    detail: str = ""


def verify_manifest(manifest: dict,
                      members: dict[str, bytes]) -> list[str]:
    """Judge a manifest against the bytes actually
    present. Pure. Returns the named problems: a listed
    member missing, resized, or hashing differently, and
    any member present that the manifest never listed
    (the manifest itself excepted). An empty list is the
    only pass."""
    problems: list[str] = []
    listed = set()
    for entry in manifest.get("entries", []):
        path = entry.get("archive_path", "")
        listed.add(path)
        data = members.get(path)
        if data is None:
            problems.append(f"{path}: listed in the manifest but missing")
            continue
        if len(data) != entry.get("bytes"):
            problems.append(
                f"{path}: manifest says {entry.get('bytes')} bytes, "
                f"the archive holds {len(data)}")
        elif sha256_bytes(data) != entry.get("sha256"):
            problems.append(f"{path}: checksum does not match the manifest")
    for path in sorted(members):
        if path != MANIFEST_NAME and path not in listed:
            problems.append(f"{path}: in the archive but not in the manifest")
    return problems


@dataclass(frozen=True)
class InstanceExport:
    archive_path: Path
    manifest_path: Path
    archive_sha256: str
    archive_bytes: int
    exported_at: int
    repos_included: int
    repos_excluded: int
    lfs_objects: int
    entries: int

    @property
    def headline(self) -> str:
        return (f"whole-instance export: {self.repos_included} "
                f"repositories, {self.lfs_objects} LFS objects, "
                f"{self.entries} archive members, "
                f"{self.repos_excluded} repositories excluded by name")


@dataclass
class ExportVerification:
    ok: bool
    problems: list[str] = field(default_factory=list)
    entries_checked: int = 0
    repos_included: int = 0
    repos_excluded: int = 0

    @property
    def headline(self) -> str:
        if self.ok:
            return (f"export verified: {self.entries_checked} members "
                    f"match the manifest exactly")
        return (f"export NOT verified: {len(self.problems)} problems "
                f"({'; '.join(self.problems[:3])})")


class WholeInstanceExportService:
    def __init__(self, conn: sqlite3.Connection, data_root: Path,
                 accounts: AccountStore, repositories: RepositoryStore,
                 config: Config | None = None,
                 secrets: Secrets | None = None,
                 time_fn: Callable[[], float] = time.time):
        self._conn = conn
        self._data_root = Path(data_root)
        self._accounts = accounts
        self._repos = repositories
        self._config = config
        self._secrets = secrets
        self._now = time_fn
        self._backup = RepoBackup(conn, data_root, accounts, repositories,
                                  time_fn=time_fn)

    # -- facts -----------------------------------------------------
    def _all_repositories(self) -> list[Repository]:
        rows = self._conn.execute(
            "SELECT * FROM repositories ORDER BY owner_lower, name_lower"
        ).fetchall()
        from .repositories import _row_to_repo
        return [_row_to_repo(r) for r in rows]

    def _fact(self, repo: Repository) -> RepoFact:
        path = self._repos.path_for(repo.owner, repo.name)
        on_disk = path.is_dir()
        has_refs = bool(on_disk and RefStore(path).list_refs())
        return RepoFact(full_name=repo.full_name, owner=repo.owner,
                        name=repo.name, on_disk=on_disk, has_refs=has_refs)

    def _lfs_objects(self, repo: Repository) -> list[tuple[str, Path]]:
        """(oid, path) for every LFS object of one repo,
        in oid order. A file under the store whose name is
        not its oid is drift, named and refused -- never
        silently carried into a backup."""
        root = self._repos.path_for(repo.owner, repo.name) / "lfs" / "objects"
        if not root.is_dir():
            return []
        found = []
        for path in sorted(root.rglob("*")):
            if path.is_file():
                found.append((path.name, path))
        return found

    # -- the export --------------------------------------------------
    def export_instance(self, actor_user_id: int,
                        dest_dir: Path) -> InstanceExport:
        actor = self._accounts.get_by_id(actor_user_id)
        if actor is None:
            raise WholeInstanceExportError(
                "no_such_user", "No such account.")
        if not actor.is_admin:
            raise WholeInstanceExportError(
                "permission_denied",
                "Whole-instance exports are for admins: the archive "
                "carries every repository's entire content.")
        repos = self._all_repositories()
        plan = plan_instance_export([self._fact(r) for r in repos])
        if not plan.included:
            raise WholeInstanceExportError(
                "nothing_to_export",
                "No repository in this instance can be exported "
                "(all are empty or missing on disk); an archive of "
                "nothing would be a false backup.")
        by_name = {r.full_name: r for r in repos}
        now = int(self._now())
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        archive_path = dest / f"samverk-instance-{now}.tar.gz"
        manifest_path = dest / f"samverk-instance-{now}.manifest.json"
        if archive_path.exists() or manifest_path.exists():
            raise WholeInstanceExportError(
                "export_exists",
                "An export already sits at that destination; refusing "
                "to overwrite a backup silently.")
        import tempfile
        staging = Path(tempfile.mkdtemp(prefix="samverk-export-",
                                        dir=str(dest)))
        entries: list[ManifestEntry] = []
        excluded: list[dict] = [
            {"name": name, "reason": reason}
            for name, reason in plan.excluded]
        members: list[tuple[str, Path]] = []
        lfs_count = 0
        try:
            for fact in plan.included:
                repo = by_name[fact.full_name]
                stem = f"{repo.owner_lower}-{repo.name_lower}"
                try:
                    single = self._backup.export_repo(
                        actor_user_id, repo.owner, repo.name, staging)
                except BackupError as exc:
                    excluded.append({"name": fact.full_name,
                                     "reason": exc.reason})
                    continue
                for src, kind, arc in (
                        (single.bundle_path, KIND_BUNDLE,
                         f"repos/{stem}.bundle"),
                        (single.metadata_path, KIND_REPO_META,
                         f"repos/{stem}.json")):
                    data = src.read_bytes()
                    entries.append(ManifestEntry(
                        arc, kind, sha256_bytes(data), len(data),
                        fact.full_name))
                    members.append((arc, src))
                for oid, obj_path in self._lfs_objects(repo):
                    data = obj_path.read_bytes()
                    if oid_for(data) != oid:
                        raise WholeInstanceExportError(
                            "lfs_corrupt",
                            f"LFS object {oid} of {fact.full_name} no "
                            f"longer hashes to its oid; refusing to "
                            f"ship a corrupt backup.")
                    arc = f"lfs/{stem}/{oid}"
                    entries.append(ManifestEntry(
                        arc, KIND_LFS, sha256_bytes(data), len(data), oid))
                    members.append((arc, obj_path))
                    lfs_count += 1
            included_names = {e.detail for e in entries
                              if e.kind == KIND_BUNDLE}
            if not included_names:
                raise WholeInstanceExportError(
                    "nothing_to_export",
                    "Every repository export failed; no archive was made.")
            repo_excluded_count = len(excluded)
            # Database: a consistent snapshot, never a live copy.
            db_snap = staging / "samverk.db"
            snap_conn = sqlite3.connect(str(db_snap))
            try:
                self._conn.backup(snap_conn)
            finally:
                snap_conn.close()
            data = db_snap.read_bytes()
            entries.append(ManifestEntry(
                "database/samverk.db", KIND_DATABASE,
                sha256_bytes(data), len(data),
                f"schema {schema_version(self._conn)}"))
            members.append(("database/samverk.db", db_snap))
            # Config: values, never secret values (S-002/S-003).
            cfg_doc = self._config_document(excluded)
            cfg_bytes = (json.dumps(cfg_doc, indent=2, sort_keys=True)
                         + "\n").encode("utf-8")
            cfg_file = staging / "config.json"
            cfg_file.write_bytes(cfg_bytes)
            entries.append(ManifestEntry(
                "config/config.json", KIND_CONFIG,
                sha256_bytes(cfg_bytes), len(cfg_bytes), "boot config"))
            members.append(("config/config.json", cfg_file))
            cfg = self._config
            if (cfg is not None and cfg.tls_cert_file is not None
                    and Path(cfg.tls_cert_file).is_file()
                    and not is_secret_name(Path(cfg.tls_cert_file).name)):
                cert = Path(cfg.tls_cert_file)
                data = cert.read_bytes()
                entries.append(ManifestEntry(
                    "config/tls_cert.pem", KIND_CERT,
                    sha256_bytes(data), len(data), "TLS certificate"))
                members.append(("config/tls_cert.pem", cert))
            ini = self._data_root / "samverk.ini"
            if ini.is_file() and not is_secret_name(ini.name):
                data = ini.read_bytes()
                entries.append(ManifestEntry(
                    "config/samverk.ini", KIND_CONFIG,
                    sha256_bytes(data), len(data), "instance config file"))
                members.append(("config/samverk.ini", ini))
            manifest = {
                "format": FORMAT,
                "exported_at": now,
                "schema_version": schema_version(self._conn),
                "repos_included": sorted(included_names),
                "repos_excluded": [e for e in excluded
                                   if not e["name"].startswith("config:")],
                "excluded": excluded,
                "lfs_objects": lfs_count,
                "entries": [
                    {"archive_path": e.archive_path, "kind": e.kind,
                     "sha256": e.sha256, "bytes": e.size,
                     "detail": e.detail}
                    for e in sorted(entries, key=lambda e: e.archive_path)],
            }
            manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True)
                              + "\n").encode("utf-8")
            manifest_path.write_bytes(manifest_bytes)
            with tarfile.open(archive_path, "w:gz") as tar:
                info = tarfile.TarInfo(MANIFEST_NAME)
                info.size = len(manifest_bytes)
                tar.addfile(info, io.BytesIO(manifest_bytes))
                for arc, src in sorted(members, key=lambda m: m[0]):
                    tar.add(str(src), arcname=arc, recursive=False)
        finally:
            import shutil
            shutil.rmtree(staging, ignore_errors=True)
        archive_bytes = archive_path.read_bytes()
        return InstanceExport(
            archive_path=archive_path, manifest_path=manifest_path,
            archive_sha256=sha256_bytes(archive_bytes),
            archive_bytes=len(archive_bytes), exported_at=now,
            repos_included=len(included_names),
            repos_excluded=repo_excluded_count, lfs_objects=lfs_count,
            entries=len(entries) + 1)

    def _config_document(self, excluded: list[dict]) -> dict:
        """The exported config: boot values in the open,
        and every S-003 hold-back named in `excluded` with
        its reason. Secret *names* may be listed (an
        operator restoring the instance must know which
        secrets to re-provide); secret values never are."""
        cfg = self._config or Config(data_root=self._data_root)
        doc = {
            "host": cfg.host, "port": cfg.port,
            "data_root": str(cfg.data_root),
            "log_level": cfg.log_level,
            "secure_cookies": cfg.secure_cookies,
            "csp_mode": cfg.csp_mode,
            "secret_names": (self._secrets.names()
                             if self._secrets is not None else []),
        }
        if cfg.secret_file is not None:
            excluded.append({
                "name": f"config:{Path(cfg.secret_file).name}",
                "reason": "secret_file_values_never_exported"})
            doc["secret_file"] = Path(cfg.secret_file).name
        env_file = self._data_root / "secrets.env"
        if env_file.is_file():
            excluded.append({"name": "config:secrets.env",
                             "reason": "secret_file_values_never_exported"})
        if cfg.tls_key_file is not None:
            excluded.append({
                "name": f"config:{Path(cfg.tls_key_file).name}",
                "reason": "tls_private_key_never_exported"})
            doc["tls_key_file"] = Path(cfg.tls_key_file).name
        if cfg.tls_cert_file is not None:
            doc["tls_cert_file"] = Path(cfg.tls_cert_file).name
        return doc


def verify_export(archive_path: Path) -> ExportVerification:
    """Re-open an instance archive and check it against
    its own manifest: every listed member present at the
    listed size with the listed checksum, and nothing
    present that the manifest never listed. A corrupt or
    unreadable archive is a failed verification with the
    reason named, never an exception escaping."""
    try:
        with tarfile.open(archive_path, "r:gz") as tar:
            members: dict[str, bytes] = {}
            for member in tar.getmembers():
                if member.isfile():
                    fh = tar.extractfile(member)
                    members[member.name] = fh.read() if fh else b""
    except (tarfile.TarError, OSError, EOFError) as exc:
        return ExportVerification(
            ok=False, problems=[f"archive unreadable: {exc}"])
    raw = members.get(MANIFEST_NAME)
    if raw is None:
        return ExportVerification(
            ok=False, problems=["manifest.json: missing from the archive"])
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        return ExportVerification(
            ok=False, problems=[f"manifest.json: unreadable: {exc}"])
    if manifest.get("format") != FORMAT:
        return ExportVerification(ok=False, problems=[
            f"manifest format {manifest.get('format')!r} is not {FORMAT!r}"])
    problems = verify_manifest(manifest, members)
    return ExportVerification(
        ok=not problems, problems=problems,
        entries_checked=len(manifest.get("entries", [])),
        repos_included=len(manifest.get("repos_included", [])),
        repos_excluded=len(manifest.get("repos_excluded", [])))


def render_whole_instance_export_page(export: InstanceExport) -> str:
    """The whole-instance export page: the archive named
    with its counts and checksum, in words, never
    colour-only. All text escaped."""
    parts = ["<h1>Whole-instance export</h1>",
             f"<p>{escape_html_text(export.headline)}.</p>",
             f"<p>Archive: {escape_html_text(export.archive_path.name)} "
             f"({export.archive_bytes} bytes, sha256 "
             f"{escape_html_text(export.archive_sha256)}).</p>",
             f"<p>Manifest: {escape_html_text(export.manifest_path.name)}; "
             f"every member is listed there with its checksum, and "
             f"every exclusion is named there with its reason.</p>"]
    return "\n".join(parts)
