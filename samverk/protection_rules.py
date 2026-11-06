"""Protection rule model (S-169) — Part VIII's foundation.

Part VIII's enforcement slices (S-170..S-180) each refuse
something on a protected branch; this slice builds the
thing they all consult: the rule record, which branches
it attaches to, and the order matching rules are judged
in. Before this slice, the only protection-adjacent
facts in the tree were seams waiting for a model to
exist — S-159's `_branch_is_protected` ("no-rules today
because branch protection does not exist yet") and the
receive gate's `protection` stage (S-089, "the rules
themselves land in their own parts"). Now there is one
place:

- **A rule attaches to a branch-name pattern in one
  repository** (migration 65's `protection_rules`, one
  row per (repository, pattern) pair — a pattern names
  at most one rule per repository, so re-creating a
  pattern is refused `protection_rule_taken` and a rule
  is changed through `update_rule`, never by shadowing).
  A rule carries the whole Part VIII policy shape as
  stored fields — require a pull request (S-170), the
  required approval count (S-171), dismiss stale reviews
  (S-172), require code-owner review (S-173), required
  status checks and the up-to-date toggle (S-174),
  require signed commits (S-175), require linear history
  (S-176), block force pushes and block branch deletion
  (S-177; both default ON, as on the public forges: a
  protected branch is never force-moved or deleted by
  default), restrict who can push and the bypass list
  (S-178/S-179, stored as actor-name lists; empty means
  no restriction / nobody bypasses), and enforce for
  admins (S-180; default ON — sovereignty means the
  owner's rules bind the owner). This slice stores and
  evaluates that shape; the enforcement slices wire
  each field to its refusal point and own no policy
  storage of their own. A rule may be disabled: a
  disabled rule is kept, listed, and said as disabled,
  and never matches or protects anything.
- **Pattern matching is segment-aware glob, anchored at
  both ends.** `*` matches any run of characters except
  `/`; `**` matches any run including `/`; `?` matches
  exactly one character except `/`; `[...]` is a
  character class (the S-151 CODEOWNERS glob discipline,
  applied to branch names). A pattern with no wildcards
  matches exactly one branch name. Patterns are
  validated whole (`protection_pattern_invalid`): plain
  branch-name characters plus the wildcards, at most
  200 characters, no `..`, no `//`, no `@{`, no leading
  or trailing `/`, a closed character class, and at
  least one literal character — a pattern that is only
  wildcards would attach to everything and names
  nothing, so it is refused by name.
- **Evaluation order is documented and deterministic**
  (the roadmap's own words for this slice). Matching
  enabled rules are judged in exactly this order:
  (1) a wildcard-free pattern (an exact branch name)
  before any wildcard pattern; (2) more literal
  (non-wildcard) characters first — the more specific
  pattern speaks first; (3) fewer wildcards first;
  (4) the lexicographically smaller pattern first;
  (5) the lower rule id first. Rule ids are unique, so
  the order is total: two evaluations of the same rule
  set over the same branch always walk the same list
  in the same order, whatever order the rows were
  created or read in. `order_rules` is the pure half;
  the battery pins it against shuffled inputs.
- **The effective rule is most-restrictive-wins.**
  `evaluate_rules` folds the matching rules, in
  evaluation order, into one effective policy: every
  boolean requirement is met when ANY matching rule
  requires it (so `enforce_admins` binds when any
  matching rule says it binds); the required approval
  count is the maximum; required status checks are the
  union, in evaluation order; and the actor lists
  combine by intersection — a pusher must be allowed
  by every matching rule that restricts pushing, and a
  bypasser bypasses only when every matching rule
  names them (one rule's door is not another rule's
  door). S-181's layered rulesets resolve the same way
  when they land; this slice fixes the algebra now so
  they cannot invent a second one.
- **Reads and writes follow the house.** Reading rules
  follows S-054 (`can_read`); a stranger to a private
  repository gets the uniform `repo_not_found` before
  any rule is named. Writing rules is an admin act
  (`can_admin`: the owner, or a site admin); anyone
  else is refused `permission_denied` and nothing is
  written. Writes commit before they answer, and a
  real change audits under the frozen
  `repo.protection.change` (taxonomy unchanged, 119
  events) with detail `{"branch": <pattern>, "rule":
  "create"|"update"|"delete", "rule_id": ...}` — the
  taxonomy doc's named detail shape. A same-value
  update is a quiet no-op (the S-149 settings pattern):
  it stores nothing and audits nothing. Refusals write
  nothing and emit no event.
- **Said in words, never a colour alone.** A rule says
  its own position as `words` (pattern, enabled or
  disabled, and each requirement it carries), an
  evaluation says which rules matched in which order
  and what the effective policy requires, and the two
  renderers print exactly those words, escaped through
  S-010. No route is invented: surfaces consume the
  store when their slices land, exactly as S-164's
  seam landed route-free.
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
from .permissions import can_admin, can_read
from .repositories import Repository, RepositoryError, RepositoryStore

__all__ = [
    "PATTERN_MAX", "EffectiveProtection", "ProtectionEvaluation",
    "ProtectionRule", "ProtectionRuleError", "ProtectionRuleStore",
    "ProtectionSettings", "evaluate_rules", "matches_pattern",
    "order_rules", "pattern_specificity", "render_protection_evaluation",
    "render_protection_rule", "validate_pattern",
]

PATTERN_MAX = 200
CHECK_MAX_COUNT = 100
CHECK_MAX_LEN = 200
ACTOR_MAX_COUNT = 100

_PATTERN_CHARS_RE = re.compile(r"^[A-Za-z0-9._/*?!\[\]-]+$")
_ACTOR_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)?$")


class ProtectionRuleError(RepositoryError):
    """A protection-rule refusal: a RepositoryError
    carrying `.reason`, mirroring BranchHousekeepingError
    and SettingsError."""


# -- patterns: the pure half -------------------------------------------

def validate_pattern(pattern: object) -> str:
    """One branch-name pattern, validated whole.
    Refusals are `protection_pattern_invalid` and name
    what is wrong in words."""
    if not isinstance(pattern, str):
        raise ProtectionRuleError(
            "protection_pattern_invalid",
            "A branch pattern must be text.")
    text = pattern.strip()
    if not text or len(text) > PATTERN_MAX:
        raise ProtectionRuleError(
            "protection_pattern_invalid",
            f"A branch pattern is 1 to {PATTERN_MAX} characters.")
    if not _PATTERN_CHARS_RE.match(text) or ".." in text \
            or "//" in text or "@{" in text \
            or text.startswith("/") or text.endswith("/") \
            or text.endswith(".") or text.endswith(".lock"):
        raise ProtectionRuleError(
            "protection_pattern_invalid",
            f"That branch pattern is not valid: {pattern!r} "
            "(branch-name characters plus * ? [...] wildcards; "
            "no '..', no '//', no leading or trailing '/').")
    if "[" in text or "]" in text:
        i = 0
        while i < len(text):
            if text[i] == "[":
                end = text.find("]", i + 1)
                if end < 0 or end == i + 1:
                    raise ProtectionRuleError(
                        "protection_pattern_invalid",
                        f"That branch pattern is not valid: "
                        f"{pattern!r} (a character class [...] "
                        "must be closed and non-empty).")
                i = end + 1
            elif text[i] == "]":
                raise ProtectionRuleError(
                    "protection_pattern_invalid",
                    f"That branch pattern is not valid: "
                    f"{pattern!r} (a ']' with no '[' before it).")
            else:
                i += 1
    if not any(c.isalnum() for c in text):
        raise ProtectionRuleError(
            "protection_pattern_invalid",
            "A branch pattern must name something: at least "
            "one letter or digit among its wildcards.")
    return text


def _glob_regex(pattern: str) -> str:
    """One anchored glob pattern -> a regex string (the
    S-151 discipline): `**/` is zero or more directories,
    `**` any run including `/`, `*` any run except `/`,
    `?` one character except `/`."""
    out: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern[i:i + 3] == "**/":
            out.append("(?:.*/)?")
            i += 3
        elif pattern[i:i + 2] == "**":
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        elif pattern[i] == "[":
            end = pattern.find("]", i + 1)
            if end < 0:
                out.append(re.escape(pattern[i]))
                i += 1
            else:
                out.append(pattern[i:end + 1])
                i = end + 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return "^" + "".join(out) + "$"


def matches_pattern(pattern: str, branch: str) -> bool:
    """Whether one branch-name pattern matches one
    branch name: a full, anchored match under the
    segment-aware glob discipline above."""
    if not isinstance(branch, str) or not branch:
        return False
    return re.match(_glob_regex(pattern), branch) is not None


def pattern_specificity(pattern: str) -> tuple:
    """The pattern half of the evaluation-order key:
    (has wildcards, fewer literal characters later,
    more wildcards later, the pattern itself). Combined
    with the rule id in `evaluation_order_key` this is
    the documented deterministic order."""
    wildcards = pattern.count("*") + pattern.count("?")
    literal = len(pattern) - wildcards
    return (1 if wildcards else 0, -literal, wildcards, pattern)


def evaluation_order_key(rule) -> tuple:
    """One rule's full evaluation-order key: the
    pattern's specificity, then the rule id — unique,
    so the order over any rule set is total."""
    return pattern_specificity(rule.pattern) + (rule.id,)


def order_rules(rules) -> tuple:
    """The rules in evaluation order (see the module
    docstring): exact before wildcard, more literal
    first, fewer wildcards first, lexicographically
    smaller first, lower id first. Pure: the same set
    in any input order yields the same output order."""
    return tuple(sorted(rules, key=evaluation_order_key))


# -- the policy shape ----------------------------------------------------

_BOOL_FIELDS = (
    "enabled", "require_pull_request", "dismiss_stale_reviews",
    "require_code_owner_review", "require_branch_up_to_date",
    "require_signed_commits", "require_linear_history",
    "block_force_pushes", "block_branch_deletion", "enforce_admins")


def _validate_bool(name: str, value: object) -> bool:
    if not isinstance(value, bool):
        raise ProtectionRuleError(
            "protection_rule_invalid",
            f"{name} is on or off (a boolean).")
    return value


def _validate_checks(checks: object) -> tuple:
    if checks is None:
        return ()
    if isinstance(checks, str) or not isinstance(checks, (list, tuple)):
        raise ProtectionRuleError(
            "protection_rule_invalid",
            "Required status checks are a list of check names.")
    out: list[str] = []
    for raw in checks:
        if not isinstance(raw, str) or not raw.strip() \
                or len(raw.strip()) > CHECK_MAX_LEN:
            raise ProtectionRuleError(
                "protection_rule_invalid",
                "A required status check is a name of 1 to "
                f"{CHECK_MAX_LEN} characters.")
        name = raw.strip()
        if name not in out:
            out.append(name)
    if len(out) > CHECK_MAX_COUNT:
        raise ProtectionRuleError(
            "protection_rule_invalid",
            f"At most {CHECK_MAX_COUNT} required status checks.")
    return tuple(out)


def _validate_actors(label: str, actors: object) -> tuple:
    if actors is None:
        return ()
    if isinstance(actors, str) or not isinstance(actors, (list, tuple)):
        raise ProtectionRuleError(
            "protection_rule_invalid",
            f"{label} are a list of user or team names.")
    out: list[str] = []
    for raw in actors:
        if not isinstance(raw, str) or not _ACTOR_RE.match(raw.strip()):
            raise ProtectionRuleError(
                "protection_rule_invalid",
                f"That {label} name is not valid: {raw!r} "
                "(a user name, or owner/team).")
        name = raw.strip()
        if name not in out:
            out.append(name)
    if len(out) > ACTOR_MAX_COUNT:
        raise ProtectionRuleError(
            "protection_rule_invalid",
            f"At most {ACTOR_MAX_COUNT} names in {label}.")
    return tuple(out)


@dataclass(frozen=True)
class ProtectionSettings:
    """The Part VIII policy shape one rule carries, as
    stored values. Defaults are the model's defaults:
    every requirement off except block_force_pushes,
    block_branch_deletion, and enforce_admins, which
    are on — a protected branch is never force-moved
    or deleted by default, and the owner's rules bind
    the owner (S-180). An unlawful shape is refused
    whole, in the house error shape, before any rule
    is stored."""
    enabled: bool = True
    require_pull_request: bool = False
    required_approvals: int = 0
    dismiss_stale_reviews: bool = False
    require_code_owner_review: bool = False
    required_status_checks: tuple = ()
    require_branch_up_to_date: bool = False
    require_signed_commits: bool = False
    require_linear_history: bool = False
    block_force_pushes: bool = True
    block_branch_deletion: bool = True
    enforce_admins: bool = True
    allowed_push_actors: tuple = ()
    bypass_actors: tuple = ()

    def __post_init__(self):
        for name in _BOOL_FIELDS:
            _validate_bool(name, getattr(self, name))
        if isinstance(self.required_approvals, bool) \
                or not isinstance(self.required_approvals, int) \
                or self.required_approvals < 0:
            raise ProtectionRuleError(
                "protection_rule_invalid",
                "Required approvals is a whole number, zero "
                "or more.")
        object.__setattr__(self, "required_status_checks",
                           _validate_checks(self.required_status_checks))
        object.__setattr__(self, "allowed_push_actors", _validate_actors(
            "allowed push actors", self.allowed_push_actors))
        object.__setattr__(self, "bypass_actors", _validate_actors(
            "bypass actors", self.bypass_actors))

    def requirement_words(self) -> tuple:
        """Each requirement this shape carries, one
        plain sentence fragment per requirement — the
        words a rule's `words` and an evaluation's
        summary are built from."""
        out = []
        if self.require_pull_request:
            out.append("a pull request is required before merging")
        if self.required_approvals:
            noun = ("approval" if self.required_approvals == 1
                    else "approvals")
            verb = "is" if self.required_approvals == 1 else "are"
            out.append(
                f"{self.required_approvals} {noun} {verb} required")
        if self.dismiss_stale_reviews:
            out.append("stale reviews are dismissed on new pushes")
        if self.require_code_owner_review:
            out.append("code-owner review is required")
        if self.required_status_checks:
            out.append("required status checks: "
                       + ", ".join(self.required_status_checks))
        if self.require_branch_up_to_date:
            out.append("the branch must be up to date before merging")
        if self.require_signed_commits:
            out.append("signed commits are required")
        if self.require_linear_history:
            out.append("linear history is required")
        if self.block_force_pushes:
            out.append("force pushes are blocked")
        if self.block_branch_deletion:
            out.append("branch deletion is blocked")
        if self.enforce_admins:
            out.append("the rule is enforced for admins")
        if self.allowed_push_actors:
            out.append("only these actors may push directly: "
                       + ", ".join(self.allowed_push_actors))
        if self.bypass_actors:
            out.append("these actors may bypass: "
                       + ", ".join(self.bypass_actors))
        return tuple(out)


@dataclass(frozen=True)
class ProtectionRule:
    """One protection rule: a pattern in one repository
    and the policy shape it carries."""
    id: int
    repo_id: int
    full_name: str
    pattern: str
    settings: ProtectionSettings
    created_by: int | None
    created_at: int
    updated_at: int

    @property
    def enabled(self) -> bool:
        return self.settings.enabled

    @property
    def is_exact(self) -> bool:
        return "*" not in self.pattern and "?" not in self.pattern \
            and "[" not in self.pattern

    def matches(self, branch: str) -> bool:
        """Whether this rule attaches to `branch`:
        enabled, and the pattern matches."""
        return self.settings.enabled and matches_pattern(self.pattern, branch)

    @property
    def words(self) -> str:
        state = "enabled" if self.settings.enabled else "disabled"
        reqs = self.settings.requirement_words()
        if reqs:
            body = "; ".join(reqs)
        else:
            body = "no requirements beyond being protected"
        return (f"Rule for pattern '{self.pattern}' in "
                f"{self.full_name} ({state}): {body}.")


@dataclass(frozen=True)
class EffectiveProtection:
    """The folded policy of every matching rule:
    most-restrictive-wins, as documented in the module
    docstring. The folded shape keeps each field's own
    convention: an empty `allowed_push_actors` means no
    matching rule restricted pushing, and an empty
    `bypass_actors` means nobody bypasses — the actors
    every matching rule names (the intersection
    rule)."""
    settings: ProtectionSettings
    rule_ids: tuple
    patterns: tuple


@dataclass(frozen=True)
class ProtectionEvaluation:
    """One branch's protection position, resolved once:
    the matching rules in evaluation order and the
    effective policy they fold into — the answer the
    enforcement slices act on."""
    full_name: str
    branch: str
    matching: tuple            # of ProtectionRule, evaluation order
    effective: EffectiveProtection | None

    @property
    def is_protected(self) -> bool:
        return self.effective is not None

    @property
    def words(self) -> str:
        if self.effective is None:
            return (f"No protection rule matches branch "
                    f"'{self.branch}' in {self.full_name}: "
                    "the branch is not protected.")
        patterns = ", ".join(
            f"'{rule.pattern}'" for rule in self.matching)
        noun = "rule matches" if len(self.matching) == 1 else "rules match"
        reqs = self.effective.settings.requirement_words()
        body = "; ".join(reqs) if reqs else "being protected"
        return (f"{len(self.matching)} protection {noun} branch "
                f"'{self.branch}' in {self.full_name}, in "
                f"evaluation order: {patterns}. The effective "
                f"rule requires: {body}.")


def evaluate_rules(rules, branch: str, *,
                     full_name: str = "") -> ProtectionEvaluation:
    """The pure half of evaluation: from any iterable
    of rules, the ones that attach to `branch`, in the
    documented evaluation order, folded
    most-restrictive-wins. No database is touched here,
    so the order and the algebra are provable in
    isolation; the store below only has to gather one
    repository's rules honestly."""
    matching = order_rules(
        [rule for rule in rules if rule.matches(branch)])
    if not matching:
        return ProtectionEvaluation(
            full_name=full_name, branch=branch,
            matching=(), effective=None)
    allowed: tuple | None = None
    checks: list[str] = []
    for rule in matching:
        s = rule.settings
        for name in s.required_status_checks:
            if name not in checks:
                checks.append(name)
        if s.allowed_push_actors:
            allowed = s.allowed_push_actors if allowed is None else tuple(
                name for name in allowed if name in s.allowed_push_actors)
    # Bypass intersects over EVERY matching rule: a rule
    # whose bypass list is empty names nobody, so it
    # closes the door for the branch as a whole.
    bypass = matching[0].settings.bypass_actors
    for other in matching[1:]:
        bypass = tuple(
            name for name in bypass
            if name in other.settings.bypass_actors)
    effective_settings = ProtectionSettings(
        enabled=True,
        require_pull_request=any(
            r.settings.require_pull_request for r in matching),
        required_approvals=max(
            r.settings.required_approvals for r in matching),
        dismiss_stale_reviews=any(
            r.settings.dismiss_stale_reviews for r in matching),
        require_code_owner_review=any(
            r.settings.require_code_owner_review for r in matching),
        required_status_checks=tuple(checks),
        require_branch_up_to_date=any(
            r.settings.require_branch_up_to_date for r in matching),
        require_signed_commits=any(
            r.settings.require_signed_commits for r in matching),
        require_linear_history=any(
            r.settings.require_linear_history for r in matching),
        block_force_pushes=any(
            r.settings.block_force_pushes for r in matching),
        block_branch_deletion=any(
            r.settings.block_branch_deletion for r in matching),
        enforce_admins=any(
            r.settings.enforce_admins for r in matching),
        allowed_push_actors=() if allowed is None else allowed,
        bypass_actors=bypass)
    return ProtectionEvaluation(
        full_name=full_name, branch=branch, matching=matching,
        effective=EffectiveProtection(
            settings=effective_settings,
            rule_ids=tuple(rule.id for rule in matching),
            patterns=tuple(rule.pattern for rule in matching)))


# -- the store -------------------------------------------------------------

_SETTINGS_COLUMNS = (
    "enabled", "require_pull_request", "required_approvals",
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


def _row_to_rule(row: sqlite3.Row, full_name: str) -> ProtectionRule:
    return ProtectionRule(
        id=row["id"], repo_id=row["repo_id"], full_name=full_name,
        pattern=row["pattern"], settings=_settings_from_row(row),
        created_by=row["created_by"], created_at=row["created_at"],
        updated_at=row["updated_at"])


class ProtectionRuleStore:
    """The store half of the model: one repository's
    rules, gathered honestly through S-054's guards.
    Enforcement slices hold this store and read
    `evaluate_branch` / `rules_for_branch`; they never
    re-derive matching or ordering themselves."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._audit = audit
        self._now = time_fn

    # -- guards ------------------------------------------------------
    def _repo_for_read(self, viewer: User | None, owner: object,
                       repo: object) -> Repository:
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise ProtectionRuleError(
                "repo_not_found", "No such repository.")
        return current

    def _repo_for_admin(self, actor: User | None, owner: object,
                        repo: object) -> Repository:
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise ProtectionRuleError(
                "repo_not_found", "No such repository.")
        if actor is None or not can_read(actor, current):
            raise ProtectionRuleError(
                "repo_not_found", "No such repository.")
        if not can_admin(actor, current):
            raise ProtectionRuleError(
                "permission_denied",
                "Only a repository admin can manage "
                "protection rules.")
        return current

    # -- row access ----------------------------------------------------
    def _by_id(self, repo_id: int, rule_id: object,
               full_name: str) -> ProtectionRule | None:
        if isinstance(rule_id, bool) or not isinstance(rule_id, int):
            return None
        row = self._conn.execute(
            "SELECT * FROM protection_rules"
            " WHERE repo_id = ? AND id = ?",
            (repo_id, rule_id)).fetchone()
        return _row_to_rule(row, full_name) if row is not None else None

    def _by_pattern(self, repo_id: int, pattern: str,
                    full_name: str) -> ProtectionRule | None:
        row = self._conn.execute(
            "SELECT * FROM protection_rules"
            " WHERE repo_id = ? AND pattern = ?",
            (repo_id, pattern)).fetchone()
        return _row_to_rule(row, full_name) if row is not None else None

    def _all(self, current: Repository) -> list[ProtectionRule]:
        rows = self._conn.execute(
            "SELECT * FROM protection_rules WHERE repo_id = ?"
            " ORDER BY id", (current.id,)).fetchall()
        return [_row_to_rule(r, current.full_name) for r in rows]

    # -- CRUD ------------------------------------------------------------
    def create_rule(self, actor: User | None, owner: object,
                    repo: object, pattern: object, *,
                    settings: ProtectionSettings | None = None,
                    source_ip: str | None = None,
                    **fields) -> ProtectionRule:
        """Create one rule for `pattern` in this
        repository. The policy shape arrives either as
        a `ProtectionSettings` or as field keywords
        (never both). One rule per pattern per
        repository: a second create for the same
        pattern is refused `protection_rule_taken`."""
        current = self._repo_for_admin(actor, owner, repo)
        text = validate_pattern(pattern)
        shape = self._shape(settings, fields)
        now = int(self._now())
        columns = ", ".join(_SETTINGS_COLUMNS)
        marks = ", ".join("?" for _ in _SETTINGS_COLUMNS)
        with self._conn:  # commits before the answer
            try:
                cur = self._conn.execute(
                    f"INSERT INTO protection_rules (repo_id, pattern,"
                    f" {columns}, created_by, created_at, updated_at)"
                    f" VALUES (?, ?, {marks}, ?, ?, ?)",
                    (current.id, text, *_settings_values(shape),
                     actor.id if actor is not None else None, now, now))
            except sqlite3.IntegrityError:
                raise ProtectionRuleError(
                    "protection_rule_taken",
                    f"A protection rule for pattern {text!r} "
                    "already exists in this repository; update "
                    "that rule instead.") from None
        rule = self._by_id(current.id, int(cur.lastrowid), current.full_name)
        assert rule is not None
        self._emit(actor, current, rule, "create", source_ip)
        return rule

    def get_rule(self, viewer: User | None, owner: object,
                 repo: object, rule_id: object) -> ProtectionRule:
        current = self._repo_for_read(viewer, owner, repo)
        rule = self._by_id(current.id, rule_id, current.full_name)
        if rule is None:
            raise ProtectionRuleError(
                "protection_rule_not_found", "No such protection rule.")
        return rule

    def get_rule_by_pattern(self, viewer: User | None, owner: object,
                            repo: object,
                            pattern: object) -> ProtectionRule:
        current = self._repo_for_read(viewer, owner, repo)
        text = validate_pattern(pattern)
        rule = self._by_pattern(current.id, text, current.full_name)
        if rule is None:
            raise ProtectionRuleError(
                "protection_rule_not_found", "No such protection rule.")
        return rule

    def list_rules(self, viewer: User | None, owner: object,
                   repo: object) -> list[ProtectionRule]:
        """Every rule in the repository, creation order
        (id ascending) — the management listing. The
        judgment order is `rules_for_branch` /
        `evaluate_branch`, never this listing."""
        current = self._repo_for_read(viewer, owner, repo)
        return self._all(current)

    def update_rule(self, actor: User | None, owner: object,
                    repo: object, rule_id: object, *,
                    pattern: object = None,
                    settings: ProtectionSettings | None = None,
                    source_ip: str | None = None,
                    **fields) -> ProtectionRule:
        """Change one rule: its pattern, its whole shape
        (a `ProtectionSettings`), or individual fields
        (a field left out keeps its stored value). A
        same-value update is a quiet no-op: it stores
        nothing and audits nothing."""
        current = self._repo_for_admin(actor, owner, repo)
        rule = self._by_id(current.id, rule_id, current.full_name)
        if rule is None:
            raise ProtectionRuleError(
                "protection_rule_not_found", "No such protection rule.")
        text = rule.pattern if pattern is None else validate_pattern(pattern)
        if settings is not None and fields:
            raise ProtectionRuleError(
                "protection_rule_invalid",
                "Give a rule's shape whole, or field by "
                "field — not both.")
        if settings is not None:
            shape = settings
            if not isinstance(shape, ProtectionSettings):
                raise ProtectionRuleError(
                    "protection_rule_invalid",
                    "A rule's shape is a ProtectionSettings.")
        elif fields:
            merged = {
                name: getattr(rule.settings, name)
                for name in ("enabled", "require_pull_request",
                             "required_approvals",
                             "dismiss_stale_reviews",
                             "require_code_owner_review",
                             "required_status_checks",
                             "require_branch_up_to_date",
                             "require_signed_commits",
                             "require_linear_history",
                             "block_force_pushes",
                             "block_branch_deletion", "enforce_admins",
                             "allowed_push_actors", "bypass_actors")}
            unknown = set(fields) - set(merged)
            if unknown:
                raise ProtectionRuleError(
                    "protection_rule_invalid",
                    f"Unknown protection rule field(s): "
                    f"{', '.join(sorted(unknown))}.")
            merged.update(fields)
            shape = ProtectionSettings(**merged)
        else:
            shape = rule.settings
        if text == rule.pattern and shape == rule.settings:
            return rule  # a same-value retry is a quiet no-op
        now = int(self._now())
        columns = ", ".join(f"{name} = ?" for name in _SETTINGS_COLUMNS)
        with self._conn:  # commits before the answer
            try:
                self._conn.execute(
                    f"UPDATE protection_rules SET pattern = ?,"
                    f" {columns}, updated_at = ? WHERE id = ?",
                    (text, *_settings_values(shape), now, rule.id))
            except sqlite3.IntegrityError:
                raise ProtectionRuleError(
                    "protection_rule_taken",
                    f"A protection rule for pattern {text!r} "
                    "already exists in this repository; update "
                    "that rule instead.") from None
        updated = self._by_id(current.id, rule.id, current.full_name)
        assert updated is not None
        self._emit(actor, current, updated, "update", source_ip)
        return updated

    def delete_rule(self, actor: User | None, owner: object,
                    repo: object, rule_id: object, *,
                    source_ip: str | None = None) -> ProtectionRule:
        current = self._repo_for_admin(actor, owner, repo)
        rule = self._by_id(current.id, rule_id, current.full_name)
        if rule is None:
            raise ProtectionRuleError(
                "protection_rule_not_found", "No such protection rule.")
        with self._conn:  # commits before the answer
            self._conn.execute(
                "DELETE FROM protection_rules WHERE id = ?", (rule.id,))
        self._emit(actor, current, rule, "delete", source_ip)
        return rule

    # -- evaluation ------------------------------------------------------
    def rules_for_branch(self, viewer: User | None, owner: object,
                         repo: object,
                         branch: object) -> tuple:
        """The enabled rules that attach to `branch`,
        in the documented evaluation order — the list
        enforcement slices walk."""
        current = self._repo_for_read(viewer, owner, repo)
        name = self._branch(branch)
        evaluation = evaluate_rules(
            self._all(current), name, full_name=current.full_name)
        return evaluation.matching

    def evaluate_branch(self, viewer: User | None, owner: object,
                        repo: object,
                        branch: object) -> ProtectionEvaluation:
        """THE one evaluation Part VIII consults: this
        branch's protection position, resolved once —
        matching rules in evaluation order and the
        most-restrictive effective policy they fold
        into."""
        current = self._repo_for_read(viewer, owner, repo)
        name = self._branch(branch)
        return evaluate_rules(
            self._all(current), name, full_name=current.full_name)

    def is_protected(self, viewer: User | None, owner: object,
                     repo: object, branch: object) -> bool:
        """Whether any enabled rule attaches to
        `branch` — the boolean seam S-159's housekeeping
        guard and S-177's wiring will consult."""
        return self.evaluate_branch(viewer, owner, repo, branch).is_protected

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _branch(branch: object) -> str:
        from .repositories import validate_branch_name
        return validate_branch_name(branch)

    @staticmethod
    def _shape(settings, fields) -> ProtectionSettings:
        if settings is not None and fields:
            raise ProtectionRuleError(
                "protection_rule_invalid",
                "Give a rule's shape whole, or field by "
                "field — not both.")
        if settings is not None:
            if not isinstance(settings, ProtectionSettings):
                raise ProtectionRuleError(
                    "protection_rule_invalid",
                    "A rule's shape is a ProtectionSettings.")
            return settings
        try:
            return ProtectionSettings(**fields)
        except TypeError:
            unknown = set(fields) - {
                "enabled", "require_pull_request", "required_approvals",
                "dismiss_stale_reviews", "require_code_owner_review",
                "required_status_checks", "require_branch_up_to_date",
                "require_signed_commits", "require_linear_history",
                "block_force_pushes", "block_branch_deletion",
                "enforce_admins", "allowed_push_actors", "bypass_actors"}
            raise ProtectionRuleError(
                "protection_rule_invalid",
                f"Unknown protection rule field(s): "
                f"{', '.join(sorted(unknown))}.") from None

    def _emit(self, actor, current, rule, verb, source_ip) -> None:
        if self._audit is None or actor is None:
            return
        self._audit.append(
            actor_kind="user", actor_id=actor.id,
            action="repo.protection.change", target_kind="repo",
            target_id=current.full_name, outcome="success",
            source_ip=source_ip,
            detail={"branch": rule.pattern, "rule": verb,
                    "rule_id": rule.id, "pattern": rule.pattern})


def render_protection_rule(rule: ProtectionRule) -> str:
    """One rule in words — exactly the rule's own
    `words`, escaped through S-010, never a colour
    alone. A renderer for the model's answer, not a
    page: no route consumes rules yet, so none is
    invented."""
    return (
        '<div class="protection-rule">'
        f"<p>{escape_html_text(rule.words)}</p></div>")


def render_protection_evaluation(evaluation: ProtectionEvaluation) -> str:
    """One branch's protection position in words —
    exactly the evaluation's own `words`, escaped
    through S-010. The sentences S-183's rule insights
    will quote when they answer "why was this refused?"."""
    return (
        '<div class="protection-evaluation">'
        f"<p>{escape_html_text(evaluation.words)}</p></div>")
