"""Status and checks API (S-246).

Status and checks API -- external CI posts commit
statuses and check runs (consumed by S-157); identity
of the poster is scoped and audit-logged. S-237's
contract named this slice and stated both shapes;
S-157 built the panel's one record
(`commit_checks`) and named this slice as the seam
that posts through it. This module is that seam.

- **One record behind both faces.** A commit status
  IS an S-157 check result: posting a status calls
  `PullRequestChecksStore.record_result` and nothing
  else, so the status lands in the very row the
  checks panel lists and the required-checks gate
  (S-174) judges -- same context, same three states
  (`pending`, `failed`, `passed`), same validation,
  same re-report-updates-the-row law. There is no
  second status store for the panel to miss. A check
  run is the richer CI report (a name, a run status,
  and -- once completed -- a conclusion); it is kept
  in its own table (migration 95, `check_runs`) AND
  folded onto the same S-157 record under its name,
  with the panel state decided purely from
  (status, conclusion): queued and in-progress runs
  are `pending`, completed runs conclude `passed`
  on success / neutral / skipped and `failed` on
  failure / cancelled / timed_out / action_required.
  S-301 and S-321 build on exactly this fold.
- **The poster is scoped (S-238 + S-190).** Every
  call resolves through S-238's door
  (`ApiAuthenticator`) and nothing else. Posting is
  a write: the caller must be authenticated (a
  missing header is `authentication_required`,
  never an anonymous post), S-190's resolved role
  in the repository must cover `write` (a missing
  or unwritable repository is the one uniform
  `repo_not_found`), and a token credential must
  additionally carry the repo write scope -- a
  read-only token, or a fine-grained token bound
  to another repository, is refused
  `insufficient_scope`, checked only after S-190
  has answered. Reading is a read at the `read`
  rung under the same law, so a private
  repository's statuses are indistinguishable from
  a missing one's. Rate limiting stays the door's
  S-241 brake, as on every landed face.
- **The poster is audit-logged.** Every successful
  post appends exactly one audit entry naming the
  poster: `repo.status.post` for a status,
  `repo.check_run.post` for a check run (two
  S-246 additions to the taxonomy: 131 stand --
  33 auth / 85 repo / 13 admin), with the poster's
  username, credential kind and token id in the
  detail beside the commit, the context or name,
  and the state posted. The row itself carries the
  poster's username (`poster`, migration 95), so
  the panel's data and the log agree about who
  spoke. A re-post audits again -- every word an
  external system says is witnessed, not just the
  first. Refused posts store nothing and audit
  nothing.
- **Shapes are the contract's.** A status is
  S-237's contracted fields exactly (id, oid,
  state, context, description, target_url,
  poster, created_at); a check run is its
  contracted fields exactly (id, oid, name,
  status, conclusion, poster, created_at,
  updated_at -- an uncompleted run's conclusion
  is the empty string). Refusals are S-240's
  shape: every refusal is a
  `StatusChecksAPIError` with a machine-branchable
  reason -- S-238's reasons verbatim for
  authentication and scope, S-157's reasons
  verbatim for the record's own validation, this
  face's own for the check-run vocabulary --
  rendered by `error_to_dict` in the one problem
  format through samverk/error_shape.py.
- **Validation is whole.** A payload that is not
  an object, or carries a key this face does not
  know, is refused `payload_invalid` before
  anything is judged; a status validates through
  S-157's own law (`check_head_invalid`,
  `check_context_invalid`, `check_state_invalid`,
  `check_url_invalid`); a check run's name, commit,
  status and conclusion validate here
  (`check_name_invalid`, `check_head_invalid`,
  `check_status_invalid`,
  `check_conclusion_invalid` -- a conclusion on an
  unfinished run, and a completed run with no
  conclusion, are both refused whole). Nothing
  partial is ever stored.
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
from .issues import IssueStore
from .pull_request_checks import PullRequestChecksStore
from .pull_requests import PullRequestError
from .repositories import RepositoryStore

__all__ = [
    "CHECK_RUNS_API_PATH", "CHECK_RUN_CONCLUSIONS",
    "CHECK_RUN_STATUSES", "PANEL_STATE_BY_CONCLUSION",
    "STATUS_API_PATH", "StatusChecksAPI",
    "StatusChecksAPIError", "check_run_to_dict",
    "decide_check_run_panel_state",
    "decide_check_run_payload", "decide_status_payload",
    "error_to_dict", "render_api_checks_page",
    "status_to_dict", "to_json",
]

STATUS_API_PATH = "/api/v1/repos/{owner}/{repo}/statuses/{oid}"
CHECK_RUNS_API_PATH = "/api/v1/repos/{owner}/{repo}/check-runs"

#: The run statuses a check run may carry -- the
#: CI vocabulary, and no others.
CHECK_RUN_STATUSES = ("queued", "in_progress", "completed")

#: The conclusions a completed check run may carry.
CHECK_RUN_CONCLUSIONS = (
    "success", "failure", "neutral", "cancelled",
    "skipped", "timed_out", "action_required")

#: A completed run's conclusion, folded onto
#: S-157's three panel states.
PANEL_STATE_BY_CONCLUSION = {
    "success": "passed", "neutral": "passed",
    "skipped": "passed", "failure": "failed",
    "cancelled": "failed", "timed_out": "failed",
    "action_required": "failed",
}

_STATUS_KEYS = frozenset(
    {"state", "context", "description", "target_url"})
_CHECK_RUN_KEYS = frozenset(
    {"oid", "name", "status", "conclusion",
     "target_url", "description"})
_REPO_NOT_FOUND = "No such repository."


class StatusChecksAPIError(ValueError):
    """One refused status/checks-API call: a
    machine-branchable reason with its human
    detail."""

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def error_to_dict(exc: StatusChecksAPIError) -> dict:
    """One refusal as data, in S-240's one problem
    format (samverk/error_shape.py): type, title,
    status, detail, error_id -- nothing else."""
    return problem_to_dict(problem_from_error(exc))


def to_json(payload: dict) -> str:
    """One payload as a JSON text: keys sorted so
    the same answer renders byte-identically
    twice."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def decide_check_run_panel_state(status: object,
                                 conclusion: object) -> str:
    """The S-157 panel state one check run folds
    onto: an unfinished run is `pending`; a
    completed run is `passed` or `failed` by its
    conclusion's word. Pure: the caller validates
    the vocabulary first."""
    if status != "completed":
        return "pending"
    return PANEL_STATE_BY_CONCLUSION[str(conclusion)]


def decide_status_payload(payload: object) -> dict:
    """One status payload, judged whole: it must
    be an object carrying only the keys a status
    knows, with a state and a context (their own
    words are S-157's law, judged by the record).
    Returns the normalised report. Pure."""
    if not isinstance(payload, dict):
        raise StatusChecksAPIError(
            "payload_invalid",
            "payload_invalid -- a status posts as an "
            "object of fields. Nothing was recorded.")
    unknown = set(payload) - _STATUS_KEYS
    if unknown:
        raise StatusChecksAPIError(
            "payload_invalid",
            "payload_invalid -- a status knows only "
            "state, context, description and "
            "target_url. Nothing was recorded.")
    return {
        "state": payload.get("state", "pending"),
        "context": payload.get("context"),
        "description": payload.get("description", ""),
        "target_url": payload.get("target_url", ""),
    }


def decide_check_run_payload(payload: object) -> dict:
    """One check-run payload, judged whole: an
    object carrying only the keys a check run
    knows, a commit and a name, a status in the
    run vocabulary, and a conclusion exactly when
    the run is completed. Returns the normalised
    report, with its folded panel state. Pure."""
    if not isinstance(payload, dict):
        raise StatusChecksAPIError(
            "payload_invalid",
            "payload_invalid -- a check run posts as "
            "an object of fields. Nothing was recorded.")
    unknown = set(payload) - _CHECK_RUN_KEYS
    if unknown:
        raise StatusChecksAPIError(
            "payload_invalid",
            "payload_invalid -- a check run knows "
            "only oid, name, status, conclusion, "
            "target_url and description. Nothing "
            "was recorded.")
    oid = payload.get("oid")
    if not isinstance(oid, str) or not oid.strip():
        raise StatusChecksAPIError(
            "check_head_invalid",
            "check_head_invalid -- a check run names "
            "the commit it ran on. Nothing was recorded.")
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        raise StatusChecksAPIError(
            "check_name_invalid",
            "check_name_invalid -- a check run names "
            "its check. Nothing was recorded.")
    status = payload.get("status", "queued")
    if status not in CHECK_RUN_STATUSES:
        raise StatusChecksAPIError(
            "check_status_invalid",
            f"check_status_invalid -- {status!r} is "
            "not a check-run status: a status is "
            "queued, in_progress or completed. "
            "Nothing was recorded.")
    conclusion = payload.get("conclusion") or ""
    if status == "completed":
        if conclusion not in CHECK_RUN_CONCLUSIONS:
            raise StatusChecksAPIError(
                "check_conclusion_invalid",
                "check_conclusion_invalid -- a "
                "completed check run concludes: "
                "success, failure, neutral, cancelled, "
                "skipped, timed_out or action_required. "
                "Nothing was recorded.")
    elif conclusion:
        raise StatusChecksAPIError(
            "check_conclusion_invalid",
            "check_conclusion_invalid -- an "
            "unfinished check run has no conclusion "
            "yet. Nothing was recorded.")
    return {
        "oid": oid, "name": name, "status": status,
        "conclusion": conclusion,
        "target_url": payload.get("target_url", ""),
        "description": payload.get("description", ""),
        "panel_state": decide_check_run_panel_state(
            status, conclusion),
    }


@dataclass(frozen=True)
class StatusRecord:
    """One posted commit status, as the wire
    carries it: S-157's row plus its poster."""
    id: int
    oid: str
    state: str
    context: str
    description: str
    target_url: str
    poster: str
    created_at: int
    updated_at: int


@dataclass(frozen=True)
class CheckRunRecord:
    """One posted check run, as the wire carries
    it: the run's own vocabulary plus its poster."""
    id: int
    oid: str
    name: str
    status: str
    conclusion: str
    poster: str
    created_at: int
    updated_at: int


def status_to_dict(record: StatusRecord) -> dict:
    """One status as JSON-safe data, in S-237's
    contracted field order exactly: id, oid,
    state, context, description, target_url,
    poster, created_at. Data carries the raw
    values -- S-010 escaping is the page's law,
    not the wire's."""
    return {
        "id": record.id,
        "oid": record.oid,
        "state": record.state,
        "context": record.context,
        "description": record.description,
        "target_url": record.target_url,
        "poster": record.poster,
        "created_at": record.created_at,
    }


def check_run_to_dict(record: CheckRunRecord) -> dict:
    """One check run as JSON-safe data, in
    S-237's contracted field order exactly: id,
    oid, name, status, conclusion, poster,
    created_at, updated_at."""
    return {
        "id": record.id,
        "oid": record.oid,
        "name": record.name,
        "status": record.status,
        "conclusion": record.conclusion,
        "poster": record.poster,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


class StatusChecksAPI:
    """The S-246 face: external CI posts commit
    statuses and check runs through S-238's door,
    onto S-157's one record, witnessed by the
    audit log. It owns no permission law and no
    check vocabulary of its own beyond the
    check-run words."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        accounts: AccountStore,
        repositories: RepositoryStore,
        issues: IssueStore,
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
        self._checks = PullRequestChecksStore(
            conn, repositories, accounts, issues,
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
            raise StatusChecksAPIError(
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
            raise StatusChecksAPIError(
                exc.reason, str(exc)) from None

    def _witness(self, identity: ApiIdentity, action: str,
                 full_name: str, detail: dict) -> None:
        """One successful post, audit-logged with
        its poster's scoped identity: who posted,
        by what credential, and what was said."""
        if self._audit is None or identity.user is None:
            return
        self._audit.append(
            actor_kind="user", actor_id=identity.user.id,
            action=action, target_kind="repository",
            target_id=full_name, outcome="success",
            detail={
                "poster": identity.username,
                "credential": identity.kind,
                "token_id": identity.token_id,
                **detail,
            })

    # -- statuses ----------------------------------

    def _status_row(self, row_id: int) -> StatusRecord:
        row = self._conn.execute(
            "SELECT * FROM commit_checks WHERE id = ?",
            (row_id,)).fetchone()
        return StatusRecord(
            id=row["id"], oid=row["head_oid"],
            state=row["state"], context=row["context"],
            description=row["description"],
            target_url=row["target_url"],
            poster=row["poster"],
            created_at=row["created_at"],
            updated_at=row["updated_at"])

    def post_status(self, header: object, owner: object,
                    repo: object, oid: object,
                    payload: object) -> dict:
        """Post one commit status: the caller must
        hold write on the repository (S-190, with
        the token scope as its ceiling); the report
        validates through S-157's own law and lands
        on S-157's record; the poster is stamped on
        the row and witnessed in the audit log.
        Answers the status as data."""
        identity = self._caller(header, required=True)
        authz = self._authorize(identity, owner, repo, "write")
        report = decide_status_payload(payload)
        try:
            recorded = self._checks.record_result(
                owner, repo, oid, report["context"],
                report["state"],
                target_url=report["target_url"],
                description=report["description"])
        except PullRequestError as exc:
            raise StatusChecksAPIError(
                exc.reason, str(exc)) from None
        poster = identity.username or ""
        with self._conn:
            self._conn.execute(
                "UPDATE commit_checks SET poster = ?"
                " WHERE id = ?", (poster, recorded.id))
        record = self._status_row(recorded.id)
        self._witness(
            identity, "repo.status.post",
            authz.repository.full_name,
            {"oid": record.oid, "context": record.context,
             "state": record.state})
        return status_to_dict(record)

    def list_statuses(self, header: object, owner: object,
                      repo: object, oid: object) -> dict:
        """Every status posted for one commit in
        one repository, in the order they first
        landed -- S-157's panel rows as data. The
        caller is judged at the read rung: a
        missing or unreadable repository is the
        one `repo_not_found`."""
        identity = self._caller(header, required=False)
        authz = self._authorize(identity, owner, repo, "read")
        rows = self._conn.execute(
            "SELECT * FROM commit_checks"
            " WHERE repo_id = ? AND head_oid = ? ORDER BY id",
            (authz.repository.id, str(oid))).fetchall()
        records = [
            StatusRecord(
                id=r["id"], oid=r["head_oid"],
                state=r["state"], context=r["context"],
                description=r["description"],
                target_url=r["target_url"],
                poster=r["poster"],
                created_at=r["created_at"],
                updated_at=r["updated_at"])
            for r in rows]
        return {
            "oid": str(oid),
            "total": len(records),
            "returned": len(records),
            "complete": True,
            "statuses": [status_to_dict(r) for r in records],
        }

    # -- check runs --------------------------------

    def _run_row(self, row_id: int) -> CheckRunRecord:
        row = self._conn.execute(
            "SELECT * FROM check_runs WHERE id = ?",
            (row_id,)).fetchone()
        return CheckRunRecord(
            id=row["id"], oid=row["head_oid"],
            name=row["name"], status=row["status"],
            conclusion=row["conclusion"],
            poster=row["poster"],
            created_at=row["created_at"],
            updated_at=row["updated_at"])

    def post_check_run(self, header: object, owner: object,
                       repo: object, payload: object) -> dict:
        """Post or update one check run: the caller
        is judged exactly as for a status; the run
        validates whole here, folds onto S-157's
        record under its name at its decided panel
        state, and is kept in `check_runs` in its
        own vocabulary, poster stamped, the post
        witnessed in the audit log. Answers the
        run as data."""
        identity = self._caller(header, required=True)
        authz = self._authorize(identity, owner, repo, "write")
        report = decide_check_run_payload(payload)
        try:
            self._checks.record_result(
                owner, repo, report["oid"], report["name"],
                report["panel_state"],
                target_url=report["target_url"],
                description=report["description"])
        except PullRequestError as exc:
            raise StatusChecksAPIError(
                exc.reason, str(exc)) from None
        poster = identity.username or ""
        now = int(self._now())
        repo_id = authz.repository.id
        with self._conn:
            row = self._conn.execute(
                "SELECT * FROM check_runs"
                " WHERE repo_id = ? AND head_oid = ?"
                " AND name = ?",
                (repo_id, report["oid"],
                 report["name"])).fetchone()
            if row is None:
                cur = self._conn.execute(
                    "INSERT INTO check_runs"
                    " (repo_id, head_oid, name, status,"
                    " conclusion, poster, target_url,"
                    " description, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (repo_id, report["oid"], report["name"],
                     report["status"], report["conclusion"],
                     poster, str(report["target_url"] or ""),
                     str(report["description"] or ""),
                     now, now))
                row_id = int(cur.lastrowid)
            else:
                self._conn.execute(
                    "UPDATE check_runs SET status = ?,"
                    " conclusion = ?, poster = ?,"
                    " target_url = ?, description = ?,"
                    " updated_at = ? WHERE id = ?",
                    (report["status"], report["conclusion"],
                     poster, str(report["target_url"] or ""),
                     str(report["description"] or ""),
                     now, row["id"]))
                row_id = int(row["id"])
            self._conn.execute(
                "UPDATE commit_checks SET poster = ?"
                " WHERE repo_id = ? AND head_oid = ?"
                " AND context = ?",
                (poster, repo_id, report["oid"],
                 report["name"]))
        record = self._run_row(row_id)
        self._witness(
            identity, "repo.check_run.post",
            authz.repository.full_name,
            {"oid": record.oid, "name": record.name,
             "status": record.status,
             "conclusion": record.conclusion})
        return check_run_to_dict(record)

    def list_check_runs(self, header: object, owner: object,
                        repo: object,
                        oid: object = None) -> dict:
        """Every check run posted in one repository
        -- or, with a commit named, that commit's
        runs -- in the order they first landed.
        The caller is judged at the read rung, as
        for statuses."""
        identity = self._caller(header, required=False)
        authz = self._authorize(identity, owner, repo, "read")
        if oid is None:
            rows = self._conn.execute(
                "SELECT * FROM check_runs"
                " WHERE repo_id = ? ORDER BY id",
                (authz.repository.id,)).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM check_runs"
                " WHERE repo_id = ? AND head_oid = ?"
                " ORDER BY id",
                (authz.repository.id, str(oid))).fetchall()
        records = [
            CheckRunRecord(
                id=r["id"], oid=r["head_oid"],
                name=r["name"], status=r["status"],
                conclusion=r["conclusion"],
                poster=r["poster"],
                created_at=r["created_at"],
                updated_at=r["updated_at"])
            for r in rows]
        return {
            "total": len(records),
            "returned": len(records),
            "complete": True,
            "check_runs": [check_run_to_dict(r) for r in records],
        }

    # -- JSON forms --------------------------------

    def post_status_json(self, header: object, owner: object,
                         repo: object, oid: object,
                         payload: object) -> str:
        return to_json(self.post_status(
            header, owner, repo, oid, payload))

    def post_check_run_json(self, header: object,
                            owner: object, repo: object,
                            payload: object) -> str:
        return to_json(self.post_check_run(
            header, owner, repo, payload))


def render_api_checks_page() -> str:
    """The status and checks API, in plain words,
    where a script's author finds it: who may post,
    what a post must carry, how check runs fold
    onto the panel, and how the poster is
    witnessed. Every value escaped through
    S-010."""
    parts = [
        "<h1>Status and checks API</h1>",
        "<p>External CI reports against a commit "
        "under /api/v1: POST a status to a "
        "commit's statuses, or POST a check run, "
        "and read either back as data. A status is "
        "one check result -- a context, a state "
        "(pending, failed or passed), a one-line "
        "description and a details link; a check "
        "run is the richer report -- a name, a "
        "status (queued, in_progress or "
        "completed) and, once completed, a "
        "conclusion. Both land on the one record "
        "the pull-request checks panel lists "
        "(S-157): a check run folds onto it under "
        "its name, unfinished runs as pending, "
        "completed runs as passed or failed by "
        "their conclusion.</p>",
        "<p>Posting takes a credential and write "
        "standing on the repository, judged by "
        "the permission engine (S-190) through "
        "the API door (S-238): a token narrows "
        "its owner, never widens, so a read-only "
        "token cannot post. Every post is "
        "audit-logged with its poster's name and "
        "credential, and the posted row carries "
        "that name as its poster. Reading takes "
        "read standing; a repository you may not "
        "read answers exactly as one that does "
        "not exist.</p>",
        "<p>Refusals speak the one problem format "
        "(S-240): type, title, status, detail and "
        "error id, with the door's reasons for "
        "sign-in and scope, the record's reasons "
        "for a status that cannot be understood, "
        "and this face's reasons for a check run "
        "whose status or conclusion is not in "
        "its vocabulary.</p>",
    ]
    return "\n".join(parts)
