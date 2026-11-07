"""Rulesets (S-181) — Part VIII's generalisation of S-169.

S-169's protection rule attaches one policy shape to a
branch-name pattern in ONE repository. A ruleset is the
same policy shape aimed wider: one record that targets
many repositories, and branch AND tag name patterns in
each of them, and layers over the per-repository rules
with the same most-restrictive-wins algebra. GitHub's
users know this shape as a ruleset; Samverk's is stored,
evaluated, and said in words in the house way:

- **One ruleset targets many repos/branches/tags.**
  A ruleset (migration 67's `protection_rulesets`, one
  row per ruleset, its name unique across the instance
  case-insensitively, so re-creating a name is refused
  `protection_ruleset_taken` and a ruleset is changed
  through `update_ruleset`, never by shadowing) carries
  a target — `branch`, `tag`, or `all` (both kinds of
  ref) — a list of repository-name patterns matched
  against the repository's full name (`owner/repo`),
  a list of branch-name patterns, a list of tag-name
  patterns, and the whole Part VIII policy shape as an
  S-169 `ProtectionSettings`. Every pattern is judged
  by S-169's segment-aware glob discipline, reused not
  re-derived (`validate_pattern` / `matches_pattern`):
  `*` never crosses `/`, `**` does, patterns are
  anchored at both ends and validated whole. A branch
  target needs at least one branch pattern, a tag
  target at least one tag pattern, `all` at least one
  of each, and every target at least one repository
  pattern — a ruleset that names nothing is refused
  by name. A ruleset may be disabled (its settings'
  `enabled` off): a disabled ruleset is kept, listed,
  said as disabled, and never matches or protects
  anything, exactly as a disabled S-169 rule.
- **Ruleset order is documented and deterministic.**
  Matching rulesets are judged in exactly this order:
  (1) the lexicographically smaller name first
  (case-insensitive, as names are unique that way);
  (2) the lower ruleset id first. Ids are unique, so
  the order is total: two evaluations of the same
  ruleset set over the same target always walk the
  same list in the same order. `order_rulesets` is
  the pure half; the battery pins it against shuffled
  inputs.
- **Layered rules resolve most-restrictive-wins — by
  S-169's own fold.** A ref's position is resolved
  once: the per-repository layer is S-169's
  `evaluate_rules` over that repository's rules (for
  a branch ref; S-169 rules attach to branch patterns
  only, so a tag ref has no per-repository layer),
  the ruleset layer is every matching ruleset in
  ruleset order, and the combined effective policy is
  S-169's `fold_settings` over the matching shapes in
  layer order — per-repository rules first, in their
  documented evaluation order, then rulesets in
  theirs. The fold is the same function, not a second
  algebra: every boolean requirement holds when ANY
  layer requires it, the required approval count is
  the maximum, required status checks are the union,
  and the actor lists combine by intersection (a
  pusher must be allowed by every restricting layer;
  a bypasser bypasses only when every matching layer
  names them, and a layer naming nobody closes the
  door). One layer can only ever tighten another —
  never loosen it.
- **Writes are site-admin acts.** Rulesets are
  instance policy — they reach across repositories no
  single repository admin owns — so creating,
  changing, deleting, and the management reads (get /
  list) require a site admin (`User.is_admin`, the
  standing S-045 notion; no second notion is
  invented). Anyone else is refused
  `permission_denied` in words. Refusals write
  nothing and emit no event, and writes commit before
  answering, as everywhere in the house. Rule changes
  audit under the frozen `repo.protection.change`
  (no new taxonomy event — 120 stand: 29 auth,
  79 repo, 12 admin), with detail naming the ruleset,
  the verb, and the target.
- **Evaluation reads follow S-054.** The store's one
  evaluation, `evaluate_ref`, resolves the repository
  through S-169's read guard: a stranger to a private
  repository gets the uniform `repo_not_found` before
  any ruleset position is named. Everything is said
  in words, never a colour alone: a ruleset carries
  its position as `words`, a layered evaluation says
  which layers matched and what the effective policy
  requires, and the renderers print exactly those
  words, escaped through S-010. No route is invented:
  surfaces consume the store when their slices land,
  exactly as S-164's seam landed route-free. S-183's
  rule insights can quote these sentences when they
  answer "why was this refused?".
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .permissions import can_read
from .protection_rules import (
    ProtectionEvaluation, ProtectionRuleStore, ProtectionSettings,
    evaluate_rules, fold_settings, matches_pattern, validate_pattern)
from .repositories import Repository, RepositoryError, RepositoryStore

__all__ = [
    "NAME_MAX", "PATTERNS_MAX", "REF_KINDS", "TARGETS",
    "LayeredEvaluation", "Ruleset", "RulesetError", "RulesetEvaluation",
    "RulesetStore", "evaluate_layered", "evaluate_rulesets",
    "order_rulesets", "render_layered_evaluation", "render_ruleset",
    "render_ruleset_evaluation", "validate_ruleset_name",
    "validate_target",
]

NAME_MAX = 100
PATTERNS_MAX = 50
TARGETS = ("branch", "tag", "all")
REF_KINDS = ("branch", "tag")

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]*$")


class RulesetError(RepositoryError):
    """A ruleset refusal: a RepositoryError carrying
    `.reason`, mirroring ProtectionRuleError."""


# -- names, targets, patterns: the pure half -----------------------------

def validate_ruleset_name(name: object) -> str:
    """One ruleset name, validated whole. Refusals are
    `protection_ruleset_invalid` and name what is wrong
    in words."""
    if not isinstance(name, str):
        raise RulesetError(
            "protection_ruleset_invalid",
            "A ruleset name must be text.")
    text = name.strip()
    if not text or len(text) > NAME_MAX or not _NAME_RE.match(text):
        raise RulesetError(
            "protection_ruleset_invalid",
            f"That ruleset name is not valid: {name!r} "
            f"(1 to {NAME_MAX} characters: letters, digits, "
            "spaces, '.', '_' or '-', starting with a "
            "letter or digit).")
    return text


def validate_target(target: object) -> str:
    """One ruleset target: 'branch', 'tag', or 'all'."""
    if target not in TARGETS:
        raise RulesetError(
            "protection_ruleset_invalid",
            "A ruleset target is 'branch', 'tag', or "
            "'all' (branches and tags).")
    return str(target)


def _validate_ref_kind(ref_kind: object) -> str:
    if ref_kind not in REF_KINDS:
        raise RulesetError(
            "protection_ruleset_invalid",
            "A ref kind is 'branch' or 'tag'.")
    return str(ref_kind)


def _validate_patterns(label: str, patterns: object) -> tuple:
    if patterns is None:
        return ()
    if isinstance(patterns, str) or not isinstance(
            patterns, (list, tuple)):
        raise RulesetError(
            "protection_ruleset_invalid",
            f"{label} patterns are a list of patterns.")
    out: list[str] = []
    for raw in patterns:
        try:
            text = validate_pattern(raw)
        except RepositoryError:
            raise RulesetError(
                "protection_ruleset_invalid",
                f"That {label} pattern is not valid: "
                f"{raw!r} (branch-name characters plus "
                "* ? [...] wildcards; no '..', no '//', "
                "no leading or trailing '/').") from None
        if text not in out:
            out.append(text)
    if len(out) > PATTERNS_MAX:
        raise RulesetError(
            "protection_ruleset_invalid",
            f"At most {PATTERNS_MAX} {label} patterns "
            "in one ruleset.")
    return tuple(out)


def _require_target_patterns(target: str, branch_patterns: tuple,
                             tag_patterns: tuple) -> None:
    if target in ("branch", "all") and not branch_patterns:
        raise RulesetError(
            "protection_ruleset_invalid",
            "A ruleset that targets branches names at "
            "least one branch pattern.")
    if target in ("tag", "all") and not tag_patterns:
        raise RulesetError(
            "protection_ruleset_invalid",
            "A ruleset that targets tags names at "
            "least one tag pattern.")


# -- the record ------------------------------------------------------------

@dataclass(frozen=True)
class Ruleset:
    """One ruleset: a name, a target, the repository /
    branch / tag patterns it aims at, and the Part VIII
    policy shape (an S-169 `ProtectionSettings`) it
    carries into every repository it matches."""
    id: int
    name: str
    target: str
    repo_patterns: tuple
    branch_patterns: tuple
    tag_patterns: tuple
    settings: ProtectionSettings
    created_by: int | None
    created_at: int
    updated_at: int

    @property
    def enabled(self) -> bool:
        return self.settings.enabled

    def matched_ref_pattern(self, full_name: str,
                            ref_kind: str,
                            ref_name: str) -> str | None:
        """The ref pattern this ruleset matches this ref
        through, or None when it does not attach: the
        ruleset is enabled, its target covers the ref
        kind, some repository pattern matches the full
        name, and some pattern for the ref kind matches
        the ref name — all under S-169's glob."""
        if not self.settings.enabled:
            return None
        if self.target == "branch" and ref_kind != "branch":
            return None
        if self.target == "tag" and ref_kind != "tag":
            return None
        if not any(matches_pattern(p, full_name)
                   for p in self.repo_patterns):
            return None
        patterns = (self.branch_patterns if ref_kind == "branch"
                    else self.tag_patterns)
        for pattern in patterns:
            if matches_pattern(pattern, ref_name):
                return pattern
        return None

    def matches(self, full_name: str, ref_kind: str,
                ref_name: str) -> bool:
        return self.matched_ref_pattern(
            full_name, ref_kind, ref_name) is not None

    @property
    def words(self) -> str:
        state = "enabled" if self.settings.enabled else "disabled"
        target_words = {
            "branch": "branches",
            "tag": "tags",
            "all": "branches and tags"}[self.target]
        repos = ", ".join(f"'{p}'" for p in self.repo_patterns)
        parts = [
            f"Ruleset '{self.name}' ({state}) targets "
            f"{target_words} in repositories matching: {repos}."]
        if self.target in ("branch", "all"):
            parts.append(
                "Branch patterns: "
                + ", ".join(f"'{p}'" for p in self.branch_patterns)
                + ".")
        if self.target in ("tag", "all"):
            parts.append(
                "Tag patterns: "
                + ", ".join(f"'{p}'" for p in self.tag_patterns)
                + ".")
        reqs = self.settings.requirement_words()
        if reqs:
            parts.append("It requires: " + "; ".join(reqs) + ".")
        else:
            parts.append(
                "It carries no requirements beyond being "
                "protected.")
        return " ".join(parts)


def ruleset_order_key(ruleset: Ruleset) -> tuple:
    """One ruleset's evaluation-order key: the name
    (case-insensitive), then the id — unique, so the
    order over any ruleset set is total."""
    return (ruleset.name.lower(), ruleset.id)


def order_rulesets(rulesets) -> tuple:
    """The rulesets in evaluation order (see the module
    docstring): smaller name first, lower id first.
    Pure: the same set in any input order yields the
    same output order."""
    return tuple(sorted(rulesets, key=ruleset_order_key))


# -- evaluation: the pure half ---------------------------------------------

@dataclass(frozen=True)
class RulesetEvaluation:
    """One ref's ruleset layer, resolved once: the
    matching rulesets in ruleset order and the
    effective policy they fold into (S-169's fold)."""
    full_name: str
    ref_kind: str
    ref_name: str
    matching: tuple            # of Ruleset, ruleset order
    effective: ProtectionSettings | None

    @property
    def is_protected(self) -> bool:
        return self.effective is not None

    @property
    def words(self) -> str:
        ref = f"{self.ref_kind} '{self.ref_name}'"
        if self.effective is None:
            return (f"No ruleset matches {ref} in "
                    f"{self.full_name}: the ruleset layer "
                    "protects nothing here.")
        names = ", ".join(f"'{r.name}'" for r in self.matching)
        noun = "ruleset matches" if len(self.matching) == 1 \
            else "rulesets match"
        reqs = self.effective.requirement_words()
        body = "; ".join(reqs) if reqs else "being protected"
        return (f"{len(self.matching)} {noun} {ref} in "
                f"{self.full_name}, in ruleset order: "
                f"{names}. The ruleset layer requires: "
                f"{body}.")


@dataclass(frozen=True)
class LayeredEvaluation:
    """One ref's whole protection position, resolved
    once: the per-repository layer (S-169's evaluation;
    None for a tag ref, whose repository layer does not
    exist), the ruleset layer, and the combined
    most-restrictive effective policy the two fold
    into — the answer enforcement consults."""
    full_name: str
    ref_kind: str
    ref_name: str
    repo_evaluation: ProtectionEvaluation | None
    ruleset_evaluation: RulesetEvaluation
    matching_rules: tuple      # of ProtectionRule
    matching_rulesets: tuple   # of Ruleset
    effective: ProtectionSettings | None

    @property
    def is_protected(self) -> bool:
        return self.effective is not None

    @property
    def words(self) -> str:
        ref = f"{self.ref_kind} '{self.ref_name}'"
        if self.effective is None:
            return (f"No protection rule or ruleset "
                    f"matches {ref} in {self.full_name}: "
                    "the ref is not protected.")
        layers = []
        if self.matching_rules:
            patterns = ", ".join(
                f"'{r.pattern}'" for r in self.matching_rules)
            layers.append(
                f"{len(self.matching_rules)} repository "
                f"rule(s) ({patterns})")
        if self.matching_rulesets:
            names = ", ".join(
                f"'{r.name}'" for r in self.matching_rulesets)
            layers.append(
                f"{len(self.matching_rulesets)} ruleset(s) "
                f"({names})")
        reqs = self.effective.requirement_words()
        body = "; ".join(reqs) if reqs else "being protected"
        return (f"{ref} in {self.full_name} is protected "
                "by " + " and ".join(layers)
                + ", layered most-restrictive-wins. The "
                "effective policy requires: " + body + ".")


def evaluate_rulesets(rulesets, full_name: str, ref_kind: str,
                      ref_name: str) -> RulesetEvaluation:
    """The pure half of the ruleset layer: from any
    iterable of rulesets, the ones that attach to this
    ref in this repository, in the documented ruleset
    order, folded most-restrictive-wins by S-169's
    `fold_settings`. No database is touched here."""
    kind = _validate_ref_kind(ref_kind)
    matching = order_rulesets(
        [r for r in rulesets if r.matches(full_name, kind, ref_name)])
    if not matching:
        return RulesetEvaluation(
            full_name=full_name, ref_kind=kind,
            ref_name=ref_name, matching=(), effective=None)
    return RulesetEvaluation(
        full_name=full_name, ref_kind=kind, ref_name=ref_name,
        matching=matching,
        effective=fold_settings([r.settings for r in matching]))


def evaluate_layered(repo_rules, rulesets, full_name: str,
                     ref_kind: str,
                     ref_name: str) -> LayeredEvaluation:
    """The pure half of the whole layered position:
    S-169's `evaluate_rules` over `repo_rules` (the
    per-repository layer — branch refs only; a tag ref
    has no repository layer, because S-169 rules attach
    to branch patterns) and `evaluate_rulesets` over
    `rulesets`, folded together most-restrictive-wins
    by S-169's `fold_settings`, per-repository shapes
    first in their evaluation order, then ruleset
    shapes in theirs. No database is touched here, so
    the layering matrix is provable in isolation; the
    store below only has to gather the two layers
    honestly."""
    kind = _validate_ref_kind(ref_kind)
    repo_evaluation = None
    matching_rules: tuple = ()
    if kind == "branch":
        repo_evaluation = evaluate_rules(
            repo_rules, ref_name, full_name=full_name)
        matching_rules = repo_evaluation.matching
    ruleset_evaluation = evaluate_rulesets(
        rulesets, full_name, kind, ref_name)
    shapes = [r.settings for r in matching_rules] + [
        r.settings for r in ruleset_evaluation.matching]
    return LayeredEvaluation(
        full_name=full_name, ref_kind=kind, ref_name=ref_name,
        repo_evaluation=repo_evaluation,
        ruleset_evaluation=ruleset_evaluation,
        matching_rules=matching_rules,
        matching_rulesets=ruleset_evaluation.matching,
        effective=fold_settings(shapes) if shapes else None)


# -- the store ---------------------------------------------------------------

_SETTINGS_COLUMNS = (
    "enabled", "require_pull_request", "required_approvals",
    "require_last_pusher_approval",
    "dismiss_stale_reviews", "require_code_owner_review",
    "required_status_checks", "require_branch_up_to_date",
    "require_signed_commits", "require_linear_history",
    "block_force_pushes", "block_branch_deletion", "enforce_admins",
    "allowed_push_actors", "bypass_actors")


def _settings_from_row(row: sqlite3.Row) -> ProtectionSettings:
    def _json_list(value) -> tuple:
        try:
            parsed = json.loads(value) if value else []
        except (ValueError, TypeError):
            parsed = []
        return tuple(parsed) if isinstance(parsed, list) else ()
    return ProtectionSettings(
        enabled=bool(row["enabled"]),
        require_pull_request=bool(row["require_pull_request"]),
        required_approvals=int(row["required_approvals"]),
        require_last_pusher_approval=bool(
            row["require_last_pusher_approval"]),
        dismiss_stale_reviews=bool(row["dismiss_stale_reviews"]),
        require_code_owner_review=bool(row["require_code_owner_review"]),
        required_status_checks=_json_list(row["required_status_checks"]),
        require_branch_up_to_date=bool(row["require_branch_up_to_date"]),
        require_signed_commits=bool(row["require_signed_commits"]),
        require_linear_history=bool(row["require_linear_history"]),
        block_force_pushes=bool(row["block_force_pushes"]),
        block_branch_deletion=bool(row["block_branch_deletion"]),
        enforce_admins=bool(row["enforce_admins"]),
        allowed_push_actors=_json_list(row["allowed_push_actors"]),
        bypass_actors=_json_list(row["bypass_actors"]))


def _settings_values(settings: ProtectionSettings) -> tuple:
    return (
        1 if settings.enabled else 0,
        1 if settings.require_pull_request else 0,
        settings.required_approvals,
        1 if settings.require_last_pusher_approval else 0,
        1 if settings.dismiss_stale_reviews else 0,
        1 if settings.require_code_owner_review else 0,
        json.dumps(list(settings.required_status_checks)),
        1 if settings.require_branch_up_to_date else 0,
        1 if settings.require_signed_commits else 0,
        1 if settings.require_linear_history else 0,
        1 if settings.block_force_pushes else 0,
        1 if settings.block_branch_deletion else 0,
        1 if settings.enforce_admins else 0,
        json.dumps(list(settings.allowed_push_actors)),
        json.dumps(list(settings.bypass_actors)))


def _json_patterns(value) -> tuple:
    try:
        parsed = json.loads(value) if value else []
    except (ValueError, TypeError):
        parsed = []
    return tuple(parsed) if isinstance(parsed, list) else ()


def _row_to_ruleset(row: sqlite3.Row) -> Ruleset:
    return Ruleset(
        id=row["id"], name=row["name"], target=row["target"],
        repo_patterns=_json_patterns(row["repo_patterns"]),
        branch_patterns=_json_patterns(row["branch_patterns"]),
        tag_patterns=_json_patterns(row["tag_patterns"]),
        settings=_settings_from_row(row),
        created_by=row["created_by"], created_at=row["created_at"],
        updated_at=row["updated_at"])


class RulesetStore:
    """The store half of rulesets: the instance's
    rulesets, managed by site admins, and the one
    layered evaluation Part VIII consults for a ref.
    Enforcement holds this store and reads
    `evaluate_ref`; it never re-derives targeting,
    ordering, or the fold itself."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
        protection_rules: ProtectionRuleStore | None = None,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._audit = audit
        self._now = time_fn
        self._rules = protection_rules or ProtectionRuleStore(
            conn, repositories, accounts,
            audit=audit, time_fn=time_fn)

    # -- guards ------------------------------------------------------
    @staticmethod
    def _require_site_admin(actor: User | None) -> User:
        if actor is None or not actor.is_admin:
            raise RulesetError(
                "permission_denied",
                "Only a site admin can manage rulesets: "
                "a ruleset reaches across repositories, "
                "so it is instance policy.")
        return actor

    def _repo_for_read(self, viewer: User | None, owner: object,
                       repo: object) -> Repository:
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise RulesetError(
                "repo_not_found", "No such repository.")
        return current

    # -- row access ----------------------------------------------------
    def _by_id(self, ruleset_id: object) -> Ruleset | None:
        if isinstance(ruleset_id, bool) \
                or not isinstance(ruleset_id, int):
            return None
        row = self._conn.execute(
            "SELECT * FROM protection_rulesets WHERE id = ?",
            (ruleset_id,)).fetchone()
        return _row_to_ruleset(row) if row is not None else None

    def _by_name(self, name: str) -> Ruleset | None:
        row = self._conn.execute(
            "SELECT * FROM protection_rulesets"
            " WHERE name_lower = ?",
            (name.lower(),)).fetchone()
        return _row_to_ruleset(row) if row is not None else None

    def _all(self) -> list[Ruleset]:
        rows = self._conn.execute(
            "SELECT * FROM protection_rulesets ORDER BY id"
        ).fetchall()
        return [_row_to_ruleset(r) for r in rows]

    # -- CRUD ------------------------------------------------------------
    def create_ruleset(self, actor: User | None, name: object, *,
                       target: object = "branch",
                       repo_patterns: object = (),
                       branch_patterns: object = (),
                       tag_patterns: object = (),
                       settings: ProtectionSettings | None = None,
                       source_ip: str | None = None,
                       **fields) -> Ruleset:
        """Create one ruleset. The policy shape arrives
        either as a `ProtectionSettings` or as field
        keywords (never both). One ruleset per name
        across the instance: a second create for the
        same name (in any letter case) is refused
        `protection_ruleset_taken`."""
        admin = self._require_site_admin(actor)
        text = validate_ruleset_name(name)
        kind = validate_target(target)
        repos = _validate_patterns("repository", repo_patterns)
        if not repos:
            raise RulesetError(
                "protection_ruleset_invalid",
                "A ruleset names at least one repository "
                "pattern: it must say which repositories "
                "it targets.")
        branches = _validate_patterns("branch", branch_patterns)
        tags = _validate_patterns("tag", tag_patterns)
        _require_target_patterns(kind, branches, tags)
        shape = self._shape(settings, fields)
        now = int(self._now())
        columns = ", ".join(_SETTINGS_COLUMNS)
        marks = ", ".join("?" for _ in _SETTINGS_COLUMNS)
        with self._conn:  # commits before the answer
            try:
                cur = self._conn.execute(
                    f"INSERT INTO protection_rulesets (name,"
                    f" name_lower, target, repo_patterns,"
                    f" branch_patterns, tag_patterns, {columns},"
                    f" created_by, created_at, updated_at)"
                    f" VALUES (?, ?, ?, ?, ?, ?, {marks},"
                    f" ?, ?, ?)",
                    (text, text.lower(), kind,
                     json.dumps(list(repos)),
                     json.dumps(list(branches)),
                     json.dumps(list(tags)),
                     *_settings_values(shape),
                     admin.id, now, now))
            except sqlite3.IntegrityError:
                raise RulesetError(
                    "protection_ruleset_taken",
                    f"A ruleset named {text!r} already "
                    "exists; update that ruleset instead."
                    ) from None
        ruleset = self._by_id(int(cur.lastrowid))
        assert ruleset is not None
        self._emit(admin, ruleset, "create", source_ip)
        return ruleset

    def get_ruleset(self, actor: User | None,
                    ruleset_id: object) -> Ruleset:
        self._require_site_admin(actor)
        ruleset = self._by_id(ruleset_id)
        if ruleset is None:
            raise RulesetError(
                "protection_ruleset_not_found",
                "No such ruleset.")
        return ruleset

    def get_ruleset_by_name(self, actor: User | None,
                            name: object) -> Ruleset:
        self._require_site_admin(actor)
        text = validate_ruleset_name(name)
        ruleset = self._by_name(text)
        if ruleset is None:
            raise RulesetError(
                "protection_ruleset_not_found",
                "No such ruleset.")
        return ruleset

    def list_rulesets(self, actor: User | None) -> list[Ruleset]:
        """Every ruleset on the instance, creation order
        (id ascending) — the management listing. The
        judgment order is `order_rulesets` /
        `evaluate_ref`, never this listing."""
        self._require_site_admin(actor)
        return self._all()

    def update_ruleset(self, actor: User | None,
                       ruleset_id: object, *,
                       name: object = None,
                       target: object = None,
                       repo_patterns: object = None,
                       branch_patterns: object = None,
                       tag_patterns: object = None,
                       settings: ProtectionSettings | None = None,
                       source_ip: str | None = None,
                       **fields) -> Ruleset:
        """Change one ruleset: its name, target, pattern
        lists, its whole shape (a `ProtectionSettings`),
        or individual shape fields (a field left out
        keeps its stored value). A same-value update is
        a quiet no-op: it stores nothing and audits
        nothing."""
        admin = self._require_site_admin(actor)
        ruleset = self._by_id(ruleset_id)
        if ruleset is None:
            raise RulesetError(
                "protection_ruleset_not_found",
                "No such ruleset.")
        text = ruleset.name if name is None \
            else validate_ruleset_name(name)
        kind = ruleset.target if target is None \
            else validate_target(target)
        repos = ruleset.repo_patterns if repo_patterns is None \
            else _validate_patterns("repository", repo_patterns)
        if not repos:
            raise RulesetError(
                "protection_ruleset_invalid",
                "A ruleset names at least one repository "
                "pattern: it must say which repositories "
                "it targets.")
        branches = ruleset.branch_patterns \
            if branch_patterns is None else _validate_patterns(
                "branch", branch_patterns)
        tags = ruleset.tag_patterns if tag_patterns is None \
            else _validate_patterns("tag", tag_patterns)
        _require_target_patterns(kind, branches, tags)
        if settings is not None and fields:
            raise RulesetError(
                "protection_ruleset_invalid",
                "Give a ruleset's shape whole, or field "
                "by field — not both.")
        if settings is not None:
            if not isinstance(settings, ProtectionSettings):
                raise RulesetError(
                    "protection_ruleset_invalid",
                    "A ruleset's shape is a "
                    "ProtectionSettings.")
            shape = settings
        elif fields:
            merged = {
                f: getattr(ruleset.settings, f)
                for f in _SETTINGS_COLUMNS}
            unknown = set(fields) - set(merged)
            if unknown:
                raise RulesetError(
                    "protection_ruleset_invalid",
                    f"Unknown ruleset field(s): "
                    f"{', '.join(sorted(unknown))}.")
            merged.update(fields)
            shape = ProtectionSettings(**merged)
        else:
            shape = ruleset.settings
        if (text == ruleset.name and kind == ruleset.target
                and repos == ruleset.repo_patterns
                and branches == ruleset.branch_patterns
                and tags == ruleset.tag_patterns
                and shape == ruleset.settings):
            return ruleset  # a same-value retry is a quiet no-op
        now = int(self._now())
        columns = ", ".join(
            f"{c} = ?" for c in _SETTINGS_COLUMNS)
        with self._conn:  # commits before the answer
            try:
                self._conn.execute(
                    f"UPDATE protection_rulesets SET name = ?,"
                    f" name_lower = ?, target = ?,"
                    f" repo_patterns = ?, branch_patterns = ?,"
                    f" tag_patterns = ?, {columns},"
                    f" updated_at = ? WHERE id = ?",
                    (text, text.lower(), kind,
                     json.dumps(list(repos)),
                     json.dumps(list(branches)),
                     json.dumps(list(tags)),
                     *_settings_values(shape), now, ruleset.id))
            except sqlite3.IntegrityError:
                raise RulesetError(
                    "protection_ruleset_taken",
                    f"A ruleset named {text!r} already "
                    "exists; update that ruleset instead."
                    ) from None
        updated = self._by_id(ruleset.id)
        assert updated is not None
        self._emit(admin, updated, "update", source_ip)
        return updated

    def delete_ruleset(self, actor: User | None,
                       ruleset_id: object, *,
                       source_ip: str | None = None) -> Ruleset:
        admin = self._require_site_admin(actor)
        ruleset = self._by_id(ruleset_id)
        if ruleset is None:
            raise RulesetError(
                "protection_ruleset_not_found",
                "No such ruleset.")
        with self._conn:  # commits before the answer
            self._conn.execute(
                "DELETE FROM protection_rulesets WHERE id = ?",
                (ruleset.id,))
        self._emit(admin, ruleset, "delete", source_ip)
        return ruleset

    # -- evaluation ------------------------------------------------------
    def evaluate_ref(self, viewer: User | None, owner: object,
                     repo: object, ref_kind: object,
                     ref_name: object) -> LayeredEvaluation:
        """THE one layered evaluation: this ref's whole
        protection position in this repository, resolved
        once — the per-repository rules and every
        matching ruleset, layered most-restrictive-wins.
        The repository is resolved through S-054's read
        guard, so a stranger to a private repository
        gets the uniform `repo_not_found` before any
        position is named."""
        current = self._repo_for_read(viewer, owner, repo)
        kind = _validate_ref_kind(ref_kind)
        name = self._ref_name(kind, ref_name)
        repo_rules: tuple = ()
        if kind == "branch":
            repo_rules = tuple(
                self._rules.list_rules(viewer, owner, repo))
        return evaluate_layered(
            repo_rules, self._all(), current.full_name,
            kind, name)

    def is_protected(self, viewer: User | None, owner: object,
                     repo: object, ref_kind: object,
                     ref_name: object) -> bool:
        """Whether any repository rule or ruleset
        attaches to this ref."""
        return self.evaluate_ref(
            viewer, owner, repo, ref_kind, ref_name).is_protected

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _ref_name(kind: str, ref_name: object) -> str:
        from .repositories import validate_branch_name
        return validate_branch_name(ref_name)

    @staticmethod
    def _shape(settings, fields) -> ProtectionSettings:
        if settings is not None and fields:
            raise RulesetError(
                "protection_ruleset_invalid",
                "Give a ruleset's shape whole, or field "
                "by field — not both.")
        if settings is not None:
            if not isinstance(settings, ProtectionSettings):
                raise RulesetError(
                    "protection_ruleset_invalid",
                    "A ruleset's shape is a "
                    "ProtectionSettings.")
            return settings
        try:
            return ProtectionSettings(**fields)
        except TypeError:
            unknown = set(fields) - set(_SETTINGS_COLUMNS)
            raise RulesetError(
                "protection_ruleset_invalid",
                f"Unknown ruleset field(s): "
                f"{', '.join(sorted(unknown))}.") from None

    def _emit(self, actor, ruleset, verb, source_ip) -> None:
        if self._audit is None or actor is None:
            return
        self._audit.append(
            actor_kind="user", actor_id=actor.id,
            action="repo.protection.change",
            target_kind="ruleset",
            target_id=ruleset.name, outcome="success",
            source_ip=source_ip,
            detail={"ruleset": verb, "ruleset_id": ruleset.id,
                    "name": ruleset.name,
                    "target": ruleset.target})


def render_ruleset(ruleset: Ruleset) -> str:
    """One ruleset in words — exactly the ruleset's own
    `words`, escaped through S-010, never a colour
    alone."""
    return (
        '<div class="protection-ruleset">'
        f"<p>{escape_html_text(ruleset.words)}</p></div>")


def render_ruleset_evaluation(
        evaluation: RulesetEvaluation) -> str:
    """One ref's ruleset layer in words — exactly the
    evaluation's own `words`, escaped through S-010."""
    return (
        '<div class="protection-ruleset-evaluation">'
        f"<p>{escape_html_text(evaluation.words)}</p></div>")


def render_layered_evaluation(
        evaluation: LayeredEvaluation) -> str:
    """One ref's whole layered position in words —
    exactly the evaluation's own `words`, escaped
    through S-010. The sentences S-183's rule insights
    will quote when they answer "why was this
    refused?"."""
    return (
        '<div class="protection-layered-evaluation">'
        f"<p>{escape_html_text(evaluation.words)}</p></div>")
