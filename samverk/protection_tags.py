"""Tag protection (S-182).

Tag name patterns protected from deletion and
force-move; release tags get the strongest default.

- **The pattern layer is S-181's rulesets.** A tag's
  position is resolved once through
  `RulesetStore.evaluate_ref(viewer, owner, repo,
  "tag", tag)` — the layered evaluation (per-repo
  rules do not attach to tags, so the ruleset layer
  is the tag layer). A ruleset targeting tags (or
  all refs) whose tag patterns match this tag, in a
  repo its repo patterns match, protects the tag.
  Its folded settings speak: `block_force_pushes`
  is the force-move block and `block_branch_deletion`
  is the deletion block for a tag (the S-169 shape's
  two blocks, applied to the ref kind at hand).
- **Release tags get the strongest default.** A tag
  is a release tag when it looks like a release:
  `v` followed by a digit version (`v1`, `v1.2`,
  `v1.2.3`, with any suffix), a bare semantic version
  (`1.2.3`), or a `release-` / `release/` prefix
  (case-insensitive). A release tag is protected by
  default even when no ruleset matches it, and for a
  release tag BOTH blocks bind at their strongest:
  deletion and force-move are refused for everyone,
  whatever a matching ruleset's settings say about
  either block — a ruleset can add protection to a
  release tag, never take the default away.
- **A tag update has one shape** — S-177's
  `update_shape` reused, never re-derived: creation,
  fast-forward, force move, deletion, no-op, or
  unproven. Ancestry is git's own answer.
- **Everyone is bound.** No role is consulted:
  owner, admin, writer — a blocked shape is refused
  for all alike. S-179 bypass and S-180 admin
  toggles are not smuggled in; no silent door.
- **An unproven move never passes a force block.**
- **Creations, fast-forwards and no-ops pass.**
- **The refusal is one code** `protected_tag_refused`
  with a human-readable reason sentence.
- **A pure read.** No migration (schema stays 67),
  no new taxonomy event (120 stand); docs record
  the slice. Reads ride S-181's guard: a stranger
  to a private repo gets `repo_not_found` first.
"""
from __future__ import annotations

import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .issues import IssueStore
from .proc import run_git_in
from .protection_push_shape import update_shape, CREATION, DELETION, FAST_FORWARD, FORCE, NO_OP, UNPROVEN
from .protection_rulesets import LayeredEvaluation, RulesetStore
from .receive_gate import GateVeto
from .repositories import RepositoryError, RepositoryStore

__all__ = [
    "PROTECTED_TAG_REFUSED",
    "TagDecision", "TagProtectionStore", "TagRefusedError",
    "decide_tag_update", "is_release_tag", "render_tag_decision",
    "tag_from_ref",
]

PROTECTED_TAG_REFUSED = "protected_tag_refused"
ZERO_OID = "0" * 40
_TAG_PREFIX = "refs/tags/"

_RELEASE_RE = re.compile(
    r"^(?:v\d+(?:\.\d+){0,2}(?:[-+._].*)?|\d+\.\d+\.\d+(?:[-+._].*)?|release[-/].+)$",
    re.IGNORECASE)

_SHAPE_WORDS = {
    CREATION: "the update creates the tag",
    FAST_FORWARD: "the update fast-forwards the tag",
    FORCE: "the update is a force move of the tag",
    DELETION: "the update deletes the tag",
    NO_OP: "the update changes nothing",
    UNPROVEN: "the update moves the tag, and its fast-forwardness was not proven",
}


def is_release_tag(tag: object) -> bool:
    if not isinstance(tag, str):
        return False
    return bool(_RELEASE_RE.match(tag.strip()))


def tag_from_ref(ref: object) -> str | None:
    if not isinstance(ref, str):
        return None
    if not ref.startswith(_TAG_PREFIX):
        return None
    tag = ref[len(_TAG_PREFIX):]
    return tag or None


class TagRefusedError(RepositoryError):
    pass


@dataclass(frozen=True)
class TagDecision:
    full_name: str
    tag: str
    evaluation: LayeredEvaluation | None
    old_oid: str
    new_oid: str
    shape: str
    release: bool = False

    @property
    def _settings(self):
        if self.evaluation is None:
            return None
        return self.evaluation.effective

    @property
    def is_protected(self) -> bool:
        return self.release or bool(self.evaluation is not None and self.evaluation.is_protected)

    @property
    def blocks_deletion(self) -> bool:
        if self.release:
            return True
        s = self._settings
        return bool(s is not None and s.block_branch_deletion)

    @property
    def blocks_force_move(self) -> bool:
        if self.release:
            return True
        s = self._settings
        return bool(s is not None and s.block_force_pushes)

    @property
    def blockers(self) -> tuple:
        out = []
        if self.shape == DELETION and self.blocks_deletion:
            why = "it is a release tag, and release tags get the strongest default protection" if self.release and not (self.evaluation and self.evaluation.is_protected) else "the tag protection blocks deletion"
            out.append(
                f"This update deletes tag '{self.tag}', and {why}; "
                f"a protected tag cannot be deleted — remove or retarget the tag protection first if the tag must go. "
                f"The block binds everyone, admins included.")
        elif self.shape == FORCE and self.blocks_force_move:
            why = "it is a release tag, and release tags get the strongest default protection" if self.release and not (self.evaluation and self.evaluation.is_protected) else "the tag protection blocks force moves"
            out.append(
                f"This update is a force move of tag '{self.tag}' (the old tip {self.old_oid[:12]} is not an ancestor of the new tip {self.new_oid[:12]}), "
                f"and {why}; move the work so the push fast-forwards, or create a new tag. The block binds everyone, admins included.")
        elif self.shape == UNPROVEN and self.blocks_force_move and self.old_oid and self.old_oid != ZERO_OID and self.new_oid and self.new_oid != ZERO_OID:
            out.append(
                f"This update moves tag '{self.tag}', its fast-forwardness could not be proven, and the tag protection blocks force moves; "
                f"a gate that blocks force moves never passes a move it cannot prove is a fast-forward — push again so the update can be judged.")
        return tuple(out)

    @property
    def satisfied(self) -> bool:
        return not self.blockers

    @property
    def reason(self) -> str:
        return self.blockers[0] if self.blockers else self.words

    @property
    def words(self) -> str:
        shape_words = _SHAPE_WORDS[self.shape]
        if self.release:
            rule_words = "the tag is a release tag (strongest default: deletion and force moves are blocked)"
        elif self.is_protected:
            parts = []
            parts.append("deletion is blocked" if self.blocks_deletion else "deletion is not blocked")
            parts.append("force moves are blocked" if self.blocks_force_move else "force moves are not blocked")
            rule_words = "the tag is protected; " + "; ".join(parts)
        else:
            rule_words = "no tag protection matches"
        verdict = "satisfied" if self.satisfied else "not satisfied"
        return f"Tag protection gate for a push to tag '{self.tag}' in {self.full_name}: {shape_words}; {rule_words}. The tag protection gate is {verdict}."


def decide_tag_update(evaluation, tag: str, old_oid: str, new_oid: str, *, ancestor: bool | None = None, full_name: str = "", release: bool | None = None) -> TagDecision:
    fn = full_name
    if evaluation is not None:
        fn = getattr(evaluation, "full_name", "") or fn
    rel = is_release_tag(tag) if release is None else bool(release)
    return TagDecision(
        full_name=fn, tag=str(tag), evaluation=evaluation,
        old_oid=str(old_oid or ""), new_oid=str(new_oid or ""),
        shape=update_shape(old_oid, new_oid, ancestor), release=rel)


def _ref_of(update):
    ref = getattr(update, "ref", None)
    if ref is not None:
        return ref
    if isinstance(update, dict):
        return update.get("ref")
    if isinstance(update, (tuple, list)) and update:
        return update[0]
    return None


def _oid_of(update, *names, index):
    for name in names:
        v = getattr(update, name, None)
        if v:
            return str(v)
    if isinstance(update, dict):
        for name in names:
            if update.get(name):
                return str(update[name])
    if isinstance(update, (tuple, list)) and len(update) > index:
        return str(update[index]) if update[index] else ""
    return ""


class TagProtectionStore:
    def __init__(self, conn: sqlite3.Connection, repositories: RepositoryStore, accounts: AccountStore, issues: IssueStore | None = None, audit: AuditLog | None = None, time_fn: Callable[[], float] = time.time, rulesets: RulesetStore | None = None):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._issues = issues
        self._audit = audit
        self._now = time_fn
        self._rulesets = rulesets or RulesetStore(conn, repositories, accounts, audit=audit, time_fn=time_fn)

    def _is_ancestor(self, repo_path, old_oid, new_oid):
        result = run_git_in(repo_path, ["merge-base", "--is-ancestor", old_oid, new_oid], timeout=15.0)
        if result.returncode == 0:
            return True
        if result.returncode == 1:
            return False
        return None

    def check_tag_update(self, viewer, owner, repo, tag, old_oid, new_oid) -> TagDecision:
        evaluation = self._rulesets.evaluate_ref(viewer, owner, repo, "tag", tag)
        old = str(old_oid or ""); new = str(new_oid or "")
        ancestor = None
        if old and old != ZERO_OID and new and new != ZERO_OID and old != new:
            base_repo = self._repos.get_repository(owner, repo)
            if base_repo is not None:
                repo_path = self._repos.path_for(base_repo.owner, base_repo.name)
                ancestor = self._is_ancestor(repo_path, old, new)
        return decide_tag_update(evaluation, str(tag), old, new, ancestor=ancestor)

    def enforce_tag_update(self, viewer, owner, repo, tag, old_oid, new_oid) -> TagDecision:
        d = self.check_tag_update(viewer, owner, repo, tag, old_oid, new_oid)
        if not d.satisfied:
            raise TagRefusedError(PROTECTED_TAG_REFUSED, d.reason)
        return d

    def check_push(self, viewer, owner, repo, updates) -> tuple:
        decisions = []
        for update in updates or ():
            tag = tag_from_ref(_ref_of(update))
            if tag is None:
                continue
            old_oid = _oid_of(update, "old_oid", "old", index=1)
            new_oid = _oid_of(update, "new_oid", "new", index=2)
            if not new_oid:
                continue
            decisions.append(self.check_tag_update(viewer, owner, repo, tag, old_oid, new_oid))
        return tuple(decisions)

    def enforce_push(self, viewer, owner, repo, updates) -> tuple:
        decisions = self.check_push(viewer, owner, repo, updates)
        for d in decisions:
            if not d.satisfied:
                raise TagRefusedError(PROTECTED_TAG_REFUSED, d.reason)
        return decisions

    def receive_gate_plugin(self):
        def plugin(context):
            actor = context.actor
            viewer = None
            if isinstance(actor, str) and actor:
                viewer = self._accounts.get_by_username(actor)
            decisions = self.check_push(viewer, context.owner, context.repo_name, context.updates)
            for d in decisions:
                if not d.satisfied:
                    raise GateVeto(d.reason)
            return None
        return plugin


def render_tag_decision(decision: TagDecision) -> str:
    blockers = ""
    if decision.blockers:
        items = "".join(f"<li>{escape_html_text(b)}</li>" for b in decision.blockers)
        blockers = f"<ul>{items}</ul>"
    return '<div class="protection-tag">' f"<p>{escape_html_text(decision.words)}</p>" f"{blockers}</div>"
