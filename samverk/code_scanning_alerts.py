"""Code scanning alerts (S-303).

Roadmap S-303: SARIF fingerprinting and dedup --
the same finding across runs is one alert;
new/fixed transitions computed per branch.

S-302 lands SARIF documents per commit and stops
there: every upload is a document, and nothing in
it says whether the finding it reports is the one
yesterday's run reported, a new one, or the last
sighting of one that has since been fixed. This
module is that judgement, built on S-302's stored
uploads alone:

- **A finding is one result, fingerprinted.** The
  pure `extract_findings` walks a judged SARIF
  document (S-302's `sarif_problems` law) and
  lifts every result into a `Finding`: its run's
  tool name, its rule id, its level (SARIF's
  default `warning` where it states none), its
  message (text, else id), and its primary
  location -- the first location's artifact URI
  and region start line and column, empty and
  zero where the result names none. The pure
  `fingerprint_finding` then names the finding
  across runs. Where the scanner supplied SARIF's
  own `partialFingerprints`, the fingerprint is
  those values under the tool and rule (basis
  `partial`): the scanner's own identity for the
  finding, which stands even when the finding
  moves lines. Where it supplied none, the
  fingerprint is the structural shape -- tool,
  rule, artifact, line, column, message (basis
  `structural`) -- and the limit is said plainly:
  a finding that moves lines then reads as one
  fixed and one new, which is exactly why SARIF
  carries partial fingerprints. Results in one
  document that share a fingerprint are one
  finding; the collapse is counted, never hidden.
- **Transitions are computed per branch.** An
  upload's ref names its branch (`branch_of`:
  `refs/heads/main` and `main` are the one branch
  `main`; an upload naming no ref stands under
  the empty branch, grouped with its own kind).
  `CodeScanningAlertsAPI.process_upload` takes
  one stored S-302 upload -- through S-238's
  door, at the write rung, like the upload
  itself -- and settles its branch's alerts
  against the upload's findings: a fingerprint
  with no alert is a **new** alert, open; one
  standing open is still open, its last sighting
  brought current; one standing fixed that a
  run reports again is **reopened**; an open
  alert the run no longer reports is **fixed**
  by that run -- the transition names the upload
  and commit that first did not carry it, and
  claims no human resolver. The pure
  `compute_transitions` states the same law over
  fingerprint sets, so the arithmetic is judged
  without storage. One branch's transitions
  never touch another's: a finding fixed on
  `main` stands open on `dev` until a run there
  stops reporting it.
- **Processing is in upload order, per branch.**
  Migration 124's `code_scanning_branch_heads`
  remembers the newest upload processed for each
  branch. Processing that head again answers its
  standing summary with nothing rewritten (every
  finding still open, its sighting count
  unmoved); processing an older upload is
  refused `code_scanning_stale_upload`, because
  its transitions would rewrite a newer run's
  verdicts -- the caller processes the branch's
  uploads oldest first, and a refusal changes
  nothing. An upload id standing in no
  repository the caller may write is the S-302
  face's one `code_scanning_not_found`.
- **Alerts are read through the same door.**
  `list_alerts` answers one repository's alerts
  -- filtered by branch and by state where the
  caller names them -- newest first; `get_alert`
  answers one whole. Reading is the read rung:
  a missing or unreadable repository is the one
  uniform `repo_not_found`, and an alert id that
  stands in no repository the caller may read is
  `code_scanning_alert_not_found`, as a missing
  one is. A state filter outside `open` /
  `fixed` is refused `payload_invalid`.
- **Unwitnessed in the audit taxonomy -- said
  plainly.** No new taxonomy event: 135 stand
  (33 auth / 89 repo / 13 admin). An alert is
  derived data, recomputed from stored uploads
  that were themselves witnessed at the door
  (`repo.code_scanning.upload`); processing and
  reading append nothing, like S-299's refresh.
- **Shapes are this face's own.** An alert
  answers as `alert_to_dict`'s fields exactly;
  refusals are S-240's one problem format through
  samverk/error_shape.py, this face's two reasons
  registered there. Every rendered value escapes
  through S-010, and standing is always said in
  words beside any mark -- never a colour alone.
  Alerts and branch heads live in migration
  124's rows (schema 123 to 124); the suite's
  standing schema pins moved in-slice, and its
  taxonomy pins stand unmoved at 135.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore
from .api_auth import ApiAuthError, ApiAuthenticator, ApiIdentity
from .audit import AuditLog
from .code_scanning import summarise_sarif  # noqa: F401  (re-export seam)
from .error_shape import problem_from_error, problem_to_dict
from .escaping import escape_html_text
from .repositories import RepositoryStore

__all__ = [
    "ALERT_STATES", "CODE_SCANNING_ALERTS_API_PATH", "Finding",
    "CodeScanningAlert", "CodeScanningAlertsAPI",
    "CodeScanningAlertsError", "alert_to_dict", "branch_of",
    "compute_transitions", "error_to_dict",
    "extract_findings", "fingerprint_finding",
    "render_alert", "render_code_scanning_alerts_page",
    "to_json",
]

CODE_SCANNING_ALERTS_API_PATH = (
    "/api/v1/repos/{owner}/{repo}/code-scanning/alerts")

#: The states one code-scanning alert stands in:
#: reported by the latest processed run on its
#: branch (`open`), or no longer reported there
#: (`fixed`). A fixed alert a run reports again
#: returns to `open` -- the reopening is a
#: transition, counted, not a third state.
ALERT_STATES = ("open", "fixed")


class CodeScanningAlertsError(ValueError):
    """One refused code-scanning-alerts call: a
    machine-branchable reason with its human
    detail, in the house shape."""

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def error_to_dict(exc: CodeScanningAlertsError) -> dict:
    """One refusal as data, in S-240's one problem
    format: type, title, status, detail, error_id."""
    return problem_to_dict(problem_from_error(exc))


def to_json(payload: dict) -> str:
    """One payload as a JSON text: keys sorted so
    the same answer renders byte-identically
    twice."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


# ------------------------------------------------------------------
# Branches, findings, fingerprints (pure)
# ------------------------------------------------------------------

def branch_of(ref: object) -> str:
    """The branch one upload's ref names: a full
    `refs/heads/<branch>` ref and the bare branch
    name are the one branch; any other ref stands
    as it is written; no ref -- or a non-string --
    is the empty branch. Pure."""
    if not isinstance(ref, str):
        return ""
    ref = ref.strip()
    if ref.startswith("refs/heads/"):
        return ref[len("refs/heads/"):]
    return ref


@dataclass(frozen=True)
class Finding:
    """One SARIF result lifted out of its run:
    the identity fields a fingerprint is computed
    over, and the standing facts an alert carries.
    `partial` is the result's partialFingerprints
    as sorted (name, value) pairs, string values
    only; empty where the scanner supplied none."""
    tool_name: str
    rule_id: str
    level: str
    message: str
    artifact_uri: str
    start_line: int
    start_column: int
    partial: tuple


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int) and value > 0:
        return value
    return 0


def _result_finding(tool_name: str, result: dict) -> Finding:
    message = result.get("message")
    text = ""
    if isinstance(message, dict):
        if isinstance(message.get("text"), str):
            text = message["text"]
        elif isinstance(message.get("id"), str):
            text = message["id"]
    uri = ""
    line = 0
    column = 0
    locations = result.get("locations")
    if isinstance(locations, list) and locations:
        first = locations[0]
        if isinstance(first, dict):
            physical = first.get("physicalLocation")
            if isinstance(physical, dict):
                artifact = physical.get("artifactLocation")
                if isinstance(artifact, dict) \
                        and isinstance(artifact.get("uri"), str):
                    uri = artifact["uri"]
                region = physical.get("region")
                if isinstance(region, dict):
                    line = _as_int(region.get("startLine"))
                    column = _as_int(region.get("startColumn"))
    partial_raw = result.get("partialFingerprints")
    partial: tuple = ()
    if isinstance(partial_raw, dict):
        partial = tuple(sorted(
            (str(name), value)
            for name, value in partial_raw.items()
            if isinstance(value, str)))
    rule = result.get("ruleId")
    level = result.get("level")
    return Finding(
        tool_name=tool_name,
        rule_id=rule if isinstance(rule, str) else "",
        level=level if isinstance(level, str) else "warning",
        message=text, artifact_uri=uri,
        start_line=line, start_column=column,
        partial=partial)


def fingerprint_finding(finding: Finding) -> tuple:
    """One finding's fingerprint across runs, and
    the basis it stands on. With partial
    fingerprints: sha256 over the tool, the rule
    and the sorted partial values (basis
    `partial`) -- the scanner's own identity,
    indifferent to where the finding now stands.
    Without: sha256 over the structural shape --
    tool, rule, artifact, line, column, message
    (basis `structural`). Pure."""
    if finding.partial:
        basis = "partial"
        identity = {
            "tool": finding.tool_name,
            "rule": finding.rule_id,
            "partial": [list(pair) for pair in finding.partial],
        }
    else:
        basis = "structural"
        identity = {
            "tool": finding.tool_name,
            "rule": finding.rule_id,
            "uri": finding.artifact_uri,
            "line": finding.start_line,
            "column": finding.start_column,
            "message": finding.message,
        }
    canonical = json.dumps(
        identity, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"))
    return hashlib.sha256(
        canonical.encode("utf-8")).hexdigest(), basis


def extract_findings(document: dict) -> tuple:
    """Every distinct finding one judged SARIF
    document carries, in document order, as
    (finding, fingerprint, basis) triples.
    Results sharing a fingerprint are one
    finding -- the first stands -- so the
    document's duplicates collapse here, at the
    seam, and the caller counts the collapse
    against the document's result count. The
    caller has judged the document with S-302's
    `sarif_problems`; shapes this face does not
    rely on are read defensively, never trusted.
    Pure."""
    seen: set = set()
    out: list = []
    for run in document.get("runs") or ():
        if not isinstance(run, dict):
            continue
        tool = run.get("tool")
        driver = tool.get("driver") if isinstance(tool, dict) else None
        name = driver.get("name") if isinstance(driver, dict) else None
        tool_name = name if isinstance(name, str) else ""
        for result in run.get("results") or ():
            if not isinstance(result, dict):
                continue
            finding = _result_finding(tool_name, result)
            fingerprint, basis = fingerprint_finding(finding)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            out.append((finding, fingerprint, basis))
    return tuple(out)


def compute_transitions(previous_open: object,
                        current: object) -> dict:
    """The new/fixed arithmetic over fingerprint
    sets, stated pure: `new` stands in the current
    run and in no standing alert set the caller
    names apart -- here the caller passes the
    branch's standing-open set as `previous_open`
    and judges newness against every alert it
    holds; this helper answers the open-set law:
    fingerprints in both sets are `still_open`,
    only in the current are `appeared`, only in
    the previous are `fixed`. Sorted, so the same
    sets answer identically twice. Pure."""
    previous = set(previous_open)  # type: ignore[arg-type]
    now = set(current)  # type: ignore[arg-type]
    return {
        "appeared": sorted(now - previous),
        "still_open": sorted(now & previous),
        "fixed": sorted(previous - now),
    }


# ------------------------------------------------------------------
# The stored record
# ------------------------------------------------------------------

@dataclass(frozen=True)
class CodeScanningAlert:
    """One code-scanning alert, as the wire
    carries it: one fingerprint on one branch of
    one repository, its standing facts from the
    run that most recently reported it, its state,
    and the uploads that first reported it, most
    recently reported it, and -- where it stands
    fixed -- first stopped reporting it."""
    id: int
    repo_id: int
    branch: str
    fingerprint: str
    basis: str
    tool_name: str
    rule_id: str
    level: str
    message: str
    artifact_uri: str
    start_line: int
    start_column: int
    state: str
    first_seen_upload_id: int
    first_seen_oid: str
    last_seen_upload_id: int
    last_seen_oid: str
    fixed_upload_id: int | None
    fixed_oid: str
    times_seen: int
    times_fixed: int
    created_at: int
    updated_at: int


def alert_to_dict(record: CodeScanningAlert) -> dict:
    """One alert as JSON-safe data, in this face's
    contracted field order exactly. Data carries
    the raw values -- S-010 escaping is the
    page's law, not the wire's."""
    return {
        "id": record.id,
        "branch": record.branch,
        "fingerprint": record.fingerprint,
        "basis": record.basis,
        "tool": record.tool_name,
        "rule_id": record.rule_id,
        "level": record.level,
        "message": record.message,
        "artifact_uri": record.artifact_uri,
        "start_line": record.start_line,
        "start_column": record.start_column,
        "state": record.state,
        "first_seen_upload": record.first_seen_upload_id,
        "first_seen_oid": record.first_seen_oid,
        "last_seen_upload": record.last_seen_upload_id,
        "last_seen_oid": record.last_seen_oid,
        "fixed_upload": record.fixed_upload_id,
        "fixed_oid": record.fixed_oid,
        "times_seen": record.times_seen,
        "times_fixed": record.times_fixed,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


# ------------------------------------------------------------------
# The API face
# ------------------------------------------------------------------

class CodeScanningAlertsAPI:
    """The S-303 face: fingerprints and dedup over
    S-302's stored uploads, transitions per
    branch, alerts read back through S-238's
    door. It owns no permission law of its own:
    the door and S-190 judge every call."""

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
            raise CodeScanningAlertsError(
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
            raise CodeScanningAlertsError(
                exc.reason, str(exc)) from None

    # -- rows ---------------------------------------

    def _row(self, row) -> CodeScanningAlert:
        return CodeScanningAlert(
            id=row["id"], repo_id=row["repo_id"],
            branch=row["branch"],
            fingerprint=row["fingerprint"],
            basis=row["basis"],
            tool_name=row["tool_name"],
            rule_id=row["rule_id"], level=row["level"],
            message=row["message"],
            artifact_uri=row["artifact_uri"],
            start_line=row["start_line"],
            start_column=row["start_column"],
            state=row["state"],
            first_seen_upload_id=row["first_seen_upload_id"],
            first_seen_oid=row["first_seen_oid"],
            last_seen_upload_id=row["last_seen_upload_id"],
            last_seen_oid=row["last_seen_oid"],
            fixed_upload_id=row["fixed_upload_id"],
            fixed_oid=row["fixed_oid"],
            times_seen=row["times_seen"],
            times_fixed=row["times_fixed"],
            created_at=row["created_at"],
            updated_at=row["updated_at"])

    def _alerts(self, repo_id: int, branch: str) -> list:
        rows = self._conn.execute(
            "SELECT * FROM code_scanning_alerts"
            " WHERE repo_id = ? AND branch = ?"
            " ORDER BY id", (repo_id, branch)).fetchall()
        return [self._row(r) for r in rows]

    # -- processing ---------------------------------

    def process_upload(self, header: object, owner: object,
                       repo: object, upload_id: object) -> dict:
        """Settle one stored S-302 upload against
        its branch's alerts: the caller must hold
        write on the repository (S-190, with the
        token scope as its ceiling), as for the
        upload itself. The upload's findings are
        extracted and fingerprinted; new, reopened,
        still-open and fixed transitions land in
        migration 124's rows in one transaction,
        and the branch head moves to this upload.
        Processing the standing head again rewrites
        nothing and answers the standing summary;
        an older upload is refused
        `code_scanning_stale_upload` and changes
        nothing. Answers the transition summary as
        data: the upload, its branch, its finding
        and collapsed-duplicate counts, the four
        transition fingerprint lists, and the
        branch's open alert count after."""
        identity = self._caller(header, required=True)
        authz = self._authorize(identity, owner, repo, "write")
        repo_id = authz.repository.id
        try:
            wanted = int(upload_id)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise CodeScanningAlertsError(
                "code_scanning_not_found",
                "code_scanning_not_found -- no such "
                "code-scanning upload.") from None
        row = self._conn.execute(
            "SELECT * FROM code_scanning_uploads"
            " WHERE repo_id = ? AND id = ?",
            (repo_id, wanted)).fetchone()
        if row is None:
            raise CodeScanningAlertsError(
                "code_scanning_not_found",
                "code_scanning_not_found -- no such "
                "code-scanning upload.")
        branch = branch_of(row["ref"])
        document = json.loads(row["sarif_text"])
        extracted = extract_findings(document)
        summary = summarise_sarif(document)
        duplicates = summary.result_count - len(extracted)
        head = self._conn.execute(
            "SELECT * FROM code_scanning_branch_heads"
            " WHERE repo_id = ? AND branch = ?",
            (repo_id, branch)).fetchone()
        standing = self._alerts(repo_id, branch)
        by_fp = {a.fingerprint: a for a in standing}
        current_fps = [fp for _, fp, _ in extracted]
        if head is not None and wanted < int(head["upload_id"]):
            raise CodeScanningAlertsError(
                "code_scanning_stale_upload",
                "code_scanning_stale_upload -- upload "
                f"{wanted} is older than upload "
                f"{int(head['upload_id'])}, the newest "
                "processed for its branch; its "
                "transitions would rewrite that run's "
                "verdicts. Nothing was recorded.")
        if head is not None and wanted == int(head["upload_id"]):
            still = sorted(
                fp for fp in current_fps
                if fp in by_fp and by_fp[fp].state == "open")
            open_total = sum(
                1 for a in standing if a.state == "open")
            return {
                "upload": wanted, "oid": row["commit_oid"],
                "ref": row["ref"], "branch": branch,
                "findings": len(extracted),
                "duplicates_collapsed": duplicates,
                "new": [], "reopened": [],
                "still_open": still,
                "fixed": [], "open_alerts": open_total,
            }
        now = int(self._now())
        new: list = []
        reopened: list = []
        still_open: list = []
        fixed: list = []
        with self._conn:
            for finding, fingerprint, basis in extracted:
                alert = by_fp.get(fingerprint)
                if alert is None:
                    self._conn.execute(
                        "INSERT INTO code_scanning_alerts"
                        " (repo_id, branch, fingerprint,"
                        " basis, tool_name, rule_id, level,"
                        " message, artifact_uri, start_line,"
                        " start_column, state,"
                        " first_seen_upload_id,"
                        " first_seen_oid,"
                        " last_seen_upload_id,"
                        " last_seen_oid, fixed_upload_id,"
                        " fixed_oid, times_seen,"
                        " times_fixed, created_at,"
                        " updated_at)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?,"
                        " ?, ?, ?, 'open', ?, ?, ?, ?,"
                        " NULL, '', 1, 0, ?, ?)",
                        (repo_id, branch, fingerprint,
                         basis, finding.tool_name,
                         finding.rule_id, finding.level,
                         finding.message,
                         finding.artifact_uri,
                         finding.start_line,
                         finding.start_column,
                         wanted, row["commit_oid"],
                         wanted, row["commit_oid"],
                         now, now))
                    new.append(fingerprint)
                elif alert.state == "fixed":
                    self._conn.execute(
                        "UPDATE code_scanning_alerts"
                        " SET state = 'open', level = ?,"
                        " message = ?, artifact_uri = ?,"
                        " start_line = ?, start_column = ?,"
                        " last_seen_upload_id = ?,"
                        " last_seen_oid = ?,"
                        " fixed_upload_id = NULL,"
                        " fixed_oid = '',"
                        " times_seen = times_seen + 1,"
                        " updated_at = ? WHERE id = ?",
                        (finding.level, finding.message,
                         finding.artifact_uri,
                         finding.start_line,
                         finding.start_column,
                         wanted, row["commit_oid"],
                         now, alert.id))
                    reopened.append(fingerprint)
                else:
                    self._conn.execute(
                        "UPDATE code_scanning_alerts"
                        " SET level = ?, message = ?,"
                        " artifact_uri = ?,"
                        " start_line = ?, start_column = ?,"
                        " last_seen_upload_id = ?,"
                        " last_seen_oid = ?,"
                        " times_seen = times_seen + 1,"
                        " updated_at = ? WHERE id = ?",
                        (finding.level, finding.message,
                         finding.artifact_uri,
                         finding.start_line,
                         finding.start_column,
                         wanted, row["commit_oid"],
                         now, alert.id))
                    still_open.append(fingerprint)
            current = set(current_fps)
            for alert in standing:
                if alert.state == "open" \
                        and alert.fingerprint not in current:
                    self._conn.execute(
                        "UPDATE code_scanning_alerts"
                        " SET state = 'fixed',"
                        " fixed_upload_id = ?,"
                        " fixed_oid = ?,"
                        " times_fixed = times_fixed + 1,"
                        " updated_at = ? WHERE id = ?",
                        (wanted, row["commit_oid"],
                         now, alert.id))
                    fixed.append(alert.fingerprint)
            self._conn.execute(
                "INSERT INTO code_scanning_branch_heads"
                " (repo_id, branch, upload_id, oid,"
                " updated_at) VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(repo_id, branch) DO UPDATE"
                " SET upload_id = excluded.upload_id,"
                " oid = excluded.oid,"
                " updated_at = excluded.updated_at",
                (repo_id, branch, wanted,
                 row["commit_oid"], now))
        open_total = self._conn.execute(
            "SELECT COUNT(*) AS n FROM"
            " code_scanning_alerts WHERE repo_id = ?"
            " AND branch = ? AND state = 'open'",
            (repo_id, branch)).fetchone()["n"]
        return {
            "upload": wanted, "oid": row["commit_oid"],
            "ref": row["ref"], "branch": branch,
            "findings": len(extracted),
            "duplicates_collapsed": duplicates,
            "new": sorted(new),
            "reopened": sorted(reopened),
            "still_open": sorted(still_open),
            "fixed": sorted(fixed),
            "open_alerts": int(open_total),
        }

    # -- reading -------------------------------------

    def list_alerts(self, header: object, owner: object,
                    repo: object, branch: object = None,
                    state: object = None) -> dict:
        """Every code-scanning alert standing in
        one repository -- narrowed by branch and by
        state where the caller names them -- newest
        first, as data. The caller is judged at the
        read rung: a missing or unreadable
        repository is the one `repo_not_found`; a
        state outside `open` / `fixed` is refused
        `payload_invalid`."""
        identity = self._caller(header, required=False)
        authz = self._authorize(identity, owner, repo, "read")
        if state is not None and state not in ALERT_STATES:
            raise CodeScanningAlertsError(
                "payload_invalid",
                "payload_invalid -- a code-scanning "
                "alert state is open or fixed. Nothing "
                "was recorded.")
        clauses = ["repo_id = ?"]
        params: list = [authz.repository.id]
        if branch is not None:
            clauses.append("branch = ?")
            params.append(branch_of(branch))
        if state is not None:
            clauses.append("state = ?")
            params.append(str(state))
        rows = self._conn.execute(
            "SELECT * FROM code_scanning_alerts WHERE "
            + " AND ".join(clauses) + " ORDER BY id DESC",
            params).fetchall()
        records = [self._row(r) for r in rows]
        return {
            "branch": None if branch is None
            else branch_of(branch),
            "state": state,
            "total": len(records),
            "returned": len(records),
            "complete": True,
            "alerts": [alert_to_dict(r) for r in records],
        }

    def get_alert(self, header: object, owner: object,
                  repo: object, alert_id: object) -> dict:
        """One code-scanning alert, whole. The
        caller is judged at the read rung, as for
        listings; an id that stands in no
        repository the caller may read -- or in
        none at all -- is
        `code_scanning_alert_not_found`."""
        identity = self._caller(header, required=False)
        authz = self._authorize(identity, owner, repo, "read")
        try:
            wanted = int(alert_id)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise CodeScanningAlertsError(
                "code_scanning_alert_not_found",
                "code_scanning_alert_not_found -- no "
                "such code-scanning alert.") from None
        row = self._conn.execute(
            "SELECT * FROM code_scanning_alerts"
            " WHERE repo_id = ? AND id = ?",
            (authz.repository.id, wanted)).fetchone()
        if row is None:
            raise CodeScanningAlertsError(
                "code_scanning_alert_not_found",
                "code_scanning_alert_not_found -- no "
                "such code-scanning alert.")
        return alert_to_dict(self._row(row))

    # -- JSON forms ----------------------------------

    def process_upload_json(self, header: object,
                            owner: object, repo: object,
                            upload_id: object) -> str:
        return to_json(self.process_upload(
            header, owner, repo, upload_id))

    def list_alerts_json(self, header: object,
                         owner: object, repo: object,
                         branch: object = None,
                         state: object = None) -> str:
        return to_json(self.list_alerts(
            header, owner, repo, branch=branch,
            state=state))

    def get_alert_json(self, header: object, owner: object,
                       repo: object,
                       alert_id: object) -> str:
        return to_json(self.get_alert(
            header, owner, repo, alert_id))


# ------------------------------------------------------------------
# Rendering (S-010 escaped; words, never colour alone)
# ------------------------------------------------------------------

def render_alert(record: CodeScanningAlert) -> str:
    """One alert as an HTML fragment: its branch
    and state said in words, its rule, level,
    message and location, its fingerprint basis,
    and the commits that first reported it, most
    recently reported it, and -- where it stands
    fixed -- first stopped reporting it. Every
    value escapes through S-010."""
    where = escape_html_text(record.artifact_uri) or "no location"
    if record.start_line:
        where += f" line {record.start_line}"
        if record.start_column:
            where += f" column {record.start_column}"
    parts = [
        '<div class="code-scanning-alert">',
        (f'<p class="code-scanning-alert-standing">Alert '
         f'#{record.id} on branch '
         f'{escape_html_text(record.branch) or "the unnamed branch"}'
         f' is {escape_html_text(record.state)}: '
         f'{escape_html_text(record.level)} from '
         f'{escape_html_text(record.tool_name)}'
         + (f' rule {escape_html_text(record.rule_id)}'
            if record.rule_id else "")
         + f' at {where}.</p>'),
        (f'<p class="code-scanning-alert-message">'
         f'{escape_html_text(record.message)}</p>'),
        (f'<p class="code-scanning-alert-fingerprint">'
         f'Fingerprint {escape_html_text(record.fingerprint)} '
         f'({escape_html_text(record.basis)} basis), first '
         f'reported by upload '
         f'{record.first_seen_upload_id} at commit '
         f'{escape_html_text(record.first_seen_oid)}, most '
         f'recently by upload {record.last_seen_upload_id} '
         f'at commit '
         f'{escape_html_text(record.last_seen_oid)}, seen '
         f'{record.times_seen} time(s).</p>'),
    ]
    if record.state == "fixed":
        parts.append(
            f'<p class="code-scanning-alert-fixed">First '
            f'not reported by upload '
            f'{record.fixed_upload_id} at commit '
            f'{escape_html_text(record.fixed_oid)}.</p>')
    parts.append("</div>")
    return "".join(parts)


def render_code_scanning_alerts_page() -> str:
    """Code scanning alerts, in plain words, where
    a scanner's author finds it: how a finding is
    fingerprinted, how transitions are computed
    per branch, and how alerts are read back."""
    parts = [
        "<h1>Code scanning alerts</h1>",
        "<p>Every SARIF result S-302 stores is a "
        "finding. A finding is fingerprinted across "
        "runs: where the scanner supplied SARIF "
        "partial fingerprints, those values under "
        "the tool and rule are the identity, and a "
        "finding that moves lines is still the one "
        "finding; where it supplied none, the "
        "fingerprint is the structural shape -- "
        "tool, rule, file, line, column and message "
        "-- and a finding that moves lines then "
        "reads as one fixed and one new.</p>",
        "<p>Processing one stored upload settles "
        "its branch's alerts against its findings: "
        "a fingerprint never seen on that branch is "
        "a new, open alert; one standing open is "
        "still open; one standing fixed that a run "
        "reports again is reopened; and an open "
        "alert the run no longer reports is fixed "
        "by that run, named by the upload and "
        "commit that first did not carry it. One "
        "branch's transitions never touch "
        "another's. Uploads are processed per "
        "branch in upload order: an upload older "
        "than the newest processed is refused, "
        "because its transitions would rewrite a "
        "newer run's verdicts.</p>",
        "<p>Alerts are read through the same API "
        "door that took the uploads, at the read "
        "rung, listed newest first and filtered by "
        "branch and state where named. Processing "
        "takes the write rung, like uploading. "
        "Alerts are derived from witnessed uploads "
        "and are not themselves audit events.</p>",
    ]
    return "\n".join(parts)
