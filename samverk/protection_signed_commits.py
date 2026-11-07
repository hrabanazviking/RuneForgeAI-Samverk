"""Require signed commits (S-175).

Pushes and merges carrying unsigned commits refused:
the branch protection rule (S-169) may require signed
commits on a branch, and this slice is the gate that
judges the commits a push or a pull-request merge
would land against that requirement, in the shape
S-170 (direct-push refusal), S-171 (approvals), S-173
(code owners) and S-174 (status checks) established.

- **The requirement is the folded rule's word.** The
  branch is resolved once through S-169's
  `ProtectionRuleStore.evaluate_branch` (matching,
  documented evaluation order, and the
  most-restrictive fold are never re-derived here):
  the gate speaks the folded `require_signed_commits`.
  A branch no rule matches carries no requirement,
  and the gate is satisfied by construction.
- **Signed means a signature header is present.**
  Cryptographic verification of commit signatures
  lands in Part XV; the rule shape lands here. A
  commit is signed when its raw commit object carries
  a non-empty `gpgsig` header (the OpenPGP shape git
  writes for `commit.gpgsign`) or a non-empty
  `gpgsig-sha256` header (its SHA-256 twin), read from
  the header block only — a signature-looking line in
  the commit message body vouches for nothing, and an
  empty header vouches for nothing. Whether the
  signature is *valid* is Part XV's question, never
  this gate's: this gate refuses the unsigned, and
  says so in exactly those words.
- **Every carried commit is judged.** At the push
  door, the commits judged are the ones the update
  carries: `old..new` for a move, and for a branch
  creation the commits reachable from the new tip
  that no existing ref already carries. A deletion
  carries no commits and is not refused here (branch
  deletion has S-177's own block, later). At the
  merge door, the commits judged are the pull
  request's head commits the base does not already
  have (`base..head`, a cross-fork head fetched under
  this gate's scratch ref and the scratch ref always
  dropped afterwards — the merge road's discipline).
  The merge commit the forge itself would mint on
  landing is not judged: it does not exist yet, and
  forge-minted commits are the forge's own signing
  policy, not the pusher's.
- **An uncountable position never passes.** When the
  commits cannot be enumerated or read at all (a ref
  that does not resolve, an unreadable object), a
  branch whose rule requires signed commits is
  refused with the position said in words — a gate
  that demands proof never passes on no proof. With
  no requirement, an uncounted position binds
  nothing and the decision still says it was not
  counted.
- **The refusal is one code, the reason a sentence.**
  `enforce_*` raises `signed_commits_required` (a
  `RepositoryError` carrying `.reason`) with the
  first blocker's sentence: which commit (by short
  oid and subject) carries no signature, and what to
  do about it — sign the commits and push or update
  again. The decision says its whole position in
  words, and the one renderer prints exactly those
  words escaped through S-010, never a colour alone.
- **A pure read.** The judgment writes nothing and
  audits nothing, so no taxonomy event is added
  (119 stand) and no migration is claimed (schema
  stays 66); rule changes already audit under the
  frozen `repo.protection.change`, and
  docs/AUDIT_TAXONOMY.md records the slice on that
  basis. Reads ride the house guards first — S-169's
  evaluation for branches, S-141's seam for pull
  requests — so a stranger to a private repository
  gets the uniform `repo_not_found` /
  `pull_request_not_found` before any signature
  position is named.
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
from .proc import run_git_fetch_ref, run_git_in
from .protection_pull_request import branch_from_ref
from .protection_rules import ProtectionEvaluation, ProtectionRuleStore
from .pull_request_forks import ForkPullRequestStore
from .pull_requests import PullRequestStore
from .receive_gate import GateVeto
from .refs import RefStore, branch_ref
from .repositories import RepositoryError, RepositoryStore

__all__ = [
    "SIGNED_COMMITS_REQUIRED", "CommitSignature",
    "SignedCommitDecision", "SignedCommitProtectionStore",
    "SignedCommitsRequiredError", "commit_signature",
    "decide_signed_commits", "render_signed_commit_decision",
]

SIGNED_COMMITS_REQUIRED = "signed_commits_required"

#: The null oid a ref update carries for a ref that
#: does not exist on that side (creation / deletion).
ZERO_OID = "0" * 40

#: The scratch ref a cross-fork head is fetched under
#: while its commits are judged — under this gate's
#: own name so it never collides with another gate's;
#: always dropped after the judgment.
SCRATCH_REF = "refs/samverk-signed-commits/head"

#: Signature header name (lowercase, as git writes it)
#: -> the kind word the decision speaks.
_SIGNATURE_HEADERS = {
    "gpgsig": "OpenPGP",
    "gpgsig-sha256": "OpenPGP (SHA-256)",
}


class SignedCommitsRequiredError(RepositoryError):
    """A signed-commits refusal: a RepositoryError
    carrying `.reason` (`signed_commits_required`),
    mirroring StatusChecksRequiredError and
    PullRequestRequiredError."""


@dataclass(frozen=True)
class CommitSignature:
    """One commit's signature position, read from its
    raw object: whether a signature header is present
    and non-empty, the kind word for it ('' when
    unsigned), and the commit's subject for refusal
    sentences."""
    oid: str
    signed: bool
    kind: str = ""
    subject: str = ""

    @property
    def short_oid(self) -> str:
        return self.oid[:12]


def commit_signature(raw: bytes, oid: str = "") -> CommitSignature:
    """One raw commit object's signature position.
    Only the header block (everything before the first
    blank line) speaks: a header whose name is a known
    signature header and whose value — first line plus
    space-led continuation lines — is non-empty marks
    the commit signed. Anything in the message body is
    not a header and vouches for nothing."""
    head, _, message = raw.partition(b"\n\n")
    subject = (message.decode("utf-8", "replace")
               .split("\n", 1)[0].strip() or "no subject")
    headers: dict[str, str] = {}
    name: str | None = None
    for line in head.split(b"\n"):
        if line.startswith(b" ") and name is not None:
            headers[name] += "\n" + line[1:].decode("utf-8", "replace")
            continue
        key, _, value = line.partition(b" ")
        name = key.decode("ascii", "replace").lower()
        headers[name] = value.decode("utf-8", "replace")
    for header, kind in _SIGNATURE_HEADERS.items():
        value = headers.get(header)
        if value is not None and value.strip():
            return CommitSignature(
                oid=oid, signed=True, kind=kind, subject=subject)
    return CommitSignature(oid=oid, signed=False, subject=subject)


@dataclass(frozen=True)
class SignedCommitDecision:
    """One landing's signed-commits position, resolved
    once: the S-169 evaluation for the branch being
    landed on, the commits the landing carries (None
    when they could not be counted), and the answer
    said in words. `number` is the pull request number
    at the merge door, 0 at the push door."""
    full_name: str
    branch: str
    number: int
    evaluation: ProtectionEvaluation
    commits: tuple | None      # of CommitSignature; None = uncounted

    @property
    def required(self) -> bool:
        effective = self.evaluation.effective
        return bool(
            effective is not None
            and effective.settings.require_signed_commits)

    @property
    def counted(self) -> bool:
        return self.commits is not None

    @property
    def unsigned_commits(self) -> tuple:
        if not self.counted:
            return ()
        return tuple(c for c in self.commits if not c.signed)

    @property
    def signed_count(self) -> int:
        if not self.counted:
            return 0
        return sum(1 for c in self.commits if c.signed)

    @property
    def blockers(self) -> tuple:
        out: list[str] = []
        if not self.required:
            return ()
        if not self.counted:
            out.append(
                f"The rule requires signed commits on "
                f"branch '{self.branch}', and the commits "
                f"this landing carries could not be "
                f"counted; sign the commits and try again.")
            return tuple(out)
        for commit in self.unsigned_commits:
            out.append(
                f"Commit {commit.short_oid} "
                f"('{commit.subject}') carries no "
                f"signature, and the rule requires signed "
                f"commits on branch '{self.branch}'; sign "
                f"the commits and push or update again.")
        return tuple(out)

    @property
    def satisfied(self) -> bool:
        if not self.required:
            return True
        return self.counted and not self.unsigned_commits

    @property
    def reason(self) -> str:
        blockers = self.blockers
        if blockers:
            return blockers[0]
        return self.words

    @property
    def door(self) -> str:
        if self.number:
            return f"pull request #{self.number} merging into"
        return "a push to"

    @property
    def words(self) -> str:
        if not self.required:
            position = "no rule requires signed commits"
        elif not self.counted:
            position = "the commits it carries were not counted"
        else:
            total = len(self.commits)
            position = (
                f"{self.signed_count} of {total} carried "
                f"commit{'s' if total != 1 else ''} signed")
        verdict = "satisfied" if self.satisfied else "not satisfied"
        return (
            f"Signed-commits gate for {self.door} branch "
            f"'{self.branch}' in {self.full_name}: "
            f"{position}. The signed-commits gate is {verdict}.")


def decide_signed_commits(
        evaluation: ProtectionEvaluation,
        commits, *,
        number: int = 0) -> SignedCommitDecision:
    """The pure half of the gate: one landing's
    signed-commits decision from its already-resolved
    S-169 evaluation and the CommitSignature records
    of the commits it carries (None when they could
    not be counted). No database and no git repository
    are touched here, so the judgment is provable in
    isolation; the store below only has to gather the
    records honestly."""
    return SignedCommitDecision(
        full_name=evaluation.full_name,
        branch=evaluation.branch,
        number=number,
        evaluation=evaluation,
        commits=None if commits is None else tuple(commits))


def _ref_of(update: object) -> object:
    """One ref update's ref, from whatever shape the
    caller carries it in: a RefUpdate (`.ref`), a
    mapping (`ref` key), or a tuple/list whose first
    item is the ref — the S-170 shape, so callers that
    carry pushes in any of these shapes work here."""
    ref = getattr(update, "ref", None)
    if ref is not None:
        return ref
    if isinstance(update, dict):
        return update.get("ref")
    if isinstance(update, (tuple, list)) and update:
        return update[0]
    return None


def _oid_of(update: object, *names: str, index: int) -> str:
    """One ref update's old or new oid, from the same
    shapes: a RefUpdate's `.old_oid` / `.new_oid`, a
    mapping's `old` / `new` / `old_oid` / `new_oid`
    keys, or a tuple/list position. '' when unknown —
    the caller then judges nothing, per S-089's law
    that transports pass the updates they know."""
    for name in names:
        value = getattr(update, name, None)
        if value:
            return str(value)
    if isinstance(update, dict):
        for name in names:
            if update.get(name):
                return str(update[name])
    if isinstance(update, (tuple, list)) and len(update) > index:
        return str(update[index]) if update[index] else ""
    return ""


class SignedCommitProtectionStore:
    """The store half of the gate: gather one branch's
    evaluation through S-169's store, enumerate the
    commits a landing carries through git, read each
    commit's signature header, and delegate to
    `decide_signed_commits`. Push and merge callers
    hold this store and never re-derive protection,
    history, or signature presence themselves."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        issues: IssueStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
        protection_rules: ProtectionRuleStore | None = None,
        forks: ForkPullRequestStore | None = None,
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
        self._forks = forks or ForkPullRequestStore(
            conn, repositories, accounts, issues, audit=audit,
            time_fn=time_fn)

    # -- git reading -------------------------------------------------

    def _read_commit(self, repo_path, oid: str) -> CommitSignature | None:
        """One commit's signature position from its raw
        object, or None when the object cannot be read."""
        result = run_git_in(repo_path, ["cat-file", "commit", oid],
                            timeout=15.0)
        if result.returncode != 0:
            return None
        return commit_signature(result.stdout, oid=oid)

    def _commits(self, repo_path, range_args: list[str]
                 ) -> tuple | None:
        """The CommitSignature records for one rev-list
        walk, newest first — None when the walk or any
        object read fails, so the decision fails closed
        instead of judging a partial history."""
        result = run_git_in(
            repo_path, ["rev-list", *range_args], timeout=30.0)
        if result.returncode != 0:
            return None
        commits: list[CommitSignature] = []
        for oid in result.stdout.decode().split():
            record = self._read_commit(repo_path, oid)
            if record is None:
                return None
            commits.append(record)
        return tuple(commits)

    def _push_commits(self, repo_path, old_oid: str, new_oid: str
                      ) -> tuple | None:
        """The commits one branch update carries: a move
        carries `old..new`; a creation carries the
        commits reachable from the new tip that no
        existing ref already carries; a deletion
        carries none."""
        if not new_oid or new_oid == ZERO_OID:
            return ()
        if old_oid and old_oid != ZERO_OID:
            return self._commits(repo_path, [f"{old_oid}..{new_oid}"])
        return self._commits(repo_path, [new_oid, "--not", "--all"])

    # -- the push door -------------------------------------------------

    def check_push_update(self, viewer: User | None, owner: object,
                          repo: object, branch: object,
                          old_oid: str, new_oid: str
                          ) -> SignedCommitDecision:
        """THE one check the push door consults: this
        branch update's signed-commits decision. The
        evaluation is read through S-169, so a stranger
        to a private repository gets the uniform
        `repo_not_found` before any signature position
        is named."""
        evaluation = self._rules.evaluate_branch(
            viewer, owner, repo, branch)
        base_repo = self._repos.get_repository(owner, repo)
        if base_repo is None:
            return decide_signed_commits(evaluation, None)
        repo_path = self._repos.path_for(base_repo.owner, base_repo.name)
        commits = self._push_commits(repo_path, old_oid, new_oid)
        return decide_signed_commits(evaluation, commits)

    def enforce_push_update(self, viewer: User | None, owner: object,
                            repo: object, branch: object,
                            old_oid: str, new_oid: str
                            ) -> SignedCommitDecision:
        """The push check, as a refusal: returns the
        satisfied decision, or raises
        `signed_commits_required` carrying the
        human-readable reason."""
        decision = self.check_push_update(
            viewer, owner, repo, branch, old_oid, new_oid)
        if not decision.satisfied:
            raise SignedCommitsRequiredError(
                SIGNED_COMMITS_REQUIRED, decision.reason)
        return decision

    def check_push(self, viewer: User | None, owner: object,
                   repo: object, updates, *,
                   via_pull_request: bool = False
                   ) -> tuple:
        """Every branch decision in one push, in the
        push's own update order. Non-branch refs are
        skipped. A landing that arrives by pull
        request is not a direct push: its commits are
        judged at the merge door, never here, and the
        push door allows it in words. Updates whose
        oids are unknown carry no commits this gate
        can judge and are skipped — S-089's law that
        transports pass the updates they know."""
        decisions = []
        for update in updates or ():
            branch = branch_from_ref(_ref_of(update))
            if branch is None:
                continue
            old_oid = _oid_of(update, "old_oid", "old", index=1)
            new_oid = _oid_of(update, "new_oid", "new", index=2)
            if via_pull_request:
                evaluation = self._rules.evaluate_branch(
                    viewer, owner, repo, branch)
                decisions.append(decide_signed_commits(
                    evaluation, ()))
                continue
            if not new_oid:
                continue
            decisions.append(self.check_push_update(
                viewer, owner, repo, branch, old_oid, new_oid))
        return tuple(decisions)

    def enforce_push(self, viewer: User | None, owner: object,
                     repo: object, updates, *,
                     via_pull_request: bool = False
                     ) -> tuple:
        """A whole push, as a refusal: the first refused
        branch in update order raises
        `signed_commits_required` with its reason —
        first refusal wins, as at S-089's gate."""
        decisions = self.check_push(
            viewer, owner, repo, updates,
            via_pull_request=via_pull_request)
        for decision in decisions:
            if not decision.satisfied:
                raise SignedCommitsRequiredError(
                    SIGNED_COMMITS_REQUIRED, decision.reason)
        return decisions

    # -- the merge door -------------------------------------------------

    def _pr_commits(self, viewer: User | None, owner: object,
                    repo: object, pr) -> tuple | None:
        """The head commits one pull request's merge
        would land: `base..head`, a cross-fork head
        fetched under this gate's scratch ref and the
        scratch ref always dropped afterwards."""
        base_repo = self._repos.get_repository(owner, repo)
        if base_repo is None:
            return None
        base_path = self._repos.path_for(base_repo.owner, base_repo.name)
        refs = RefStore(base_path)
        base_oid = refs.resolve(branch_ref(pr.base_branch)) or ""
        if not base_oid:
            return None
        record = self._forks.get_cross_fork(viewer, owner, repo, pr.number)
        scratch_live = False
        try:
            if record is not None:
                head_repo = self._repos.get_repository(
                    *record.head_full_name.split("/", 1))
                if head_repo is None:
                    return None
                head_path = self._repos.path_for(
                    head_repo.owner, head_repo.name)
                result = run_git_fetch_ref(
                    base_path, head_path,
                    branch_ref(pr.head_branch), SCRATCH_REF)
                if result.returncode != 0:
                    return None
                scratch_live = True
                head_oid = refs.resolve(SCRATCH_REF)
            else:
                head_oid = refs.resolve(branch_ref(pr.head_branch))
            if not head_oid:
                return None
            return self._commits(
                base_path, [f"{base_oid}..{head_oid}"])
        finally:
            if scratch_live:
                run_git_in(base_path, ["update-ref", "-d", SCRATCH_REF],
                           timeout=15.0)

    def check_pull_request(self, viewer: User | None, owner: object,
                           repo: object, number: object
                           ) -> SignedCommitDecision:
        """THE one check the merge door consults: this
        pull request's signed-commits decision. The
        pull request is read through S-141's seam
        first, so a stranger to a private repository
        gets the uniform `pull_request_not_found`
        before any signature position is named."""
        pr = self._prs.get_pull_request(viewer, owner, repo, number)
        evaluation = self._rules.evaluate_branch(
            viewer, owner, repo, pr.base_branch)
        commits = self._pr_commits(viewer, owner, repo, pr)
        return decide_signed_commits(
            evaluation, commits, number=pr.number)

    def enforce_pull_request(self, viewer: User | None, owner: object,
                             repo: object, number: object
                             ) -> SignedCommitDecision:
        """The merge check, as a refusal: returns the
        satisfied decision, or raises
        `signed_commits_required` carrying the
        human-readable reason."""
        decision = self.check_pull_request(
            viewer, owner, repo, number)
        if not decision.satisfied:
            raise SignedCommitsRequiredError(
                SIGNED_COMMITS_REQUIRED, decision.reason)
        return decision

    # -- the S-089 gate plug-in -----------------------------------------

    def receive_gate_plugin(self):
        """This check as an S-089 `protection`-stage
        plug-in: a callable over the gate context that
        allows (returns None) or vetoes with the
        refusal sentence (raises GateVeto). The actor
        is the gate context's username, resolved
        through the account store — an actor that
        resolves to nobody is judged as an anonymous
        viewer, so a private repository's position is
        never named to them (the gate then fails
        closed on S-169's `repo_not_found`, as every
        gate stage does on error). The merge road
        marks its landings with the payload key
        `via_pull_request`; the wire transports never
        set it, so a receive-pack push is always
        judged as the direct push it is."""
        def plugin(context):
            actor = context.actor
            viewer = None
            if isinstance(actor, str) and actor:
                viewer = self._accounts.get_by_username(actor)
            via = bool(context.payload.get("via_pull_request"))
            decisions = self.check_push(
                viewer, context.owner, context.repo_name,
                context.updates, via_pull_request=via)
            for decision in decisions:
                if not decision.satisfied:
                    raise GateVeto(decision.reason)
            return None
        return plugin


def render_signed_commit_decision(decision: SignedCommitDecision) -> str:
    """One signed-commits decision in words — exactly
    the decision's own `words`, with its blockers
    listed when it has any, escaped through S-010,
    never a colour alone. The sentences S-183's rule
    insights will quote when they answer "why was
    this push or merge refused?"."""
    blockers = ""
    if decision.blockers:
        items = "".join(
            f"<li>{escape_html_text(blocker)}</li>"
            for blocker in decision.blockers)
        blockers = f"<ul>{items}</ul>"
    return (
        '<div class="protection-signed-commits">'
        f"<p>{escape_html_text(decision.words)}</p>"
        f"{blockers}</div>")
