"""Error shape (S-240).

One problem format (type, title, status, detail,
error id) across all endpoints; the web UI's
refusals match it. S-237's contract recorded the
target fields and named this slice to land them;
S-238, S-239, S-216 and S-231 each stated honestly
that their two-field refusal (`error`, `detail`)
was not yet it. This module is the one place the
format lives, and every refusal surface derives
from it, so the surfaces cannot drift apart:

- the API faces (S-238 auth, S-239 pagination,
  S-231 events, S-216 search) render their
  refusals through `problem_from_error` in their
  own `error_to_dict`;
- the server's S-019 body (`public_error_body`)
  renders through `problem_for_public_code`, so
  the JSON a browser client receives is the same
  format a script receives;
- the web UI's designed error states (S-113, in
  `page_states`) take their titles and messages
  from this module's canonical words for the
  S-019 codes, and `render_problem_page` renders
  one problem as a page carrying the same title,
  status, detail and error id the wire carries.

- **The five fields, nothing else.** `type` is
  the problem's stable address,
  `/api/v1/problems/<reason>`, where the reason
  is the machine-branchable name a caller already
  branches on (the faces' own reasons, verbatim).
  `title` is that reason's one plain-words title
  from the registry below -- a summary that does
  not change from occurrence to occurrence.
  `status` is the HTTP status the registry maps
  the reason to. `detail` is the occurrence's
  own human sentence (the raising error's
  message, which the faces already write in
  plain words). `error_id` is S-019's opaque id
  (CSPRNG hex, encoding nothing), minted fresh
  per refusal, so a user can quote it and an
  operator can find the failure in the server
  log under the same id -- and it identifies
  nothing else.
- **The registry is the status law.** Every
  reason the API faces raise is registered here
  with its status and title; the battery holds
  the faces to that list. A reason nobody
  registered still renders -- a refusal must
  never crash while being refused -- through
  the pure fallback in `decide_problem_status`:
  the name's own suffix law (`*_not_found` is
  404, `*_invalid` and its kin are 400,
  permission and sign-in names are 403 / 401,
  `*_taken` and `already_*` are 409), with the
  generic title of its status. Registered is
  the proven road; the fallback is the honest
  floor, and it invents no private fact either.
- **Leakage law is unchanged (S-019 / S-209).**
  A problem carries the reason, its public
  title, the status, the caller's own detail
  sentence, and an opaque id -- never a stack
  trace, a path, an exception's private text,
  or any fact about a resource the caller may
  not read: a missing repository and an
  unreadable one remain the one `repo_not_found`
  problem, identical in type, title, status and
  detail, differing only in the error id every
  refusal mints. Successful responses are
  untouched: this module shapes refusals only.
- **A read that witnesses nothing.** Shaping a
  refusal writes no row and audits nothing.
  No migration (schema stays 94), no taxonomy
  event (129 stand: 33 auth / 83 repo / 13
  admin).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .api_contract import PROBLEM_FIELDS
from .errors import new_error_id
from .escaping import escape_html_text

__all__ = [
    "ERROR_SHAPE_PATH", "PROBLEM_FIELDS", "PROBLEM_TYPE_BASE",
    "STATUS_TITLES", "ErrorShapeError", "Problem",
    "canonical_public_words", "decide_problem_status",
    "is_registered_reason", "problem_for_public_code",
    "problem_from_error", "problem_title_for", "problem_to_dict",
    "problem_type_for", "registered_reasons",
    "render_error_shape_page", "render_problem_page",
]

ERROR_SHAPE_PATH = "/api/error-shape"
PROBLEM_TYPE_BASE = "/api/v1/problems/"

_REASON_SHAPE = re.compile(r"^[a-z][a-z0-9_]*$")


class ErrorShapeError(ValueError):
    """One unshapeable refusal: a reason that is
    not a machine-branchable name at all."""

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


# The generic title of each status the fallback
# can land on: plain words, true of any refusal
# that carries that status.
STATUS_TITLES = {
    400: "That request could not be understood",
    401: "Sign-in needed",
    403: "That action is not allowed",
    404: "That could not be found",
    405: "That action is not available here",
    409: "That change conflicts with what is already there",
    429: "Too many requests just now",
    500: "Something went wrong on our side",
}

# reason -> (status, title). The S-019 public
# codes first (their titles are the web UI's own
# designed titles, S-113), then the API faces'
# reasons, each face's own set, verbatim.
_PROBLEM_REGISTRY: dict[str, tuple[int, str]] = {
    # S-019 public codes (server + web UI)
    "bad_request": (400, "That request could not be understood"),
    "csrf_failed": (403, "That form could not be accepted"),
    "internal": (500, "Something went wrong on our side"),
    "method_not_allowed": (405, "That action is not available here"),
    "not_found": (404, "That page could not be found"),
    "rate_limited": (429, "Too many requests just now"),
    "unauthorized": (401, "Sign-in needed"),
    # S-238 -- API authentication
    "authentication_required": (401, "Sign-in needed"),
    "credentials_invalid": (401, "That credential does not authenticate"),
    "scheme_unsupported": (400, "That authentication scheme is not supported"),
    "insufficient_scope": (
        403, "That token does not carry the scope for this call"),
    "resource_unknown": (404, "No such API resource"),
    "role_invalid": (400, "No such permission rung"),
    # S-239 -- API pagination and conditional requests
    "cursor_invalid": (400, "That cursor does not name a page"),
    "page_size_invalid": (400, "That page size is not allowed"),
    "header_invalid": (400, "That header could not be understood"),
    "ordering_invalid": (500, "Something went wrong on our side"),
    "payload_not_json": (500, "Something went wrong on our side"),
    # S-231 -- events API (its own reasons, plus the
    # stores' reasons it carries verbatim)
    "limit_invalid": (400, "That limit is not allowed"),
    "filter_invalid": (400, "That filter could not be understood"),
    "repo_not_found": (404, "No such repository"),
    "event_not_found": (404, "No such event"),
    "no_such_user": (404, "No such user"),
    # S-216 -- search API (the engine's reasons,
    # carried verbatim)
    "query_invalid": (400, "That search could not be understood"),
    "auth_required": (401, "Sign-in needed"),
    "recent_not_found": (404, "No such recent search"),
    # S-237 -- the contract's own refusals
    "rule_unknown": (404, "No such API contract rule"),
    # S-241 -- API rate limiting (its refusal rides the
    # S-019 rate_limited registration above, at 429)
    "rate_settings_invalid": (
        400, "That rate-limit setting is not allowed"),
    # S-242 -- repositories API (its own reasons, plus
    # the web stores' reasons it carries verbatim)
    "payload_invalid": (
        400, "That request body could not be understood"),
    "repo_taken": (409, "That repository name is already taken"),
    "repo_path_exists": (
        409, "A directory already exists at that path"),
    "repo_invalid": (400, "That repository name is not valid"),
    "description_invalid": (400, "That description is not allowed"),
    "visibility_invalid": (400, "That visibility is not allowed"),
    "branch_invalid": (400, "That branch name is not valid"),
    "not_repo_owner": (
        403, "Only the repository's owner can do that"),
    "git_init_failed": (500, "Something went wrong on our side"),
    "git_head_failed": (500, "Something went wrong on our side"),
    "git_clone_failed": (500, "Something went wrong on our side"),
    "fork_visibility_escalation": (
        400, "That fork would widen a repository's visibility"),
    "ref_not_found": (404, "No such ref"),
    "ref_invalid": (400, "That ref is not valid"),
    "path_not_found": (404, "No such path"),
    "path_invalid": (400, "That path is not valid"),
    "not_a_file": (400, "That path is not a file"),
    "already_pending": (409, "That is already scheduled"),
    "sudo_required": (403, "A fresh confirmation is needed"),
    "content_too_large": (413, "That content is too large to return"),
    "object_not_found": (404, "No such object"),
    "wrong_type": (400, "That object is not the kind asked for"),
    # S-243 -- issues and PRs API (its own reasons,
    # plus the web stores' reasons it carries
    # verbatim)
    "issue_not_found": (404, "No such issue"),
    "pull_request_not_found": (
        404, "No such pull request"),
    "comment_not_found": (404, "No such comment"),
    "label_not_found": (404, "No such label"),
    "milestone_not_found": (404, "No such milestone"),
    "base_not_found": (404, "No such base branch"),
    "head_not_found": (404, "No such head branch"),
    "head_repo_not_found": (
        404, "No such head repository"),
    "file_not_found": (404, "No such file"),
    "title_required": (400, "An issue needs a title"),
    "title_invalid": (400, "That title is not valid"),
    "body_invalid": (400, "That body is not valid"),
    "state_invalid": (400, "That state is not valid"),
    "reason_invalid": (400, "That reason is not valid"),
    "permission_denied": (
        403, "That action is not allowed"),
    "edit_conflict": (
        409, "That edit conflicts with a newer change"),
    "blank_issue_not_allowed": (
        400, "Blank issues are turned off here"),
    "conversation_locked": (
        403, "That conversation is locked"),
    "comment_required": (
        400, "A comment needs some text"),
    "comment_invalid": (400, "That comment is not valid"),
    "same_branch": (
        400, "The base and head branches are the same"),
    "no_commits": (400, "There is nothing to propose"),
    "already_exists": (409, "That already exists"),
    "verdict_invalid": (
        400, "That review verdict is not valid"),
    "summary_invalid": (
        400, "That review summary is not valid"),
    "summary_required": (
        400, "Requesting changes needs a summary"),
    "self_review": (
        403, "You cannot review your own pull request"),
    "pull_request_closed": (
        409, "That pull request is closed"),
    "pull_request_draft": (
        409, "That pull request is a draft"),
    "already_merged": (409, "That is already merged"),
    "unrelated_history": (
        400, "Those branches share no history"),
    "merge_conflict": (409, "That merge conflicts"),
    "message_invalid": (
        400, "That merge message is not valid"),
    "merge_failed": (500, "Something went wrong on our side"),
    "assignee_cannot_read": (
        400, "That account cannot see this repository"),
    "assignee_limit": (
        400, "That issue has all the assignees it may carry"),
    "object_unreadable": (
        500, "Something went wrong on our side"),
    # S-244 -- users, orgs, teams API (its own reasons,
    # plus the web stores' reasons it carries
    # verbatim)
    "org_not_found": (404, "No such organization"),
    "team_not_found": (404, "No such team"),
    "parent_not_found": (404, "No such parent team"),
    "not_a_member": (404, "No such organization member"),
    "not_team_member": (404, "No such team member"),
    "not_collaborator": (
        404, "No such outside collaborator"),
    "not_linked": (
        404, "That repository is not linked to this team"),
    "org_invalid": (
        400, "That organization name is not valid"),
    "org_reserved": (
        400, "That organization name is reserved"),
    "org_name_is_user": (
        409, "That name belongs to a user account"),
    "org_taken": (
        409, "That organization name is already taken"),
    "display_name_invalid": (
        400, "That display name is not valid"),
    "display_name_too_long": (
        400, "That display name is too long"),
    "bio_invalid": (400, "That bio is not valid"),
    "bio_too_long": (400, "That bio is too long"),
    "website_invalid": (400, "That website is not valid"),
    "not_org_steward": (
        403, "Only the organization's steward or a "
        "site admin can do that"),
    "not_org_owner": (
        403, "Only an organization owner or a site "
        "admin can do that"),
    "not_repo_admin": (
        403, "Only a repository administrator can do that"),
    "last_owner": (
        409, "An organization must keep at least one owner"),
    "last_admin": (
        409, "That would leave the repository with "
        "no administrator"),
    "already_member": (
        409, "That person is already a member"),
    "already_team_member": (
        409, "That person is already in this team"),
    "already_linked": (
        409, "That repository is already linked to this team"),
    "already_collaborator": (
        409, "That person already holds a grant here"),
    "already_owner": (
        409, "That person already owns this repository"),
    "team_invalid": (400, "That team name is not valid"),
    "team_too_long": (400, "That team name is too long"),
    "team_taken": (409, "That team name is already taken"),
    "privacy_invalid": (
        400, "That team privacy is not valid"),
    "parent_not_in_org": (
        400, "That parent team is in another organization"),
    "repo_not_in_org": (
        400, "That repository is in another organization"),
    "not_org_member": (
        400, "That person is not a member of the organization"),
    "description_too_long": (
        400, "That description is too long"),
    # S-246 -- status and checks API (its own
    # reasons, plus S-157's record reasons it
    # carries verbatim)
    "check_name_invalid": (
        400, "That check name is not valid"),
    "check_status_invalid": (
        400, "That check status is not valid"),
    "check_conclusion_invalid": (
        400, "That check conclusion is not valid"),
    "check_state_invalid": (
        400, "That check state is not valid"),
    "check_context_invalid": (
        400, "That check context is not valid"),
    "check_head_invalid": (
        400, "That commit could not be understood"),
    "check_url_invalid": (
        400, "That check link is not valid"),
    # S-266 -- CI artifacts API (its own reasons,
    # plus S-012's upload reasons it carries and
    # S-246's check reasons it reuses verbatim)
    "artifact_not_found": (404, "No such artifact"),
    "artifact_taken": (
        409, "That artifact name is already taken"),
    "artifact_expired": (
        410, "That artifact has expired"),
    "artifact_missing": (
        500, "Something went wrong on our side"),
    "artifact_name_required": (
        400, "An artifact needs a name"),
    "artifact_name_invalid": (
        400, "That artifact name is not valid"),
    "check_run_not_found": (404, "No such check run"),
    "retention_invalid": (
        400, "That retention policy is not allowed"),
    "too_many_artifacts": (
        409, "That check run carries too many artifacts"),
    "upload_not_found": (404, "No such upload"),
    "upload_closed": (400, "That upload is no longer open"),
    "chunk_empty": (400, "That chunk carries no bytes"),
    "chunk_too_large": (413, "That chunk is too large"),
    "chunk_out_of_order": (
        400, "That chunk is not the next one expected"),
    "size_invalid": (400, "That size is not valid"),
    "size_mismatch": (
        400, "That upload does not match its declared size"),
    "too_large": (413, "That artifact is too large"),
    "empty": (400, "That artifact carries no bytes"),
    # S-255 -- API abuse defences (its own reasons;
    # the refusals every S-255 judgement raises)
    "payload_too_large": (
        413, "That request body is too large"),
    "payload_size_invalid": (
        400, "That payload size could not be understood"),
    "concurrency_limit_exceeded": (
        429, "Too many calls in flight just now"),
    "abuse_settings_invalid": (
        400, "That abuse-defence setting is not allowed"),
    "endpoint_unknown": (404, "No such API endpoint"),
    "lease_invalid": (
        400, "That concurrency lease is not valid"),
    # S-271 -- download integrity (its own reasons;
    # every other reason it raises is a door store
    # reason carried verbatim)
    "range_invalid": (
        400, "That range could not be understood"),
    "range_not_satisfiable": (
        416, "That range cannot be served from this file"),
}

# The canonical detail sentence of each S-019
# public code: the web UI's designed message
# (S-113), word for word, so a problem for a
# public code and the error page for the same
# code say the same thing in title and detail.
_PUBLIC_DETAILS: dict[str, str] = {
    "bad_request": (
        "Something about the request was malformed, so nothing "
        "was changed."),
    "csrf_failed": (
        "The form's safety token did not check out, so nothing "
        "was changed. This can happen if the page sat open a "
        "long while."),
    "internal": (
        "The server hit an unexpected problem and could not "
        "finish. Your data was not changed by this failure."),
    "method_not_allowed": (
        "The address is real, but it does not accept the kind "
        "of request that was sent to it."),
    "not_found": (
        "It may not exist, or it may belong to a repository "
        "you do not have permission to see — the answer is the "
        "same either way."),
    "rate_limited": (
        "This instance limits how fast requests may arrive, "
        "and that limit was reached. Nothing was changed."),
    "unauthorized": (
        "This page or action needs a signed-in account, or "
        "the sign-in has expired."),
}


def _check_reason(reason: object) -> str:
    if not isinstance(reason, str) or not _REASON_SHAPE.match(reason):
        raise ErrorShapeError(
            "reason_invalid",
            f"No problem can be shaped for reason {reason!r}: a "
            "reason is a lower-case machine-branchable name.")
    return reason


def decide_problem_status(reason: str) -> int:
    """The HTTP status of one refusal *reason*:
    the registry's mapping where the reason is
    registered, else the pure suffix law -- the
    name's own ending judges it (`*_not_found`
    404, `*_invalid` / `*_required` / `*_unknown`
    / `*_unsupported` 400, permission names 403,
    sign-in names 401, `*_taken` / `already_*`
    409), and a name no rule claims is a 400, the
    caller's request being the thing that failed.
    Pure: no storage is read here."""
    registered = _PROBLEM_REGISTRY.get(reason)
    if registered is not None:
        return registered[0]
    if reason.endswith("_not_found") or reason == "not_found":
        return 404
    if (reason.startswith("authentication")
            or reason in ("auth_required", "login_required")
            or reason.startswith("credentials")):
        return 401
    if (reason == "permission_denied"
            or reason.startswith("insufficient")
            or reason.startswith("not_")
            and reason.endswith(("_owner", "_admin", "_member"))):
        return 403
    if reason.endswith("_taken") or reason.startswith("already_"):
        return 409
    if "rate" in reason or reason.endswith("_quota_exceeded"):
        return 429
    return 400


def problem_title_for(reason: str) -> str:
    """One reason's plain-words title: the
    registry's where registered, else the generic
    title of the status the fallback assigns."""
    registered = _PROBLEM_REGISTRY.get(reason)
    if registered is not None:
        return registered[1]
    return STATUS_TITLES[decide_problem_status(reason)]


def problem_type_for(reason: str) -> str:
    """One reason's problem type: its stable
    address under the versioned base."""
    return f"{PROBLEM_TYPE_BASE}{_check_reason(reason)}"


def is_registered_reason(reason: object) -> bool:
    """Whether *reason* stands in the registry
    with its own status and title."""
    return isinstance(reason, str) and reason in _PROBLEM_REGISTRY


def registered_reasons() -> tuple[str, ...]:
    """Every registered reason, in registry
    order."""
    return tuple(_PROBLEM_REGISTRY)


def canonical_public_words(code: str) -> tuple[int, str, str]:
    """The canonical (status, title, detail) of
    one S-019 public *code* -- the words the web
    UI's error states (S-113) and the server's
    problem body both speak. An unregistered
    code is refused here, as S-019 refuses it."""
    registered = _PROBLEM_REGISTRY.get(code)
    if registered is None or code not in _PUBLIC_DETAILS:
        raise ErrorShapeError(
            "reason_invalid",
            f"No public problem is designed for code {code!r} "
            "(S-019's registry governs).")
    status, title = registered
    return status, title, _PUBLIC_DETAILS[code]


@dataclass(frozen=True)
class Problem:
    """One refusal in the one format: the reason
    it branches on (carried in `type`, and held
    here for the caller's own branching), its
    stable type address, its plain-words title,
    the HTTP status, the occurrence's detail
    sentence, and the opaque error id that ties
    it to the server log."""
    reason: str
    type: str
    title: str
    status: int
    detail: str
    error_id: str


def make_problem(reason: object, detail: object = None, *,
                 status: int | None = None,
                 error_id: str | None = None) -> Problem:
    """Shape one refusal: *reason* judged by the
    registry (an explicit *status* -- a handler's
    own, as S-019's `PublicError` carries -- wins
    over the registry's), *detail* the occurrence's
    plain sentence (the canonical public detail
    for an S-019 code, else the title itself, when
    none is given), and a fresh opaque error id
    unless one rides along."""
    name = _check_reason(reason)
    resolved_status = (
        status if status is not None
        else decide_problem_status(name))
    if detail is None or (isinstance(detail, str) and not detail):
        detail = _PUBLIC_DETAILS.get(name) or problem_title_for(name)
    elif detail == name and name in _PUBLIC_DETAILS:
        # S-019's PublicError stringifies to its own
        # code; the occurrence's sentence is the
        # canonical public detail, not the code.
        detail = _PUBLIC_DETAILS[name]
    return Problem(
        reason=name,
        type=problem_type_for(name),
        title=problem_title_for(name),
        status=resolved_status,
        detail=str(detail),
        error_id=error_id or new_error_id())


def problem_to_dict(problem: Problem) -> dict:
    """One problem as JSON-safe data: exactly the
    five fields of S-237's PROBLEM_FIELDS, in
    that order, and nothing else."""
    return {
        "type": problem.type,
        "title": problem.title,
        "status": problem.status,
        "detail": problem.detail,
        "error_id": problem.error_id,
    }


def problem_from_error(exc: BaseException, *,
                       error_id: str | None = None) -> Problem:
    """One raised refusal as a problem: the
    reason of the faces' errors (`.reason`), or
    the code of S-019's `PublicError` (`.code`,
    whose own `.status` wins), with the error's
    plain message as the detail."""
    reason = getattr(exc, "reason", None) or getattr(exc, "code", None)
    status = getattr(exc, "status", None)
    return make_problem(
        reason, str(exc) or None, status=status, error_id=error_id)


def problem_for_public_code(code: str, status: int, *,
                            error_id: str | None = None) -> Problem:
    """The problem of one S-019 public *code* at
    the *status* its handler judged: canonical
    title and detail, the handler's status."""
    _status, title, detail = canonical_public_words(code)
    return Problem(
        reason=code, type=problem_type_for(code), title=title,
        status=status, detail=detail,
        error_id=error_id or new_error_id())


# ------------------------------------------------------------------
# The web faces -- one problem as a page, and the help page
# ------------------------------------------------------------------

def render_problem_page(problem: Problem) -> str:
    """One problem as the web UI's refusal page:
    the same title, status, detail and error id
    the wire carries, in words -- never colour
    alone, and every value escaped through
    S-010."""
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{escape_html_text(problem.title)} — Samverk</title></head>",
        "<body>",
        f'<main class="problem" data-type="{escape_html_text(problem.type)}">',
        f"<h1>{escape_html_text(problem.title)}</h1>",
        f'<p class="problem-status">Status: {problem.status}</p>',
        f'<p class="problem-detail">{escape_html_text(problem.detail)}</p>',
        f'<p class="problem-id">Error id: '
        f"{escape_html_text(problem.error_id)} — quote this id when "
        "you ask for help; it is how the failure can be found "
        "in the server log.</p>",
        f'<p class="problem-type">Problem type: '
        f"{escape_html_text(problem.type)}</p>",
        "</main></body></html>",
    ]
    return "\n".join(parts)


def render_error_shape_page(problem: Problem | None = None) -> str:
    """The one format, in plain words, where a
    script's author finds it: the five fields,
    the type law, the registry of reasons with
    their statuses and titles -- and one live
    problem's own fields when one rides along.
    Every value escaped through S-010."""
    parts = [
        "<h1>Error shape</h1>",
        "<p>Every refused call in /api/v1 answers "
        "with one problem format, and the web UI's "
        "refusals match it: type (the problem's "
        "stable address, "
        f"{escape_html_text(PROBLEM_TYPE_BASE)}"
        "followed by the machine-branchable "
        "reason), title (that reason's plain-words "
        "summary, the same for every occurrence), "
        "status (the HTTP status), detail (this "
        "occurrence's human sentence), and "
        "error_id (an opaque id that ties the "
        "refusal to the server log and identifies "
        "nothing else). A repository you may not "
        "read answers with exactly the problem of "
        "one that does not exist.</p>",
        "<ul>",
    ]
    for reason in registered_reasons():
        status, title = _PROBLEM_REGISTRY[reason]
        parts.append(
            "<li>"
            f"{escape_html_text(problem_type_for(reason))} "
            f"— status {status} — "
            f"{escape_html_text(title)}</li>")
    parts.append("</ul>")
    if problem is not None:
        parts.append(
            "<p>One refusal in this format: "
            f"{escape_html_text(problem.title)} "
            f"(status {problem.status}) — "
            f"{escape_html_text(problem.detail)} "
            "Error id: "
            f"{escape_html_text(problem.error_id)}.</p>")
    return "\n".join(parts)
