"""Releases (S-257; states S-258).

A release binds three things together in one
repository: a **tag** that already stands in git, a
**title**, and **Markdown notes**. The binding is a row
(migration 100); the tag's target commit is captured at
creation, so a release keeps naming the commit it was
cut from even if the tag is later moved (S-183's tag
protection judges such moves separately).

Three doors create a release, one law behind all three:

- **The web** — `create_release` with ``source="web"``:
  a repository writer names the tag, the title and the
  notes directly.
- **The API** — `create_release_from_api`: the same act
  from a JSON-shaped payload dict (``tag`` / ``title`` /
  ``notes`` and nothing else; an unknown key is refused
  by name). `release_to_dict` is the shape the API
  answers with — the programmatic face of the same
  capability, never a back door (the S-237 law): it
  resolves through the same write permission.
- **A tag push with a notes file** —
  `create_release_from_tag_push`: when a pushed tag's
  commit carries ``RELEASE_NOTES.md`` at its root, the
  file becomes the release — its first ``# Heading``
  line is the title when it has one (else the tag is),
  and the remaining text is the notes. A tag whose tree
  carries no notes file creates nothing and is refused
  by name (`notes_file_missing`): a release is never
  invented from a bare tag. A repeated push of the same
  tag returns the standing release instead of failing,
  so push retries are safe; the web and API doors
  refuse a second release for one tag
  (`release_taken`), because a person asking twice
  should be told.

Further laws:

- **The tag must stand.** Creation resolves
  ``refs/tags/<tag>`` in the bare repository; a tag
  that does not stand is refused `tag_not_found`
  before any row is written. The stored target is the
  commit the tag points at (an annotated tag's peeled
  commit), never the tag object itself.
- **Permissions ride the repository's (S-054).**
  Creating, editing and deleting are writer acts;
  reading follows read access, and a stranger to a
  private repository gets the uniform `repo_not_found`.
- **Notes are Markdown, rendered through the one
  pipeline.** The row stores the Markdown source;
  `render_release` renders it through S-108's
  sanitised pipeline, and every other field rides
  S-010 escaping.
- **States (S-258).** A release is *published* the
  moment it is created unless it is created as a
  **draft** (``draft=True``) or marked a
  **prerelease** (``prerelease=True``) — two
  independent flags on the row (migration 101), so a
  draft may also carry the prerelease mark it will
  wear once published. The flags ride every door:
  ``create_release`` keywords on the web door and
  ``draft`` / ``prerelease`` keys on the API door
  (any other unknown key is still refused by name);
  the tag-push door always creates published, never
  a draft — a pushed tag is a public act. The pure
  ``release_state`` names the standing state
  (``draft`` wins over ``prerelease``: an unpublished
  prerelease is a draft first).
- **Drafts are private to writers.** A draft is
  visible only to a viewer who can write the
  repository (S-054's ``can_write`` — the owner,
  site admins, write collaborators): ``list_releases``
  omits drafts for everyone else, and ``get_release``
  answers the uniform ``release_not_found`` for a
  draft the viewer may not see, so a draft's
  existence is itself private — the private-repo
  anti-enumeration law applied one level down. A
  draft is not a publication: creating one witnesses
  nothing. ``publish_release`` (writer only) clears
  the draft flag and is the moment of publication;
  publishing a release that is not a draft is refused
  ``release_not_draft``, because a person asking
  twice should be told. The prerelease flag may be
  set or cleared later through ``update_release``;
  the draft flag moves only through creation and
  ``publish_release``, never sideways through an edit.
- **Prereleases are marked in every listing, in
  text.** Every face carries the word: the API shape
  (``release_to_dict``) gains ``draft``,
  ``prerelease`` and ``state``; the rendered release
  and the releases page carry a plain-text
  ``Draft`` / ``Pre-release`` marker (words, never
  colour alone). A published release carries no
  marker — the absence is the ordinary case.
  Assets are S-259 (samverk/release_assets.py);
  the latest pointer
  with S-261. Publication is witnessed on the
  standing verb `repo.release.publish` with detail
  ``{"tag": ...}`` (named in the taxonomy since its
  founding and in S-247's webhook taxonomy as the one
  releases-category event) — no new taxonomy event:
  131 stand (33 auth / 85 repo / 13 admin).
  Edits and deletions carry no verb of their own in
  the frozen vocabulary and are not witnessed.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .markdown_pipeline import render_markdown
from .objects import ObjectError, ObjectReader
from .permissions import can_read, can_write
from .refs import RefError, RefStore, tag_ref, validate_ref_name
from .repositories import Repository, RepositoryStore

TITLE_MAX = 200
NOTES_MAX = 65536
NOTES_FILE = "RELEASE_NOTES.md"
SOURCES = ("web", "api", "tag_push")
SOURCE_WORDS = {
    "web": "created from the web",
    "api": "created from the API",
    "tag_push": "created from a tag push",
}
_API_KEYS = frozenset({"tag", "title", "notes", "draft", "prerelease"})
STATE_WORDS = {
    "draft": "Draft",
    "prerelease": "Pre-release",
    "published": "Published",
}

__all__ = [
    "NOTES_FILE", "NOTES_MAX", "SOURCES", "SOURCE_WORDS",
    "STATE_WORDS", "TITLE_MAX", "Release", "ReleaseError",
    "ReleaseStore", "parse_notes_file", "release_state",
    "release_to_dict", "render_release", "render_releases_page",
    "state_markers", "validate_notes", "validate_source",
    "validate_state_flag", "validate_tag", "validate_title",
]


class ReleaseError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class Release:
    id: int
    repo_id: int
    tag: str
    title: str
    notes: str
    target_oid: str
    author_id: int
    source: str
    created_at: int
    updated_at: int
    draft: bool = False
    prerelease: bool = False


def _row_to_release(row: sqlite3.Row) -> Release:
    return Release(
        id=row["id"], repo_id=row["repo_id"], tag=row["tag"],
        title=row["title"], notes=row["notes"],
        target_oid=row["target_oid"], author_id=row["author_id"],
        source=row["source"], created_at=row["created_at"],
        updated_at=row["updated_at"],
        draft=bool(row["draft"]) if "draft" in row.keys() else False,
        prerelease=(bool(row["prerelease"])
                    if "prerelease" in row.keys() else False))


def validate_tag(tag: object) -> str:
    try:
        return validate_ref_name(tag)
    except RefError:
        raise ReleaseError(
            "tag_invalid", f"Not a tag name: {tag!r}") from None


def validate_title(title: object) -> str:
    if not isinstance(title, str) or not title.strip():
        raise ReleaseError(
            "release_title_required", "A release needs a title.")
    text = title.strip()
    if len(text) > TITLE_MAX or any(
            ord(c) < 0x20 or ord(c) == 0x7F for c in text):
        raise ReleaseError(
            "release_title_invalid",
            f"Release titles are at most {TITLE_MAX} characters "
            "of plain text.")
    return text


def validate_notes(notes: object) -> str:
    if notes is None:
        return ""
    if not isinstance(notes, str):
        raise ReleaseError(
            "notes_invalid", "Release notes must be Markdown text.")
    if len(notes) > NOTES_MAX:
        raise ReleaseError(
            "notes_invalid",
            f"Release notes are at most {NOTES_MAX} characters.")
    return notes


def validate_state_flag(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ReleaseError(
            "state_flag_invalid",
            f"The {field} state of a release is true or false.")
    return value


def release_state(release: Release) -> str:
    """The standing state's name: a draft first (an
    unpublished prerelease is a draft before it is
    anything else), then prerelease, then published."""
    if release.draft:
        return "draft"
    if release.prerelease:
        return "prerelease"
    return "published"


def state_markers(release: Release) -> list[str]:
    """The plain-text marks a listing must carry for
    this release: Draft and/or Pre-release, in words.
    A published, non-prerelease release carries none."""
    marks = []
    if release.draft:
        marks.append(STATE_WORDS["draft"])
    if release.prerelease:
        marks.append(STATE_WORDS["prerelease"])
    return marks


def validate_source(source: object) -> str:
    if source not in SOURCES:
        raise ReleaseError(
            "source_invalid",
            "A release is created from the web, the API, "
            "or a tag push.")
    return str(source)


def parse_notes_file(text: str) -> tuple[str | None, str]:
    """Split a notes file into (title, notes): the first
    ``# Heading`` line is the title when one leads the
    file; the rest of the file is the notes. No heading
    means no title and the whole file is the notes."""
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            rest = "\n".join(lines[idx + 1:]).strip("\n")
            return (title or None), rest
        return None, text.strip("\n")
    return None, ""


def release_to_dict(release: Release, full_name: str = "") -> dict:
    """One release as the API answers it."""
    return {
        "repository": full_name,
        "tag": release.tag,
        "title": release.title,
        "notes": release.notes,
        "target_oid": release.target_oid,
        "author_id": release.author_id,
        "source": release.source,
        "created_at": release.created_at,
        "updated_at": release.updated_at,
        "draft": release.draft,
        "prerelease": release.prerelease,
        "state": release_state(release),
    }


def render_release(release: Release, full_name: str = "") -> str:
    """One release as HTML: title and tag escaped, the
    notes through the sanitised Markdown pipeline, and
    the S-258 state carried as plain-text markers
    (words, never colour alone)."""
    repo_line = (
        f"<p>{escape_html_text(full_name)}</p>" if full_name else "")
    marks = "".join(
        ' &middot; <span class="release-state">'
        + escape_html_text(word) + "</span>"
        for word in state_markers(release))
    return (
        '<section class="release"><h3>'
        + escape_html_text(release.title) + "</h3>"
        + repo_line
        + "<p>Tag " + escape_html_text(release.tag)
        + " &middot; commit "
        + escape_html_text(release.target_oid[:12])
        + " &middot; "
        + escape_html_text(SOURCE_WORDS[release.source])
        + marks
        + "</p><div class=\"release-notes\">"
        + render_markdown(release.notes)
        + "</div></section>")


def render_releases_page(full_name: str,
                         releases: list[Release]) -> str:
    """The releases listing for one repository."""
    if not releases:
        body = "<p>No releases yet.</p>"
    else:
        body = "".join(
            render_release(r, full_name) for r in releases)
    return (
        '<section class="releases"><h2>Releases of '
        + escape_html_text(full_name) + "</h2>" + body
        + "</section>")


class ReleaseStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore | None = None,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._audit = audit
        self._now = time_fn

    def _repo_for_read(self, viewer: User | None, owner: object,
                       repo: object) -> Repository:
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise ReleaseError(
                "repo_not_found", "No such repository.")
        return current

    def _repo_for_write(self, actor: User, owner: object,
                        repo: object) -> Repository:
        current = self._repo_for_read(actor, owner, repo)
        if not can_write(actor, current):
            raise ReleaseError(
                "permission_denied",
                "Only a repository writer can manage releases.")
        return current

    def _visible(self, viewer: User | None,
                 current: Repository, release: Release) -> bool:
        """S-258: a published release is visible to every
        reader; a draft only to a repository writer."""
        if not release.draft:
            return True
        return viewer is not None and can_write(viewer, current)

    def _tag_target(self, current: Repository, tag: str) -> str:
        repo_path = self._repos.path_for(current.owner, current.name)
        refs = RefStore(repo_path)
        full = tag_ref(tag)
        found = next(
            (r for r in refs.list_tags() if r.name == full), None)
        if found is None:
            raise ReleaseError(
                "tag_not_found",
                f"No tag named {tag!r} stands in this repository.")
        if found.peeled_oid:
            return found.peeled_oid
        if found.type == "tag":
            # An annotated tag with no peeled id in the
            # listing: the tag object's own header names
            # the commit it points at.
            try:
                obj = ObjectReader(repo_path).read_object(found.oid)
            except ObjectError as exc:
                raise ReleaseError(exc.reason, str(exc)) from None
            for line in obj.data.decode(
                    "utf-8", "replace").splitlines():
                if line.startswith("object "):
                    return line[7:].strip()
        return found.oid

    def _notes_file_at(self, current: Repository,
                       commit_oid: str) -> str | None:
        repo_path = self._repos.path_for(current.owner, current.name)
        reader = ObjectReader(repo_path)
        try:
            commit = reader.read_commit(commit_oid)
            stack: list[tuple[str, str]] = [("", commit.tree)]
            found_oid: str | None = None
            while stack:
                prefix, tree_oid = stack.pop()
                for entry in reader.read_tree(tree_oid):
                    path = f"{prefix}{entry.name}"
                    if entry.type == "tree":
                        stack.append((path + "/", entry.oid))
                    elif path == NOTES_FILE:
                        found_oid = entry.oid
            if found_oid is None:
                return None
            raw = reader.read_blob(found_oid)
        except ObjectError as exc:
            raise ReleaseError(exc.reason, str(exc)) from None
        return raw.decode("utf-8", "replace")

    def create_release(self, actor: User, owner: object,
                       repo: object, tag: object,
                       title: object, notes: object = "",
                       *, source: object = "web",
                       draft: object = False,
                       prerelease: object = False,
                       source_ip: str | None = None) -> Release:
        current = self._repo_for_write(actor, owner, repo)
        tag_text = validate_tag(tag)
        title_text = validate_title(title)
        notes_text = validate_notes(notes)
        source_text = validate_source(source)
        draft_flag = validate_state_flag(draft, "draft")
        prerelease_flag = validate_state_flag(
            prerelease, "prerelease")
        target = self._tag_target(current, tag_text)
        now = int(self._now())
        with self._conn:
            try:
                cur = self._conn.execute(
                    "INSERT INTO releases (repo_id, tag, title,"
                    " notes, target_oid, author_id, source,"
                    " created_at, updated_at, draft, prerelease)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (current.id, tag_text, title_text, notes_text,
                     target, actor.id, source_text, now, now,
                     int(draft_flag), int(prerelease_flag)))
            except sqlite3.IntegrityError:
                raise ReleaseError(
                    "release_taken",
                    f"A release for tag {tag_text!r} already "
                    "exists in this repository.") from None
        release = self._by_id(int(cur.lastrowid))
        assert release is not None
        if not release.draft:
            self._emit(actor, current, release, source_ip)
        return release

    def create_release_from_api(self, actor: User, owner: object,
                                repo: object, payload: object,
                                *, source_ip: str | None = None
                                ) -> Release:
        if not isinstance(payload, dict):
            raise ReleaseError(
                "payload_invalid", "A release payload is an object.")
        unknown = sorted(set(payload) - _API_KEYS)
        if unknown:
            raise ReleaseError(
                "payload_unknown_field",
                f"Unknown release field: {unknown[0]!r}.")
        return self.create_release(
            actor, owner, repo, payload.get("tag"),
            payload.get("title"), payload.get("notes", ""),
            source="api", draft=payload.get("draft", False),
            prerelease=payload.get("prerelease", False),
            source_ip=source_ip)

    def create_release_from_tag_push(
            self, actor: User, owner: object, repo: object,
            tag: object, *, source_ip: str | None = None) -> Release:
        current = self._repo_for_write(actor, owner, repo)
        tag_text = validate_tag(tag)
        existing = self._by_tag(current.id, tag_text)
        if existing is not None:
            return existing
        target = self._tag_target(current, tag_text)
        text = self._notes_file_at(current, target)
        if text is None:
            raise ReleaseError(
                "notes_file_missing",
                f"Tag {tag_text!r} carries no {NOTES_FILE}; "
                "no release is created from a bare tag.")
        title, notes = parse_notes_file(text)
        return self.create_release(
            actor, owner, repo, tag_text,
            title if title else tag_text, notes,
            source="tag_push", source_ip=source_ip)

    def get_release(self, viewer: User | None, owner: object,
                    repo: object, tag: object) -> Release:
        current = self._repo_for_read(viewer, owner, repo)
        release = self._by_tag(current.id, tag)
        if release is None or not self._visible(
                viewer, current, release):
            raise ReleaseError(
                "release_not_found", "No such release.")
        return release

    def list_releases(self, viewer: User | None, owner: object,
                      repo: object) -> list[Release]:
        current = self._repo_for_read(viewer, owner, repo)
        rows = self._conn.execute(
            "SELECT * FROM releases WHERE repo_id = ?"
            " ORDER BY created_at DESC, id DESC",
            (current.id,)).fetchall()
        return [release for release in
                (_row_to_release(r) for r in rows)
                if self._visible(viewer, current, release)]

    def update_release(self, actor: User, owner: object,
                       repo: object, tag: object, *,
                       title: object = None,
                       notes: object = None,
                       prerelease: object = None) -> Release:
        current = self._repo_for_write(actor, owner, repo)
        release = self._by_tag(current.id, tag)
        if release is None:
            raise ReleaseError(
                "release_not_found", "No such release.")
        title_text = (release.title if title is None
                      else validate_title(title))
        notes_text = (release.notes if notes is None
                      else validate_notes(notes))
        prerelease_flag = (release.prerelease if prerelease is None
                           else validate_state_flag(
                               prerelease, "prerelease"))
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "UPDATE releases SET title = ?, notes = ?,"
                " prerelease = ?, updated_at = ? WHERE id = ?",
                (title_text, notes_text, int(prerelease_flag),
                 now, release.id))
        updated = self._by_id(release.id)
        assert updated is not None
        return updated

    def publish_release(self, actor: User, owner: object,
                        repo: object, tag: object, *,
                        source_ip: str | None = None) -> Release:
        """Publish a draft: clears the draft flag (the
        prerelease mark, if any, is kept) and witnesses
        the publication on the standing verb. A release
        that is not a draft is refused release_not_draft."""
        current = self._repo_for_write(actor, owner, repo)
        release = self._by_tag(current.id, tag)
        if release is None:
            raise ReleaseError(
                "release_not_found", "No such release.")
        if not release.draft:
            raise ReleaseError(
                "release_not_draft",
                f"Release {release.tag!r} is not a draft.")
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "UPDATE releases SET draft = 0, updated_at = ?"
                " WHERE id = ?", (now, release.id))
        published = self._by_id(release.id)
        assert published is not None
        self._emit(actor, current, published, source_ip)
        return published

    def delete_release(self, actor: User, owner: object,
                       repo: object, tag: object) -> Release:
        current = self._repo_for_write(actor, owner, repo)
        release = self._by_tag(current.id, tag)
        if release is None:
            raise ReleaseError(
                "release_not_found", "No such release.")
        with self._conn:
            self._conn.execute(
                "DELETE FROM releases WHERE id = ?", (release.id,))
        return release

    def _by_id(self, release_id: int) -> Release | None:
        row = self._conn.execute(
            "SELECT * FROM releases WHERE id = ?",
            (release_id,)).fetchone()
        return _row_to_release(row) if row else None

    def _by_tag(self, repo_id: int, tag: object) -> Release | None:
        if not isinstance(tag, str) or not tag.strip():
            return None
        row = self._conn.execute(
            "SELECT * FROM releases WHERE repo_id = ? AND tag = ?",
            (repo_id, tag.strip())).fetchone()
        return _row_to_release(row) if row else None

    def _emit(self, actor: User, current: Repository,
              release: Release, source_ip: str | None) -> None:
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="repo.release.publish",
                target_kind="repo", target_id=current.full_name,
                outcome="success", source_ip=source_ip,
                detail={"tag": release.tag})
