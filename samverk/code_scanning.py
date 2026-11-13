"""Code scanning ingestion (S-302).

Roadmap S-302: Code scanning ingestion -- SARIF
uploads via API, validated against the SARIF
schema, stored per commit.

Static analysers (CodeQL and its kin) speak SARIF:
the Static Analysis Results Interchange Format,
version 2.1.0 -- one JSON document carrying one or
more runs, each run naming its tool and listing its
results against the code as it stood at one commit.
This module is where those documents land in
Samverk:

- **Uploads arrive through the API door (S-238 +
  S-190), as data.** `CodeScanningAPI.upload_sarif`
  takes the parsed request body -- an object naming
  the commit (`oid`), an optional `ref`, and the
  SARIF document itself (an object, or a JSON text
  carrying one) -- exactly as S-246's status face
  takes its payloads. Uploading is a write: the
  caller must be authenticated, S-190's resolved
  role in the repository must cover `write`, and a
  token credential must additionally carry the repo
  write scope. A missing or unwritable repository is
  the one uniform `repo_not_found`. Reading is a
  read at the `read` rung under the same law, so a
  private repository's uploads are indistinguishable
  from a missing one's.
- **Validation is the SARIF schema's standing
  shape, judged whole, before anything is stored.**
  The pure `sarif_problems` walks the document
  against the SARIF 2.1.0 structure this face
  relies on: an object whose `version` is exactly
  `2.1.0`, a non-empty `runs` array (at most
  `MAX_RUNS_PER_UPLOAD` runs), every run an object
  whose `tool.driver.name` is a non-empty string,
  `results` -- where present -- an array of result
  objects each carrying a `message` object with a
  `text` or an `id`, a `level` -- where present --
  in the SARIF vocabulary (`error`, `warning`,
  `note`, `none`), and `locations` -- where present
  -- an array of location objects. SARIF is an
  extensible format, so unknown properties are
  carried, never refused: what the schema requires
  is judged, what it merely permits is left alone.
  Every problem found is named in the refusal's
  detail (the first twelve; the count is never
  hidden), the refusal is the one reason
  `sarif_invalid`, and a refused upload stores
  nothing and audits nothing. A document whose
  canonical text crosses `MAX_SARIF_BYTES` is
  refused `sarif_too_large` before it is stored.
- **Storage is per commit, in migration 123's
  `code_scanning_uploads`.** One row per accepted
  upload: the repository, the commit oid and ref it
  was reported against, the document's canonical
  JSON text (keys sorted, so the same document
  stores byte-identically twice), the tool names
  its runs declare, its run and result counts, its
  per-level result counts, the poster's username,
  and when it landed. An upload is never updated in
  place: a re-upload for the same commit is a new
  row beside the old, and listings read newest
  first, so the standing upload for a commit is its
  latest and its history is never rewritten. The
  commit itself is not judged against the object
  store: like S-246's statuses, an upload names the
  commit it was computed against, and a scanner may
  report on a commit the forge has not fetched --
  the oid is the key, stated as given.
- **Retrieval is the same door, at the read rung.**
  `list_uploads` answers one repository's uploads
  -- or, with a commit named, that commit's uploads
  alone -- as summaries (id, oid, ref, tool names,
  runs, results, levels, poster, created_at);
  `get_upload` answers one upload whole, its stored
  document parsed back under the `sarif` key. An
  upload id that stands in no repository the caller
  may read is `code_scanning_not_found`, as a
  missing one is.
- **The poster is audit-logged.** Every accepted
  upload appends exactly one
  `repo.code_scanning.upload` (one S-302 addition
  to the taxonomy: 135 stand -- 33 auth / 89 repo /
  13 admin), naming the poster's username,
  credential kind and token id beside the commit,
  the ref, and the run and result counts. The row
  itself carries the poster's username (`poster`),
  so the stored data and the log agree about who
  spoke. Downloads and listings audit nothing.
- **Shapes are this face's own.** An upload answers
  as `upload_to_dict`'s fields exactly; refusals
  are S-240's one problem format through
  samverk/error_shape.py, this face's reasons
  registered there. Every rendered value escapes
  through S-010, and standing is always said in
  words beside any mark -- never a colour alone.
  Uploads live in migration 123's
  `code_scanning_uploads` row (schema 122 to 123);
  the suite's standing schema and taxonomy pins
  moved in-slice.
"""
from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore
from .api_auth import ApiAuthError, ApiAuthenticator, ApiIdentity
from .audit import AuditLog
from .error_shape import problem_from_error, problem_to_dict
from .escaping import escape_html_text
from .repositories import RepositoryStore

__all__ = [
    "CODE_SCANNING_API_PATH", "LEVELS", "MAX_RUNS_PER_UPLOAD",
    "MAX_SARIF_BYTES", "SARIF_VERSION", "CodeScanningAPI",
    "CodeScanningError", "CodeScanningUpload", "SarifSummary",
    "error_to_dict", "render_code_scanning_page",
    "render_upload", "sarif_problems", "summarise_sarif",
    "to_json", "upload_to_dict", "validate_upload_payload",
]

CODE_SCANNING_API_PATH = (
    "/api/v1/repos/{owner}/{repo}/code-scanning/sarifs")

#: The one SARIF version this face ingests: the
#: format's standing interchange version.
SARIF_VERSION = "2.1.0"

#: The result levels the SARIF schema allows.
LEVELS = ("error", "warning", "note", "none")

#: One upload carries at most this many runs and
#: at most this many canonical bytes: a scanner's
#: report is data, not an archive, and a document
#: past either cap is refused whole, never cut.
MAX_RUNS_PER_UPLOAD = 100
MAX_SARIF_BYTES = 10 * 1024 * 1024

#: How many validation problems one refusal names
#: before it counts the rest instead of listing on.
_MAX_PROBLEMS_LISTED = 12

_UPLOAD_KEYS = frozenset({"oid", "ref", "sarif"})


class CodeScanningError(ValueError):
    """One refused code-scanning call: a
    machine-branchable reason with its human
    detail, in the house shape."""

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def error_to_dict(exc: CodeScanningError) -> dict:
    """One refusal as data, in S-240's one problem
    format: type, title, status, detail, error_id."""
    return problem_to_dict(problem_from_error(exc))


def to_json(payload: dict) -> str:
    """One payload as a JSON text: keys sorted so
    the same answer renders byte-identically
    twice."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


# ------------------------------------------------------------------
# The SARIF judgement (pure)
# ------------------------------------------------------------------

@dataclass(frozen=True)
class SarifSummary:
    """One valid SARIF document, summarised: the
    tool names its runs declare (in run order,
    duplicates kept where two runs name one tool),
    how many runs it carries, how many results
    stand across them, and the results counted by
    level (a result with no level counts under
    SARIF's default, `warning`)."""
    tool_names: tuple
    run_count: int
    result_count: int
    level_counts: dict


def _is_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def sarif_problems(document: object) -> tuple:
    """Every way one document stands against the
    SARIF 2.1.0 structure this face relies on, as
    plain problem sentences in document order.
    Pure: no storage, no clock. An empty tuple is
    a document this face may store. Unknown
    properties are never a problem -- SARIF is
    extensible, and what the schema permits is
    carried, not refused."""
    if not isinstance(document, dict):
        return ("the document is not a JSON object",)
    problems: list[str] = []
    if "$schema" in document \
            and not isinstance(document["$schema"], str):
        problems.append("$schema is not a string")
    if document.get("version") != SARIF_VERSION:
        problems.append(
            f"version is not {SARIF_VERSION!r}")
    runs = document.get("runs")
    if not isinstance(runs, list):
        problems.append("runs is missing or is not an array")
        return tuple(problems)
    if not runs:
        problems.append("runs is empty")
    if len(runs) > MAX_RUNS_PER_UPLOAD:
        problems.append(
            f"runs carries {len(runs)} runs, more than "
            f"the {MAX_RUNS_PER_UPLOAD} one upload may carry")
    for index, run in enumerate(runs):
        where = f"runs[{index}]"
        if not isinstance(run, dict):
            problems.append(f"{where} is not an object")
            continue
        tool = run.get("tool")
        if not isinstance(tool, dict):
            problems.append(f"{where}.tool is missing or "
                            "is not an object")
            continue
        driver = tool.get("driver")
        if not isinstance(driver, dict):
            problems.append(
                f"{where}.tool.driver is missing or "
                "is not an object")
            continue
        if not _is_text(driver.get("name")):
            problems.append(
                f"{where}.tool.driver.name is missing "
                "or is not a non-empty string")
        rules = driver.get("rules")
        if rules is not None and not isinstance(rules, list):
            problems.append(
                f"{where}.tool.driver.rules is not an array")
        results = run.get("results")
        if results is None:
            continue
        if not isinstance(results, list):
            problems.append(f"{where}.results is not an array")
            continue
        for r_index, result in enumerate(results):
            r_where = f"{where}.results[{r_index}]"
            if not isinstance(result, dict):
                problems.append(f"{r_where} is not an object")
                continue
            if "ruleId" in result \
                    and not isinstance(result["ruleId"], str):
                problems.append(f"{r_where}.ruleId is not a string")
            if "level" in result \
                    and result["level"] not in LEVELS:
                problems.append(
                    f"{r_where}.level is not one of "
                    "error, warning, note, none")
            message = result.get("message")
            if not isinstance(message, dict):
                problems.append(
                    f"{r_where}.message is missing or "
                    "is not an object")
            elif not _is_text(message.get("text")) \
                    and not _is_text(message.get("id")):
                problems.append(
                    f"{r_where}.message carries neither "
                    "a text nor an id")
            locations = result.get("locations")
            if locations is not None:
                if not isinstance(locations, list):
                    problems.append(
                        f"{r_where}.locations is not an array")
                else:
                    for l_index, location in enumerate(locations):
                        if not isinstance(location, dict):
                            problems.append(
                                f"{r_where}.locations[{l_index}] "
                                "is not an object")
    return tuple(problems)


def summarise_sarif(document: dict) -> SarifSummary:
    """One valid document's summary (the caller has
    judged it with `sarif_problems`): its runs'
    tool names, its run and result counts, and its
    results by level, a level-less result counting
    under SARIF's default level, `warning`. Pure."""
    tool_names: list[str] = []
    result_count = 0
    level_counts: dict[str, int] = {}
    for run in document["runs"]:
        tool_names.append(run["tool"]["driver"]["name"])
        for result in run.get("results") or ():
            result_count += 1
            level = result.get("level", "warning")
            level_counts[level] = level_counts.get(level, 0) + 1
    return SarifSummary(
        tool_names=tuple(tool_names),
        run_count=len(document["runs"]),
        result_count=result_count, level_counts=level_counts)


def _parse_sarif(value: object) -> dict:
    """The document one upload carries: an object
    as it stands, or a JSON text parsed into one.
    Anything else -- no document, an unparseable
    text, a text that parses to a non-object -- is
    refused `sarif_invalid` before the schema
    judgement is ever reached."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            raise CodeScanningError(
                "sarif_invalid",
                "sarif_invalid -- the SARIF text is not "
                "JSON. Nothing was recorded.") from None
    if not isinstance(value, dict):
        raise CodeScanningError(
            "sarif_invalid",
            "sarif_invalid -- an upload carries one SARIF "
            "document, as a JSON object. Nothing was "
            "recorded.")
    return value


def validate_upload_payload(payload: object) -> dict:
    """One upload payload, judged whole: an object
    carrying only the keys an upload knows, a
    commit it names, and a SARIF document that
    stands against the schema. Returns the
    normalised report: the commit, the ref, the
    document, its canonical text, and its summary.
    Pure but for nothing -- it touches no storage.
    A payload that is not an object, or carries a
    key this face does not know, is refused
    `payload_invalid` before anything is judged."""
    if not isinstance(payload, dict):
        raise CodeScanningError(
            "payload_invalid",
            "payload_invalid -- a SARIF upload posts as "
            "an object of fields. Nothing was recorded.")
    unknown = set(payload) - _UPLOAD_KEYS
    if unknown:
        raise CodeScanningError(
            "payload_invalid",
            "payload_invalid -- a SARIF upload knows "
            "only oid, ref and sarif. Nothing was "
            "recorded.")
    oid = payload.get("oid")
    if not isinstance(oid, str) or not oid.strip():
        raise CodeScanningError(
            "check_head_invalid",
            "check_head_invalid -- a SARIF upload names "
            "the commit it was computed against. Nothing "
            "was recorded.")
    ref = payload.get("ref", "")
    if not isinstance(ref, str):
        raise CodeScanningError(
            "payload_invalid",
            "payload_invalid -- a SARIF upload's ref is "
            "a string. Nothing was recorded.")
    document = _parse_sarif(payload.get("sarif"))
    problems = sarif_problems(document)
    if problems:
        listed = "; ".join(problems[:_MAX_PROBLEMS_LISTED])
        if len(problems) > _MAX_PROBLEMS_LISTED:
            listed += (f"; and {len(problems) - _MAX_PROBLEMS_LISTED} "
                       "more")
        raise CodeScanningError(
            "sarif_invalid",
            f"sarif_invalid -- the document stands "
            f"against the SARIF {SARIF_VERSION} schema: "
            f"{listed}. Nothing was recorded.")
    canonical = json.dumps(
        document, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"))
    if len(canonical.encode("utf-8")) > MAX_SARIF_BYTES:
        raise CodeScanningError(
            "sarif_too_large",
            f"sarif_too_large -- one upload carries at "
            f"most {MAX_SARIF_BYTES} bytes of SARIF. "
            "Nothing was recorded.")
    return {
        "oid": oid.strip(), "ref": ref, "document": document,
        "sarif_text": canonical,
        "summary": summarise_sarif(document),
    }


# ------------------------------------------------------------------
# The stored record
# ------------------------------------------------------------------

@dataclass(frozen=True)
class CodeScanningUpload:
    """One stored SARIF upload, as the wire carries
    it: the commit it was reported against, the
    summary its document was stored with, and its
    poster. The document itself rides only the
    whole-upload answer (`get_upload`)."""
    id: int
    repo_id: int
    oid: str
    ref: str
    tool_names: tuple
    run_count: int
    result_count: int
    level_counts: dict
    poster: str
    created_at: int


def upload_to_dict(record: CodeScanningUpload) -> dict:
    """One upload as JSON-safe data, in this face's
    contracted field order exactly: id, oid, ref,
    tool_names, runs, results, levels, poster,
    created_at. Data carries the raw values --
    S-010 escaping is the page's law, not the
    wire's."""
    return {
        "id": record.id,
        "oid": record.oid,
        "ref": record.ref,
        "tool_names": list(record.tool_names),
        "runs": record.run_count,
        "results": record.result_count,
        "levels": dict(record.level_counts),
        "poster": record.poster,
        "created_at": record.created_at,
    }


# ------------------------------------------------------------------
# The API face
# ------------------------------------------------------------------

class CodeScanningAPI:
    """The S-302 face: SARIF documents posted
    through S-238's door, validated against the
    SARIF schema, stored per commit in migration
    123's row, and read back through the same door.
    It owns no permission law of its own: the door
    and S-190 judge every call."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        accounts: AccountStore,
        repositories: RepositoryStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._repos = repositories
        self._audit = audit
        self._now = time_fn
        self._auth = ApiAuthenticator(
            conn, accounts, repositories, audit=audit,
            time_fn=time_fn)

    # -- the door ----------------------------------

    def _caller(self, header: object, *,
                required: bool) -> ApiIdentity:
        """The caller of one call through S-238's
        door alone; its refusals ride this face's
        error verbatim (reason and detail)."""
        try:
            return self._auth.resolve_caller(
                header, required=required)
        except ApiAuthError as exc:
            raise CodeScanningError(
                exc.reason, str(exc)) from None

    def _authorize(self, identity: ApiIdentity,
                   owner: object, repo: object,
                   minimum: str):
        """S-190's judgement over this caller on
        this repository, through S-238 alone; its
        refusals ride this face's error verbatim."""
        try:
            return self._auth.authorize_identity(
                identity, owner, repo, minimum=minimum,
                resource="repo")
        except ApiAuthError as exc:
            raise CodeScanningError(
                exc.reason, str(exc)) from None

    def _witness(self, identity: ApiIdentity,
                 full_name: str, detail: dict) -> None:
        """One accepted upload, audit-logged with
        its poster's scoped identity: who posted,
        by what credential, and what landed."""
        if self._audit is None or identity.user is None:
            return
        self._audit.append(
            actor_kind="user", actor_id=identity.user.id,
            action="repo.code_scanning.upload",
            target_kind="repository", target_id=full_name,
            outcome="success",
            detail={
                "poster": identity.username,
                "credential": identity.kind,
                "token_id": identity.token_id,
                **detail,
            })

    # -- rows ---------------------------------------

    def _row(self, row) -> CodeScanningUpload:
        return CodeScanningUpload(
            id=row["id"], repo_id=row["repo_id"],
            oid=row["commit_oid"], ref=row["ref"],
            tool_names=tuple(json.loads(row["tool_names"])),
            run_count=row["run_count"],
            result_count=row["result_count"],
            level_counts=json.loads(row["level_counts"]),
            poster=row["poster"],
            created_at=row["created_at"])

    # -- uploads ------------------------------------

    def upload_sarif(self, header: object, owner: object,
                     repo: object, payload: object) -> dict:
        """Post one SARIF document for one commit:
        the caller must hold write on the repository
        (S-190, with the token scope as its ceiling);
        the payload validates whole -- envelope, then
        the document against the SARIF schema, then
        the size cap -- before one row lands in
        migration 123's table and the post is
        witnessed in the audit log. Answers the
        upload's summary as data."""
        identity = self._caller(header, required=True)
        authz = self._authorize(identity, owner, repo, "write")
        report = validate_upload_payload(payload)
        summary = report["summary"]
        poster = identity.username or ""
        now = int(self._now())
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO code_scanning_uploads"
                " (repo_id, commit_oid, ref, sarif_text,"
                " tool_names, run_count, result_count,"
                " level_counts, poster, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (authz.repository.id, report["oid"],
                 report["ref"], report["sarif_text"],
                 json.dumps(list(summary.tool_names)),
                 summary.run_count, summary.result_count,
                 json.dumps(summary.level_counts,
                            sort_keys=True),
                 poster, now))
            row_id = int(cur.lastrowid)
        row = self._conn.execute(
            "SELECT * FROM code_scanning_uploads"
            " WHERE id = ?", (row_id,)).fetchone()
        record = self._row(row)
        self._witness(
            identity, authz.repository.full_name,
            {"oid": record.oid, "ref": record.ref,
             "runs": record.run_count,
             "results": record.result_count})
        return upload_to_dict(record)

    def list_uploads(self, header: object, owner: object,
                     repo: object,
                     oid: object = None) -> dict:
        """Every SARIF upload stored in one
        repository -- or, with a commit named, that
        commit's uploads alone -- newest first, as
        summaries. The caller is judged at the read
        rung: a missing or unreadable repository is
        the one `repo_not_found`."""
        identity = self._caller(header, required=False)
        authz = self._authorize(identity, owner, repo, "read")
        if oid is None:
            rows = self._conn.execute(
                "SELECT * FROM code_scanning_uploads"
                " WHERE repo_id = ? ORDER BY id DESC",
                (authz.repository.id,)).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM code_scanning_uploads"
                " WHERE repo_id = ? AND commit_oid = ?"
                " ORDER BY id DESC",
                (authz.repository.id, str(oid))).fetchall()
        records = [self._row(r) for r in rows]
        return {
            "oid": None if oid is None else str(oid),
            "total": len(records),
            "returned": len(records),
            "complete": True,
            "uploads": [upload_to_dict(r) for r in records],
        }

    def get_upload(self, header: object, owner: object,
                   repo: object, upload_id: object) -> dict:
        """One stored upload, whole: its summary
        fields plus its document, parsed back from
        the stored canonical text under `sarif`.
        The caller is judged at the read rung, as
        for listings; an id that stands in no
        repository the caller may read -- or in
        none at all -- is `code_scanning_not_found`."""
        identity = self._caller(header, required=False)
        authz = self._authorize(identity, owner, repo, "read")
        try:
            wanted = int(upload_id)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise CodeScanningError(
                "code_scanning_not_found",
                "code_scanning_not_found -- no such "
                "code-scanning upload.") from None
        row = self._conn.execute(
            "SELECT * FROM code_scanning_uploads"
            " WHERE repo_id = ? AND id = ?",
            (authz.repository.id, wanted)).fetchone()
        if row is None:
            raise CodeScanningError(
                "code_scanning_not_found",
                "code_scanning_not_found -- no such "
                "code-scanning upload.")
        record = self._row(row)
        answer = upload_to_dict(record)
        answer["sarif"] = json.loads(row["sarif_text"])
        return answer

    # -- JSON forms ---------------------------------

    def upload_sarif_json(self, header: object, owner: object,
                          repo: object, payload: object) -> str:
        return to_json(self.upload_sarif(
            header, owner, repo, payload))

    def list_uploads_json(self, header: object, owner: object,
                          repo: object,
                          oid: object = None) -> str:
        return to_json(self.list_uploads(
            header, owner, repo, oid=oid))

    def get_upload_json(self, header: object, owner: object,
                        repo: object, upload_id: object) -> str:
        return to_json(self.get_upload(
            header, owner, repo, upload_id))


# ------------------------------------------------------------------
# Rendering (S-010 escaped; words, never colour alone)
# ------------------------------------------------------------------

def render_upload(record: CodeScanningUpload) -> str:
    """One upload as an HTML fragment: the commit
    and ref it was reported against, the tools its
    runs declare, its run and result counts said in
    words, its results by level, and its poster.
    Every value escapes through S-010."""
    tools = ", ".join(record.tool_names) or "no tool named"
    levels = ", ".join(
        f"{level}: {record.level_counts[level]}"
        for level in LEVELS if level in record.level_counts)
    parts = [
        '<div class="code-scanning-upload">',
        (f'<p class="code-scanning-standing">SARIF upload '
         f'#{record.id} for commit '
         f'{escape_html_text(record.oid)}'
         + (f' (ref {escape_html_text(record.ref)})'
            if record.ref else "")
         + f': {record.run_count} run(s), '
         f'{record.result_count} result(s), posted by '
         f'{escape_html_text(record.poster)}.</p>'),
        (f'<p class="code-scanning-tools">Tools: '
         f'{escape_html_text(tools)}.</p>'),
    ]
    if levels:
        parts.append(
            f'<p class="code-scanning-levels">Results by '
            f'level: {escape_html_text(levels)}.</p>')
    parts.append("</div>")
    return "".join(parts)


def render_code_scanning_page() -> str:
    """Code scanning ingestion, in plain words,
    where a scanner's author finds it: who may
    post, what a post must carry, how the document
    is judged, and how uploads are stored and read
    back. Every value escaped through S-010."""
    parts = [
        "<h1>Code scanning ingestion</h1>",
        "<p>Static analysers report in SARIF 2.1.0 "
        "under /api/v1: POST one document to a "
        "repository's code-scanning sarifs, naming "
        "the commit it was computed against (oid) "
        "and, where the scanner knows it, the ref. "
        "The document may ride as a JSON object or "
        "as a JSON text carrying one.</p>",
        "<p>Every document is validated against the "
        "SARIF schema before anything is stored: "
        "its version must be 2.1.0, its runs a "
        "non-empty array, every run's tool driver "
        "named, and every result carrying a message "
        "and -- where it states one -- a level in "
        "the SARIF vocabulary. A document that "
        "stands against the schema is refused whole "
        "with its problems named, and nothing is "
        "recorded; unknown properties are carried, "
        "never refused, because SARIF is extensible.</p>",
        "<p>Accepted uploads are stored per commit "
        "and read back through the same door: list "
        "a repository's uploads, or one commit's, "
        "newest first, and fetch one upload whole "
        "with its document. Posting takes a "
        "credential and write standing on the "
        "repository, judged by the permission "
        "engine (S-190) through the API door "
        "(S-238): a token narrows its owner, never "
        "widens, so a read-only token cannot post. "
        "Every accepted post is audit-logged with "
        "its poster's name and credential, and the "
        "stored row carries that name as its "
        "poster. Reading takes read standing; a "
        "repository you may not read answers "
        "exactly as one that does not exist.</p>",
        "<p>Refusals speak the one problem format "
        "(S-240): type, title, status, detail and "
        "error id, with the door's reasons for "
        "sign-in and scope, and this face's reasons "
        "for a document that is not SARIF as the "
        "schema states it.</p>",
    ]
    return "\n".join(parts)
