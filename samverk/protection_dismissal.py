"""Dismiss stale reviews (S-172).

Part VIII's stale-dismissal rule: the S-169 rule field
`dismiss_stale_reviews`, wired to the record it governs.
Before this slice that field was stored policy with no
teeth — a rule could say stale reviews are dismissed
and an approval of code that no longer stood on the
head branch still counted everywhere S-149's repository
policy left it counting. Now there is one place that
answers, for a pull request, the question a merge gate
asks about dismissal:

- **The one judgment.** `DismissalProtectionStore` —
  and, for a caller that already holds the records, the
  pure `decide_dismissal` it delegates to — resolves
  the pull request's base branch once through S-169's
  `ProtectionRuleStore.evaluate_branch` (the one
  evaluation Part VIII consults; matching, ordering,
  and the most-restrictive fold are never re-derived
  here, so the rule speaks when ANY matching rule
  carries the toggle) and the pull request's reviews
  once through S-149's `freshness_for` (the one
  freshness judgment; which head each review was
  submitted against, and the head as it stands now,
  are S-149's record, never re-read here), then
  applies the rule between them. No new policy storage
  is owned: no migration (schema stays 66), no new
  taxonomy event (119 events stand; rule changes
  already audit under the frozen
  `repo.protection.change`, and a judgment itself
  writes nothing and audits nothing, exactly as
  S-170's and S-171's checks do).
- **What the rule dismisses.** When the effective rule
  for the base branch carries `dismiss_stale_reviews`,
  a new push dismisses approvals per S-149: an approval
  submitted against an older head is *dismissed* — it
  no longer counts for any gate that consults this
  decision — whether or not the repository's own S-149
  policy would have stale-dated it. The rule is, in
  effect, S-149's `approvals` mode scoped to the
  protected branch. Change requests and comment reviews
  are NOT dismissed by the rule: a change request
  against an older head still blocks until its reviewer
  approves (it may still go stale under the
  repository's own policy, in S-149's words, as before),
  and a comment, which gates nothing, is untouched.
- **Dismissal is judged on read, never stored** (the
  S-145/S-146/S-149 law). No push hook writes dismissal
  flags that could disagree with the record, and no
  review row changes: a dismissal appears when the head
  moves, and lifts in exactly two ways — the reviewer
  approves again against the head as it now stands
  (their new approval counts; their dismissed one is
  still shown, marked dismissed), or the rule is
  changed so it no longer dismisses (the next judgment
  counts the approval again under the repository
  policy as it then stands). A reviewer's *latest
  counting* verdict is what speaks for them: an
  approval superseded by a counting change request
  approves nothing, and a dismissed approval superseded
  by a fresh approval counts through the fresh one.
- **Self-approval never counts** (the S-164/S-171 law,
  kept here so a gate cannot get it wrong): S-148
  refuses a verdict on one's own pull request at
  submission, and this decision additionally never
  counts the pull request's author among its approvers,
  whatever record it is handed — though the author's
  own old approval can still be *shown* as dismissed,
  it vouches for nothing in either state.
- **Reads ride the house guards, and mutate nothing.**
  The pull request is read through S-141's seam first
  (a stranger to a private repository gets the uniform
  `pull_request_not_found` before any dismissal is
  named) and the branch's policy through S-169's store
  (the uniform `repo_not_found`). The judgment is a
  pure read: no row changes, no audit row, no stored
  verdict of its own.
- **Said in words, never a colour alone.** A decision
  carries its position as `words`, each dismissed
  approval is named with its reason in the entries'
  own words, and the one renderer says exactly those
  words, escaped through S-010. No route is invented:
  the store is the surface, as S-170's and S-171's
  checks landed route-free.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .issues import IssueStore
from .protection_rules import (
    ProtectionEvaluation, ProtectionRuleStore)
from .pull_request_review_freshness import (
    FreshnessReport, PullRequestReviewFreshnessStore,
    ReviewFreshness)
from .pull_requests import PullRequestStore
from .repositories import RepositoryStore

__all__ = [
    "DismissalDecision", "DismissalEntry",
    "DismissalProtectionStore", "decide_dismissal",
    "render_dismissal_decision",
]


@dataclass(frozen=True)
class DismissalEntry:
    """One submitted review under the dismissal rule:
    S-149's freshness entry, whether the branch rule
    dismisses it, and the position said in words."""
    freshness: ReviewFreshness

    # Set by decide_dismissal; carried on the entry so
    # every surface says the same words.
    rule_dismissed: bool = False

    @property
    def review(self):
        return self.freshness.review

    @property
    def counts(self) -> bool:
        """Whether this review still counts after both
        judgments: S-149 counts it, and the branch rule
        does not dismiss it."""
        return self.freshness.counts and not self.rule_dismissed

    @property
    def is_stale(self) -> bool:
        """S-149's own word: the repository policy
        stale-dates this review."""
        return self.freshness.is_stale

    @property
    def state_words(self) -> str:
        if self.rule_dismissed:
            return "Dismissed — no longer counts"
        return self.freshness.state_words

    @property
    def reason_words(self) -> str:
        if self.rule_dismissed:
            return ("Submitted against an earlier head; "
                    "the head has moved since, and this "
                    "branch's protection rule dismisses "
                    "stale approvals on a new push.")
        return self.freshness.reason_words


@dataclass(frozen=True)
class DismissalDecision:
    """One pull request's dismissal position, resolved
    once: the S-169 evaluation for its base branch, the
    S-149 freshness report it was judged against, and
    every review marked counting or dismissed."""
    full_name: str
    number: int
    base_branch: str
    head_branch: str
    author_id: int
    evaluation: ProtectionEvaluation
    freshness: FreshnessReport
    entries: tuple             # of DismissalEntry, oldest first

    # -- the rule ------------------------------------------------------
    @property
    def dismiss_stale_reviews(self) -> bool:
        """Whether the effective rule for the base
        branch carries the dismissal toggle — the fold
        of every matching rule, per S-169."""
        effective = self.evaluation.effective
        return bool(
            effective is not None
            and effective.settings.dismiss_stale_reviews)

    # -- the entries -----------------------------------------------------
    @property
    def total(self) -> int:
        return len(self.entries)

    @property
    def dismissed_entries(self) -> tuple:
        """Approvals the branch rule dismisses."""
        return tuple(e for e in self.entries if e.rule_dismissed)

    @property
    def dismissed_count(self) -> int:
        return len(self.dismissed_entries)

    @property
    def counting_entries(self) -> tuple:
        return tuple(e for e in self.entries if e.counts)

    @property
    def counting_count(self) -> int:
        return len(self.counting_entries)

    @property
    def stale_count(self) -> int:
        """Reviews S-149's repository policy itself
        stale-dates, before the rule is applied."""
        return self.freshness.stale_count

    # -- who still speaks --------------------------------------------------
    @property
    def latest_counting_by_reviewer(self) -> dict:
        """Each reviewer's latest verdict that still
        counts after dismissal — the record merge gates
        consult, on S-149/S-164's shape."""
        latest: dict = {}
        for entry in self.entries:
            if entry.counts:
                latest[entry.review.reviewer_id] = entry.review.verdict
        return latest

    @property
    def counting_approver_ids(self) -> tuple:
        """Reviewers whose latest counting verdict
        approves — the author never among them."""
        return tuple(
            rid for rid, verdict
            in self.latest_counting_by_reviewer.items()
            if verdict == "approved" and rid != self.author_id)

    @property
    def approval_count(self) -> int:
        return len(self.counting_approver_ids)

    @property
    def dismissed_approver_ids(self) -> tuple:
        """Reviewers an approval was dismissed from who
        hold no counting approval now — a reviewer who
        approved again against the current head is not
        among them; their fresh approval speaks."""
        out = []
        for entry in self.dismissed_entries:
            rid = entry.review.reviewer_id
            if rid not in self.counting_approver_ids \
                    and rid not in out:
                out.append(rid)
        return tuple(out)

    @property
    def has_dismissed_approval(self) -> bool:
        return bool(self.dismissed_entries)

    # -- the position, in words --------------------------------------------
    @property
    def words(self) -> str:
        if self.dismiss_stale_reviews:
            rule = (f"Branch '{self.base_branch}' dismisses "
                    f"stale reviews on new pushes")
        else:
            rule = (f"Branch '{self.base_branch}' does not "
                    f"dismiss stale reviews")
        if self.total == 0:
            return (f"Pull request #{self.number} in "
                    f"{self.full_name}: {rule}; no reviews "
                    f"have been submitted yet.")
        position = (
            f"Pull request #{self.number} in {self.full_name}: "
            f"{rule}; {self.counting_count} of {self.total} "
            f"{'review still counts' if self.counting_count == 1 else 'reviews still count'}"
            f"; {self.approval_count} "
            f"{'approval counts' if self.approval_count == 1 else 'approvals count'}.")
        if self.dismissed_count:
            noun = ("approval was" if self.dismissed_count == 1
                    else "approvals were")
            position += (
                f" {self.dismissed_count} {noun} dismissed: "
                f"submitted against an earlier head, and the "
                f"head has moved since.")
        elif self.dismiss_stale_reviews:
            position += " No approval stands dismissed."
        return position


def decide_dismissal(
        evaluation: ProtectionEvaluation,
        freshness: FreshnessReport, *,
        author_id: int,
        head_branch: str = "") -> DismissalDecision:
    """The pure half of the rule: one pull request's
    dismissal decision from its already-resolved S-169
    evaluation and S-149 freshness report. An approval
    is rule-dismissed iff the effective rule dismisses
    stale reviews, the approval's verdict is `approved`,
    and the head it was submitted against is no longer
    the current head — S-149's own stale test for
    approvals, scoped to the protected branch. No
    database is touched here, so the judgment is
    provable in isolation; the store below only has to
    gather the records honestly."""
    effective = evaluation.effective
    dismiss = bool(
        effective is not None
        and effective.settings.dismiss_stale_reviews)
    current_head = freshness.current_head_oid
    entries = tuple(
        DismissalEntry(
            freshness=entry,
            rule_dismissed=bool(
                dismiss
                and entry.review.verdict == "approved"
                and entry.review.head_oid != current_head))
        for entry in freshness.entries)
    return DismissalDecision(
        full_name=evaluation.full_name,
        number=freshness.number,
        base_branch=evaluation.branch,
        head_branch=head_branch,
        author_id=author_id,
        evaluation=evaluation,
        freshness=freshness,
        entries=entries)


class DismissalProtectionStore:
    """The store half of the rule: gather one pull
    request through S-141's seam, its base branch's
    evaluation through S-169's store, and its reviews
    through S-149's freshness store, then delegate to
    `decide_dismissal`. Merge gates hold this store and
    never re-derive protection, freshness, or dismissal
    themselves."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        issues: IssueStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
        protection_rules: ProtectionRuleStore | None = None,
        freshness: PullRequestReviewFreshnessStore | None = None,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._issues = issues
        self._audit = audit
        self._now = time_fn
        self._rules = protection_rules or ProtectionRuleStore(
            conn, repositories, accounts,
            audit=audit, time_fn=time_fn)
        self._prs = PullRequestStore(
            conn, repositories, accounts, issues, audit=audit,
            time_fn=time_fn)
        self._freshness = freshness or PullRequestReviewFreshnessStore(
            conn, repositories, accounts, issues, audit=audit,
            time_fn=time_fn)

    def dismissal_for(self, viewer: User | None, owner: object,
                      repo: object, number: object) -> DismissalDecision:
        """THE one judgment S-172's rule consults: this
        pull request's dismissal decision, resolved
        once. The pull request is read through S-141's
        seam first, so a stranger to a private
        repository gets the uniform
        `pull_request_not_found` before any dismissal
        position is named."""
        pr = self._prs.get_pull_request(viewer, owner, repo, number)
        evaluation = self._rules.evaluate_branch(
            viewer, owner, repo, pr.base_branch)
        freshness = self._freshness.freshness_for(
            viewer, owner, repo, pr.number)
        return decide_dismissal(
            evaluation, freshness, author_id=pr.author_id,
            head_branch=pr.head_branch)


def render_dismissal_decision(decision: DismissalDecision) -> str:
    """One dismissal decision in words — the decision's
    own `words`, then every review with its state and
    reason in words, escaped through S-010, never a
    colour alone. The sentences S-183's rule insights
    will quote when they answer "why did my approval
    stop counting?"."""
    items = "".join(
        '<li class="review-dismissal">'
        f"{escape_html_text(entry.review.verdict_words)} — "
        f"{escape_html_text(entry.state_words)} "
        f"({escape_html_text(entry.reason_words)})"
        "</li>"
        for entry in decision.entries)
    listing = f"<ul>{items}</ul>" if items else ""
    return (
        '<div class="protection-dismissal">'
        f"<p>{escape_html_text(decision.words)}</p>"
        f"{listing}</div>")
