"""Compare-in-release (S-270).

Roadmap S-270: Compare-in-release — release notes
can embed the compare range (S-105) between the
previous tag and this one.

The laws:

- **The range is S-105's compare, unchanged.** The
  embedded range is `CompareService.compare`
  between the previous tag and this release's tag:
  the same ahead/behind counts, the same capped
  commit list (the true ahead count always named,
  a capped list saying how many it is not
  showing), and the same S-104 diff totals the
  compare page shows. Nothing here recounts.
- **The previous tag is S-269's, or the previous
  release's.** For a version tag the previous tag
  is S-269's previous version tag — the highest
  other version tag whose target is an ancestor
  of this tag's target, by git's own ancestry
  answer. For any other tag (S-257 releases may
  bind any standing tag) the previous tag is the
  newest other release in this repository whose
  stored target is an ancestor of this release's
  target and is not this release's target — the
  release order S-257's listing already keeps.
  When no previous tag stands there is no range:
  the compare answers `previous_tag` None in
  words, and embedding is refused by name
  (`no_previous_tag`) — a base is never invented,
  and the whole-history road stays S-269's notes.
- **Embedding is explicit, marked, and once.**
  `embed_compare` is pure: it replaces the
  `{{compare}}` placeholder when the notes carry
  one, and otherwise appends the section. The
  section opens with the standing marker
  (`COMPARE_MARKER`), so an already-embedded
  release is known by its own notes:
  `embed_in_release` refuses a second embedding
  by name (`compare_already_embedded`) and
  changes nothing. A writer who wants a fresh
  range edits the old section out by hand — the
  notes stay the writer's, always.
- **The section says what it is, in words.** It
  names both tags, the ahead/behind counts, the
  files changed with their +/− totals, and each
  listed commit by short id, subject and author;
  an empty range (the two tags naming one commit,
  or no commits between them) says exactly that.
  The stored section is Markdown source, rendered
  later by S-257's one pipeline like all notes;
  this module's own HTML face escapes every field
  through S-010.
- **Permissions ride the release's own (S-257 /
  S-258).** Reading a compare resolves through
  `ReleaseStore.get_release`, so a private
  repository answers the uniform `repo_not_found`
  and a draft release is invisible — compare and
  all — to everyone but a writer, answering the
  uniform `release_not_found`. Embedding writes
  through `ReleaseStore.update_release`, a writer
  act: a mere reader is refused
  `permission_denied`, the draft flag never moves
  sideways through an embed, and an embed that
  would overflow the notes limit is refused
  `notes_invalid` with the notes unchanged.

Embedding is an edit of a release's notes, and
edits carry no verb of their own in the frozen
taxonomy vocabulary (S-257): it is not witnessed
and notifies nobody. No migration: the slice
reads the rows and refs that already stand.
No new taxonomy event: 133 stand
(33 auth / 87 repo / 13 admin); schema 106 stands.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .compare_view import CompareError, CompareService, CompareView
from .escaping import escape_html_text
from .proc import run_git_in
from .release_from_tag import ReleaseFromTagStore, is_version_tag
from .releases import Release, ReleaseError, ReleaseStore
from .repositories import RepositoryStore

COMPARE_MARKER = "<!-- samverk:compare-in-release -->"
EMBED_PLACEHOLDER = "{{compare}}"

__all__ = [
    "COMPARE_MARKER", "EMBED_PLACEHOLDER",
    "ReleaseCompare", "ReleaseCompareError",
    "ReleaseCompareStore", "build_compare_section",
    "compare_to_dict", "embed_compare",
    "has_embedded_compare", "render_compare_section",
]


class ReleaseCompareError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class ReleaseCompare:
    """One release's compare range: the release
    itself, the previous tag the range starts from
    (None when no previous tag stands), and S-105's
    compare of that range (None exactly when there
    is no previous tag — never a fabricated base)."""

    release: Release
    previous_tag: str | None
    compare: CompareView | None

    @property
    def tag(self) -> str:
        return self.release.tag

    @property
    def has_previous(self) -> bool:
        return self.previous_tag is not None

    @property
    def range_words(self) -> str:
        if self.previous_tag is None:
            return (f"No previous tag stands before "
                    f"{self.release.tag}; there is no "
                    "compare range.")
        return f"{self.previous_tag}…{self.release.tag}"

    @property
    def words(self) -> str:
        if self.compare is None:
            return self.range_words
        view = self.compare
        return (f"{self.range_words} · {view.ahead} ahead · "
                f"{view.behind} behind · "
                f"{view.files_changed} files changed · "
                f"+{view.diff.additions} −{view.diff.deletions}")


def has_embedded_compare(notes: object) -> bool:
    """Whether notes already carry an embedded
    compare section, known by the standing marker."""
    return isinstance(notes, str) and COMPARE_MARKER in notes


def build_compare_section(rc: ReleaseCompare) -> str:
    """The embeddable section, as Markdown: the
    marker, the range named in words, the totals,
    the listed commits, and the files changed. An
    empty range says so — no entry is invented.
    Refused `no_previous_tag` when there is no
    range to build."""
    if rc.compare is None or rc.previous_tag is None:
        raise ReleaseCompareError(
            "no_previous_tag",
            f"No previous tag stands before {rc.tag}; "
            "there is no compare range to embed.")
    view = rc.compare
    lines = [
        COMPARE_MARKER,
        f"## Compare: {rc.previous_tag}…{rc.tag}",
        "",
        (f"{view.ahead} ahead · {view.behind} behind · "
         f"{view.files_changed} files changed · "
         f"+{view.diff.additions} −{view.diff.deletions}"),
        "",
    ]
    if view.ahead == 0 and view.behind == 0:
        lines.append(
            "These two tags name the same commit. "
            "There is nothing to compare.")
        return "\n".join(lines) + "\n"
    if view.commits:
        lines.append("Commits:")
        lines.append("")
        for commit in view.commits:
            lines.append(
                f"- {commit.oid[:12]} {commit.subject} "
                f"({commit.author_name})")
        if view.commits_truncated:
            lines.append(
                f"- … {view.commits_truncated} further commits "
                "are not listed; the count above is the "
                "true total.")
        lines.append("")
    elif view.ahead:
        lines.append(
            f"No commits are listed for this range, "
            f"though it stands {view.ahead} ahead.")
        lines.append("")
    else:
        lines.append("No commits in this range.")
        lines.append("")
    if view.diff.files:
        lines.append("Files changed:")
        lines.append("")
        for diff_file in view.diff.files:
            if diff_file.is_binary:
                lines.append(f"- {diff_file.path} (binary)")
            elif diff_file.old_path is None:
                lines.append(
                    f"- {diff_file.path} (new file, "
                    f"+{diff_file.additions} "
                    f"−{diff_file.deletions})")
            elif diff_file.new_path is None:
                lines.append(
                    f"- {diff_file.path} (deleted, "
                    f"+{diff_file.additions} "
                    f"−{diff_file.deletions})")
            else:
                lines.append(
                    f"- {diff_file.path} "
                    f"(+{diff_file.additions} "
                    f"−{diff_file.deletions})")
    else:
        lines.append("No file changes in this range.")
    return "\n".join(lines) + "\n"


def embed_compare(notes: object, rc: ReleaseCompare) -> str:
    """Notes with the compare section embedded
    (pure): the `{{compare}}` placeholder is
    replaced when the notes carry one, otherwise
    the section is appended. Notes already carrying
    a section are refused `compare_already_embedded`
    — embedding is once, by name."""
    if not isinstance(notes, str):
        raise ReleaseCompareError(
            "notes_invalid", "Release notes must be Markdown text.")
    if has_embedded_compare(notes):
        raise ReleaseCompareError(
            "compare_already_embedded",
            f"Release {rc.tag!r} already embeds a compare "
            "range; edit the standing section out by hand "
            "to embed a fresh one.")
    section = build_compare_section(rc)
    if EMBED_PLACEHOLDER in notes:
        return notes.replace(EMBED_PLACEHOLDER, section.rstrip("\n"), 1)
    if not notes.strip():
        return section
    return notes.rstrip("\n") + "\n\n" + section


def compare_to_dict(rc: ReleaseCompare) -> dict:
    """One release compare as the API would answer
    it: the range in words and numbers, or an
    honest `previous_tag` of None with no compare."""
    out: dict = {
        "tag": rc.tag,
        "previous_tag": rc.previous_tag,
        "range": rc.range_words,
        "embedded": has_embedded_compare(rc.release.notes),
    }
    if rc.compare is None:
        out.update({
            "ahead": None, "behind": None,
            "files_changed": None, "additions": None,
            "deletions": None, "commits": [], "files": [],
            "commits_truncated": 0})
        return out
    view = rc.compare
    out.update({
        "ahead": view.ahead, "behind": view.behind,
        "files_changed": view.files_changed,
        "additions": view.diff.additions,
        "deletions": view.diff.deletions,
        "commits_truncated": view.commits_truncated,
        "commits": [
            {"oid": c.oid, "subject": c.subject,
             "author": c.author_name}
            for c in view.commits],
        "files": [
            {"path": f.path, "additions": f.additions,
             "deletions": f.deletions, "binary": f.is_binary}
            for f in view.diff.files],
    })
    return out


def render_compare_section(rc: ReleaseCompare) -> str:
    """The compare's own HTML face: the range and
    totals in words and the listed commits, every
    field S-010-escaped (words, never colour
    alone). A release with no previous tag says so."""
    parts = ['<section class="release-compare"><h4>'
             "Compare</h4>"]
    parts.append(
        '<p class="compare-range">'
        + escape_html_text(rc.words) + "</p>")
    if rc.compare is not None and rc.compare.commits:
        parts.append('<ol class="commits">')
        for commit in rc.compare.commits:
            parts.append(
                '<li class="commit"><span class="oid">'
                + escape_html_text(commit.oid[:12])
                + '</span> <span class="subject">'
                + escape_html_text(commit.subject)
                + '</span> <span class="author">'
                + escape_html_text(commit.author_name)
                + "</span></li>")
        parts.append("</ol>")
        if rc.compare.commits_truncated:
            parts.append(
                '<p class="truncated">'
                + escape_html_text(
                    f"{rc.compare.commits_truncated} further "
                    "commits are not listed; the count above "
                    "is the true total.")
                + "</p>")
    parts.append("</section>")
    return "".join(parts)


class ReleaseCompareStore:
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
        self._from_tag = ReleaseFromTagStore(
            conn, repositories, releases, accounts,
            audit=audit, time_fn=time_fn)
        self._compare = CompareService(repositories)

    @staticmethod
    def _carry(exc: ReleaseError | CompareError) -> ReleaseCompareError:
        return ReleaseCompareError(exc.reason, str(exc))

    def _release_for_read(self, viewer: User | None, owner: object,
                          repo: object, tag: object) -> Release:
        """The release through its own read gate
        (S-257/S-258): private repo and unseen draft
        both answer their uniform not-found."""
        try:
            return self._releases.get_release(viewer, owner, repo, tag)
        except ReleaseError as exc:
            raise self._carry(exc) from None

    def _is_ancestor(self, owner: str, repo: str,
                     old_oid: str, new_oid: str) -> bool:
        """Git's own ancestry answer (the S-182 seam,
        as S-269 judges it): only a clean 0 counts —
        every other outcome fails closed."""
        repo_path = self._repos.path_for(owner, repo)
        result = run_git_in(
            repo_path,
            ["merge-base", "--is-ancestor", old_oid, new_oid],
            timeout=15.0)
        return result.returncode == 0

    def previous_tag(self, viewer: User | None, owner: object,
                     repo: object, tag: object) -> str | None:
        """The previous tag for this release's tag:
        S-269's previous version tag for a version
        tag; for any other tag, the tag of the
        newest other visible release whose stored
        target is an ancestor of this release's
        target (never this release's own target).
        None when no previous tag stands."""
        release = self._release_for_read(viewer, owner, repo, tag)
        if is_version_tag(release.tag):
            from .release_from_tag import ReleaseFromTagError
            try:
                return self._from_tag.previous_version_tag(
                    viewer, owner, repo, release.tag)
            except ReleaseFromTagError as exc:
                raise self._carry(exc) from None
        current = self._repos.get_repository(owner, repo)
        assert current is not None  # the release required read
        candidates: list[Release] = []
        for other in self._releases.list_releases(viewer, owner, repo):
            if other.id == release.id:
                continue
            if other.target_oid == release.target_oid:
                continue
            if self._is_ancestor(
                    current.owner, current.name,
                    other.target_oid, release.target_oid):
                candidates.append(other)
        if not candidates:
            return None
        newest = max(
            candidates, key=lambda r: (r.created_at, r.id))
        return newest.tag

    def compare_for_release(
            self, viewer: User | None, owner: object,
            repo: object, tag: object, *,
            ignore_whitespace: bool = False) -> ReleaseCompare:
        """This release's compare range (read-gated
        through the release itself): S-105's compare
        of previous tag … this tag, or an honest
        no-previous answer when none stands."""
        release = self._release_for_read(viewer, owner, repo, tag)
        previous = self.previous_tag(viewer, owner, repo, release.tag)
        if previous is None:
            return ReleaseCompare(release, None, None)
        try:
            view = self._compare.compare(
                viewer, owner, repo, previous, release.tag,
                ignore_whitespace=ignore_whitespace)
        except CompareError as exc:
            raise self._carry(exc) from None
        return ReleaseCompare(release, previous, view)

    def preview_embedded_notes(
            self, viewer: User | None, owner: object,
            repo: object, tag: object) -> str:
        """The notes as an embed would leave them,
        without writing (read-gated through the
        release itself). Refusals are the embed's
        own: `no_previous_tag` /
        `compare_already_embedded`."""
        rc = self.compare_for_release(viewer, owner, repo, tag)
        return embed_compare(rc.release.notes, rc)

    def embed_in_release(
            self, actor: User, owner: object, repo: object,
            tag: object) -> Release:
        """Embed the compare range in the standing
        release's notes (writer only, through
        S-257's `update_release`): the release
        returned carries the section; its draft and
        prerelease flags never move. A release with
        no previous tag, or one already embedding a
        range, is refused by name and changed in
        nothing."""
        rc = self.compare_for_release(actor, owner, repo, tag)
        new_notes = embed_compare(rc.release.notes, rc)
        try:
            return self._releases.update_release(
                actor, owner, repo, rc.tag, notes=new_notes)
        except ReleaseError as exc:
            raise self._carry(exc) from None
