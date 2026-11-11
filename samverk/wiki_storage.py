"""Wiki storage (S-273).

Each repository's wiki is **its own bare git
repository**: ``<repo>.wiki``, standing beside the
repository's ``<repo>.git`` under S-013's layout --
``<data_root>/repos/<owner>/<repo>.wiki``. This slice
is the storage layer only: where the wiki lives, when
it comes into being, and the page primitives every
later wiki slice stands on. The web experience is
S-274, the transports are S-275, and the access
policy choice is S-276; none of that is built here.

The laws (research file 28):

- **Separate repo, parent ACL.** The wiki's history
  is its own git history -- pages are Markdown files,
  edits are commits, undo is ordinary version control
  (S-274's history reads this repo's own log). But a
  wiki grants nothing of its own: every read and write
  is judged against the *parent* repository through
  S-054's ``can_read`` / ``can_write``, exactly as the
  releases family does. A private repository's wiki is
  invisible with it -- a reader who cannot read the
  repository gets the uniform ``repo_not_found`` for
  its wiki too, on every primitive, so a private wiki
  never appears by standing beside a public code repo
  that does not exist either.
- **Lazy creation.** The wiki repository is created
  on the **first page write**, and only there:
  ``git init --bare`` through S-014's subprocess law,
  with the parent repository's default branch as its
  own. Probing (``wiki_exists``), listing, and reading
  never create it -- a repository that has never had a
  page has no wiki directory on disk at all, and
  listing its pages honestly answers an empty list.
  A path that already exists but is not a bare git
  repository is refused (``wiki_path_exists``), never
  adopted silently -- that is drift, as in S-049.
- **One page-name law.** Research 28 names the risk:
  page titles, links, and filesystem paths need one
  normalization rule or traversal and duplicate pages
  follow. Here it is: a title is trimmed, its internal
  whitespace runs collapse to single hyphens, a single
  trailing ``.md`` is canonicalised away, and the page
  is stored flat as ``<name>.md`` at the wiki root --
  no directories, ever. Separators, ``..``, control
  characters, a leading dot, and a trailing dot are
  refused (``page_title_invalid``). Page identity is
  the canonical name judged case-insensitively: two
  titles that differ only in case or spacing are the
  **same** page, so a write updates it (keeping the
  standing file's name) instead of planting a twin.
- **Pages are text, capped, committed whole.** A page
  body is Markdown text, at most ``PAGE_MAX`` bytes
  encoded as UTF-8 (``page_too_large``; non-text is
  ``page_invalid``) -- a large binary attachment
  disguised as Markdown does not enter through this
  door. A write is one commit built by plumbing
  (``hash-object`` / ``mktree`` / ``commit-tree`` /
  ``update-ref`` under S-014, the S-064 road): the new
  tree is the old tree with exactly this page's entry
  replaced or added, the commit's parent is the old
  wiki tip, and ``update-ref`` names that old tip, so
  a tip that moved under the writer refuses instead
  of being silently overwritten.
- **Optimistic conflict, named.** A writer may pass
  ``expected_oid`` -- the wiki tip they read before
  editing (research 28's stale-edit acceptance). If
  the tip has moved since, the write is refused
  ``page_conflict`` and nothing is stored: one writer
  wins, the other is told, exactly as the study
  requires. Deleting a page is the same write with
  the entry removed; deleting the last page leaves a
  standing wiki holding an empty tree, not a vanished
  repository.

- **Access policy (S-276).** Who may edit is the
  repository owner's choice, held as data: the
  policy is ``collaborators`` (the default, and the
  law above -- only a repository writer edits) or
  ``readers`` (every signed-in reader edits: anyone
  S-054 lets read the repository may write and
  delete its wiki pages). The choice is judged here,
  in the one writer door, through the pure
  ``decide_wiki_edit`` -- so the web save (S-274)
  inherits it whole, exactly as it inherits the
  conflict law. Anonymous visitors never edit under
  either policy (a commit needs an identity), and a
  private repository's readers are only those S-054
  lets read it, so ``readers`` never widens a private
  wiki past the repository's own ACL. Only an
  administrator of the repository (its owner, or a
  site admin -- S-054's ``can_admin``) may set the
  policy; the choice is shown on the wiki home
  (S-274's index and Home view carry it in words).
  The git transports (S-275) keep their repo-equal
  writer law unchanged: a push is a transport act,
  judged there, not an edit through this door.

Wiki acts carry no verb of their own in the frozen
taxonomy vocabulary and are not witnessed -- no new
taxonomy event: 133 stand (33 auth / 87 repo /
13 admin). The policy choice rides migration 107's
``wiki_access_policies`` table (schema 106 -> 107);
the wiki's pages stay git storage, not tables.
"""

from __future__ import annotations

import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .accounts import User
from .audit import AuditLog
from .escaping import escape_html_text
from .permissions import can_admin, can_read, can_write
from .platform_seam import ensure_dir
from .proc import run_git, run_git_in
from .repositories import Repository, RepositoryStore

PAGE_MAX = 1_048_576
TITLE_MAX = 120
MESSAGE_MAX = 1_000

POLICY_COLLABORATORS = "collaborators"
POLICY_READERS = "readers"
WIKI_POLICIES = (POLICY_COLLABORATORS, POLICY_READERS)
DEFAULT_POLICY = POLICY_COLLABORATORS

_PAGE_EXT = ".md"
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

__all__ = [
    "DEFAULT_POLICY", "MESSAGE_MAX", "PAGE_MAX",
    "POLICY_COLLABORATORS", "POLICY_READERS",
    "TITLE_MAX", "WIKI_POLICIES",
    "WikiAccess", "WikiError", "WikiPage", "WikiStore",
    "decide_wiki_edit", "normalize_page_title",
    "page_filename", "page_to_dict",
    "render_wiki_page_list", "wiki_path_for",
    "wiki_policy_words",
]


class WikiError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class WikiPage:
    name: str          # canonical page name (no extension)
    filename: str      # stored file name, "<name>.md"
    size: int          # body size in bytes
    blob_oid: str      # git blob of the standing body
    commit_oid: str    # wiki tip commit that carries it
    content: str = ""  # body text (read/write answers only)


def wiki_path_for(repositories: RepositoryStore,
                  current: Repository) -> Path:
    """The wiki's bare-repository path: S-013's repo
    path with its ``.git`` suffix replaced by the
    roadmap's ``.wiki`` -- one resolver, so the wiki
    inherits the traversal and containment law whole
    and can never land outside the repositories root.
    The path need not exist (lazy creation)."""
    repo_path = repositories.path_for(current.owner, current.name)
    return repo_path.with_name(
        repo_path.name[: -len(".git")] + ".wiki")


def normalize_page_title(title: object) -> str:
    """The one page-name law (module docstring):
    return the canonical page name for *title*, or
    raise WikiError(``page_title_invalid``)."""
    if not isinstance(title, str):
        raise WikiError(
            "page_title_invalid", "A page title is text.")
    text = title.strip()
    if text.lower().endswith(_PAGE_EXT):
        text = text[: -len(_PAGE_EXT)].strip()
    name = re.sub(r"\s+", "-", text)
    if (not name or len(name) > TITLE_MAX
            or any(ord(c) < 0x20 or ord(c) == 0x7F for c in name)
            or "/" in name or "\\" in name or ".." in name
            or name.startswith(".") or name.endswith(".")
            or not _NAME_RE.match(name)):
        raise WikiError(
            "page_title_invalid",
            f"That page title is not valid: {title!r}. A page "
            "title is one flat name: letters, digits, hyphens, "
            "underscores and single dots, with spaces read as "
            "hyphens.")
    return name


def page_filename(name: str) -> str:
    return f"{name}{_PAGE_EXT}"


def page_to_dict(page: WikiPage, *, with_content: bool = False) -> dict:
    out = {
        "name": page.name,
        "filename": page.filename,
        "size": page.size,
        "blob_oid": page.blob_oid,
        "commit_oid": page.commit_oid,
    }
    if with_content:
        out["content"] = page.content
    return out


@dataclass(frozen=True)
class WikiAccess:
    full_name: str
    policy: str              # POLICY_COLLABORATORS or POLICY_READERS
    updated_by: str | None   # username of the chooser, if a row stands
    updated_at: int | None

    @property
    def is_default(self) -> bool:
        return self.updated_at is None


def decide_wiki_edit(policy: object, *, signed_in: bool,
                     readable: bool, writable: bool) -> bool:
    """The S-276 judgement, pure: may this person edit
    the wiki? A writer always may; a signed-in reader
    may only under the ``readers`` policy; anyone else
    -- anonymous, or a stranger to a private repo --
    never. An unknown policy value judges as the
    default (collaborators): a corrupt row narrows,
    never widens."""
    if not signed_in or not readable:
        return False
    if writable:
        return True
    return policy == POLICY_READERS


def wiki_policy_words(policy: object) -> str:
    """The policy in plain words, for the wiki home:
    the standing choice, stated, never colour alone."""
    if policy == POLICY_READERS:
        return ("Editable by all readers -- anyone who can "
                "read this repository can edit its wiki.")
    return ("Editable by collaborators -- only repository "
            "writers can edit this wiki.")


def render_wiki_page_list(repository: Repository,
                          pages: list[WikiPage],
                          policy: str = DEFAULT_POLICY) -> str:
    """The storage face in words (S-010-escaped): the
    wiki's standing pages beside its repository, or the
    honest empty state -- a wiki with no pages may not
    exist on disk yet at all, and this says so instead
    of dressing an absence as a listing. The browsing
    experience (sidebar, footer, editing) is S-274."""
    full = escape_html_text(repository.full_name)
    access = (f'<p class="wiki-access">'
              f"{escape_html_text(wiki_policy_words(policy))}</p>")
    if not pages:
        return (
            f'<section class="wiki-storage" data-repo="{full}">'
            "<h2>Wiki</h2>"
            "<p>This repository's wiki has no pages yet. "
            "Its wiki is its own bare git repository, created "
            "lazily on the first page.</p>" + access + "</section>")
    items = "".join(
        f'<li data-page="{escape_html_text(p.name)}">'
        f"{escape_html_text(p.name)} "
        f"({p.size} bytes)</li>"
        for p in pages)
    return (
        f'<section class="wiki-storage" data-repo="{full}">'
        f"<h2>Wiki</h2><ul>{items}</ul>" + access + "</section>")


class WikiStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._repos = repositories
        self._audit = audit
        self._now = time_fn

    # -- gates ------------------------------------------------

    def _repo_for_read(self, viewer: User | None, owner: object,
                       repo: object) -> Repository:
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise WikiError("repo_not_found", "No such repository.")
        return current

    def _repo_for_write(self, actor: User | None, owner: object,
                        repo: object) -> Repository:
        if actor is None:
            raise WikiError(
                "permission_denied",
                "Only a signed-in user can write wiki pages.")
        current = self._repo_for_read(actor, owner, repo)
        if not decide_wiki_edit(
                self._policy_for(current.id), signed_in=True,
                readable=True, writable=can_write(actor, current)):
            raise WikiError(
                "permission_denied",
                "This wiki's access policy does not let this "
                "user edit its pages.")
        return current

    # -- access policy (S-276) ---------------------------

    def _policy_for(self, repo_id: int) -> str:
        """The standing policy value for a repository id:
        the row's choice, or the default when no row
        stands (no choice made yet)."""
        row = self._conn.execute(
            "SELECT policy FROM wiki_access_policies"
            " WHERE repo_id = ?", (repo_id,)).fetchone()
        if row is None or row["policy"] not in WIKI_POLICIES:
            return DEFAULT_POLICY
        return row["policy"]

    def _access_view(self, current: Repository) -> WikiAccess:
        row = self._conn.execute(
            "SELECT p.policy AS policy, p.updated_at AS at,"
            " u.username AS by_name FROM wiki_access_policies p"
            " LEFT JOIN users u ON u.id = p.updated_by"
            " WHERE p.repo_id = ?", (current.id,)).fetchone()
        if row is None:
            return WikiAccess(
                full_name=current.full_name, policy=DEFAULT_POLICY,
                updated_by=None, updated_at=None)
        policy = (row["policy"] if row["policy"] in WIKI_POLICIES
                  else DEFAULT_POLICY)
        return WikiAccess(
            full_name=current.full_name, policy=policy,
            updated_by=row["by_name"], updated_at=row["at"])

    def access_policy(self, viewer: User | None, owner: object,
                      repo: object) -> WikiAccess:
        """The wiki's standing access policy. Read-gated:
        a private repository's policy is as invisible as
        the repository (``repo_not_found``). Reading the
        policy writes nothing and creates no wiki."""
        current = self._repo_for_read(viewer, owner, repo)
        return self._access_view(current)

    def can_edit_wiki(self, viewer: User | None, owner: object,
                      repo: object) -> bool:
        """Whether *viewer* may edit this wiki under its
        standing policy (read-gated, as access_policy)."""
        current = self._repo_for_read(viewer, owner, repo)
        return decide_wiki_edit(
            self._policy_for(current.id),
            signed_in=viewer is not None, readable=True,
            writable=(can_write(viewer, current)
                      if viewer is not None else False))

    def set_access_policy(self, actor: User | None, owner: object,
                          repo: object, policy: object) -> WikiAccess:
        """The owner's choice: set who may edit the wiki.
        Only a repository administrator (the owner, or a
        site admin -- S-054's can_admin) chooses; any
        other signed-in reader is refused
        ``permission_denied`` and an unreadable or
        missing repository answers ``repo_not_found``.
        A value outside the two policies is refused
        ``policy_invalid`` and stores nothing."""
        if actor is None:
            raise WikiError(
                "permission_denied",
                "Only the repository's owner can choose who "
                "may edit its wiki.")
        current = self._repo_for_read(actor, owner, repo)
        if not can_admin(actor, current):
            raise WikiError(
                "permission_denied",
                "Only the repository's owner can choose who "
                "may edit its wiki.")
        if policy not in WIKI_POLICIES:
            raise WikiError(
                "policy_invalid",
                "A wiki is editable by collaborators or by "
                "all readers.")
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "INSERT INTO wiki_access_policies"
                " (repo_id, policy, updated_by, updated_at)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT(repo_id) DO UPDATE SET"
                " policy = excluded.policy,"
                " updated_by = excluded.updated_by,"
                " updated_at = excluded.updated_at",
                (current.id, policy, actor.id, now))
        return self._access_view(current)

    # -- paths / existence -------------------------------------

    def wiki_path(self, owner: object, repo: object) -> Path:
        """The resolved ``<repo>.wiki`` path for a named
        repository (S-013 law via the parent resolver);
        a name with no repository answers repo_not_found.
        This never creates anything."""
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise WikiError("repo_not_found", "No such repository.")
        return wiki_path_for(self._repos, current)

    def wiki_exists(self, viewer: User | None, owner: object,
                    repo: object) -> bool:
        """True only when the wiki repository stands on
        disk as a bare git repository. Read-gated: a
        private repository's wiki existence is itself
        private (``repo_not_found``). Never creates."""
        current = self._repo_for_read(viewer, owner, repo)
        return self._is_bare_wiki(wiki_path_for(self._repos, current))

    @staticmethod
    def _is_bare_wiki(path: Path) -> bool:
        if not path.is_dir():
            return False
        probe = run_git_in(
            path, ["rev-parse", "--is-bare-repository"], timeout=15.0)
        return (probe.returncode == 0
                and probe.stdout.decode("utf-8", "replace").strip()
                == "true")

    def _ensure_wiki(self, current: Repository) -> Path:
        """The lazy creation (first page write only):
        return the standing wiki path, creating the bare
        repository when it does not stand yet. A path
        that exists but is not a bare git repository is
        drift, refused -- never adopted, never removed."""
        path = wiki_path_for(self._repos, current)
        if path.exists():
            if not self._is_bare_wiki(path):
                raise WikiError(
                    "wiki_path_exists",
                    "A directory already exists at that wiki's "
                    "path and is not a bare git repository; "
                    "refusing to adopt it silently.")
            return path
        ensure_dir(path.parent)
        result = run_git(
            ["init", "--bare",
             f"--initial-branch={current.default_branch}", str(path)],
            timeout=30.0)
        if result.returncode != 0:
            raise WikiError(
                "wiki_init_failed",
                "git could not create the wiki repository: "
                + result.stderr.decode(
                    "utf-8", "replace").strip()[:200])
        return path

    # -- git helpers --------------------------------------------

    def _tip(self, path: Path, current: Repository) -> str | None:
        head = run_git_in(
            path, ["rev-parse", "--verify", "--quiet",
                   f"refs/heads/{current.default_branch}"],
            timeout=15.0)
        if head.returncode != 0:
            return None
        return head.stdout.decode("utf-8", "replace").strip() or None

    def _entries(self, path: Path, tip: str | None) -> list[str]:
        """The tip tree's raw ``ls-tree`` lines (flat:
        a wiki tree holds page files only)."""
        if tip is None:
            return []
        tree = run_git_in(path, ["ls-tree", tip], timeout=15.0)
        if tree.returncode != 0:
            raise WikiError(
                "wiki_unreadable", "git could not read the wiki tree.")
        return tree.stdout.decode(
            "utf-8", "surrogateescape").splitlines()

    @staticmethod
    def _entry_name(line: str) -> str:
        return line.partition("\t")[2]

    def _find_entry(self, entries: list[str],
                    name: str) -> tuple[int, str] | None:
        """(index, standing filename) for the page whose
        canonical name matches *name* case-insensitively,
        else None -- the duplicate-page guard of the
        one-name law."""
        wanted = page_filename(name).lower()
        for idx, line in enumerate(entries):
            filename = self._entry_name(line)
            if filename.lower() == wanted:
                return idx, filename
        return None

    def _commit_tree(self, path: Path, current: Repository,
                     actor: User, entries: list[str],
                     parent: str | None, message: str) -> str:
        new_tree = run_git_in(
            path, ["mktree"],
            input_bytes=(
                ("\n".join(entries) + "\n").encode(
                    "utf-8", "surrogateescape")
                if entries else b""),
            timeout=15.0)
        if new_tree.returncode != 0:
            raise WikiError(
                "wiki_write_failed",
                "git could not build the wiki tree.")
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
            raise WikiError(
                "wiki_write_failed",
                "git could not commit the wiki change.")
        commit_oid = commit.stdout.decode().strip()
        ref = f"refs/heads/{current.default_branch}"
        updated = run_git_in(
            path, ["update-ref", ref, commit_oid, parent or ""],
            timeout=15.0)
        if updated.returncode != 0:
            raise WikiError(
                "page_conflict",
                "The wiki changed while this page was being "
                "written; read the newest pages and write again.")
        return commit_oid

    @staticmethod
    def _validate_content(content: object) -> bytes:
        if not isinstance(content, str):
            raise WikiError(
                "page_invalid", "A wiki page body is Markdown text.")
        raw = content.encode("utf-8")
        if len(raw) > PAGE_MAX:
            raise WikiError(
                "page_too_large",
                f"A wiki page is at most {PAGE_MAX} bytes of "
                "Markdown text.")
        return raw

    @staticmethod
    def _validate_message(message: object, fallback: str) -> str:
        if message is None:
            return fallback
        if not isinstance(message, str) or not message.strip():
            raise WikiError(
                "message_invalid",
                "A wiki commit message is plain text.")
        text = message.strip()
        if len(text) > MESSAGE_MAX or "\x00" in text:
            raise WikiError(
                "message_invalid",
                f"A wiki commit message is at most {MESSAGE_MAX} "
                "characters of plain text.")
        return text

    def _check_expected(self, tip: str | None,
                        expected_oid: object) -> None:
        if expected_oid is None:
            return
        if not isinstance(expected_oid, str) or tip != expected_oid:
            raise WikiError(
                "page_conflict",
                "The wiki has changed since that version was "
                "read; read the newest pages and write again.")

    # -- reads ----------------------------------------------------

    def list_pages(self, viewer: User | None, owner: object,
                   repo: object) -> list[WikiPage]:
        """Every standing page, in canonical-name order.
        A repository with no wiki yet answers an empty
        list -- listing never creates the wiki."""
        current = self._repo_for_read(viewer, owner, repo)
        path = wiki_path_for(self._repos, current)
        if not self._is_bare_wiki(path):
            return []
        tip = self._tip(path, current)
        if tip is None:
            return []
        pages: list[WikiPage] = []
        for line in self._entries(path, tip):
            meta, _, filename = line.partition("\t")
            parts = meta.split()
            if len(parts) != 3 or parts[1] != "blob":
                continue
            if not filename.lower().endswith(_PAGE_EXT):
                continue
            blob = run_git_in(
                path, ["cat-file", "-s", parts[2]], timeout=15.0)
            size = (int(blob.stdout.decode().strip())
                    if blob.returncode == 0 else 0)
            pages.append(WikiPage(
                name=filename[: -len(_PAGE_EXT)],
                filename=filename, size=size,
                blob_oid=parts[2], commit_oid=tip))
        pages.sort(key=lambda p: p.name.lower())
        return pages

    def read_page(self, viewer: User | None, owner: object,
                  repo: object, title: object) -> WikiPage:
        """One page's standing body. A missing wiki and
        a missing page answer the same page_not_found;
        reading never creates the wiki."""
        current = self._repo_for_read(viewer, owner, repo)
        name = normalize_page_title(title)
        path = wiki_path_for(self._repos, current)
        if not self._is_bare_wiki(path):
            raise WikiError("page_not_found", "No such wiki page.")
        tip = self._tip(path, current)
        found = (self._find_entry(self._entries(path, tip), name)
                 if tip is not None else None)
        if found is None:
            raise WikiError("page_not_found", "No such wiki page.")
        _, filename = found
        blob = run_git_in(
            path, ["cat-file", "blob", f"{tip}:{filename}"],
            timeout=15.0)
        if blob.returncode != 0:
            raise WikiError("page_not_found", "No such wiki page.")
        try:
            content = blob.stdout.decode("utf-8")
        except UnicodeDecodeError:
            raise WikiError(
                "page_unreadable",
                "That wiki page is not readable text.") from None
        entries = self._entries(path, tip)
        idx, _ = found
        oid = entries[idx].split()[2]
        return WikiPage(
            name=filename[: -len(_PAGE_EXT)], filename=filename,
            size=len(blob.stdout), blob_oid=oid,
            commit_oid=tip or "", content=content)

    # -- writes ---------------------------------------------------

    def write_page(self, actor: User | None, owner: object,
                   repo: object, title: object, content: object,
                   *, message: object = None,
                   expected_oid: object = None,
                   source_ip: str | None = None) -> WikiPage:
        """Create or replace one page -- the first write
        to a repository creates its wiki lazily. Returns
        the standing page (body included)."""
        current = self._repo_for_write(actor, owner, repo)
        assert actor is not None
        name = normalize_page_title(title)
        raw = self._validate_content(content)
        path = self._ensure_wiki(current)
        tip = self._tip(path, current)
        self._check_expected(tip, expected_oid)
        entries = list(self._entries(path, tip))
        found = self._find_entry(entries, name)
        standing = found[1] if found else page_filename(name)
        text_message = self._validate_message(
            message,
            f"{'Update' if found else 'Create'} page {standing}")
        blob = run_git_in(
            path, ["hash-object", "-w", "--stdin"],
            input_bytes=raw, timeout=15.0)
        if blob.returncode != 0:
            raise WikiError(
                "wiki_write_failed",
                "git could not store the wiki page.")
        blob_oid = blob.stdout.decode().strip()
        line = f"100644 blob {blob_oid}\t{standing}"
        if found is not None:
            entries[found[0]] = line
        else:
            entries.append(line)
            entries.sort(key=self._entry_name)
        commit_oid = self._commit_tree(
            path, current, actor, entries, tip, text_message)
        return WikiPage(
            name=standing[: -len(_PAGE_EXT)], filename=standing,
            size=len(raw), blob_oid=blob_oid,
            commit_oid=commit_oid, content=content)  # type: ignore[arg-type]

    def delete_page(self, actor: User | None, owner: object,
                    repo: object, title: object,
                    *, message: object = None,
                    expected_oid: object = None,
                    source_ip: str | None = None) -> WikiPage:
        """Remove one page in one commit. The wiki itself
        stands (an empty tree) when its last page goes.
        Returns the page as it stood before removal."""
        current = self._repo_for_write(actor, owner, repo)
        assert actor is not None
        name = normalize_page_title(title)
        path = wiki_path_for(self._repos, current)
        if not self._is_bare_wiki(path):
            raise WikiError("page_not_found", "No such wiki page.")
        tip = self._tip(path, current)
        self._check_expected(tip, expected_oid)
        entries = list(self._entries(path, tip))
        found = self._find_entry(entries, name)
        if found is None:
            raise WikiError("page_not_found", "No such wiki page.")
        idx, standing = found
        before = self.read_page(actor, owner, repo, standing)
        text_message = self._validate_message(
            message, f"Delete page {standing}")
        del entries[idx]
        commit_oid = self._commit_tree(
            path, current, actor, entries, tip, text_message)
        return WikiPage(
            name=before.name, filename=before.filename,
            size=before.size, blob_oid=before.blob_oid,
            commit_oid=commit_oid, content=before.content)
