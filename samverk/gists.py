"""Gist model (S-277).

A gist is a **mini-repository**: multiple files, full
revision history, one description. This slice is the
model -- where a gist lives, what it holds, and
the primitives every later gist slice stands on.
S-278 adds the public/secret visibility choice
below and the web editor face in
``samverk/gist_web.py``. Fork and star are S-279
(this file, below); comments are S-280 (in
``samverk/gist_comments.py``, over this store);
embedding is S-281 (in ``samverk/gist_embed.py``,
over this store).

The laws:

- **Its own bare git repository.** Each gist stands
  alone as ``<data_root>/gists/<owner>/<id>.git``
  (the S-013 layout shape, one directory over from
  ``repos/``), created by ``git init --bare`` when
  the gist is created. Files are the repository's
  tree, edits are commits, and the revision history
  is the repository's own ``git log`` -- real git
  history underneath, exactly as a wiki's is (S-273).
  A gist is stock-git cloneable from the day it is
  born. The numeric id in the path comes from the
  metadata row, never from user text, so no name a
  user chooses ever meets the filesystem.
- **One row, one description.** Migration 108's
  ``gists`` table holds the metadata git cannot:
  the owner, the **one description** (a gist has
  exactly one; editing it is a metadata act and
  moves no revision), and the creation/update
  stamps. The files and their history live only in
  git, never duplicated into tables.
- **Multiple files, one filename law.** A gist
  holds at least one file and at most ``FILES_MAX``;
  every file is flat at the gist root (no
  directories, ever), named under one law --
  separators, ``..``, control characters, a leading
  dot and a trailing dot are refused
  (``filename_invalid``) -- and file identity is
  the name judged case-insensitively, so two files
  that differ only in case are refused
  (``file_duplicate``) instead of planting twins.
  File bodies are text, capped at ``FILE_MAX``
  bytes encoded as UTF-8 (``file_too_large``;
  non-text is ``file_invalid``).
- **Revisions are commits, written whole.** Every
  file-set change is one plumbing commit
  (``hash-object`` / ``mktree`` / ``commit-tree`` /
  ``update-ref`` under S-014, the S-064 road, as in
  S-273): the new tree is the standing tree with the
  caller's full file set, the commit's parent is
  the old tip, and ``update-ref`` names that old
  tip, so a tip that moved under the writer refuses
  instead of being silently overwritten. A writer
  may pass ``expected_oid``; if the tip has moved
  since, the write is refused ``gist_conflict`` and
  nothing is stored. An update names the **full**
  standing file set: a file absent from the set is
  removed by that commit, plainly, in the open.
- **The owner writes; visibility is the owner's
  choice (S-278).** Every gist is **public** or
  **secret**, chosen at creation and changeable by
  the owner as a metadata act (no revision). The
  words are honest: a *public* gist is listed for
  everyone and readable by anyone, signed in or
  not. A *secret* gist is **unlisted but linkable
  -- it is not private**: it appears in no listing
  but the owner's own, yet anyone who has the link
  (the gist's id) can read it in full, signed in or
  not, and the editor says exactly that wherever
  the choice is offered (``samverk/gist_web.py``).
  There is no third, private reading in this slice,
  and none is implied. Gists that stood before the
  choice existed (migration 109) default to
  ``secret`` -- the narrower widening, never
  silently made public. Only the owner (or a site
  admin) writes or deletes, whatever the
  visibility; any other signed-in user is refused
  ``permission_denied`` at the write doors, and an
  unknown gist id is the uniform ``gist_not_found``
  for every viewer.

- **Fork copies history (S-279).** Forking is a
  server-side bare clone through S-014's
  local-paths-only seam (``run_git_clone_local``,
  the S-055 road): the fork is a new gist owned by
  the forker, standing in its own bare repository
  with its own complete object store, so its full
  revision history -- the same commits, the same
  tip -- survives the source being edited or even
  deleted. The description is copied; the
  visibility is inherited unless the forker names
  the other choice at the fork (both are readable
  by link, so neither direction escalates anything:
  a secret gist is unlisted, never private).
  Migration 110's ``fork_of_id`` column records the
  direct source as lineage only, exactly as S-055's
  does for repositories; a fork of a fork points at
  its direct source. Forking needs a signed-in
  account (``permission_denied``, as creating does)
  and read reach, which S-278's law grants by link
  for both visibilities; an unknown id is the
  uniform ``gist_not_found``.
- **Stars work as S-222 (S-279).** A star is a
  stored row in migration 110's ``gist_stars``
  table; counts are ``COUNT(*)`` over those rows at
  read time, never a cached counter. Re-starring
  and un-starring what was never starred are quiet
  no-ops; un-starring removes only the actor's own
  row. Starring is a reader act: it needs a
  signed-in account (``login_required``, S-222's
  refusal), any signed-in reader who can reach the
  gist by its link may star it -- a secret gist
  included -- and an unknown id is the uniform
  ``gist_not_found``. Anonymous visitors read the
  counts but hold no star. Starred-gist and fork
  listings follow S-278's listing law: a secret
  gist is listed only for its owner (or an admin,
  or the holder of the star list itself).

Gist acts carry no verb of their own in the frozen
taxonomy vocabulary and are not witnessed -- no new
taxonomy event: 133 stand (33 auth / 87 repo /
13 admin). Storage is migration 108's ``gists``
table plus migration 109's ``visibility`` column
and migration 110's ``fork_of_id`` column and
``gist_stars`` table, plus migration 111's
``gist_comments`` / ``gist_comment_edits`` tables
(schema 108 -> 111); the files stay git storage,
not tables. Embedding (S-281) stores nothing of
its own and changes no schema: the schema stands
at 111.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .platform_seam import ensure_dir
from .proc import run_git, run_git_clone_local, run_git_in

FILE_MAX = 1_048_576
FILES_MAX = 100
FILENAME_MAX = 120
DESCRIPTION_MAX = 1_000
MESSAGE_MAX = 1_000
DEFAULT_BRANCH = "main"
VISIBILITY_PUBLIC = "public"
VISIBILITY_SECRET = "secret"
VISIBILITIES = (VISIBILITY_PUBLIC, VISIBILITY_SECRET)
# The honest words for the choice, stated once here
# and carried by every face that offers or reports
# it (S-278): a secret gist is NOT private.
PUBLIC_WORDS = (
    "Public — anyone can find and read this gist.")
SECRET_WORDS = (
    "Secret — unlisted, but not private: anyone who "
    "has the link can read this gist. Do not put "
    "anything in it that must stay private.")

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

__all__ = [
    "DEFAULT_BRANCH", "DESCRIPTION_MAX", "FILES_MAX",
    "FILE_MAX", "FILENAME_MAX", "MESSAGE_MAX",
    "PUBLIC_WORDS", "SECRET_WORDS", "VISIBILITIES",
    "VISIBILITY_PUBLIC", "VISIBILITY_SECRET",
    "Gist", "GistError", "GistFile", "GistRevision",
    "GistStarSummary", "GistStore", "decide_star",
    "gist_to_dict", "render_gist", "render_gist_fork_star",
    "render_gist_list", "validate_description",
    "validate_filename", "validate_files",
    "validate_visibility", "visibility_words",
]


class GistError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class Gist:
    id: int
    owner: str           # owner's username (display case)
    owner_id: int
    description: str     # the gist's one description
    visibility: str      # 'public' or 'secret' (S-278)
    created_at: int
    updated_at: int
    fork_of_id: int | None = None  # direct source (S-279)
    head_oid: str | None = None    # standing tip commit, if any
    revision_count: int = 0        # commits in the history


@dataclass(frozen=True)
class GistFile:
    name: str          # flat file name, extension kept
    size: int          # body size in bytes
    blob_oid: str      # git blob of the standing body
    commit_oid: str    # commit the body was read at
    content: str = ""  # body text (read answers only)


@dataclass(frozen=True)
class GistStarSummary:
    gist_id: int
    owner: str            # the gist owner's username
    star_count: int       # live COUNT(*) over gist_stars
    fork_count: int       # live COUNT(*) over fork_of_id
    my_starred: bool      # the viewer's own star


def decide_star(starred: bool, want: bool) -> bool:
    """Pure (S-222's law): True when moving to *want*
    changes the stored star state."""
    return starred != want


@dataclass(frozen=True)
class GistRevision:
    oid: str
    parent_oid: str | None
    author: str        # committing username
    message: str       # commit subject line
    created_at: int    # author timestamp from git


def validate_description(description: object) -> str:
    """The one description, judged: text, at most
    DESCRIPTION_MAX characters (an empty description
    is honest -- a gist may say nothing about itself)."""
    if not isinstance(description, str):
        raise GistError(
            "description_invalid", "A gist description is text.")
    if len(description) > DESCRIPTION_MAX or "\x00" in description:
        raise GistError(
            "description_invalid",
            f"A gist description is at most {DESCRIPTION_MAX} "
            "characters of plain text.")
    return description


def validate_visibility(visibility: object) -> str:
    """The S-278 choice, judged: exactly 'public' or
    'secret' -- no third reading exists or is implied."""
    if visibility not in VISIBILITIES:
        raise GistError(
            "visibility_invalid",
            "A gist is public or secret; there is no "
            "other visibility.")
    return str(visibility)


def visibility_words(visibility: str) -> str:
    """The honest words for one standing visibility."""
    return (PUBLIC_WORDS if visibility == VISIBILITY_PUBLIC
            else SECRET_WORDS)


def validate_filename(filename: object) -> str:
    """The one filename law (module docstring): return
    the standing file name for *filename*, or raise
    GistError(``filename_invalid``). Unlike a wiki page
    a gist file keeps its name whole -- extensions are
    part of a file's name, nothing is canonicalised."""
    if not isinstance(filename, str):
        raise GistError(
            "filename_invalid", "A gist file name is text.")
    name = filename.strip()
    if (not name or len(name) > FILENAME_MAX
            or any(ord(c) < 0x20 or ord(c) == 0x7F for c in name)
            or "/" in name or "\\" in name or ".." in name
            or name.startswith(".") or name.endswith(".")
            or not _NAME_RE.match(name)):
        raise GistError(
            "filename_invalid",
            f"That file name is not valid: {filename!r}. A gist "
            "file name is one flat name: letters, digits, "
            "hyphens, underscores and single dots.")
    return name


def validate_files(files: object) -> list[tuple[str, bytes]]:
    """A gist's file set, judged whole: a mapping of
    file name to text body, at least one file and at
    most FILES_MAX, names under the one law and unique
    case-insensitively, bodies text under FILE_MAX.
    Returns (name, utf-8 bytes) pairs in name order."""
    if not isinstance(files, dict) or not files:
        raise GistError(
            "files_empty", "A gist holds at least one file.")
    if len(files) > FILES_MAX:
        raise GistError(
            "files_too_many",
            f"A gist holds at most {FILES_MAX} files.")
    seen: set[str] = set()
    out: list[tuple[str, bytes]] = []
    for raw_name, body in files.items():
        name = validate_filename(raw_name)
        key = name.lower()
        if key in seen:
            raise GistError(
                "file_duplicate",
                f"Two gist files share the name {name!r} "
                "(file names are judged case-insensitively).")
        seen.add(key)
        if not isinstance(body, str):
            raise GistError(
                "file_invalid", "A gist file body is text.")
        raw = body.encode("utf-8")
        if len(raw) > FILE_MAX:
            raise GistError(
                "file_too_large",
                f"A gist file is at most {FILE_MAX} bytes of text.")
        out.append((name, raw))
    out.sort(key=lambda pair: pair[0].lower())
    return out


def _validate_message(message: object, fallback: str) -> str:
    if message is None:
        return fallback
    if not isinstance(message, str) or not message.strip():
        raise GistError(
            "message_invalid", "A gist commit message is plain text.")
    text = message.strip()
    if len(text) > MESSAGE_MAX or "\x00" in text:
        raise GistError(
            "message_invalid",
            f"A gist commit message is at most {MESSAGE_MAX} "
            "characters of plain text.")
    return text


def gist_to_dict(gist: Gist,
                 files: list[GistFile] | None = None) -> dict:
    out: dict = {
        "id": gist.id,
        "owner": gist.owner,
        "description": gist.description,
        "visibility": gist.visibility,
        "created_at": gist.created_at,
        "updated_at": gist.updated_at,
        "head_oid": gist.head_oid,
        "revision_count": gist.revision_count,
        "fork_of_id": gist.fork_of_id,
    }
    if files is not None:
        out["files"] = [
            {"name": f.name, "size": f.size,
             "blob_oid": f.blob_oid, "commit_oid": f.commit_oid}
            for f in files]
    return out


def render_gist(gist: Gist, files: list[GistFile]) -> str:
    """The model face in words (S-010-escaped): the one
    description, the file list, and the revision count
    stated as a number. The web editor is S-278."""
    desc = escape_html_text(gist.description)
    fork = (f'<p class="gist-fork">Forked from gist '
            f'{gist.fork_of_id}</p>'
            if gist.fork_of_id is not None else '')
    words = escape_html_text(visibility_words(gist.visibility))
    items = "".join(
        f'<li data-file="{escape_html_text(f.name)}">'
        f"{escape_html_text(f.name)} ({f.size} bytes)</li>"
        for f in files)
    return (
        f'<section class="gist" data-gist="{gist.id}">'
        f"<h2>Gist {gist.id}</h2>"
        f'<p class="gist-description">{desc}</p>{fork}'
        f'<p class="gist-visibility">{words}</p>'
        f"<ul>{items}</ul>"
        f'<p class="gist-revisions">{gist.revision_count} '
        f"revision(s)</p></section>")


def render_gist_fork_star(summary: GistStarSummary) -> str:
    """The fork/star panel in words (S-222's shape):
    the live counts, and the viewer's own star state
    named plainly -- meaning never rides on an icon
    or a colour alone. Every value passes S-010."""
    star_word = ("starred by you" if summary.my_starred
                 else "not starred by you")
    return "\n".join([
        '<section class="gist-fork-star">',
        f"<p>Stars: {summary.star_count} - "
        f"{escape_html_text(star_word)}</p>",
        f"<p>Forks: {summary.fork_count}</p>",
        "</section>",
    ])


def render_gist_list(gists: list[Gist]) -> str:
    """An owner's gists in words (S-010-escaped), or the
    honest empty state."""
    if not gists:
        return (
            '<section class="gist-list"><h2>Gists</h2>'
            "<p>No gists yet. A gist is a mini-repository: "
            "multiple files, full revision history, one "
            "description.</p></section>")
    items = "".join(
        f'<li data-gist="{g.id}">'
        f"{escape_html_text(g.description)} "
        f"[{escape_html_text(g.visibility)}] "
        f"({g.revision_count} revision(s))</li>"
        for g in gists)
    return (
        '<section class="gist-list"><h2>Gists</h2>'
        f"<ul>{items}</ul></section>")


class GistStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        data_root: Path,
        accounts: AccountStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._data_root = Path(data_root)
        self._accounts = accounts
        self._audit = audit
        self._now = time_fn

    # -- paths ------------------------------------------------

    def _path_for(self, owner_lower: str, gist_id: int) -> Path:
        return (self._data_root / "gists" / owner_lower
                / f"{gist_id}.git")

    def gist_path(self, gist_id: object) -> Path:
        """The resolved bare-repository path for a gist id
        (its owner's directory, the numeric id). A gist
        that does not stand answers gist_not_found. This
        never creates anything."""
        row = self._row(gist_id)
        if row is None:
            raise GistError("gist_not_found", "No such gist.")
        return self._path_for(row["owner_lower"], row["id"])

    # -- rows / gates ------------------------------------------

    def _row(self, gist_id: object) -> sqlite3.Row | None:
        if not isinstance(gist_id, int) or isinstance(gist_id, bool):
            return None
        return self._conn.execute(
            "SELECT g.id AS id, g.owner_id AS owner_id,"
            " g.description AS description,"
            " g.visibility AS visibility,"
            " g.created_at AS created_at,"
            " g.updated_at AS updated_at,"
            " g.fork_of_id AS fork_of_id,"
            " u.username AS owner, u.username_lower AS owner_lower"
            " FROM gists g JOIN users u ON u.id = g.owner_id"
            " WHERE g.id = ?", (gist_id,)).fetchone()

    @staticmethod
    def _may_read(viewer: User | None, row: sqlite3.Row) -> bool:
        # S-278: a standing gist is readable by anyone
        # who reaches it by its id -- public gists are
        # listed for all, secret gists are unlisted but
        # linkable (NOT private; see SECRET_WORDS). The
        # listing gate lives in list_gists, not here.
        return row["visibility"] in VISIBILITIES

    def _gist_for_read(self, viewer: User | None,
                       gist_id: object) -> sqlite3.Row:
        row = self._row(gist_id)
        if row is None or not self._may_read(viewer, row):
            raise GistError("gist_not_found", "No such gist.")
        return row

    def _gist_for_write(self, actor: User | None,
                        gist_id: object) -> sqlite3.Row:
        if actor is None:
            raise GistError(
                "permission_denied",
                "Only a signed-in user can change a gist.")
        row = self._row(gist_id)
        if row is None:
            raise GistError("gist_not_found", "No such gist.")
        if not (actor.id == row["owner_id"] or actor.is_admin):
            raise GistError(
                "permission_denied",
                "Only the gist's owner can change this gist.")
        return row

    # -- git helpers --------------------------------------------

    @staticmethod
    def _is_bare(path: Path) -> bool:
        if not path.is_dir():
            return False
        probe = run_git_in(
            path, ["rev-parse", "--is-bare-repository"], timeout=15.0)
        return (probe.returncode == 0
                and probe.stdout.decode("utf-8", "replace").strip()
                == "true")

    def _tip(self, path: Path) -> str | None:
        head = run_git_in(
            path, ["rev-parse", "--verify", "--quiet",
                   f"refs/heads/{DEFAULT_BRANCH}"], timeout=15.0)
        if head.returncode != 0:
            return None
        return head.stdout.decode("utf-8", "replace").strip() or None

    def _entries(self, path: Path, at: str | None) -> list[str]:
        """The raw ls-tree lines at a commit (flat: a gist
        tree holds files only); empty for no commit."""
        if at is None:
            return []
        tree = run_git_in(path, ["ls-tree", at], timeout=15.0)
        if tree.returncode != 0:
            raise GistError(
                "gist_unreadable", "git could not read the gist tree.")
        return tree.stdout.decode(
            "utf-8", "surrogateescape").splitlines()

    def _view(self, row: sqlite3.Row) -> Gist:
        path = self._path_for(row["owner_lower"], row["id"])
        tip = self._tip(path) if self._is_bare(path) else None
        count = 0
        if tip is not None:
            log = run_git_in(
                path, ["rev-list", "--count", tip], timeout=15.0)
            if log.returncode == 0:
                count = int(log.stdout.decode().strip() or "0")
        return Gist(
            id=row["id"], owner=row["owner"],
            owner_id=row["owner_id"],
            description=row["description"],
            visibility=row["visibility"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            fork_of_id=row["fork_of_id"],
            head_oid=tip, revision_count=count)

    def _commit_files(self, path: Path, actor: User,
                      files: list[tuple[str, bytes]],
                      parent: str | None, message: str) -> str:
        entries: list[str] = []
        for name, raw in files:
            blob = run_git_in(
                path, ["hash-object", "-w", "--stdin"],
                input_bytes=raw, timeout=15.0)
            if blob.returncode != 0:
                raise GistError(
                    "gist_write_failed",
                    "git could not store a gist file.")
            entries.append(
                f"100644 blob {blob.stdout.decode().strip()}\t{name}")
        entries.sort(key=lambda line: line.partition("\t")[2].lower())
        new_tree = run_git_in(
            path, ["mktree"],
            input_bytes=("\n".join(entries) + "\n").encode(
                "utf-8", "surrogateescape"), timeout=15.0)
        if new_tree.returncode != 0:
            raise GistError(
                "gist_write_failed", "git could not build the gist tree.")
        tree_oid = new_tree.stdout.decode().strip()
        env = {
            "GIT_AUTHOR_NAME": actor.username,
            "GIT_AUTHOR_EMAIL": f"{actor.username_lower}@samverk.invalid",
            "GIT_COMMITTER_NAME": actor.username,
            "GIT_COMMITTER_EMAIL":
                f"{actor.username_lower}@samverk.invalid",
        }
        args = ["commit-tree", tree_oid]
        if parent is not None:
            args += ["-p", parent]
        commit = run_git_in(
            path, args, input_bytes=message.encode("utf-8"),
            timeout=15.0, env_extra=env)
        if commit.returncode != 0:
            raise GistError(
                "gist_write_failed", "git could not commit the gist change.")
        commit_oid = commit.stdout.decode().strip()
        ref = f"refs/heads/{DEFAULT_BRANCH}"
        updated = run_git_in(
            path, ["update-ref", ref, commit_oid, parent or ""],
            timeout=15.0)
        if updated.returncode != 0:
            raise GistError(
                "gist_conflict",
                "The gist changed while it was being written; "
                "read the newest revision and write again.")
        return commit_oid

    # -- create -------------------------------------------------

    def create_gist(self, actor: User | None, description: object,
                    files: object, *, message: object = None,
                    visibility: object = VISIBILITY_PUBLIC) -> Gist:
        """Create a gist: its metadata row, its bare
        repository, and its first revision carrying the
        whole file set, as one act -- if git refuses,
        no row and no directory are left behind."""
        if actor is None:
            raise GistError(
                "permission_denied",
                "Only a signed-in user can create a gist.")
        text = validate_description(description)
        judged = validate_files(files)
        vis = validate_visibility(visibility)
        text_message = _validate_message(message, "Create gist")
        now = int(self._now())
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO gists (owner_id, description,"
                " visibility, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (actor.id, text, vis, now, now))
            gist_id = int(cur.lastrowid)
        path = self._path_for(actor.username_lower, gist_id)
        try:
            if path.exists():
                raise GistError(
                    "gist_path_exists",
                    "A directory already exists at that gist's "
                    "path; refusing to adopt it silently.")
            ensure_dir(path.parent)
            result = run_git(
                ["init", "--bare",
                 f"--initial-branch={DEFAULT_BRANCH}", str(path)],
                timeout=30.0)
            if result.returncode != 0:
                raise GistError(
                    "gist_init_failed",
                    "git could not create the gist repository: "
                    + result.stderr.decode(
                        "utf-8", "replace").strip()[:200])
            self._commit_files(path, actor, judged, None, text_message)
        except BaseException:
            with self._conn:
                self._conn.execute(
                    "DELETE FROM gists WHERE id = ?", (gist_id,))
            shutil.rmtree(path, ignore_errors=True)
            raise
        row = self._row(gist_id)
        assert row is not None
        return self._view(row)

    # -- reads ----------------------------------------------------

    def get_gist(self, viewer: User | None, gist_id: object) -> Gist:
        """One gist's standing view, by its id (the link):
        any viewer, signed in or not, for a public or a
        secret gist; an unknown id is the uniform
        gist_not_found."""
        return self._view(self._gist_for_read(viewer, gist_id))

    def list_gists(self, viewer: User | None,
                   owner: object) -> list[Gist]:
        """One owner's gists, newest-updated first, as
        *viewer* may see them listed (S-278): the owner
        (or a site admin) sees every gist, public and
        secret; everyone else -- a stranger or an
        anonymous visitor -- sees the public gists only.
        A secret gist is unlisted, never listed here for
        anyone but its owner, though it stays readable
        by its link. A misspelt owner names no user and
        answers the uniform gist_not_found."""
        if not isinstance(owner, str):
            raise GistError("gist_not_found", "No such gist.")
        known = self._conn.execute(
            "SELECT id FROM users WHERE username_lower = ?",
            (owner.lower(),)).fetchone()
        if known is None:
            raise GistError("gist_not_found", "No such gist.")
        own = (viewer is not None
               and (viewer.username_lower == owner.lower()
                    or viewer.is_admin))
        rows = self._conn.execute(
            "SELECT g.id AS id FROM gists g"
            " JOIN users u ON u.id = g.owner_id"
            " WHERE u.username_lower = ?"
            + ("" if own else
               " AND g.visibility = 'public'")
            + " ORDER BY g.updated_at DESC, g.id DESC",
            (owner.lower(),)).fetchall()
        return [self.get_gist(viewer, r["id"]) for r in rows]

    def _resolve_revision(self, path: Path, row: sqlite3.Row,
                          revision: object) -> str:
        tip = self._tip(path)
        if tip is None:
            raise GistError("gist_not_found", "No such gist.")
        if revision is None:
            return tip
        if not isinstance(revision, str):
            raise GistError(
                "revision_not_found", "No such gist revision.")
        probe = run_git_in(
            path, ["rev-parse", "--verify", "--quiet",
                   f"{revision}^{{commit}}"], timeout=15.0)
        if probe.returncode != 0:
            raise GistError(
                "revision_not_found", "No such gist revision.")
        oid = probe.stdout.decode().strip()
        inside = run_git_in(
            path, ["merge-base", "--is-ancestor", oid, tip],
            timeout=15.0)
        if inside.returncode != 0:
            raise GistError(
                "revision_not_found", "No such gist revision.")
        return oid

    def list_files(self, viewer: User | None, gist_id: object,
                   *, revision: object = None) -> list[GistFile]:
        """The standing file list, or the file list at one
        revision of the gist's own history."""
        row = self._gist_for_read(viewer, gist_id)
        path = self._path_for(row["owner_lower"], row["id"])
        at = self._resolve_revision(path, row, revision)
        out: list[GistFile] = []
        for line in self._entries(path, at):
            meta, _, filename = line.partition("\t")
            parts = meta.split()
            if len(parts) != 3 or parts[1] != "blob":
                continue
            size_probe = run_git_in(
                path, ["cat-file", "-s", parts[2]], timeout=15.0)
            size = (int(size_probe.stdout.decode().strip())
                    if size_probe.returncode == 0 else 0)
            out.append(GistFile(
                name=filename, size=size, blob_oid=parts[2],
                commit_oid=at))
        out.sort(key=lambda f: f.name.lower())
        return out

    def read_file(self, viewer: User | None, gist_id: object,
                  filename: object, *,
                  revision: object = None) -> GistFile:
        """One file's body, standing or at one revision.
        The name is judged under the one law and matched
        case-insensitively, as file identity is."""
        row = self._gist_for_read(viewer, gist_id)
        name = validate_filename(filename)
        path = self._path_for(row["owner_lower"], row["id"])
        at = self._resolve_revision(path, row, revision)
        found: tuple[str, str] | None = None
        for line in self._entries(path, at):
            meta, _, standing = line.partition("\t")
            if standing.lower() == name.lower():
                found = (standing, meta.split()[2])
                break
        if found is None:
            raise GistError("file_not_found", "No such gist file.")
        standing, blob_oid = found
        blob = run_git_in(
            path, ["cat-file", "blob", blob_oid], timeout=15.0)
        if blob.returncode != 0:
            raise GistError("file_not_found", "No such gist file.")
        try:
            content = blob.stdout.decode("utf-8")
        except UnicodeDecodeError:
            raise GistError(
                "file_unreadable",
                "That gist file is not readable text.") from None
        return GistFile(
            name=standing, size=len(blob.stdout), blob_oid=blob_oid,
            commit_oid=at, content=content)

    def list_revisions(self, viewer: User | None,
                       gist_id: object) -> list[GistRevision]:
        """The full revision history, newest first, read
        from the gist repository's own git log."""
        row = self._gist_for_read(viewer, gist_id)
        path = self._path_for(row["owner_lower"], row["id"])
        tip = self._tip(path) if self._is_bare(path) else None
        if tip is None:
            return []
        log = run_git_in(
            path, ["log", "--format=%H%x1f%P%x1f%an%x1f%at%x1f%s", tip],
            timeout=15.0)
        if log.returncode != 0:
            raise GistError(
                "gist_unreadable", "git could not read the gist log.")
        out: list[GistRevision] = []
        for line in log.stdout.decode(
                "utf-8", "replace").splitlines():
            parts = line.split("\x1f")
            if len(parts) != 5:
                continue
            parents = parts[1].split()
            out.append(GistRevision(
                oid=parts[0],
                parent_oid=parents[0] if parents else None,
                author=parts[2],
                message=parts[4],
                created_at=int(parts[3] or "0")))
        return out

    # -- writes ---------------------------------------------------

    def update_gist(self, actor: User | None, gist_id: object, *,
                    description: object = None,
                    files: object = None,
                    message: object = None,
                    expected_oid: object = None,
                    visibility: object = None) -> Gist:
        """Change a gist. A new description or a new
        visibility is a metadata act (no revision). A
        new file set is one new revision carrying
        exactly that set -- a file absent from the set
        is removed by the commit. Naming none of them
        is refused update_empty."""
        row = self._gist_for_write(actor, gist_id)
        assert actor is not None
        if (description is None and files is None
                and visibility is None):
            raise GistError(
                "update_empty",
                "An update names a description, a file set, "
                "a visibility, or a combination.")
        text = (validate_description(description)
                if description is not None else None)
        vis = (validate_visibility(visibility)
               if visibility is not None else None)
        judged = validate_files(files) if files is not None else None
        path = self._path_for(row["owner_lower"], row["id"])
        if not self._is_bare(path):
            raise GistError(
                "gist_unreadable",
                "That gist's repository does not stand on disk.")
        if judged is not None:
            tip = self._tip(path)
            if expected_oid is not None and tip != expected_oid:
                raise GistError(
                    "gist_conflict",
                    "The gist has changed since that version was "
                    "read; read the newest revision and write again.")
            text_message = _validate_message(message, "Update gist")
            self._commit_files(path, actor, judged, tip, text_message)
        now = int(self._now())
        with self._conn:
            if text is not None and vis is not None:
                self._conn.execute(
                    "UPDATE gists SET description = ?,"
                    " visibility = ?, updated_at = ?"
                    " WHERE id = ?", (text, vis, now, row["id"]))
            elif text is not None:
                self._conn.execute(
                    "UPDATE gists SET description = ?, updated_at = ?"
                    " WHERE id = ?", (text, now, row["id"]))
            elif vis is not None:
                self._conn.execute(
                    "UPDATE gists SET visibility = ?, updated_at = ?"
                    " WHERE id = ?", (vis, now, row["id"]))
            else:
                self._conn.execute(
                    "UPDATE gists SET updated_at = ? WHERE id = ?",
                    (now, row["id"]))
        fresh = self._row(row["id"])
        assert fresh is not None
        return self._view(fresh)

    def delete_gist(self, actor: User | None,
                    gist_id: object) -> Gist:
        """Remove a gist whole: its row and its repository.
        Returns the gist as it stood before removal."""
        row = self._gist_for_write(actor, gist_id)
        before = self._view(row)
        path = self._path_for(row["owner_lower"], row["id"])
        with self._conn:
            # S-280: the gist's conversation dies with
            # it -- edit history first, then comments.
            self._conn.execute(
                "DELETE FROM gist_comment_edits"
                " WHERE comment_id IN"
                " (SELECT id FROM gist_comments"
                " WHERE gist_id = ?)", (row["id"],))
            self._conn.execute(
                "DELETE FROM gist_comments WHERE gist_id = ?",
                (row["id"],))
            self._conn.execute(
                "DELETE FROM gist_stars WHERE gist_id = ?",
                (row["id"],))
            self._conn.execute(
                "DELETE FROM gists WHERE id = ?", (row["id"],))
        shutil.rmtree(path, ignore_errors=True)
        return before

    # -- fork (S-279) ------------------------------------

    def fork_gist(self, actor: User | None, gist_id: object,
                  *, visibility: object = None) -> Gist:
        """Fork a gist: a server-side bare clone of the
        source's repository (S-014's local seam, the
        S-055 road) under a new row owned by the
        forker, carrying the source's full revision
        history and its description. The visibility is
        inherited unless the forker names the other
        choice. If git refuses, no row and no
        directory are left behind."""
        if actor is None:
            raise GistError(
                "permission_denied",
                "Only a signed-in user can fork a gist.")
        row = self._gist_for_read(actor, gist_id)
        vis = (validate_visibility(visibility)
               if visibility is not None else row["visibility"])
        src_path = self._path_for(row["owner_lower"], row["id"])
        if not self._is_bare(src_path):
            raise GistError(
                "gist_unreadable",
                "That gist's repository does not stand on disk.")
        now = int(self._now())
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO gists (owner_id, description,"
                " visibility, created_at, updated_at, fork_of_id)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (actor.id, row["description"], vis, now, now,
                 row["id"]))
            new_id = int(cur.lastrowid)
        dest_path = self._path_for(actor.username_lower, new_id)
        try:
            if dest_path.exists():
                raise GistError(
                    "gist_path_exists",
                    "A directory already exists at that gist's "
                    "path; refusing to adopt it silently.")
            ensure_dir(dest_path.parent)
            result = run_git_clone_local(
                src_path, dest_path, timeout=120.0)
            if result.returncode != 0:
                raise GistError(
                    "gist_clone_failed",
                    "git could not clone the gist repository: "
                    + result.stderr.decode(
                        "utf-8", "replace").strip()[:200])
        except BaseException:
            with self._conn:
                self._conn.execute(
                    "DELETE FROM gists WHERE id = ?", (new_id,))
            shutil.rmtree(dest_path, ignore_errors=True)
            raise
        fresh = self._row(new_id)
        assert fresh is not None
        return self._view(fresh)

    def fork_count(self, gist_id: int) -> int:
        """Direct forks of a gist, counted live over
        the fork_of_id lineage rows."""
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM gists"
            " WHERE fork_of_id = ?", (gist_id,)).fetchone()
        return int(row["c"])

    def fork_source(self, viewer: User | None,
                    gist_id: object) -> Gist | None:
        """The gist this one was forked from (its direct
        source), or None for an original gist."""
        row = self._gist_for_read(viewer, gist_id)
        if row["fork_of_id"] is None:
            return None
        return self.get_gist(viewer, row["fork_of_id"])

    def list_forks(self, viewer: User | None,
                   gist_id: object) -> list[Gist]:
        """A gist's direct forks, oldest first, as
        *viewer* may see them listed (S-278's listing
        law: a secret fork is listed only for its
        owner or an admin)."""
        row = self._gist_for_read(viewer, gist_id)
        rows = self._conn.execute(
            "SELECT id FROM gists WHERE fork_of_id = ?"
            " ORDER BY id", (row["id"],)).fetchall()
        out: list[Gist] = []
        for r in rows:
            fork = self.get_gist(viewer, r["id"])
            if (fork.visibility == VISIBILITY_PUBLIC
                    or (viewer is not None
                        and (viewer.id == fork.owner_id
                             or viewer.is_admin))):
                out.append(fork)
        return out

    # -- star (S-279, as S-222) ---------------------------

    @staticmethod
    def _require_star_actor(actor: User | None) -> User:
        if actor is None:
            raise GistError(
                "login_required",
                "Starring needs a signed-in account.")
        return actor

    def _starred_row(self, gist_id: int, user_id: int) -> bool:
        row = self._conn.execute(
            "SELECT 1 AS x FROM gist_stars"
            " WHERE gist_id = ? AND user_id = ?",
            (gist_id, user_id)).fetchone()
        return row is not None

    def star(self, actor: User | None,
             gist_id: object) -> GistStarSummary:
        """Star the gist: one stored row. Re-starring
        is a quiet no-op (S-222's law)."""
        actor = self._require_star_actor(actor)
        row = self._gist_for_read(actor, gist_id)
        if decide_star(self._starred_row(row["id"], actor.id),
                       True):
            with self._conn:
                self._conn.execute(
                    "INSERT OR IGNORE INTO gist_stars"
                    " (gist_id, user_id, created_at)"
                    " VALUES (?, ?, ?)",
                    (row["id"], actor.id, int(self._now())))
        return self.star_summary(actor, gist_id)

    def unstar(self, actor: User | None,
               gist_id: object) -> GistStarSummary:
        """Take the actor's own star back. Un-starring
        what was never starred is a quiet no-op; no
        seam removes another account's star."""
        actor = self._require_star_actor(actor)
        row = self._gist_for_read(actor, gist_id)
        if decide_star(self._starred_row(row["id"], actor.id),
                       False):
            with self._conn:
                self._conn.execute(
                    "DELETE FROM gist_stars WHERE gist_id = ?"
                    " AND user_id = ?", (row["id"], actor.id))
        return self.star_summary(actor, gist_id)

    def is_starred(self, viewer: User | None,
                   gist_id: object) -> bool:
        row = self._gist_for_read(viewer, gist_id)
        if viewer is None:
            return False
        return self._starred_row(row["id"], viewer.id)

    def star_count(self, gist: Gist) -> int:
        """The star counter: counted star rows, at
        read time (S-222's seam shape)."""
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM gist_stars"
            " WHERE gist_id = ?", (gist.id,)).fetchone()
        return int(row["c"])

    def star_summary(self, viewer: User | None,
                     gist_id: object) -> GistStarSummary:
        row = self._gist_for_read(viewer, gist_id)
        gist = self._view(row)
        starred = (viewer is not None
                   and self._starred_row(row["id"], viewer.id))
        return GistStarSummary(
            gist_id=gist.id, owner=gist.owner,
            star_count=self.star_count(gist),
            fork_count=self.fork_count(gist.id),
            my_starred=starred)

    def list_starred_gists(self, viewer: User | None,
                           username: object) -> list[Gist]:
        """The gists *username* has starred, oldest star
        first, filtered to what this viewer may see
        listed (S-278's listing law): a secret gist
        shows only to its owner, an admin, or the
        holder of the list itself. An unknown username
        answers the uniform gist_not_found."""
        subject = (self._accounts.get_by_username(username)
                   if isinstance(username, str) else None)
        if subject is None:
            raise GistError("gist_not_found", "No such gist.")
        rows = self._conn.execute(
            "SELECT gist_id FROM gist_stars WHERE user_id = ?"
            " ORDER BY created_at, id", (subject.id,)).fetchall()
        out: list[Gist] = []
        for r in rows:
            gist = self.get_gist(viewer, int(r["gist_id"]))
            if (gist.visibility == VISIBILITY_PUBLIC
                    or (viewer is not None
                        and (viewer.id == gist.owner_id
                             or viewer.is_admin
                             or viewer.id == subject.id))):
                out.append(gist)
        return out
