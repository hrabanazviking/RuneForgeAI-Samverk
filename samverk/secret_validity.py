"""Validity checks seam (S-296).

Roadmap S-296: Validity checks seam -- where a
provider offers a public validation path, Samverk
may check "still live?"; the offline-honest default
is *unknown*, displayed as such.

S-291's scan on push stands every finding as a
secret alert carrying where the shape was found and
what shape it is -- never the secret itself. A
natural next question is whether the credential
behind an alert is still live at its provider.
This slice is the seam that question is answered
through, and its laws are:

- **Unknown is the default, and it is displayed
  as unknown.** An alert is born with validity
  ``unknown`` (migration 119's standing default),
  and every surface -- the alert view's ``validity``
  and ``validity_words``, ``to_dict``, the rendered
  pages -- says the word *unknown* until a real
  check through a real public validation path has
  answered otherwise. Nothing in this module ever
  guesses live or dead from the shape, the age of
  the alert, or its lifecycle state: a resolved
  alert is not thereby dead, and an open alert is
  not thereby live.
- **A check exists only where a public validation
  path exists.** The registry in this module is
  written from the providers' own public
  documentation, one entry per S-289 detector: the
  providers that offer a public way to present a
  credential and be told whether it answers (the
  token/user endpoints of GitHub, GitLab, Slack's
  ``auth.test``, and their kin), and -- said just
  as plainly -- the shapes that have none: an AWS
  access key ID alone (validation needs a signed
  request made with a secret key Samverk never
  holds), a bare Google API key, a webhook signing
  secret (validated only by verifying a delivered
  signature), a JWT (validated locally against its
  issuer's keys, not on a provider path), a PEM
  private key block (no provider at all). Where
  there is no path, no checker, however confident,
  can make the answer anything but ``unknown``:
  ``decide_validity`` refuses the checker's word
  there by construction.
- **The check is a seam, never a network call
  made from inside Samverk's judgement.** Samverk
  ships no provider client in this slice and makes
  no network call of its own: a *checker* is a
  callable an operator (or a later slice) injects
  -- ``checker(detector_id, secret)`` answering
  live / not live in any of the recognised shapes
  (``"live"`` / ``"not_live"``, ``True`` /
  ``False``, a mapping or object carrying the
  answer). With no checker configured -- the
  offline instance, the ordinary case -- the
  answer is ``unknown`` with detail
  ``no_checker_configured``. A checker that raises
  answers ``unknown`` (``checker_failed``); one
  that answers in no recognised shape answers
  ``unknown`` (``checker_result_unrecognised``).
  A failed or absent check is never dressed up as
  a verdict.
- **The secret is presented transiently and never
  kept.** Samverk stores no secret (S-289/S-291's
  law), so a standing alert alone cannot be
  checked: the caller hands the credential value
  to ``check_alert`` for this one check, it is
  passed to the checker and nowhere else -- never
  stored on the alert, never written to the check
  record, never audited, never rendered. The
  battery plants a secret and greps every surface
  for it. Without a handed-in secret the answer is
  ``unknown`` (``secret_unavailable``) even where
  a path and a checker both stand.
- **Permitted roles only for the act.** Asking a
  provider about a repository's credential is an
  act that answers for the repository's safety, so
  ``check_alert`` is judged by S-190's
  ``PermissionEngine``, never re-derived: only the
  ``admin`` and ``maintain`` rungs -- the rungs
  S-293 and S-294 trust -- may check. Every other
  rung, no access and anonymity are refused
  ``validity_not_permitted`` before the checker is
  ever called, and a stranger to a private
  repository gets the uniform ``repo_not_found``
  before any alert position is named. The pure
  ``judge`` writes nothing and calls no checker.
  Reads (the standing validity, the check history)
  answer to anyone the engine resolves to any role
  in the repository.
- **Every check is recorded, in the same
  transaction.** A performed check -- including
  one that honestly answers ``unknown`` -- appends
  one row to migration 119's
  ``secret_validity_checks`` (the alert, the
  detector, the answer, why it stands as it does,
  the checker's name, who asked, their role and
  its source, when) and moves the alert's standing
  validity columns to the same answer, inside one
  ``with conn`` transaction, so the record can
  never claim a check the alert does not show.
- **Unwitnessed in the audit taxonomy -- said
  plainly.** No new taxonomy event: 134 stand
  (33 auth / 88 repo / 13 admin), and the battery
  proves the audit log does not move across a
  check. A validity check changes no code, lands
  no push and lets no secret in; it is a judgement
  recorded on the alert's own check record, as
  S-294's lifecycle transitions stand on theirs.

Storage is migration 119's standing validity
columns on ``secret_alerts`` plus the
``secret_validity_checks`` table (schema 118 ->
119 on this base; S-293 and S-294 each claim
migration 116 on their own bases -- the keeper
renumbers at banking, and nothing else here is
renumbered).
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .escaping import escape_html_text
from .permission_engine import PermissionEngine
from .repositories import RepositoryError, RepositoryStore
from .secret_scanning import DETECTORS
from .team_permissions import role_word

__all__ = [
    "ALERT_NOT_FOUND", "DETAIL_CHECKED",
    "DETAIL_CHECKER_FAILED",
    "DETAIL_CHECKER_UNRECOGNISED",
    "DETAIL_DETECTOR_UNKNOWN", "DETAIL_NO_CHECKER",
    "DETAIL_NO_PATH", "DETAIL_NO_SECRET",
    "DETECTOR_UNKNOWN", "PERMITTED_ROLES",
    "VALIDITIES", "VALIDITY_LIVE", "VALIDITY_NOT_LIVE",
    "VALIDITY_NOT_PERMITTED", "VALIDITY_UNKNOWN",
    "VALIDITY_WORDS", "AlertValidity", "CheckDecision",
    "SecretValidityStore", "ValidationPath",
    "ValidityCheckRecord", "ValidityError",
    "ValidityVerdict", "check_validity",
    "decide_check", "decide_validity",
    "list_validation_paths", "normalise_checker_result",
    "render_validities_page", "render_validity_page",
    "validation_path_for", "validity_word",
]

#: The three validity answers. ``unknown`` is the
#: offline-honest default and the standing state of
#: every alert until a real check answers otherwise.
VALIDITY_UNKNOWN = "unknown"
VALIDITY_LIVE = "live"
VALIDITY_NOT_LIVE = "not_live"
VALIDITIES = frozenset(
    {VALIDITY_UNKNOWN, VALIDITY_LIVE, VALIDITY_NOT_LIVE})

VALIDITY_WORDS = {
    VALIDITY_UNKNOWN: "unknown",
    VALIDITY_LIVE: "still live",
    VALIDITY_NOT_LIVE: "no longer live",
}

#: Why a verdict stands as it does. ``checked`` is
#: the only detail under which live / not_live may
#: stand; every other detail stands with unknown.
DETAIL_CHECKED = "checked"
DETAIL_NO_PATH = "no_validation_path"
DETAIL_NO_CHECKER = "no_checker_configured"
DETAIL_NO_SECRET = "secret_unavailable"
DETAIL_CHECKER_FAILED = "checker_failed"
DETAIL_CHECKER_UNRECOGNISED = "checker_result_unrecognised"
DETAIL_DETECTOR_UNKNOWN = "detector_unknown"

#: The rungs that may run a validity check: the two
#: that already answer for a repository's safety.
PERMITTED_ROLES = frozenset({"admin", "maintain"})

VALIDITY_NOT_PERMITTED = "validity_not_permitted"
ALERT_NOT_FOUND = "alert_not_found"
DETECTOR_UNKNOWN = "detector_unknown"


class ValidityError(RepositoryError):
    """A validity-check error: a RepositoryError
    carrying `.reason`, in the house shape."""


def validity_word(validity: object) -> str:
    """A validity answer said in words a person
    reads. An unrecognised value is said as
    ``unknown`` -- the honest word -- never as a
    guess at live or dead."""
    return VALIDITY_WORDS.get(validity, "unknown")  # type: ignore[arg-type]


# --- the provider validation registry -------------------


@dataclass(frozen=True)
class ValidationPath:
    """One S-289 detector's validation position:
    its provider, whether that provider offers a
    public validation path, and the path (or the
    reason there is none) said in plain words."""
    detector_id: str
    provider: str
    label: str
    has_public_path: bool
    method: str

    def to_dict(self) -> dict:
        return {
            "detector_id": self.detector_id,
            "provider": self.provider,
            "label": self.label,
            "has_public_path": self.has_public_path,
            "method": self.method,
        }


#: One entry per S-289 detector, written from the
#: providers' public documentation: (offers a public
#: validation path, the path or why there is none).
_PATH_SPECS: dict = {
    "github_fine_grained_pat": (True,
        "present the token to GitHub's API: a live "
        "token answers as its owner"),
    "github_pat_classic": (True,
        "present the token to GitHub's API: a live "
        "token answers as its owner"),
    "github_oauth_token": (True,
        "present the token to GitHub's API: a live "
        "token answers as its owner"),
    "github_user_to_server": (True,
        "present the token to GitHub's API: a live "
        "token answers as its owner"),
    "github_server_to_server": (True,
        "present the token to GitHub's API: a live "
        "token answers as its owner"),
    "github_refresh_token": (True,
        "present the token to GitHub's API: a live "
        "token answers as its owner"),
    "gitlab_pat": (True,
        "present the token to GitLab's API: a live "
        "token answers as its owner"),
    "aws_access_key_id": (False,
        "no public path: AWS validates a request "
        "signed with the secret access key, and an "
        "access key ID alone cannot be presented "
        "for validation"),
    "google_api_key": (False,
        "no public path: Google offers no validation "
        "endpoint for a bare API key; a key is "
        "judged only by using it against an API"),
    "google_oauth_client_secret": (False,
        "no public path: a client secret is "
        "validated only inside an OAuth flow with "
        "its client, never on a public path"),
    "slack_token": (True,
        "present the token to Slack's auth.test "
        "method: a live token answers as its team "
        "and user"),
    "slack_webhook": (False,
        "no public path: a webhook URL is validated "
        "only by posting to it, and Samverk does "
        "not post to a credential to test it"),
    "stripe_secret_key": (True,
        "present the key to Stripe's API: a live "
        "key answers, a revoked key is refused"),
    "stripe_webhook_secret": (False,
        "no public path: a webhook signing secret "
        "is validated only by verifying a delivered "
        "signature, never on a public path"),
    "sendgrid_api_key": (True,
        "present the key to SendGrid's API: a live "
        "key answers, a revoked key is refused"),
    "twilio_api_key": (True,
        "present the key to Twilio's API: a live "
        "key answers, a revoked key is refused"),
    "npm_token": (True,
        "present the token to npm (whoami): a live "
        "token answers as its account"),
    "pypi_token": (False,
        "no public path: PyPI offers no validation "
        "endpoint for a token; a token is judged "
        "only by using it to upload"),
    "digitalocean_token": (True,
        "present the token to DigitalOcean's API: "
        "a live token answers as its account"),
    "square_access_token": (True,
        "present the token to Square's API: a live "
        "token answers, a revoked token is refused"),
    "mailchimp_api_key": (True,
        "present the key to Mailchimp's API: a "
        "live key answers, a revoked key is refused"),
    "jwt_compact": (False,
        "no public path: a JSON Web Token is "
        "validated locally against its issuer's "
        "keys; no provider validates a bare token"),
    "private_key_block": (False,
        "no public path: a private key belongs to "
        "no provider and is validated only by "
        "using it"),
}

VALIDATION_PATHS: tuple = tuple(
    ValidationPath(
        detector_id=d.id, provider=d.provider,
        label=d.label,
        has_public_path=_PATH_SPECS[d.id][0],
        method=_PATH_SPECS[d.id][1])
    for d in DETECTORS)

_BY_DETECTOR = {p.detector_id: p for p in VALIDATION_PATHS}


def validation_path_for(detector_id: object) -> ValidationPath:
    """The named detector's validation position, or
    a named refusal for a detector Samverk does not
    know -- never a silent default."""
    try:
        return _BY_DETECTOR[detector_id]  # type: ignore[index]
    except (KeyError, TypeError):
        raise ValidityError(
            DETECTOR_UNKNOWN,
            f"Unknown secret-scanning detector "
            f"{detector_id!r}: Samverk records no "
            f"validation path for it.") from None


def list_validation_paths() -> tuple:
    """Every detector's validation position, in
    S-289 registry order."""
    return VALIDATION_PATHS


# --- the pure judgement ---------------------------------


def normalise_checker_result(raw) -> str | None:
    """A checker's answer in Samverk's vocabulary:
    ``live`` / ``not_live`` / ``unknown``, or None
    when the answer is in no recognised shape.
    Recognised: the words themselves, booleans
    (True = live, False = no longer live), None
    (the checker itself answers unknown), and a
    mapping or object carrying ``validity`` /
    ``status`` / ``live``."""
    if raw is None:
        return VALIDITY_UNKNOWN
    if isinstance(raw, bool):
        return VALIDITY_LIVE if raw else VALIDITY_NOT_LIVE
    if isinstance(raw, str):
        word = raw.strip().lower().replace("-", "_").replace(" ", "_")
        if word in (VALIDITY_LIVE, "still_live", "valid", "active"):
            return VALIDITY_LIVE
        if word in (VALIDITY_NOT_LIVE, "notlive", "revoked",
                    "dead", "invalid", "inactive"):
            return VALIDITY_NOT_LIVE
        if word in (VALIDITY_UNKNOWN,):
            return VALIDITY_UNKNOWN
        return None
    if isinstance(raw, dict):
        for key in ("validity", "status", "state"):
            if key in raw:
                return normalise_checker_result(raw[key])
        if "live" in raw:
            return normalise_checker_result(bool(raw["live"]))
        return None
    for attr in ("validity", "status", "state"):
        if hasattr(raw, attr):
            return normalise_checker_result(getattr(raw, attr))
    if hasattr(raw, "live"):
        return normalise_checker_result(bool(raw.live))
    return None


@dataclass(frozen=True)
class ValidityVerdict:
    """The pure judgement over one detector: what
    Samverk may honestly say about a credential's
    validity, and why it stands as it does. Never
    carries the secret: the detector, the provider,
    the answer, its detail and the checker's name
    are the whole of it."""
    detector_id: str
    provider: str
    validity: str
    detail: str
    checker: str
    has_public_path: bool
    method: str

    @property
    def words(self) -> str:
        return validity_word(self.validity)

    @property
    def display(self) -> str:
        """The answer as a surface must show it:
        the validity word itself, so *unknown* is
        displayed as unknown."""
        return f"Validity: {self.words}"

    def to_dict(self) -> dict:
        return {
            "detector_id": self.detector_id,
            "provider": self.provider,
            "validity": self.validity,
            "validity_words": self.words,
            "detail": self.detail,
            "checker": self.checker,
            "has_public_path": self.has_public_path,
            "method": self.method,
        }


def _checker_name(checker, checker_name: str = "") -> str:
    if checker_name:
        return checker_name
    if checker is None:
        return ""
    return getattr(checker, "__name__", "") or "injected checker"


def decide_validity(detector_id: object, *,
                    secret: object = None,
                    checker: Callable | None = None,
                    checker_name: str = "") -> ValidityVerdict:
    """May Samverk say this credential is still
    live? The whole seam in one pure judgement:
    writes nothing, stores nothing, and keeps the
    secret only long enough to hand it to the
    checker. An unknown detector is refused loudly
    (``detector_unknown``); every other doubt --
    no path, no checker, no secret, a failing or
    unrecognised checker -- answers ``unknown``
    with its detail named."""
    path = validation_path_for(detector_id)
    name = _checker_name(checker, checker_name)

    def verdict(validity: str, detail: str) -> ValidityVerdict:
        return ValidityVerdict(
            detector_id=path.detector_id,
            provider=path.provider, validity=validity,
            detail=detail, checker=name,
            has_public_path=path.has_public_path,
            method=path.method)

    if not path.has_public_path:
        return verdict(VALIDITY_UNKNOWN, DETAIL_NO_PATH)
    if checker is None:
        return verdict(VALIDITY_UNKNOWN, DETAIL_NO_CHECKER)
    if not isinstance(secret, str) or not secret:
        return verdict(VALIDITY_UNKNOWN, DETAIL_NO_SECRET)
    try:
        raw = checker(path.detector_id, secret)
    except Exception:
        return verdict(VALIDITY_UNKNOWN, DETAIL_CHECKER_FAILED)
    answer = normalise_checker_result(raw)
    if answer is None:
        return verdict(
            VALIDITY_UNKNOWN, DETAIL_CHECKER_UNRECOGNISED)
    if answer == VALIDITY_UNKNOWN:
        # The checker itself answered unknown: a
        # check ran and honestly could not say.
        return verdict(VALIDITY_UNKNOWN, DETAIL_CHECKED)
    return verdict(answer, DETAIL_CHECKED)


def check_validity(detector_id: object, *,
                   secret: object = None,
                   checker: Callable | None = None,
                   checker_name: str = "") -> ValidityVerdict:
    """``decide_validity`` under its working name:
    run one check through the seam and return the
    honest verdict."""
    return decide_validity(
        detector_id, secret=secret, checker=checker,
        checker_name=checker_name)


# --- the permission judgement ---------------------------


@dataclass(frozen=True)
class CheckDecision:
    """The pure permission judgement: may this
    person, holding this role, run a validity check
    on this alert? A refusal carries its named code
    and its sentence. Pure: writes nothing and
    calls no checker."""
    may_check: bool
    role: str | None
    source: str
    code: str
    reason: str
    words: str


def decide_check(*, role: str | None, source: str,
                 actor: str | None, full_name: str) -> CheckDecision:
    """The permission half of a check, judged on
    the S-190 role alone."""
    who = actor if actor is not None else "An anonymous visitor"
    if role in PERMITTED_ROLES and actor is not None:
        return CheckDecision(
            may_check=True, role=role, source=source,
            code="", reason="",
            words=(f"{who} holds {role_word(role)} in "
                   f"{full_name} and may run a validity "
                   f"check."))
    held = role_word(role) if role is not None else "no access"
    sentence = (
        f"{who} holds {held} in {full_name} and may "
        f"not run a validity check: only the admin "
        f"and maintain rungs -- the rungs that answer "
        f"for a repository's safety -- may ask a "
        f"provider whether its credential is still "
        f"live.")
    return CheckDecision(
        may_check=False, role=role, source=source,
        code=VALIDITY_NOT_PERMITTED, reason=sentence,
        words=sentence)


# --- views ------------------------------------------------


@dataclass(frozen=True)
class AlertValidity:
    """One secret alert with its standing validity:
    where and what shape (S-291's own fields), the
    validity answer and the check that stands
    behind it. Never the secret."""
    id: int
    repo_id: int
    repository: str
    scan_id: int
    commit_oid: str
    path: str
    blob_oid: str
    source: str
    detector_id: str
    provider: str
    line: int
    column: int
    redacted: str
    fingerprint: str
    state: str
    validity: str
    validity_checked_at: int | None
    validity_checker: str
    validity_detail: str
    created_at: int

    @property
    def words(self) -> str:
        return validity_word(self.validity)

    @property
    def display(self) -> str:
        return f"Validity: {self.words}"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "repository": self.repository,
            "scan_id": self.scan_id,
            "commit": self.commit_oid,
            "path": self.path,
            "blob": self.blob_oid,
            "source": self.source,
            "detector_id": self.detector_id,
            "provider": self.provider,
            "line": self.line,
            "column": self.column,
            "redacted": self.redacted,
            "fingerprint": self.fingerprint,
            "state": self.state,
            "validity": self.validity,
            "validity_words": self.words,
            "validity_checked_at": self.validity_checked_at,
            "validity_checker": self.validity_checker,
            "validity_detail": self.validity_detail,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ValidityCheckRecord:
    """One performed check on the alert's own
    record: the answer, why it stands, the checker,
    who asked and under which role, and when."""
    id: int
    alert_id: int
    repo_id: int
    detector_id: str
    validity: str
    checker: str
    detail: str
    checked_by_id: int
    checked_by: str
    role: str
    role_source: str
    created_at: int

    @property
    def words(self) -> str:
        return (f"Validity {validity_word(self.validity)} "
                f"({self.detail}) by {self.checked_by} "
                f"via {self.checker or 'no checker'}")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "alert_id": self.alert_id,
            "detector_id": self.detector_id,
            "validity": self.validity,
            "validity_words": validity_word(self.validity),
            "checker": self.checker,
            "detail": self.detail,
            "checked_by": self.checked_by,
            "role": self.role,
            "role_source": self.role_source,
            "created_at": self.created_at,
        }


def _row_to_validity(row, full_name: str) -> AlertValidity:
    detector_id = row["detector_id"]
    path = _BY_DETECTOR.get(detector_id)
    keys = row.keys()
    return AlertValidity(
        id=row["id"], repo_id=row["repo_id"],
        repository=full_name, scan_id=row["scan_id"],
        commit_oid=row["commit_oid"], path=row["path"],
        blob_oid=row["blob_oid"], source=row["source"],
        detector_id=detector_id,
        provider=path.provider if path is not None else "",
        line=row["line"], column=row["column"],
        redacted=row["redacted"],
        fingerprint=row["fingerprint"], state=row["state"],
        validity=(row["validity"] if "validity" in keys
                  and row["validity"] else VALIDITY_UNKNOWN),
        validity_checked_at=(
            row["validity_checked_at"]
            if "validity_checked_at" in keys else None),
        validity_checker=(
            row["validity_checker"]
            if "validity_checker" in keys else "") or "",
        validity_detail=(
            row["validity_detail"]
            if "validity_detail" in keys else "") or "",
        created_at=row["created_at"])


def _row_to_record(row) -> ValidityCheckRecord:
    return ValidityCheckRecord(
        id=row["id"], alert_id=row["alert_id"],
        repo_id=row["repo_id"],
        detector_id=row["detector_id"],
        validity=row["validity"], checker=row["checker"],
        detail=row["detail"],
        checked_by_id=row["checked_by_id"],
        checked_by=row["checked_by"], role=row["role"],
        role_source=row["role_source"],
        created_at=row["created_at"])


# --- the store --------------------------------------------


class SecretValidityStore:
    """The standing validity of S-291's secret
    alerts: the offline-honest unknown until a
    permitted check through the seam answers."""

    def __init__(self, conn: sqlite3.Connection,
                 repositories: RepositoryStore,
                 accounts: AccountStore,
                 time_fn: Callable[[], float] = time.time,
                 checker: Callable | None = None,
                 checker_name: str = ""):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._now = time_fn
        self._checker = checker
        self._checker_name = checker_name
        self._engine = PermissionEngine(
            conn, accounts, audit=None, time_fn=time_fn)

    # -- resolution ------------------------------------

    def _resolve_repo(self, viewer: User | None, owner, repo,
                      *, any_role: bool):
        """(repository, resolution). A missing
        repository answers `repo_not_found`; so does
        a non-public repository the viewer holds no
        role in, before any alert position is named.
        With `any_role`, holding any role is enough
        to stand inside the door (the read law)."""
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise ValidityError(
                "repo_not_found", "No such repository.")
        resolution = self._engine.resolve(viewer, current)
        if resolution.role is None \
                and current.visibility != "public":
            raise ValidityError(
                "repo_not_found", "No such repository.")
        if any_role and resolution.role is None:
            raise ValidityError(
                "repo_not_found", "No such repository.")
        return current, resolution

    def _alert_row(self, repo_id: int, alert_id: int):
        row = self._conn.execute(
            "SELECT * FROM secret_alerts WHERE id = ?"
            " AND repo_id = ?", (alert_id, repo_id)).fetchone()
        if row is None:
            raise ValidityError(
                ALERT_NOT_FOUND,
                f"No secret alert {alert_id} stands in "
                f"this repository.")
        return row

    # -- the pure check ----------------------------------

    def judge(self, actor: User | None, owner, repo,
              alert_id: int) -> CheckDecision:
        """May this actor run a validity check on
        this alert? A pure read: writes nothing and
        calls no checker."""
        current, resolved = self._resolve_repo(
            actor, owner, repo, any_role=False)
        self._alert_row(current.id, alert_id)
        return decide_check(
            role=resolved.role, source=resolved.source,
            actor=actor.username if actor is not None else None,
            full_name=current.full_name)

    # -- the act -------------------------------------------

    def check_alert(self, actor: User | None, owner, repo,
                    alert_id: int, *,
                    secret: object = None,
                    checker: Callable | None = None,
                    checker_name: str | None = None
                    ) -> AlertValidity:
        """Run one validity check on one alert
        through the seam and stand its answer on the
        alert, with the check itself on the alert's
        record -- all before this answers. The
        handed-in secret goes to the checker alone
        and is kept nowhere."""
        current, resolved = self._resolve_repo(
            actor, owner, repo, any_role=False)
        row = self._alert_row(current.id, alert_id)
        judgement = decide_check(
            role=resolved.role, source=resolved.source,
            actor=actor.username if actor is not None else None,
            full_name=current.full_name)
        if not judgement.may_check:
            raise ValidityError(judgement.code, judgement.reason)
        effective_checker = (
            checker if checker is not None else self._checker)
        effective_name = (
            checker_name if checker_name is not None
            else self._checker_name)
        detector_id = row["detector_id"]
        if detector_id in _BY_DETECTOR:
            verdict = decide_validity(
                detector_id, secret=secret,
                checker=effective_checker,
                checker_name=effective_name or "")
        else:
            # An alert whose detector Samverk's v1 set
            # does not name (an injected scan's finding,
            # a future detector) has no recorded path:
            # the honest answer is unknown, recorded
            # as such, never a raised refusal against
            # a standing alert.
            verdict = ValidityVerdict(
                detector_id=detector_id, provider="",
                validity=VALIDITY_UNKNOWN,
                detail=DETAIL_DETECTOR_UNKNOWN, checker="",
                has_public_path=False, method="")
        created_at = int(self._now())
        with self._conn:
            self._conn.execute(
                "UPDATE secret_alerts SET validity = ?,"
                " validity_checked_at = ?,"
                " validity_checker = ?,"
                " validity_detail = ? WHERE id = ?",
                (verdict.validity, created_at,
                 verdict.checker, verdict.detail, alert_id))
            self._conn.execute(
                "INSERT INTO secret_validity_checks ("
                " alert_id, repo_id, detector_id, validity,"
                " checker, detail, checked_by_id, checked_by,"
                " role, role_source, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (alert_id, current.id, detector_id,
                 verdict.validity, verdict.checker,
                 verdict.detail, actor.id, actor.username,
                 resolved.role, resolved.source, created_at))
        return self._get_validity(current, alert_id)

    # -- the reads ------------------------------------------

    def _get_validity(self, current, alert_id: int) -> AlertValidity:
        row = self._alert_row(current.id, alert_id)
        return _row_to_validity(row, current.full_name)

    def get_validity(self, viewer: User | None, owner, repo,
                     alert_id: int) -> AlertValidity:
        """One alert with its standing validity --
        *unknown* until a check has answered."""
        current, _ = self._resolve_repo(
            viewer, owner, repo, any_role=True)
        return self._get_validity(current, alert_id)

    def list_validities(self, viewer: User | None, owner, repo, *,
                        validity: str | None = None,
                        limit: int = 100) -> tuple:
        """Newest alerts first; optionally only one
        standing validity."""
        current, _ = self._resolve_repo(
            viewer, owner, repo, any_role=True)
        if validity is not None and validity not in VALIDITIES:
            raise ValidityError(
                "validity_invalid",
                f"Unknown validity: {validity!r}")
        clamped = max(1, min(int(limit), 500))
        if validity is None:
            rows = self._conn.execute(
                "SELECT * FROM secret_alerts WHERE repo_id = ?"
                " ORDER BY id DESC LIMIT ?",
                (current.id, clamped)).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM secret_alerts WHERE repo_id = ?"
                " AND validity = ? ORDER BY id DESC LIMIT ?",
                (current.id, validity, clamped)).fetchall()
        return tuple(
            _row_to_validity(r, current.full_name) for r in rows)

    def count_validities(self, viewer: User | None, owner, repo, *,
                         validity: str | None = None) -> int:
        current, _ = self._resolve_repo(
            viewer, owner, repo, any_role=True)
        if validity is None:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM secret_alerts"
                " WHERE repo_id = ?", (current.id,)).fetchone()
        else:
            if validity not in VALIDITIES:
                raise ValidityError(
                    "validity_invalid",
                    f"Unknown validity: {validity!r}")
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM secret_alerts"
                " WHERE repo_id = ? AND validity = ?",
                (current.id, validity)).fetchone()
        return int(row["n"])

    def list_checks(self, viewer: User | None, owner, repo,
                    alert_id: int) -> tuple:
        """The alert's check record, oldest first:
        every check ever run on it, unedited."""
        current, _ = self._resolve_repo(
            viewer, owner, repo, any_role=True)
        self._alert_row(current.id, alert_id)
        rows = self._conn.execute(
            "SELECT * FROM secret_validity_checks"
            " WHERE alert_id = ? AND repo_id = ?"
            " ORDER BY id", (alert_id, current.id)).fetchall()
        return tuple(_row_to_record(r) for r in rows)


# --- the page faces ----------------------------------------


def render_validity_page(view: AlertValidity, checks=(),
                         title: str = "Secret alert validity") -> str:
    """One alert's validity face: where and what
    shape, the standing validity said in its word
    -- *unknown* displayed as unknown -- and the
    check record behind it."""
    rows = "".join(
        "<li>" + escape_html_text(c.words)
        + " &mdash; " + str(c.created_at) + "</li>"
        for c in checks)
    if not rows:
        rows = ("<li>No validity check has been run: "
                "the validity of this credential is "
                "unknown.</li>")
    return (
        "<!DOCTYPE html><html><head><title>"
        + escape_html_text(title)
        + "</title></head><body><h1>"
        + escape_html_text(title)
        + "</h1><p>"
        + escape_html_text(view.repository)
        + " &mdash; "
        + escape_html_text(view.path)
        + " ("
        + escape_html_text(view.detector_id)
        + ")</p><p>"
        + escape_html_text(view.display)
        + "</p><ul>"
        + rows
        + "</ul></body></html>")


def render_validities_page(views, title: str = "Secret alert validity") -> str:
    """The alerts' validity face: every alert with
    its standing validity word beside it."""
    rows = "".join(
        "<li>"
        + escape_html_text(v.path)
        + " ("
        + escape_html_text(v.detector_id)
        + ") &mdash; "
        + escape_html_text(v.display)
        + "</li>"
        for v in views)
    if not rows:
        rows = "<li>No secret alerts.</li>"
    return (
        "<!DOCTYPE html><html><head><title>"
        + escape_html_text(title)
        + "</title></head><body><h1>"
        + escape_html_text(title)
        + "</h1><ul>"
        + rows
        + "</ul></body></html>")
