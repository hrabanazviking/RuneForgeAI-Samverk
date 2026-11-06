"""Pull request checks panel (S-157).

Checks panel: external status/check results listed on the
pull request with links; pending/failed/passed are
text+icon, never colour-only. External systems (Part XVI
CI today, anything else that can run a check) report a
result against a commit; this slice keeps those results
and lists the ones recorded against a pull request's
head commit on the pull request itself.

- **One row per reported result** (migration 58,
  `commit_checks`): the repository the result was
  recorded against, the commit oid, the check's name
  verbatim (`context`), its state, the external details
  link (`target_url`) and a one-line `description`, with
  the stamps of when the result first landed and when it
  last changed. Unique per (repository, commit, context):
  when a check runs again it reports again under the
  same context, and the re-report updates that same row
  — state, link and description move, `updated_at` is
  stamped, `created_at` keeps the first landing. The
  panel therefore always says the latest word, and no
  context ever appears twice for one commit.
- **States are the roadmap's three words** — `pending`,
  `failed`, `passed` — and nothing else. A report in any
  other words (another forge's `success` or `error`, a
  capitalised variant, an empty string) is refused whole
  with `check_state_invalid` and stores nothing; the
  vocabulary is Samverk's, said the same way everywhere.
  A blank context is refused `check_context_invalid`,
  and a `target_url` that is not a URL Samverk may link
  to (S-010's `safe_url`: an http/https link, never a
  script or a relative path) is refused
  `check_url_invalid`, again storing nothing.
- **The recording seam is storage only.**
  `record_result` is the seam the Part XII status and
  checks API (S-246) will call when an external system
  posts a result; the scoped identity of the poster and
  its audit-logging are S-246's own law and land with
  that slice. Nothing is audited here and the taxonomy
  is untouched (110 events): there is no poster identity
  at this layer to audit honestly.
- **Reads ride the S-141 seam.** `checks_for` resolves
  the pull request through `PullRequestStore`, so a
  stranger to a private repository gets the uniform
  `pull_request_not_found` before any check is named.
  The panel lists the checks recorded against the pull
  request's own (base) repository for its head commit,
  in the order they first landed; a cross-fork pull
  request's checks are recorded against its base
  repository under its head oid, the rule S-246 posts
  by.
- **Render is text+icon, never colour alone.** Every
  row carries the state as a word (`Pending`, `Failed`,
  `Passed`) beside an icon glyph (◐, ✗, ✓), the context
  verbatim, and — when the result carries one — a
  "View details" link to the external page. The panel
  opens with the tally in words ("3 checks reported:
  1 passed; 1 failed; 1 pending."), and a pull request
  with no checks says so in words. Every value escapes
  through S-010: contexts and descriptions as text, the
  link target as an attribute.
"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .escaping import escape_html_attr, escape_html_text, safe_url
from .issues import IssueStore
from .pull_requests import PullRequestError, PullRequestStore
from .repositories import RepositoryStore

__all__ = [
    "PullRequestCheck", "PullRequestChecksStore",
    "render_pull_request_check", "render_pull_request_checks",
]

#: The three states a check result may be in — the
#: roadmap's words, and no others.
CHECK_STATES = ("pending", "failed", "passed")

_STATE_WORDS = {"pending": "Pending", "failed": "Failed",
                "passed": "Passed"}
_STATE_ICONS = {"pending": "◐", "failed": "✗", "passed": "✓"}


@dataclass(frozen=True)
class PullRequestCheck:
    id: int
    repo_id: int          # repositories row the result names
    number: int           # the pull request's #, when read for one
    head_oid: str         # the commit the result was reported on
    context: str          # the check's name, verbatim
    state: str            # 'pending' | 'failed' | 'passed'
    target_url: str       # external details link, '' when none
    description: str      # one line from the reporter, '' when none
    created_at: int
    updated_at: int

    @property
    def is_pending(self) -> bool:
        return self.state == "pending"

    @property
    def is_failed(self) -> bool:
        return self.state == "failed"

    @property
    def is_passed(self) -> bool:
        return self.state == "passed"

    @property
    def state_words(self) -> str:
        """The state in words — never a colour alone."""
        return _STATE_WORDS[self.state]

    @property
    def icon(self) -> str:
        """The state's icon glyph, always beside its word."""
        return _STATE_ICONS[self.state]

    @property
    def words(self) -> str:
        parts = [f"{self.context} — {self.state_words}"]
        if self.description:
            parts.append(self.description)
        parts.append(f"against head {self.head_oid}")
        return "; ".join(parts) + "."


class PullRequestChecksStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        issues: IssueStore,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._issues = issues
        self._now = time_fn
        self._prs = PullRequestStore(
            conn, repositories, accounts, issues, audit=None,
            time_fn=time_fn)

    # -- internals -------------------------------------------------

    def _row_to_check(self, row: sqlite3.Row,
                      number: int) -> PullRequestCheck:
        return PullRequestCheck(
            id=row["id"], repo_id=row["repo_id"], number=number,
            head_oid=row["head_oid"], context=row["context"],
            state=row["state"], target_url=row["target_url"],
            description=row["description"],
            created_at=row["created_at"],
            updated_at=row["updated_at"])

    def _for_head(self, repo_id: int, head_oid: str,
                  number: int) -> list[PullRequestCheck]:
        rows = self._conn.execute(
            "SELECT * FROM commit_checks"
            " WHERE repo_id = ? AND head_oid = ? ORDER BY id",
            (repo_id, head_oid)).fetchall()
        return [self._row_to_check(r, number) for r in rows]

    # -- recording (the seam S-246 posts through) ------------------

    def record_result(self, owner: object, repo: object,
                      head_oid: object, context: object,
                      state: object = "pending", *,
                      target_url: object = "",
                      description: object = "") -> PullRequestCheck:
        """Record one external check result against a commit.

        A re-report under the same context for the same
        commit updates the row in place: the latest state,
        link and description stand, `updated_at` moves,
        `created_at` keeps the first landing. Every part
        of the report validates before anything is stored.
        """
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise PullRequestError(
                "repository_not_found",
                "repository_not_found — no such repository; "
                "nothing was recorded.")
        if not isinstance(head_oid, str) or not head_oid.strip():
            raise PullRequestError(
                "check_head_invalid",
                "check_head_invalid — a check result names the "
                "commit it ran on. Nothing was recorded.")
        if not isinstance(context, str) or not context.strip():
            raise PullRequestError(
                "check_context_invalid",
                "check_context_invalid — a check result names "
                "its check. Nothing was recorded.")
        if state not in CHECK_STATES:
            raise PullRequestError(
                "check_state_invalid",
                f"check_state_invalid — {state!r} is not a check "
                "state: a state is pending, failed or passed. "
                "Nothing was recorded.")
        url = "" if target_url is None else str(target_url).strip()
        if url and (not url.lower().startswith(("http://", "https://"))
                    or safe_url(url) is None):
            raise PullRequestError(
                "check_url_invalid",
                "check_url_invalid — a check's details link must "
                "be an http or https URL. Nothing was recorded.")
        text = "" if description is None else str(description)
        now = int(self._now())
        with self._conn:  # commits before the answer
            row = self._conn.execute(
                "SELECT * FROM commit_checks"
                " WHERE repo_id = ? AND head_oid = ? AND context = ?",
                (current.id, head_oid, context)).fetchone()
            if row is None:
                cur = self._conn.execute(
                    "INSERT INTO commit_checks"
                    " (repo_id, head_oid, context, state, target_url,"
                    " description, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (current.id, head_oid, context, state, url,
                     text, now, now))
                row_id = int(cur.lastrowid)
            else:
                self._conn.execute(
                    "UPDATE commit_checks SET state = ?,"
                    " target_url = ?, description = ?,"
                    " updated_at = ? WHERE id = ?",
                    (state, url, text, now, row["id"]))
                row_id = int(row["id"])
        fresh = self._conn.execute(
            "SELECT * FROM commit_checks WHERE id = ?",
            (row_id,)).fetchone()
        return self._row_to_check(fresh, 0)

    # -- reads ------------------------------------------------------

    def checks_for_commit(self, owner: object, repo: object,
                          head_oid: object
                          ) -> list[PullRequestCheck]:
        """Every result recorded against one commit in one
        repository, in the order they first landed."""
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise PullRequestError(
                "repository_not_found",
                "repository_not_found — no such repository.")
        return self._for_head(current.id, str(head_oid), 0)

    def checks_for(self, viewer: User | None, owner: object,
                   repo: object, number: object
                   ) -> list[PullRequestCheck]:
        """The checks panel's rows for one pull request: the
        results recorded against its base repository for
        its head commit, in the order they first landed.
        The pull request resolves through the S-141 seam,
        so a stranger to a private repository is refused
        `pull_request_not_found` before any check is named.
        """
        pr = self._prs.get_pull_request(viewer, owner, repo, number)
        return self._for_head(pr.repo_id, pr.head_oid, pr.number)


def render_pull_request_check(row: PullRequestCheck) -> str:
    """One check result: icon and state word, the context,
    and the details link when the result carries one."""
    link = ""
    if row.target_url:
        link = (f' <a href="{escape_html_attr(row.target_url)}">'
                "View details</a>")
    return (
        f'<li class="pull-request-check check-{row.state}">'
        f'<span class="check-icon" aria-hidden="true">'
        f"{row.icon}</span> "
        f"{escape_html_text(row.words)}{link}</li>")


def render_pull_request_checks(rows) -> str:
    """The checks panel in plain words — the tally first,
    then every result with its state as text+icon and its
    link. Never a colour alone; every value escapes
    through S-010."""
    rows = list(rows)
    if not rows:
        return ('<p class="pull-request-checks">No checks have '
                "been reported for this pull request.</p>")
    counts = {state: 0 for state in CHECK_STATES}
    for row in rows:
        counts[row.state] += 1
    total = len(rows)
    noun = "check" if total == 1 else "checks"
    tally = [f"{counts[state]} {state}"
             for state in ("passed", "failed", "pending")
             if counts[state]]
    summary = f"{total} {noun} reported: {'; '.join(tally)}."
    items = "".join(render_pull_request_check(r) for r in rows)
    return (f'<div class="pull-request-checks"><p>'
            f"{escape_html_text(summary)}</p>"
            f"<ul>{items}</ul></div>")
