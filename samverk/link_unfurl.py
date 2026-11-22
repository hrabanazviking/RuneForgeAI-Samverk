"""Code in conversation (S-370).

Pasting a Samverk link in Samtal unfurls to a card —
repo, file, pull request, or issue — rendered from
Samverk's API under the frozen S-361 embed contract
(section 2): Samtal renders, Samverk decides. The
decision is judged at request time against the VIEWER's
own Samverk rights through S-190's PermissionEngine:
the card names only what the viewer may read, and a
viewer without read rights gets a refusal that leaks
nothing — no title, no snippet, not even whether the
target exists beyond the repo named in the link itself
(the pasted link is the viewer's own text).

An unfurl is a read, never a grant: the card confers
no access, and its link still lands on Samverk's own
permission-checked pages. The reference renderer
(render_card) draws exactly the decided card and
nothing else.

Guards: the seam must be enabled (seam_disabled); the
link must parse as one of the frozen embed kinds
(link_unknown / embed_kind_unknown via S-361); the
repo and target must stand (not_found); the viewer
must hold read (permission_denied). No migration, no
new taxonomy event: the unfurl stores nothing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_attr, escape_html_text
from .issues import IssueError, IssueStore
from .permission_engine import PermissionEngine
from .pull_requests import PullRequestError, PullRequestStore
from .repositories import RepositoryStore
from .seam_contract import decide_embed, seam_enabled

_SEG = r"[^/\s]+"
_PATTERNS = (
    ("pull_request", re.compile(rf"^/({_SEG})/({_SEG})/pulls/(\d+)/?$")),
    ("issue", re.compile(rf"^/({_SEG})/({_SEG})/issues/(\d+)/?$")),
    ("file", re.compile(rf"^/({_SEG})/({_SEG})/blob/({_SEG})/(.+)$")),
    ("repo", re.compile(rf"^/({_SEG})/({_SEG})/?$")),
)


class LinkUnfurlError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class UnfurlCard:
    kind: str
    repo: str
    title: str
    summary: str
    link_path: str
    decided_by: str = "samverk"


def parse_samverk_link(link: object) -> tuple:
    """Parse a pasted Samverk link into (kind, owner, repo,
    number_or_None, file_path_or_None). Anything that is
    not one of the frozen shapes raises link_unknown."""
    if not isinstance(link, str) or not link.strip():
        raise LinkUnfurlError("link_unknown", "That is not a Samverk link.")
    path = urlparse(link.strip()).path
    path = unquote(path)
    for kind, pattern in _PATTERNS:
        m = pattern.match(path)
        if not m:
            continue
        owner, repo = m.group(1), m.group(2)
        if kind in ("pull_request", "issue"):
            return (kind, owner, repo, int(m.group(3)), None)
        if kind == "file":
            file_path = m.group(4)
            if ".." in file_path.split("/"):
                raise LinkUnfurlError("link_unknown", "That is not a Samverk link.")
            return (kind, owner, repo, None, file_path)
        return (kind, owner, repo, None, None)
    raise LinkUnfurlError("link_unknown", "That is not a Samverk link.")


class LinkUnfurlService:
    """Samverk's side of the unfurl: it decides, Samtal renders."""

    def __init__(self, conn, data_root: Path, accounts: AccountStore,
                 *, settings: dict | None = None, audit: AuditLog | None = None,
                 time_fn=None):
        self._conn = conn
        self._accounts = accounts
        self._settings = settings
        self._repos = RepositoryStore(conn, data_root, accounts)
        self._issues = IssueStore(conn, self._repos, accounts, audit=audit)
        self._prs = PullRequestStore(conn, self._repos, accounts,
                                     self._issues, audit=audit)
        self._engine = PermissionEngine(conn, accounts, audit=audit,
                                        time_fn=time_fn or (lambda: 0))

    def unfurl(self, viewer: User | None, link: object) -> UnfurlCard:
        """The decided card for one pasted link and one viewer."""
        if not seam_enabled(self._settings):
            raise LinkUnfurlError(
                "seam_disabled", "The Samtal seam is not enabled.")
        kind, owner, repo_name, number, file_path = parse_samverk_link(link)
        repo = self._repos.get_repository(owner, repo_name)
        if repo is None:
            raise LinkUnfurlError("not_found", "That repository does not stand.")
        if not self._engine.can(viewer, repo, "read"):
            raise LinkUnfurlError(
                "permission_denied",
                "The viewer has no Samverk right to this.")
        decide_embed(kind, viewer_may_view=True)
        full = repo.full_name
        if kind == "repo":
            return UnfurlCard(kind, full, full,
                              repo.description or "A Samverk repository.",
                              f"/{full}")
        if kind == "file":
            return UnfurlCard(kind, full, file_path,
                              f"File in {full}.",
                              f"/{full}/blob/{repo.default_branch}/{file_path}")
        if kind == "issue":
            try:
                issue = self._issues.get_issue(viewer, owner, repo_name, number)
            except IssueError:
                raise LinkUnfurlError("not_found", "That issue does not stand.")
            return UnfurlCard(kind, full, issue.title,
                              f"Issue #{number} in {full} — {issue.state}.",
                              f"/{full}/issues/{number}")
        try:
            pr = self._prs.get_pull_request(viewer, owner, repo_name, number)
        except PullRequestError:
            raise LinkUnfurlError("not_found", "That pull request does not stand.")
        return UnfurlCard(kind, full, pr.title,
                          f"Pull request #{number} in {full} — {pr.state}.",
                          f"/{full}/pulls/{number}")

    def payload_for(self, viewer: User | None, link: object) -> dict:
        card = self.unfurl(viewer, link)
        return {"kind": card.kind, "repo": card.repo, "title": card.title,
                "summary": card.summary, "link": card.link_path,
                "decided_by": card.decided_by}


def render_card(card: UnfurlCard) -> str:
    """Samtal-side reference renderer: draws exactly the
    decided card, escaped, and nothing else."""
    return (f'<article class="samverk-card" data-kind="{escape_html_attr(card.kind)}">'
            f'<a href="{escape_html_attr(card.link_path)}">'
            f"{escape_html_text(card.title)}</a>"
            f"<p>{escape_html_text(card.summary)}</p></article>")
