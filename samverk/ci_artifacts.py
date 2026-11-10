"""CI artifacts API (S-266).

Upload/download of build artifacts tied to a
commit and a check run, with retention policies.
CI (S-246's posters, and Part XVI's runners after
them) produces files a build's readers need after
the run ends -- the built archive, the test
report, the coverage page. This module is where
those files live:

- **Tied to a commit and a check run.** An
  artifact names the commit it was built from
  (`oid`) and the check run that produced it,
  by the run's S-246 name: `begin_upload` resolves
  the standing `check_runs` row for
  (repository, commit, name) and refuses
  `check_run_not_found` when no such run stands --
  an artifact is never tied to a run that was
  never reported. The row keeps the run's id, so
  S-323's run page and S-267's expiry job read
  the same tie this slice writes.
- **The poster is scoped (S-238 + S-190).**
  Every call resolves through S-238's door
  (`ApiAuthenticator`) and nothing else, exactly
  as S-246's face does: uploading and deleting
  are writes (credential required, S-190 write
  rung, token scope as ceiling, a missing or
  unwritable repository the one uniform
  `repo_not_found`); listing and downloading
  are reads at the read rung, so a private
  repository's artifacts are indistinguishable
  from a missing one's. Chunk calls re-resolve
  the door and must come from the session's own
  uploader.
- **Chunked upload, capped as it flows**
  (S-259's wire, S-012's law). `begin_upload`
  fixes the artifact's name, its run tie and --
  when declared -- its expected size, refused at
  the door when over the per-artifact cap.
  Bytes arrive through `upload_chunk`, strictly
  in order, each chunk at most `CHUNK_MAX_BYTES`,
  the running total judged against the cap the
  moment it crosses it: the session is aborted
  and its staged bytes deleted. Staging lives in
  quarantine under the session id alone; the
  uploader's filename never forms a path.
  `complete_upload` promotes under S-012: the
  stored content type is the type the bytes
  prove, a disguised declared type is refused
  (`type_mismatch`), and the bytes land
  content-addressed under
  `<data_root>/ci-artifacts/<repo>/`, mode 600.
- **Retention policies.** Every artifact carries
  one: `retention_days` is chosen at
  `begin_upload` from `RETENTION_CHOICES`
  (7, 30, 90, 180 or 365 days, or 0 -- keep
  forever), defaulting to `DEFAULT_RETENTION_DAYS`
  (90). The row stores the choice and its
  computed `expires_at` (NULL when forever), so
  the policy is data, not folklore: listings
  state it, downloads judge it, and S-267's
  off-path job enforces exactly these stamps.
  An expired artifact is honestly gone to its
  readers from the moment it expires: listings
  mark it `expired`, and a download is refused
  `artifact_expired` and never counted -- the
  bytes' removal from disk is S-267's sweep,
  named there, not silently done here.
- **Download with counts.** `download_artifact`
  is gated at the read rung, serves the sniffed
  content type, and counts: each opened download
  increments the row's `download_count` in the
  transaction that opens it. Bytes vanished
  from disk refuse (`artifact_missing`) and are
  not counted.
- **The poster is audit-logged.** A completed
  upload appends exactly one `repo.artifact.upload`
  and a deletion one `repo.artifact.delete`
  (two S-266 additions: 133 stand -- 33 auth /
  87 repo / 13 admin), naming the poster's
  username, credential kind and token id beside
  the commit, the run and the artifact. The row
  itself carries the poster's username
  (`poster`). Refused acts store and audit
  nothing; downloads and listings audit nothing.
- **Shapes are this face's own.** An artifact
  answers as `artifact_to_dict`'s fields exactly;
  refusals are S-240's one problem format through
  samverk/error_shape.py, this face's reasons
  registered there. Storage accounting joins
  S-268; expiry enforcement joins S-267; the run
  page listing joins S-323. Artifacts live in
  migration 105's `ci_artifacts` row; open
  upload sessions in its
  `ci_artifact_upload_sessions` row
  (schema 104 to 105).
"""
from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore
from .api_auth import ApiAuthError, ApiAuthenticator, ApiIdentity
from .audit import AuditLog
from .error_shape import problem_from_error, problem_to_dict
from .issues import IssueStore
from .platform_seam import ensure_dir
from .repositories import RepositoryStore
from .uploads import UploadPolicy, UploadRejected, inspect_upload

ARTIFACT_NAME_MAX = 255
ARTIFACT_MAX_BYTES = 256 * 1024 * 1024
CHUNK_MAX_BYTES = 1 * 1024 * 1024
MAX_ARTIFACTS_PER_RUN = 100
RETENTION_CHOICES = (0, 7, 30, 90, 180, 365)
DEFAULT_RETENTION_DAYS = 90
SECONDS_PER_DAY = 86400
_DOWNLOAD_BLOCK = 64 * 1024

ARTIFACT_POLICY = UploadPolicy(
    max_bytes=ARTIFACT_MAX_BYTES,
    allowed_types=frozenset({
        "image/png", "image/jpeg", "image/gif", "image/webp",
        "application/pdf", "application/zip", "application/gzip",
        "text/plain", "application/octet-stream",
    }),
)

_EXTENSION_FOR_TYPE = {
    "image/png": ".png", "image/jpeg": ".jpg",
    "image/gif": ".gif", "image/webp": ".webp",
    "application/pdf": ".pdf", "application/zip": ".zip",
    "application/gzip": ".gz", "text/plain": ".txt",
    "application/octet-stream": ".bin",
}

_BEGIN_KEYS = frozenset({
    "oid", "check_run", "name", "declared_type",
    "expected_size", "retention_days"})

__all__ = [
    "ARTIFACT_MAX_BYTES", "ARTIFACT_NAME_MAX",
    "ARTIFACT_POLICY", "CHUNK_MAX_BYTES",
    "DEFAULT_RETENTION_DAYS", "MAX_ARTIFACTS_PER_RUN",
    "RETENTION_CHOICES", "ArtifactDownload",
    "CIArtifact", "CIArtifactsAPI", "CIArtifactsError",
    "UploadSession", "artifact_to_dict", "decide_expiry",
    "error_to_dict", "is_expired", "render_ci_artifacts_page",
    "to_json", "validate_artifact_name",
    "validate_expected_size", "validate_retention_days",
]


class CIArtifactsError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def error_to_dict(exc: CIArtifactsError) -> dict:
    """One refusal as data, in S-240's one problem
    format: type, title, status, detail, error_id."""
    return problem_to_dict(problem_from_error(exc))


def to_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def validate_artifact_name(value: object) -> str:
    """An artifact name is a bare file name: no
    path, no separators, no controls -- shown and
    offered as a download filename, never a path."""
    if not isinstance(value, str) or not value.strip():
        raise CIArtifactsError(
            "artifact_name_required",
            "artifact_name_required -- an artifact "
            "needs a name. Nothing was recorded.")
    name = value.strip()
    if (len(name) > ARTIFACT_NAME_MAX or name in (".", "..")
            or "/" in name or "\\" in name
            or any(ord(c) < 0x20 or ord(c) == 0x7F for c in name)):
        raise CIArtifactsError(
            "artifact_name_invalid",
            f"artifact_name_invalid -- artifact names "
            f"are bare file names of at most "
            f"{ARTIFACT_NAME_MAX} characters, with no "
            "path separators or control characters. "
            "Nothing was recorded.")
    return name


def validate_expected_size(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CIArtifactsError(
            "size_invalid",
            "size_invalid -- an expected size is a "
            "positive whole number of bytes. Nothing "
            "was recorded.")
    if value > ARTIFACT_POLICY.max_bytes:
        raise CIArtifactsError(
            "too_large",
            f"too_large -- an artifact is at most "
            f"{ARTIFACT_POLICY.max_bytes} bytes. "
            "Nothing was recorded.")
    return value


def validate_retention_days(value: object) -> int:
    """One retention choice, judged whole: absent
    is the default; a standing choice is one of
    RETENTION_CHOICES (0 keeps forever). Pure."""
    if value is None:
        return DEFAULT_RETENTION_DAYS
    if (isinstance(value, bool) or not isinstance(value, int)
            or value not in RETENTION_CHOICES):
        raise CIArtifactsError(
            "retention_invalid",
            "retention_invalid -- retention is one "
            "of 0 (keep forever), 7, 30, 90, 180 or "
            "365 days. Nothing was recorded.")
    return value


def decide_expiry(retention_days: int, created_at: int) -> int | None:
    """The stamp one retention choice computes:
    forever (0) never expires; any other choice
    expires that many days after creation. Pure."""
    if retention_days == 0:
        return None
    return created_at + retention_days * SECONDS_PER_DAY


def is_expired(expires_at: int | None, now: int) -> bool:
    """Whether one artifact stands expired at
    *now*: forever never expires; at the stamp
    itself the artifact is already expired. Pure."""
    return expires_at is not None and now >= expires_at


@dataclass(frozen=True)
class CIArtifact:
    id: int
    repo_id: int
    check_run_id: int
    head_oid: str
    check_run: str
    name: str
    size: int
    sha256: str
    content_type: str
    download_count: int
    retention_days: int
    expires_at: int | None
    uploader_id: int
    poster: str
    created_at: int


@dataclass(frozen=True)
class UploadSession:
    id: int
    repo_id: int
    check_run_id: int
    head_oid: str
    check_run: str
    name: str
    declared_type: str | None
    expected_size: int | None
    retention_days: int
    received: int
    chunks: int
    uploader_id: int
    poster: str
    created_at: int
    state: str


@dataclass
class ArtifactDownload:
    """One opened artifact download: the artifact
    as counted (its `download_count` already
    includes this download), the sniffed content
    type to serve, and the bytes behind an iterator."""
    artifact: CIArtifact
    filename: str
    content_type: str
    size: int
    sha256: str
    _path: Path

    def __iter__(self) -> Iterator[bytes]:
        with open(self._path, "rb") as handle:
            while True:
                block = handle.read(_DOWNLOAD_BLOCK)
                if not block:
                    return
                yield block

    def read_all(self) -> bytes:
        return b"".join(self)


def _row_to_artifact(row: sqlite3.Row) -> CIArtifact:
    return CIArtifact(
        id=row["id"], repo_id=row["repo_id"],
        check_run_id=row["check_run_id"],
        head_oid=row["head_oid"], check_run=row["check_run"],
        name=row["name"], size=row["size"],
        sha256=row["sha256"], content_type=row["content_type"],
        download_count=row["download_count"],
        retention_days=row["retention_days"],
        expires_at=row["expires_at"],
        uploader_id=row["uploader_id"], poster=row["poster"],
        created_at=row["created_at"])


def _row_to_session(row: sqlite3.Row) -> UploadSession:
    return UploadSession(
        id=row["id"], repo_id=row["repo_id"],
        check_run_id=row["check_run_id"],
        head_oid=row["head_oid"], check_run=row["check_run"],
        name=row["name"], declared_type=row["declared_type"],
        expected_size=row["expected_size"],
        retention_days=row["retention_days"],
        received=row["received"], chunks=row["chunks"],
        uploader_id=row["uploader_id"], poster=row["poster"],
        created_at=row["created_at"], state=row["state"])


def artifact_to_dict(artifact: CIArtifact, now: int | None = None) -> dict:
    """One artifact as JSON-safe data, in this
    face's field order. Data carries raw values --
    S-010 escaping is the page's law, not the
    wire's. `expired` is judged at *now* when a
    caller supplies it, else at the row's own
    reading time by the store faces."""
    expired = (is_expired(artifact.expires_at, now)
               if now is not None else False)
    return {
        "id": artifact.id, "oid": artifact.head_oid,
        "check_run": artifact.check_run, "name": artifact.name,
        "size": artifact.size, "sha256": artifact.sha256,
        "content_type": artifact.content_type,
        "download_count": artifact.download_count,
        "retention_days": artifact.retention_days,
        "expires_at": artifact.expires_at, "expired": expired,
        "poster": artifact.poster,
        "created_at": artifact.created_at,
    }


def session_to_dict(session: UploadSession) -> dict:
    return {
        "id": session.id, "oid": session.head_oid,
        "check_run": session.check_run, "name": session.name,
        "expected_size": session.expected_size,
        "retention_days": session.retention_days,
        "received": session.received, "chunks": session.chunks,
        "state": session.state,
    }


class CIArtifactsAPI:
    """The S-266 face: CI uploads and downloads
    build artifacts through S-238's door, tied to
    a commit and a standing S-246 check run, under
    a stated retention policy, witnessed on
    upload and delete."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        accounts: AccountStore,
        repositories: RepositoryStore,
        issues: IssueStore,
        data_root: Path,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
        policy: UploadPolicy = ARTIFACT_POLICY,
    ):
        self._conn = conn
        self._accounts = accounts
        self._repos = repositories
        self._data_root = Path(data_root)
        self._audit = audit
        self._now = time_fn
        self._policy = policy
        self._auth = ApiAuthenticator(
            conn, accounts, repositories, audit=audit,
            time_fn=time_fn)

    # -- the door ----------------------------------

    def _caller(self, header: object, *, required: bool) -> ApiIdentity:
        try:
            return self._auth.resolve_caller(header, required=required)
        except ApiAuthError as exc:
            raise CIArtifactsError(exc.reason, str(exc)) from None

    def _authorize(self, identity: ApiIdentity, owner: object,
                   repo: object, minimum: str):
        try:
            return self._auth.authorize_identity(
                identity, owner, repo, minimum=minimum, resource="repo")
        except ApiAuthError as exc:
            raise CIArtifactsError(exc.reason, str(exc)) from None

    def _witness(self, identity: ApiIdentity, action: str,
                 full_name: str, detail: dict) -> None:
        if self._audit is None or identity.user is None:
            return
        self._audit.append(
            actor_kind="user", actor_id=identity.user.id,
            action=action, target_kind="repository",
            target_id=full_name, outcome="success",
            detail={"poster": identity.username,
                    "credential": identity.kind,
                    "token_id": identity.token_id, **detail})

    # -- paths and rows -----------------------------

    def _staging_path(self, session_id: int) -> Path:
        return (self._data_root / "quarantine"
                / f"ci-artifact-{session_id}.part")

    def _artifact_path(self, artifact: CIArtifact) -> Path:
        ext = _EXTENSION_FOR_TYPE.get(artifact.content_type, ".bin")
        return (self._data_root / "ci-artifacts"
                / str(artifact.repo_id) / f"{artifact.sha256}{ext}")

    def _session(self, upload_id: object) -> UploadSession:
        if isinstance(upload_id, bool) or not isinstance(upload_id, int):
            raise CIArtifactsError(
                "upload_not_found",
                "upload_not_found -- no such upload. "
                "Nothing was recorded.")
        row = self._conn.execute(
            "SELECT * FROM ci_artifact_upload_sessions WHERE id = ?",
            (upload_id,)).fetchone()
        if row is None:
            raise CIArtifactsError(
                "upload_not_found",
                "upload_not_found -- no such upload. "
                "Nothing was recorded.")
        return _row_to_session(row)

    def _open_session(self, identity: ApiIdentity, repo_id: int,
                      upload_id: object) -> UploadSession:
        session = self._session(upload_id)
        if session.repo_id != repo_id:
            raise CIArtifactsError(
                "upload_not_found",
                "upload_not_found -- no such upload. "
                "Nothing was recorded.")
        if session.state != "open":
            raise CIArtifactsError(
                "upload_closed",
                "upload_closed -- that upload is no "
                "longer open. Nothing was recorded.")
        if identity.user is None or session.uploader_id != identity.user.id:
            raise CIArtifactsError(
                "permission_denied",
                "permission_denied -- only the uploader "
                "can continue that upload.")
        return session

    def _abort(self, session: UploadSession) -> None:
        staging = self._staging_path(session.id)
        with self._conn:
            self._conn.execute(
                "UPDATE ci_artifact_upload_sessions"
                " SET state = 'aborted' WHERE id = ?", (session.id,))
        try:
            staging.unlink()
        except OSError:
            pass

    def _artifact_row(self, artifact_id: object, repo_id: int) -> CIArtifact:
        if isinstance(artifact_id, bool) or not isinstance(artifact_id, int):
            raise CIArtifactsError(
                "artifact_not_found",
                "artifact_not_found -- no such artifact.")
        row = self._conn.execute(
            "SELECT * FROM ci_artifacts WHERE id = ? AND repo_id = ?",
            (artifact_id, repo_id)).fetchone()
        if row is None:
            raise CIArtifactsError(
                "artifact_not_found",
                "artifact_not_found -- no such artifact.")
        return _row_to_artifact(row)

    # -- chunked upload -----------------------------

    def begin_upload(self, header: object, owner: object,
                     repo: object, payload: object) -> dict:
        """Open one artifact upload: write rung;
        the payload names the commit, the check run
        (which must stand, posted through S-246),
        the artifact's bare name, and optionally a
        declared type, an expected size and a
        retention choice. Answers the session."""
        identity = self._caller(header, required=True)
        authz = self._authorize(identity, owner, repo, "write")
        if not isinstance(payload, dict):
            raise CIArtifactsError(
                "payload_invalid",
                "payload_invalid -- an artifact upload "
                "opens as an object of fields. Nothing "
                "was recorded.")
        unknown = set(payload) - _BEGIN_KEYS
        if unknown:
            raise CIArtifactsError(
                "payload_invalid",
                "payload_invalid -- an artifact upload "
                "knows only oid, check_run, name, "
                "declared_type, expected_size and "
                "retention_days. Nothing was recorded.")
        oid = payload.get("oid")
        if not isinstance(oid, str) or not oid.strip():
            raise CIArtifactsError(
                "check_head_invalid",
                "check_head_invalid -- an artifact names "
                "the commit it was built from. Nothing "
                "was recorded.")
        run_name = payload.get("check_run")
        if not isinstance(run_name, str) or not run_name.strip():
            raise CIArtifactsError(
                "check_name_invalid",
                "check_name_invalid -- an artifact names "
                "the check run that produced it. Nothing "
                "was recorded.")
        name = validate_artifact_name(payload.get("name"))
        expected = validate_expected_size(payload.get("expected_size"))
        retention = validate_retention_days(payload.get("retention_days"))
        declared = payload.get("declared_type")
        if declared is not None and not isinstance(declared, str):
            raise CIArtifactsError(
                "payload_invalid",
                "payload_invalid -- a declared type is "
                "text. Nothing was recorded.")
        repo_id = authz.repository.id
        run = self._conn.execute(
            "SELECT * FROM check_runs WHERE repo_id = ?"
            " AND head_oid = ? AND name = ?",
            (repo_id, oid, run_name)).fetchone()
        if run is None:
            raise CIArtifactsError(
                "check_run_not_found",
                "check_run_not_found -- no check run by "
                "that name stands for that commit. "
                "Nothing was recorded.")
        taken = self._conn.execute(
            "SELECT id FROM ci_artifacts WHERE check_run_id = ?"
            " AND name = ?", (run["id"], name)).fetchone()
        if taken is not None:
            raise CIArtifactsError(
                "artifact_taken",
                f"artifact_taken -- that check run "
                f"already carries an artifact named "
                f"{name!r}. Nothing was recorded.")
        count = int(self._conn.execute(
            "SELECT COUNT(*) c FROM ci_artifacts"
            " WHERE check_run_id = ?", (run["id"],)).fetchone()["c"])
        if count >= MAX_ARTIFACTS_PER_RUN:
            raise CIArtifactsError(
                "too_many_artifacts",
                f"too_many_artifacts -- a check run "
                f"carries at most {MAX_ARTIFACTS_PER_RUN} "
                "artifacts. Nothing was recorded.")
        now = int(self._now())
        assert identity.user is not None
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO ci_artifact_upload_sessions"
                " (repo_id, check_run_id, head_oid, check_run,"
                " name, declared_type, expected_size,"
                " retention_days, received, chunks, uploader_id,"
                " poster, created_at, state)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, 'open')",
                (repo_id, run["id"], oid, run_name, name, declared,
                 expected, retention, identity.user.id,
                 identity.username or "", now))
        session = self._session(int(cur.lastrowid))
        staging = self._staging_path(session.id)
        ensure_dir(staging.parent)
        staging.write_bytes(b"")
        try:
            staging.chmod(0o600)
        except OSError:
            pass
        return session_to_dict(session)

    def upload_chunk(self, header: object, owner: object,
                     repo: object, upload_id: object,
                     chunk_index: object, data: object) -> dict:
        identity = self._caller(header, required=True)
        authz = self._authorize(identity, owner, repo, "write")
        session = self._open_session(identity, authz.repository.id, upload_id)
        if not isinstance(data, (bytes, bytearray)) or not data:
            raise CIArtifactsError(
                "chunk_empty",
                "chunk_empty -- a chunk carries at "
                "least one byte. Nothing was recorded.")
        if len(data) > CHUNK_MAX_BYTES:
            raise CIArtifactsError(
                "chunk_too_large",
                f"chunk_too_large -- a chunk is at "
                f"most {CHUNK_MAX_BYTES} bytes. Nothing "
                "was recorded.")
        if (isinstance(chunk_index, bool)
                or not isinstance(chunk_index, int)
                or chunk_index != session.chunks):
            raise CIArtifactsError(
                "chunk_out_of_order",
                f"chunk_out_of_order -- chunk "
                f"{session.chunks} is expected next. "
                "Nothing was recorded.")
        received = session.received + len(data)
        if received > self._policy.max_bytes:
            self._abort(session)
            raise CIArtifactsError(
                "too_large",
                f"too_large -- an artifact is at most "
                f"{self._policy.max_bytes} bytes; the "
                "upload was aborted.")
        if (session.expected_size is not None
                and received > session.expected_size):
            self._abort(session)
            raise CIArtifactsError(
                "size_mismatch",
                "size_mismatch -- the upload is larger "
                "than its declared size; the upload "
                "was aborted.")
        staging = self._staging_path(session.id)
        with open(staging, "ab") as handle:
            handle.write(bytes(data))
        with self._conn:
            self._conn.execute(
                "UPDATE ci_artifact_upload_sessions SET"
                " received = ?, chunks = ? WHERE id = ?",
                (received, session.chunks + 1, session.id))
        return session_to_dict(self._session(session.id))

    def complete_upload(self, header: object, owner: object,
                        repo: object, upload_id: object) -> dict:
        """Promote one finished upload under S-012
        and witness it: the artifact row lands with
        its retention stamp computed, the session
        closes, and exactly one repo.artifact.upload
        audit entry names the poster."""
        identity = self._caller(header, required=True)
        authz = self._authorize(identity, owner, repo, "write")
        session = self._open_session(identity, authz.repository.id, upload_id)
        staging = self._staging_path(session.id)
        if session.received == 0:
            self._abort(session)
            raise CIArtifactsError(
                "empty",
                "empty -- an artifact carries at least "
                "one byte; the upload was aborted.")
        if (session.expected_size is not None
                and session.received != session.expected_size):
            self._abort(session)
            raise CIArtifactsError(
                "size_mismatch",
                "size_mismatch -- the upload is smaller "
                "than its declared size; the upload "
                "was aborted.")
        taken = self._conn.execute(
            "SELECT id FROM ci_artifacts WHERE check_run_id = ?"
            " AND name = ?",
            (session.check_run_id, session.name)).fetchone()
        if taken is not None:
            self._abort(session)
            raise CIArtifactsError(
                "artifact_taken",
                f"artifact_taken -- that check run "
                f"already carries an artifact named "
                f"{session.name!r}; the upload was aborted.")
        data = staging.read_bytes()
        try:
            inspected = inspect_upload(
                data, declared_type=session.declared_type,
                policy=self._policy)
        except UploadRejected as exc:
            self._abort(session)
            raise CIArtifactsError(exc.reason, exc.reason) from None
        now = int(self._now())
        expires = decide_expiry(session.retention_days, now)
        draft = CIArtifact(
            id=0, repo_id=session.repo_id,
            check_run_id=session.check_run_id,
            head_oid=session.head_oid, check_run=session.check_run,
            name=session.name, size=inspected.size,
            sha256=inspected.sha256,
            content_type=inspected.detected_type, download_count=0,
            retention_days=session.retention_days, expires_at=expires,
            uploader_id=session.uploader_id, poster=session.poster,
            created_at=now)
        final = self._artifact_path(draft)
        ensure_dir(final.parent)
        if not final.exists():
            final.write_bytes(data)
            try:
                final.chmod(0o600)
            except OSError:
                pass
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO ci_artifacts (repo_id, check_run_id,"
                " head_oid, check_run, name, size, sha256,"
                " content_type, download_count, retention_days,"
                " expires_at, uploader_id, poster, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)",
                (draft.repo_id, draft.check_run_id, draft.head_oid,
                 draft.check_run, draft.name, draft.size, draft.sha256,
                 draft.content_type, draft.retention_days,
                 draft.expires_at, draft.uploader_id, draft.poster, now))
            self._conn.execute(
                "DELETE FROM ci_artifact_upload_sessions WHERE id = ?",
                (session.id,))
        try:
            staging.unlink()
        except OSError:
            pass
        artifact = self._artifact_row(int(cur.lastrowid), draft.repo_id)
        self._witness(
            identity, "repo.artifact.upload",
            authz.repository.full_name,
            {"oid": artifact.head_oid, "check_run": artifact.check_run,
             "name": artifact.name, "size": artifact.size,
             "retention_days": artifact.retention_days})
        return artifact_to_dict(artifact, now=now)

    def abort_upload(self, header: object, owner: object,
                     repo: object, upload_id: object) -> dict:
        identity = self._caller(header, required=True)
        authz = self._authorize(identity, owner, repo, "write")
        session = self._open_session(identity, authz.repository.id, upload_id)
        self._abort(session)
        return session_to_dict(self._session(session.id))

    # -- reads, download, delete --------------------

    def list_artifacts(self, header: object, owner: object,
                       repo: object, oid: object = None,
                       check_run: object = None) -> dict:
        """Every artifact in one repository -- or,
        with a commit (and optionally a run) named,
        that commit's artifacts -- in landing
        order, each marked with its retention
        standing at reading time. Read rung."""
        identity = self._caller(header, required=False)
        authz = self._authorize(identity, owner, repo, "read")
        sql = "SELECT * FROM ci_artifacts WHERE repo_id = ?"
        args: list = [authz.repository.id]
        if oid is not None:
            sql += " AND head_oid = ?"; args.append(str(oid))
        if check_run is not None:
            sql += " AND check_run = ?"; args.append(str(check_run))
        sql += " ORDER BY id"
        rows = self._conn.execute(sql, args).fetchall()
        now = int(self._now())
        artifacts = [_row_to_artifact(r) for r in rows]
        return {
            "total": len(artifacts), "returned": len(artifacts),
            "complete": True,
            "artifacts": [artifact_to_dict(a, now=now) for a in artifacts],
        }

    def get_artifact(self, header: object, owner: object,
                     repo: object, artifact_id: object) -> dict:
        identity = self._caller(header, required=False)
        authz = self._authorize(identity, owner, repo, "read")
        artifact = self._artifact_row(artifact_id, authz.repository.id)
        return artifact_to_dict(artifact, now=int(self._now()))

    def download_artifact(self, header: object, owner: object,
                          repo: object,
                          artifact_id: object) -> ArtifactDownload:
        """Open one download: read rung, retention
        judged first (expired refuses, uncounted),
        bytes missing refuse uncounted, and an
        opened download counts in its transaction."""
        identity = self._caller(header, required=False)
        authz = self._authorize(identity, owner, repo, "read")
        artifact = self._artifact_row(artifact_id, authz.repository.id)
        now = int(self._now())
        if is_expired(artifact.expires_at, now):
            raise CIArtifactsError(
                "artifact_expired",
                "artifact_expired -- that artifact's "
                "retention window has closed.")
        path = self._artifact_path(artifact)
        if not path.is_file():
            raise CIArtifactsError(
                "artifact_missing",
                "artifact_missing -- that artifact's "
                "bytes are missing from storage.")
        with self._conn:
            self._conn.execute(
                "UPDATE ci_artifacts SET download_count ="
                " download_count + 1 WHERE id = ?", (artifact.id,))
        counted = self._artifact_row(artifact.id, artifact.repo_id)
        return ArtifactDownload(
            artifact=counted, filename=counted.name,
            content_type=counted.content_type, size=counted.size,
            sha256=counted.sha256, _path=path)

    def delete_artifact(self, header: object, owner: object,
                        repo: object, artifact_id: object) -> dict:
        """Delete one artifact: write rung; the row
        goes, its bytes go when no standing row in
        the repository names the same digest, and
        the act is witnessed. Expired artifacts may
        still be deleted -- S-267 sweeps them, an
        owner need not wait for the sweep."""
        identity = self._caller(header, required=True)
        authz = self._authorize(identity, owner, repo, "write")
        artifact = self._artifact_row(artifact_id, authz.repository.id)
        path = self._artifact_path(artifact)
        with self._conn:
            self._conn.execute(
                "DELETE FROM ci_artifacts WHERE id = ?", (artifact.id,))
            remaining = int(self._conn.execute(
                "SELECT COUNT(*) c FROM ci_artifacts"
                " WHERE repo_id = ? AND sha256 = ?",
                (artifact.repo_id, artifact.sha256)).fetchone()["c"])
        if remaining == 0:
            try:
                path.unlink()
            except OSError:
                pass
        self._witness(
            identity, "repo.artifact.delete",
            authz.repository.full_name,
            {"oid": artifact.head_oid, "check_run": artifact.check_run,
             "name": artifact.name})
        return artifact_to_dict(artifact, now=int(self._now()))


def render_ci_artifacts_page() -> str:
    """The CI artifacts API in plain words, where
    a script's author finds it. S-010 escaped."""
    parts = [
        "<h1>CI artifacts API</h1>",
        "<p>Build artifacts are the files a check "
        "run produces -- the built archive, the "
        "test report -- kept tied to the commit "
        "and the check run that made them. Upload "
        "is chunked: open an upload naming the "
        "commit, the check run and the file name, "
        "send the bytes in order, then complete "
        "it. An upload that names a check run "
        "which was never reported is refused: an "
        "artifact is never tied to a run that "
        "never stood.</p>",
        "<p>Every artifact carries a retention "
        "policy, chosen at upload: 7, 30, 90, 180 "
        "or 365 days, or keep forever; 90 days is "
        "the default. The listing states each "
        "artifact's expiry, an expired artifact "
        "no longer downloads, and the off-path "
        "expiry job (S-267) removes its bytes. "
        "Uploading and deleting take a credential "
        "with write standing, judged through the "
        "API door (S-238) and the permission "
        "engine (S-190), and both acts are "
        "audit-logged with their poster. Reading "
        "and downloading take read standing; a "
        "repository you may not read answers "
        "exactly as one that does not exist.</p>",
        f"<p>Each artifact is at most "
        f"{ARTIFACT_MAX_BYTES} bytes, sent in "
        f"chunks of at most {CHUNK_MAX_BYTES} "
        f"bytes, and a check run carries at most "
        f"{MAX_ARTIFACTS_PER_RUN} artifacts. An "
        "artifact's content type is the type its "
        "bytes prove, not the type claimed at "
        "upload, and every download is counted "
        "on the artifact's row.</p>",
    ]
    return "\n".join(parts)
