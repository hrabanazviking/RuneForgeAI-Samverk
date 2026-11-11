"""Release-from-tag automation (S-269).

Roadmap S-269: Release-from-tag automation —
pushing a version tag can draft a release with
generated notes from merged PRs (honest, editable
draft — never auto-published).

The laws:

- **Off until a writer turns it on.** Automation
  is a per-repository switch (migration 106's
  `release_tag_automation` row; no row means off).
  Only a repository writer may flip it
  (`set_enabled`), and the push door
  (`on_tag_push`) does nothing at all while it is
  off — it answers an outcome naming the refusal,
  never a release. A tag push is a public act, so
  silent surprise drafts are not the default.
- **Version tags only.** The pure
  `parse_version_tag` / `is_version_tag` judge the
  name: an optional leading `v`, then
  MAJOR.MINOR in digits with an optional .PATCH, then an optional
  `-prerelease` or `+build` suffix. `v1.2`,
  `release-1.2.3`, `v1.2-bare` and plain words are
  not version tags, and the automation skips them
  by name — S-257's notes-file door remains the
  road for non-version tags.
- **The draft is S-257's own row, in S-258's
  draft state.** A drafted release is created
  through `ReleaseStore.create_release` with
  ``draft=True`` and ``source="tag_push"``: its
  title is the tag, its target is the tag's peeled
  commit captured the standing way, and it is
  private to writers until a writer publishes it
  through `publish_release` — the automation
  itself never publishes, so a draft creation
  witnesses nothing (S-258: a draft is not a
  publication) and notifies nobody (S-262 derives
  from the publication witness, and there is
  none). A second push of the same tag answers
  the standing release (`already_exists`), so
  push retries are safe, exactly as S-257's
  tag-push door answers.
- **Notes are generated from merged PRs, in a
  named range, and say so.** The range is every
  merged pull request (S-153/S-154/S-155's one
  `pull_request_merges` record) whose merge
  commit is an ancestor of the new tag's target
  and is NOT an ancestor of the previous version
  tag's target — ancestry is git's own answer
  (`merge-base --is-ancestor`, the S-182 seam),
  never a guess from timestamps. The previous
  version tag is the highest other version tag
  whose target is an ancestor of the new target;
  when none stands, the range is the whole
  history and the notes say "from the beginning".
  The notes name the range, list each PR by
  number, title and author, and carry the
  honesty footer in words: generated, a draft,
  edit before publishing. When no merged PR is
  in range the notes say exactly that — a draft
  with an honest empty list, never invented
  entries.
- **Permissions ride the repository's (S-054).**
  Drafting and flipping the switch are writer
  acts; reading the switch follows read access,
  and a stranger to a private repository gets
  the uniform `repo_not_found`. The explicit
  door (`draft_release_from_tag`) refuses a
  non-version tag by name (`not_version_tag`)
  and a missing tag with S-257's `tag_not_found`;
  the push door converts the skip cases (off,
  not a version tag, release already standing)
  into outcomes instead of errors, because a
  push must not fail for an automation skip.

Enabling, disabling and drafting carry no verb
of their own in the frozen taxonomy vocabulary:
a draft creation is witnessed by nothing (it is
not a publication) and a switch flip is a
settings act with no standing verb, so neither
is witnessed. No new taxonomy event: 133 stand
(33 auth / 87 repo / 13 admin).
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
from .objects import ObjectError, ObjectReader
from .permissions import can_read, can_write
from .proc import run_git_in
from .refs import RefStore, tag_ref
from .releases import (
    Release, ReleaseError, ReleaseStore)
from .repositories import Repository, RepositoryStore

_VERSION_RE = re.compile(
    r"^v?(\d+)\.(\d+)(?:\.(\d+))?"
    r"(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?$")

AUTOMATION_RULE = (
    "When release-from-tag automation is on, pushing "
    "a version tag drafts a release with notes "
    "generated from the merged pull requests since "
    "the previous version tag. The draft is never "
    "published by the automation: a writer edits it "
    "and publishes it by hand.")

DRAFT_FOOTER = (
    "This draft was generated automatically from "
    "merged pull requests when the tag was pushed. "
    "It is a draft — edit these notes and publish "
    "the release yourself; nothing here has been "
    "published.")

__all__ = [
    "AUTOMATION_RULE", "DRAFT_FOOTER",
    "MergedPullRequestNote", "ReleaseFromTagError",
    "ReleaseFromTagStore", "TagPushOutcome",
    "generate_notes", "is_version_tag",
    "parse_version_tag", "render_automation_section",
    "version_key",
]


class ReleaseFromTagError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class MergedPullRequestNote:
    """One merged pull request as the notes name it."""

    number: int
    title: str
    author: str
    merged_at: int
    merge_commit_oid: str


@dataclass(frozen=True)
class TagPushOutcome:
    """What the push door did, in words: `action` is
    one of drafted / already_exists / disabled /
    not_version_tag; `release` stands only for the
    first two."""

    action: str
    tag: str
    release: Release | None = None

    @property
    def drafted(self) -> bool:
        return self.action == "drafted"

    @property
    def words(self) -> str:
        if self.action == "drafted":
            return (f"Tag {self.tag} drafted a release "
                    "from its merged pull requests.")
        if self.action == "already_exists":
            return (f"Tag {self.tag} already has a "
                    "release; nothing was drafted.")
        if self.action == "disabled":
            return ("Release-from-tag automation is off "
                    f"for this repository; tag {self.tag} "
                    "drafted nothing.")
        return (f"Tag {self.tag} is not a version tag; "
                "nothing was drafted.")


def parse_version_tag(tag: object) -> tuple | None:
    """The version in a tag name, or None: an
    optional leading ``v``, MAJOR.MINOR in digits
    with an optional .PATCH, and an optional prerelease / build
    suffix. Returns (major, minor, patch,
    prerelease-or-None)."""
    if not isinstance(tag, str):
        return None
    match = _VERSION_RE.match(tag.strip())
    if match is None:
        return None
    return (int(match.group(1)), int(match.group(2)),
            int(match.group(3) or 0), match.group(4))


def is_version_tag(tag: object) -> bool:
    return parse_version_tag(tag) is not None


def version_key(tag: object) -> tuple:
    """A sort key for version tags: a release sorts
    after its own prereleases, and numeric parts
    compare as numbers (v1.10 after v1.9). A
    non-version tag sorts below every version."""
    parsed = parse_version_tag(tag)
    if parsed is None:
        return (0, 0, 0, 0, "")
    major, minor, patch, prerelease = parsed
    return (major, minor, patch,
            1 if prerelease is None else 0,
            prerelease or "")


def generate_notes(tag: str, previous_tag: str | None,
                   prs: list[MergedPullRequestNote]) -> str:
    """The generated notes, as Markdown: the range
    named in words, one line per merged pull
    request, and the honesty footer. An empty
    range says so — no entry is ever invented."""
    if previous_tag is not None:
        range_line = (
            f"Merged pull requests since "
            f"{previous_tag} ({len(prs)}):")
    else:
        range_line = (
            f"Merged pull requests from the "
            f"beginning ({len(prs)}):")
    lines = ["## What's changed", "", range_line, ""]
    if prs:
        for pr in prs:
            lines.append(
                f"- #{pr.number} {pr.title} "
                f"(@{pr.author})")
    else:
        lines.append(
            "No merged pull requests were found in "
            "this range.")
    lines += ["", "---", "", DRAFT_FOOTER]
    return "\n".join(lines) + "\n"


def render_automation_section(enabled: bool,
                              full_name: str = "") -> str:
    """The automation's face on a page: the rule in
    words and the switch's standing state in text
    (words, never colour alone), S-010-escaped."""
    state = "On" if enabled else "Off"
    return (
        '<section class="release-from-tag"><h4>'
        "Release-from-tag automation</h4>"
        '<p class="automation-rule">'
        + escape_html_text(AUTOMATION_RULE) + "</p>"
        + "<p>Automation for "
        + escape_html_text(full_name or "this repository")
        + " is <strong>" + escape_html_text(state)
        + "</strong>.</p></section>")


class ReleaseFromTagStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        releases: ReleaseStore,
        accounts: AccountStore | None = None,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._repos = repositories
        self._releases = releases
        self._accounts = accounts
        self._audit = audit
        self._now = time_fn

    @staticmethod
    def _carry(exc: ReleaseError) -> ReleaseFromTagError:
        return ReleaseFromTagError(exc.reason, str(exc))

    def _repo_for_read(self, viewer: User | None, owner: object,
                       repo: object) -> Repository:
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise ReleaseFromTagError(
                "repo_not_found", "No such repository.")
        return current

    def _repo_for_write(self, actor: User, owner: object,
                        repo: object) -> Repository:
        current = self._repo_for_read(actor, owner, repo)
        if not can_write(actor, current):
            raise ReleaseFromTagError(
                "permission_denied",
                "Only a repository writer can manage "
                "release-from-tag automation.")
        return current

    # -- the switch -------------------------------------------------

    def is_enabled(self, viewer: User | None, owner: object,
                   repo: object) -> bool:
        """The switch as it stands for this viewer
        (read-gated; no row means off)."""
        current = self._repo_for_read(viewer, owner, repo)
        return self._enabled_for(current.id)

    def _enabled_for(self, repo_id: int) -> bool:
        row = self._conn.execute(
            "SELECT enabled FROM release_tag_automation"
            " WHERE repo_id = ?", (repo_id,)).fetchone()
        return bool(row["enabled"]) if row else False

    def set_enabled(self, actor: User, owner: object,
                    repo: object, enabled: object) -> bool:
        """Flip the switch (writer only). Returns the
        standing state after the call; setting the
        state it already holds is a no-op success."""
        current = self._repo_for_write(actor, owner, repo)
        if not isinstance(enabled, bool):
            raise ReleaseFromTagError(
                "enabled_invalid",
                "Release-from-tag automation is on or off.")
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "INSERT INTO release_tag_automation"
                " (repo_id, enabled, updated_by, updated_at)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT(repo_id) DO UPDATE SET"
                " enabled = excluded.enabled,"
                " updated_by = excluded.updated_by,"
                " updated_at = excluded.updated_at",
                (current.id, int(enabled), actor.id, now))
        return enabled

    # -- the range --------------------------------------------------

    def _tag_target(self, current: Repository, tag: str) -> str:
        """The commit a tag points at (an annotated
        tag's peeled commit), judged as S-257 judges
        it; a tag that does not stand is refused
        tag_not_found."""
        repo_path = self._repos.path_for(current.owner, current.name)
        refs = RefStore(repo_path)
        full = tag_ref(tag)
        found = next(
            (r for r in refs.list_tags() if r.name == full), None)
        if found is None:
            raise ReleaseFromTagError(
                "tag_not_found",
                f"No tag named {tag!r} stands in this repository.")
        if found.peeled_oid:
            return found.peeled_oid
        if found.type == "tag":
            try:
                obj = ObjectReader(repo_path).read_object(found.oid)
            except ObjectError as exc:
                raise ReleaseFromTagError(
                    exc.reason, str(exc)) from None
            for line in obj.data.decode(
                    "utf-8", "replace").splitlines():
                if line.startswith("object "):
                    return line[7:].strip()
        return found.oid

    def _is_ancestor(self, current: Repository,
                     old_oid: str, new_oid: str) -> bool:
        """Git's own ancestry answer (the S-182 seam):
        only a clean 0 counts as ancestry — every
        other outcome fails closed."""
        repo_path = self._repos.path_for(current.owner, current.name)
        result = run_git_in(
            repo_path,
            ["merge-base", "--is-ancestor", old_oid, new_oid],
            timeout=15.0)
        return result.returncode == 0

    def previous_version_tag(self, viewer: User | None,
                             owner: object, repo: object,
                             tag: object) -> str | None:
        """The previous version tag for `tag`: the
        highest other version tag whose target is an
        ancestor of this tag's target (read-gated).
        None when no earlier version tag stands in
        this tag's history."""
        current = self._repo_for_read(viewer, owner, repo)
        tag_text = self._version_tag_or_refuse(tag)
        target = self._tag_target(current, tag_text)
        repo_path = self._repos.path_for(current.owner, current.name)
        candidates: list[tuple] = []
        for ref in RefStore(repo_path).list_tags():
            name = ref.short
            if name == tag_text or not is_version_tag(name):
                continue
            try:
                other = self._tag_target(current, name)
            except ReleaseFromTagError:
                continue
            if other == target:
                continue
            if self._is_ancestor(current, other, target):
                candidates.append((version_key(name), name))
        if not candidates:
            return None
        return max(candidates)[1]

    def merged_pull_requests(self, viewer: User | None,
                             owner: object, repo: object,
                             tag: object
                             ) -> list[MergedPullRequestNote]:
        """The merged pull requests in this tag's
        range (read-gated): merge record standing,
        merge commit an ancestor of the tag's
        target, and not an ancestor of the previous
        version tag's target. Ordered by merge time,
        then number — the order the notes list in."""
        current = self._repo_for_read(viewer, owner, repo)
        tag_text = self._version_tag_or_refuse(tag)
        target = self._tag_target(current, tag_text)
        previous = self.previous_version_tag(
            viewer, owner, repo, tag_text)
        previous_target = (
            self._tag_target(current, previous)
            if previous is not None else None)
        rows = self._conn.execute(
            "SELECT i.number AS number, i.title AS title,"
            " i.author_id AS author_id,"
            " m.merge_commit_oid AS merge_commit_oid,"
            " COALESCE(m.merged_at, m.created_at) AS merged_at"
            " FROM pull_request_merges m"
            " JOIN pull_requests p ON p.id = m.pull_request_id"
            " JOIN issues i ON i.id = p.issue_id"
            " WHERE m.repo_id = ?"
            " ORDER BY merged_at ASC, i.number ASC",
            (current.id,)).fetchall()
        notes: list[MergedPullRequestNote] = []
        for row in rows:
            merge_oid = row["merge_commit_oid"]
            if not self._is_ancestor(current, merge_oid, target):
                continue
            if previous_target is not None and self._is_ancestor(
                    current, merge_oid, previous_target):
                continue
            author = ""
            if self._accounts is not None:
                user = self._accounts.get_by_id(row["author_id"])
                author = user.username if user else ""
            notes.append(MergedPullRequestNote(
                number=row["number"], title=row["title"],
                author=author, merged_at=row["merged_at"],
                merge_commit_oid=merge_oid))
        return notes

    def _version_tag_or_refuse(self, tag: object) -> str:
        if isinstance(tag, str) and is_version_tag(tag.strip()):
            return tag.strip()
        raise ReleaseFromTagError(
            "not_version_tag",
            f"Tag {tag!r} is not a version tag "
            "(vMAJOR.MINOR[.PATCH]).")

    # -- the doors --------------------------------------------------

    def draft_release_from_tag(
            self, actor: User, owner: object, repo: object,
            tag: object, *, source_ip: str | None = None
            ) -> Release:
        """The explicit door: draft the release for a
        version tag now (writer only), whatever the
        switch says — asking by hand is its own
        opt-in. A tag that already has a release
        answers the standing release, so retries are
        safe; a bare refusal (not_version_tag /
        tag_not_found) writes nothing."""
        current = self._repo_for_write(actor, owner, repo)
        tag_text = self._version_tag_or_refuse(tag)
        try:
            existing = self._releases.get_release(
                actor, owner, repo, tag_text)
        except ReleaseError as exc:
            if exc.reason != "release_not_found":
                raise self._carry(exc) from None
            existing = None
        if existing is not None:
            return existing
        prs = self.merged_pull_requests(actor, owner, repo, tag_text)
        previous = self.previous_version_tag(
            actor, owner, repo, tag_text)
        notes = generate_notes(tag_text, previous, prs)
        try:
            return self._releases.create_release(
                actor, owner, repo, tag_text, tag_text, notes,
                source="tag_push", draft=True,
                source_ip=source_ip)
        except ReleaseError as exc:
            raise self._carry(exc) from None

    def on_tag_push(self, actor: User, owner: object,
                    repo: object, tag: object, *,
                    source_ip: str | None = None) -> TagPushOutcome:
        """The push door: what a pushed tag does.
        Skips (switch off, not a version tag, release
        already standing) are outcomes, never errors;
        a drafted release is a draft — this door
        never publishes."""
        current = self._repo_for_write(actor, owner, repo)
        tag_text = tag.strip() if isinstance(tag, str) else ""
        if not self._enabled_for(current.id):
            return TagPushOutcome("disabled", tag_text)
        if not is_version_tag(tag_text):
            return TagPushOutcome("not_version_tag", tag_text)
        try:
            existing = self._releases.get_release(
                actor, owner, repo, tag_text)
        except ReleaseError as exc:
            if exc.reason != "release_not_found":
                raise self._carry(exc) from None
            existing = None
        if existing is not None:
            return TagPushOutcome(
                "already_exists", tag_text, existing)
        release = self.draft_release_from_tag(
            actor, owner, repo, tag_text, source_ip=source_ip)
        return TagPushOutcome("drafted", tag_text, release)
