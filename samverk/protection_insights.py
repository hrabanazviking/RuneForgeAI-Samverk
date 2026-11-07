"""Rule insights (S-183).

A page answering "why was this push/merge
refused?" from the audit trail, in plain words
(the user-friendliness law).

- **The source is the audit trail itself**
  (S-007's hash-chained log): rows whose target is
  this repository and whose outcome is a refusal
  (`denied` or `failure`). A refusal a gate made
  without writing an audit row cannot appear here,
  and the page says so — an absent explanation is
  never dressed up as "nothing was refused".
- **Plain words first.** Every refusal is explained
  by `explain_refusal`: what was attempted (from
  the audit action), the recorded reason turned
  into a sentence, and the recorded context the
  detail carries (branch, gate, pull request
  number, matching patterns, rule ids). Technical
  names ride second, never first, and never alone.
- **The guard is the house guard.** The repository
  is resolved through S-049's store and S-054's
  `can_read`; a stranger to a private repository
  gets the uniform `repo_not_found` before any
  row is read — a private repo's refusals are as
  private as its code.
- **A pure read.** No migration (schema stays
  67), no new taxonomy event (120 stand); the
  judgments that produced these rows wrote them,
  this slice only reads and explains.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass

from .accounts import AccountStore, User
from .escaping import escape_html_text
from .permissions import can_read
from .repositories import RepositoryError, RepositoryStore

__all__ = [
    "REFUSAL_OUTCOMES",
    "RuleInsight", "RuleInsightsStore",
    "explain_refusal", "render_insight",
    "render_insights_page",
]

REFUSAL_OUTCOMES = frozenset({"denied", "failure"})

_ACTION_WORDS = {
    "repo.pull_request.merge": "a pull request merge",
    "repo.pull_request.squash_merge":
        "a pull request squash merge",
    "repo.pull_request.rebase":
        "a pull request rebase merge",
    "repo.pull_request.auto_merge_fire":
        "an automatic pull request merge",
    "repo.protection.bypass": "a protection bypass",
    "repo.push": "a push",
    "repo.create": "a repository creation",
    "repo.delete": "a repository deletion",
    "repo.transfer": "a repository transfer",
}

_REASON_WORDS = {
    "permission_denied":
        "the person did not have the standing "
        "this action needs",
    "status_checks_required":
        "a required status check was not green",
    "signed_commits_required":
        "a commit the action carried was not signed",
    "approvals_required":
        "the required approving reviews were "
        "not there",
    "code_owner_review_required":
        "a code owner had not approved",
    "protected_tag_refused":
        "the tag is protected against this update",
    "protected_push_refused":
        "the branch protection forbids this kind "
        "of push",
    "push_actor_required":
        "the pusher is not named as allowed to "
        "push here",
    "bypass_not_allowed":
        "the person is not named on the rule's "
        "bypass list",
    "bypass_audit_required":
        "the bypass could not be witnessed in "
        "the audit log",
    "linear_history_required":
        "the branch requires a linear history and "
        "the action carried a merge commit",
    "repo_not_found":
        "the repository could not be found",
}


def _humanise(code: str) -> str:
    return code.replace("_", " ").strip()


def _detail_text(detail: dict | None, key: str) -> str | None:
    if not isinstance(detail, dict):
        return None
    value = detail.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def explain_refusal(action: str, outcome: str,
                    detail: dict | None) -> str:
    """One refusal, explained in plain words.

    Built only from what the audit row records:
    the action, the outcome, and the detail keys
    the gates actually write (reason, branch,
    gate, number, patterns, rule_ids, actor).
    Nothing is inferred beyond the row.
    """
    what = _ACTION_WORDS.get(
        action, f"an action recorded as {action}")
    parts = [f"This was {what}, and it was refused."]
    reason = _detail_text(detail, "reason")
    if reason is not None:
        words = _REASON_WORDS.get(reason)
        if words is not None:
            parts.append(f"Why: {words}.")
        else:
            parts.append(
                f"Why: the recorded reason was "
                f"'{_humanise(reason)}'.")
    number = _detail_text(detail, "number")
    if number is not None:
        parts.append(f"It concerned pull request "
                     f"#{number}.")
    branch = _detail_text(detail, "branch")
    if branch is not None:
        parts.append(f"The branch was '{branch}'.")
    gate = _detail_text(detail, "gate")
    if gate is not None:
        parts.append(f"The gate was the {gate} gate.")
    if isinstance(detail, dict):
        patterns = detail.get("patterns")
        if isinstance(patterns, (list, tuple)) and patterns:
            joined = ", ".join(str(p) for p in patterns)
            parts.append(
                f"The matching rule patterns were: "
                f"{joined}.")
        rule_ids = detail.get("rule_ids")
        if isinstance(rule_ids, (list, tuple)) and rule_ids:
            joined = ", ".join(str(r) for r in rule_ids)
            parts.append(f"The rules involved were "
                         f"numbered {joined}.")
    return " ".join(parts)


@dataclass(frozen=True)
class RuleInsight:
    seq: int
    ts: int
    action: str
    outcome: str
    actor_id: int | None
    actor: str | None
    target_id: str | None
    detail: dict | None

    @property
    def explanation(self) -> str:
        return explain_refusal(
            self.action, self.outcome, self.detail)

    @property
    def words(self) -> str:
        who = (f"by {self.actor}" if self.actor
               else "by an unnamed actor")
        return (f"{_stamp(self.ts)} — "
                f"{self.explanation} "
                f"The attempt was made {who}.")


class RuleInsightsStore:
    """Reads this repository's refusals from the
    audit trail and explains them. Pure read."""

    def __init__(self, conn: sqlite3.Connection,
                 repositories: RepositoryStore,
                 accounts: AccountStore):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts

    def _guard(self, viewer, owner, repo):
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise RepositoryError(
                "repo_not_found", "No such repository.")
        return current

    def _insight(self, row) -> RuleInsight:
        detail = None
        if row["detail"]:
            try:
                parsed = json.loads(row["detail"])
            except (ValueError, TypeError):
                parsed = None
            if isinstance(parsed, dict):
                detail = parsed
        actor = None
        if row["actor_id"] is not None:
            account = self._accounts.get_by_id(
                row["actor_id"])
            if account is not None:
                actor = account.username
        return RuleInsight(
            seq=row["seq"], ts=row["ts"],
            action=row["action"], outcome=row["outcome"],
            actor_id=row["actor_id"], actor=actor,
            target_id=row["target_id"], detail=detail)

    def insights_for(self, viewer, owner, repo, *,
                     limit: int = 100) -> tuple:
        """This repository's refusals, newest first.

        `limit` is clamped to 1..500, the house
        shape, so a surface cannot page the whole
        chain by accident.
        """
        current = self._guard(viewer, owner, repo)
        limit = max(1, min(int(limit), 500))
        rows = self._conn.execute(
            "SELECT seq, ts, actor_id, action, target_id,"
            " outcome, detail FROM audit_log"
            " WHERE target_kind = 'repo' AND target_id = ?"
            " ORDER BY seq DESC",
            (current.full_name,)).fetchall()
        out: list[RuleInsight] = []
        for row in rows:
            if row["outcome"] not in REFUSAL_OUTCOMES:
                continue
            out.append(self._insight(row))
            if len(out) >= limit:
                break
        return tuple(out)

    def explain_one(self, viewer, owner, repo,
                    seq: int) -> RuleInsight | None:
        """The explanation for one audit row, or
        None when that row is not a refusal of this
        repository (another repo's rows, success
        rows, and unknown sequences all answer
        None — never another repo's explanation)."""
        current = self._guard(viewer, owner, repo)
        row = self._conn.execute(
            "SELECT seq, ts, actor_id, action, target_id,"
            " outcome, detail FROM audit_log WHERE seq = ?",
            (int(seq),)).fetchone()
        if row is None:
            return None
        if row["target_id"] != current.full_name:
            return None
        if row["outcome"] not in REFUSAL_OUTCOMES:
            return None
        return self._insight(row)

    def latest_refusal(self, viewer, owner, repo):
        """The newest refusal's explanation, or
        None when nothing has been refused."""
        found = self.insights_for(
            viewer, owner, repo, limit=1)
        return found[0] if found else None


def _stamp(ts: int) -> str:
    return time.strftime(
        "%Y-%m-%d %H:%M UTC", time.gmtime(ts))


def render_insight(insight: RuleInsight) -> str:
    """One refusal explained, escaped through
    S-010: the words, then the recorded action
    and outcome as data, never colour alone."""
    return (
        '<div class="rule-insight">'
        f"<p>{escape_html_text(insight.words)}</p>"
        f"<p>Recorded as "
        f"{escape_html_text(insight.action)} · "
        f"{escape_html_text(insight.outcome)} · "
        f"audit entry {insight.seq}.</p>"
        "</div>")


def render_insights_page(full_name: str,
                         insights) -> str:
    """The rule insights page for one repository:
    why pushes and merges were refused, in plain
    words, from the audit trail."""
    who = escape_html_text(full_name)
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Rule insights — {who} — Samverk</title>"
        "</head>",
        "<body>",
        "<h1>Rule insights</h1>",
        f"<p>Why pushes and merges in {who} were "
        "refused, in plain words, from the audit "
        "trail.</p>",
        "<p>This page explains the refusals the "
        "audit trail recorded. A refusal a gate made "
        "without writing an audit row cannot appear "
        "here.</p>",
    ]
    if not insights:
        parts.append(
            '<p class="empty">Nothing has been '
            "refused in this repository yet. When a "
            "protection rule refuses a push or a "
            "merge, the refusal and its reason will "
            "be explained here.</p>")
    for insight in insights:
        parts.append(render_insight(insight))
    parts.append("</body></html>")
    return "\n".join(parts)
