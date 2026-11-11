"""Wiki transports (S-275).

Roadmap S-275: Wiki transports -- the wiki clones and
pushes over both transports with repo-equal permissions
(Parts IV machinery, reused whole).

S-273 gave each repository a wiki that is its own bare
git repository, `<repo>.wiki` beside `<repo>.git`. This
slice puts that repository on the wire. There is no new
transport here: the wiki is served by the very services
Parts IV built for code repositories --
`SmartHttpService` and `TransportGate`
(`samverk/git_http.py`) on the HTTP door and
`SshServeService` (`samverk/ssh_serve.py`) on the SSH
door -- with exactly one seam changed, the resolution
step: a repository name carrying the wiki suffix names
the *parent* repository's wiki repository on disk
instead of the code repository. Everything else is the
machinery itself, inherited whole and never re-judged:
the S-077 advertisement, the S-078/S-079 stateless-rpc
pack legs, protocol v2 (S-080), the S-083 anonymous /
existence shape at the gate, the S-089 pre-receive gate,
the S-090 canonical push event, the S-091 transfer
limits, the S-092 push locks, the S-093 archive leg and
the S-094 transport audit. A wiki push is witnessed
exactly as a code push is -- the standing `repo.push`
verb on the parent repository, ranges read back from
the wiki's refs -- because the machinery records it;
no new taxonomy event is added.

The laws:

- **One naming law.** On either transport the wiki of
  `owner/repo` is named `owner/repo.wiki` (a single
  trailing `.git` is canonicalised away first, by
  S-013's name law, so `repo.wiki.git` is the same
  name). `split_wiki_repo_name` is the one splitter:
  it returns the parent repository's name for a wiki
  name and `None` for anything else -- a code
  repository's own name, a bare `.wiki`, or a name
  S-013 refuses. An exact repository row always wins:
  a repository literally named `data.wiki` is a code
  repository and is served as one; the wiki reading
  applies only when no such row stands, exactly so no
  standing repository is ever hijacked by its suffix.
- **Repo-equal permissions.** The permission gate is
  the transports' own gate, judged on the parent
  repository through S-054's `can_read` / `can_write`
  before any pack byte moves: clone and fetch follow
  read access, push follows the repository's writer
  law, deploy keys are authorised against the parent
  repository (a read-only deploy key's wiki push is
  refused before any pack byte, as on the code door).
  A private repository's wiki is invisible exactly as
  the repository is: on HTTP it answers the uniform
  `repo_not_found` (and the gate's uniform 401/404
  shapes), on SSH the one refusal message a missing
  repository gets -- existence never leaks through
  either door.
- **A wiki that does not stand is not served.** S-273
  creates the wiki lazily on the first page write,
  through the store; the transports never create it
  (a clone or push attempt creates nothing). Until
  the first page stands, a wiki name answers
  `repo_not_found` on every leg of both transports,
  together with a missing repository -- the same
  answer GitHub gives for a wiki with no pages. Once
  a page stands, the wiki clones and pushes like any
  repository.
- **The two repositories never touch.** Serving the
  wiki reads and writes only `<repo>.wiki`; a wiki
  push moves no code ref, and a code push moves no
  wiki ref. The battery proves both directions
  against the refs on disk.

Wiki acts carry no verb of their own in the frozen
taxonomy vocabulary: a transport push is witnessed by
the machinery's standing `repo.push` on the parent,
so no new taxonomy event -- 133 stand (33 auth / 87
repo / 13 admin). No migration: a wiki is git storage,
not a table, and the schema stays 106.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .accounts import User
from .audit import AuditLog
from .escaping import escape_html_text
from .permissions import can_read
from .repo_paths import RepoPathError, validate_repo_name
from .repositories import Repository, RepositoryStore
from .wiki_storage import WikiStore, wiki_path_for

WIKI_SUFFIX = ".wiki"
TRANSPORTS = ("http", "ssh")
SERVICES = ("git-upload-pack", "git-receive-pack", "git-upload-archive")

__all__ = [
    "SERVICES", "TRANSPORTS", "WIKI_SUFFIX",
    "WikiTransportAudit", "WikiTransportError",
    "audit_wiki_transports", "is_wiki_repo_name",
    "render_wiki_transports_page", "resolve_wiki_parent",
    "split_wiki_repo_name", "wiki_repo_name",
]


class WikiTransportError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def wiki_repo_name(parent: object) -> str:
    """The transport name of *parent*'s wiki: the parent
    repository's canonical name plus the wiki suffix,
    judged by S-013's name law whole."""
    try:
        canonical = validate_repo_name(parent)
    except RepoPathError:
        raise WikiTransportError(
            "repo_name_invalid",
            f"Not a lawful repository name: {parent!r}.") from None
    return canonical + WIKI_SUFFIX


def split_wiki_repo_name(name: object) -> str | None:
    """The one splitter: the parent repository's name
    when *name* is a wiki transport name, else `None`.

    The name is canonicalised by S-013 first (one
    trailing `.git` stripped), so `repo.wiki` and
    `repo.wiki.git` split the same way. A bare `.wiki`,
    a code repository's own name, and any name S-013
    refuses are not wiki names and answer `None` --
    callers fall back to the ordinary not-found answer,
    never to a new refusal shape."""
    if not isinstance(name, str):
        return None
    try:
        canonical = validate_repo_name(name)
    except RepoPathError:
        return None
    if len(canonical) <= len(WIKI_SUFFIX):
        return None
    if canonical[-len(WIKI_SUFFIX):].lower() != WIKI_SUFFIX:
        return None
    parent = canonical[:-len(WIKI_SUFFIX)]
    if not parent:
        return None
    return parent


def is_wiki_repo_name(name: object) -> bool:
    return split_wiki_repo_name(name) is not None


def resolve_wiki_parent(repositories: RepositoryStore,
                        owner: object, repo: object) -> Repository | None:
    """The parent repository a wiki transport name
    names, or `None` when the name is not a wiki name
    for a standing repository.

    An exact repository row wins over the wiki reading:
    when a repository literally bears the requested
    name it is a code repository, and this returns
    `None` so the transports serve it as one."""
    if repositories.get_repository(owner, repo) is not None:
        return None
    parent = split_wiki_repo_name(repo)
    if parent is None:
        return None
    return repositories.get_repository(owner, parent)


@dataclass(frozen=True)
class WikiTransportAudit:
    full_name: str            # the parent repository
    wiki_name: str            # its transport name, "<repo>.wiki"
    wiki_path: str            # the wiki repository on disk
    wiki_standing: bool       # a bare wiki repository stands there
    default_branch: str       # the parent's (the wiki's own, S-273)
    transports: tuple[str, ...] = TRANSPORTS
    services: tuple[str, ...] = SERVICES


def audit_wiki_transports(
    repositories: RepositoryStore,
    viewer: User | None,
    owner: object,
    repo: object,
) -> WikiTransportAudit:
    """Re-prove the slice's invariants for one wiki
    name, from the disk and the rows -- and write
    nothing: no wiki is created, no row moves, the
    audit log does not grow.

    The name must be a wiki transport name for a
    repository the viewer may read; a missing
    repository, a private repository the viewer may
    not read, a code repository's own name and a
    literal `.wiki` code repository all answer the
    one `repo_not_found`, so the audit leaks nothing
    the transports would not."""
    parent_name = split_wiki_repo_name(repo)
    parent = resolve_wiki_parent(repositories, owner, repo)
    if parent is None or parent_name is None \
            or not can_read(viewer, parent):
        raise WikiTransportError(
            "repo_not_found", "No such repository.")
    path = wiki_path_for(repositories, parent)
    return WikiTransportAudit(
        full_name=parent.full_name,
        wiki_name=f"{parent.name}{WIKI_SUFFIX}",
        wiki_path=str(path),
        wiki_standing=WikiStore._is_bare_wiki(path),
        default_branch=parent.default_branch,
    )


def render_wiki_transports_page(audit: WikiTransportAudit) -> str:
    """The transport face in words (S-010-escaped): how
    this repository's wiki is cloned and pushed, over
    both transports, or the honest not-yet state -- a
    wiki with no page answers not-found on the wire
    until its first page stands."""
    full = escape_html_text(audit.full_name)
    wiki = escape_html_text(audit.wiki_name)
    if not audit.wiki_standing:
        return (
            f'<section class="wiki-transports" data-repo="{full}">'
            f"<h2>Wiki transports</h2>"
            f"<p>This repository's wiki has no pages yet. Its wiki "
            f"is created on the first page; until then the "
            f"transports answer not found for {wiki}, exactly as "
            f"for a missing repository.</p></section>")
    services = escape_html_text(", ".join(audit.services))
    return (
        f'<section class="wiki-transports" data-repo="{full}">'
        f"<h2>Wiki transports</h2>"
        f"<p>The wiki of {full} is its own git repository and "
        f"clones and pushes over both transports with the "
        f"repository's own permissions ({services}).</p>"
        f'<ul><li>HTTP: <code>/{full}.wiki.git</code></li>'
        f"<li>SSH: <code>git@samverk:{full}.wiki.git</code></li>"
        f"</ul></section>")


class WikiTransports:
    """The slice's seam in one place, for callers that
    hold the stores rather than a transport service:
    name a wiki, resolve its parent, and audit the
    standing state. Serving itself is the Parts IV
    services' work -- this class spawns no pack process
    and judges no permission of its own; it stands on
    `resolve_wiki_parent` and `audit_wiki_transports`,
    which judge through S-054 exactly as the doors do.
    """

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

    def parent_for(self, owner: object,
                   repo: object) -> Repository | None:
        return resolve_wiki_parent(self._repos, owner, repo)

    def audit(self, viewer: User | None, owner: object,
              repo: object) -> WikiTransportAudit:
        return audit_wiki_transports(self._repos, viewer, owner, repo)
