"""Samverk surface in Samtal (S-368).

A Samverk panel inside Samtal's UI — the viewer's repos,
their open pull requests, and their inbox count — served
by Samverk's API under the frozen S-361 embed contract:
Samtal renders, Samverk decides. The panel payload is
computed entirely on the Samverk side, from the standing
stores (RepositoryStore, PullRequestStore over the real
Git refs, NotificationStore for the inbox count), judged
for the viewer themself: a panel names only what the
viewer owns and may read, and the payload carries its
verdict with it (decided_by: samverk) so no renderer can
mistake whose judgement it is showing.

The panel is a read, never a grant: holding the payload
confers no access, and every link in it still lands on
Samverk's own permission-checked pages. Samtal's side
of this slice is the reference renderer (render_panel),
which draws exactly the decided payload and nothing
else — a deployment's Samtal UI may restyle it, but may
not widen it.

Guards: the seam must be enabled (seam_disabled); a
panel needs its viewer (actor_required). No migration,
no new taxonomy event: the panel stores nothing.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .issues import IssueStore
from .notification_reasons import NotificationStore
from .pull_requests import PullRequestStore
from .repositories import RepositoryStore
from .seam_contract import seam_enabled


class SamtalPanelError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class PanelRepo:
    full_name: str
    link_path: str


@dataclass(frozen=True)
class PanelPull:
    repo: str
    number: int
    title: str
    link_path: str


@dataclass(frozen=True)
class Panel:
    username: str
    repos: tuple
    open_pulls: tuple
    inbox_unread: int
    decided_by: str = "samverk"

    @property
    def open_pull_count(self) -> int:
        return len(self.open_pulls)


class SamtalPanelService:
    """Samverk's side of the panel: it decides, Samtal renders."""

    def __init__(self, conn, data_root: Path, accounts: AccountStore,
                 *, settings: dict | None = None, audit: AuditLog | None = None,
                 time_fn=None):
        self._conn = conn
        self._accounts = accounts
        self._settings = settings
        self._repos = RepositoryStore(conn, data_root, accounts)
        issues = IssueStore(conn, self._repos, accounts, audit=audit)
        self._prs = PullRequestStore(conn, self._repos, accounts, issues,
                                     audit=audit)
        self._notifications = NotificationStore(
            conn, accounts, time_fn=time_fn or (lambda: 0))

    def panel_for(self, viewer: User | None) -> Panel:
        """The decided panel payload for one viewer."""
        if not seam_enabled(self._settings):
            raise SamtalPanelError(
                "seam_disabled", "The Samtal seam is not enabled.")
        if viewer is None or self._accounts.get_by_id(viewer.id) is None:
            raise SamtalPanelError(
                "actor_required", "A panel needs its signed-in viewer.")
        repos: list[PanelRepo] = []
        pulls: list[PanelPull] = []
        for repo in self._repos.list_for_owner(viewer.username):
            full = repo.full_name
            repos.append(PanelRepo(full_name=full, link_path=f"/{full}"))
            for pr in self._prs.list_pull_requests(
                    viewer, repo.owner, repo.name, state="open"):
                pulls.append(PanelPull(
                    repo=full, number=pr.number, title=pr.title,
                    link_path=f"/{full}/pulls/{pr.number}"))
        return Panel(username=viewer.username, repos=tuple(repos),
                     open_pulls=tuple(pulls),
                     inbox_unread=self._notifications.unread_count(viewer))

    def payload_for(self, viewer: User | None) -> dict:
        """The API shape Samtal renders from — Samverk's decision,
        serialised; the renderer adds nothing of its own."""
        panel = self.panel_for(viewer)
        return {
            "viewer": panel.username,
            "repos": [{"name": r.full_name, "link": r.link_path}
                      for r in panel.repos],
            "open_pull_requests": [
                {"repo": p.repo, "number": p.number, "title": p.title,
                 "link": p.link_path} for p in panel.open_pulls],
            "inbox_unread": panel.inbox_unread,
            "decided_by": panel.decided_by,
            "rendered_by": "samtal",
        }


def render_panel(panel: Panel) -> str:
    """Samtal's reference rendering of the decided payload:
    repos, open pull requests, and the inbox count, every
    value through S-010's escaping seam."""
    out = ['<section class="samverk-panel">\n',
           f"<h2>Samverk — {escape_html_text(panel.username)}</h2>\n",
           "<ul class=\"panel-repos\">\n"]
    for repo in panel.repos:
        out.append(f'<li><a href="{escape_html_text(repo.link_path)}">'
                   f"{escape_html_text(repo.full_name)}</a></li>\n")
    out.append("</ul>\n<ul class=\"panel-pulls\">\n")
    for pull in panel.open_pulls:
        out.append(f'<li><a href="{escape_html_text(pull.link_path)}">'
                   f"{escape_html_text(pull.repo)} #{pull.number} — "
                   f"{escape_html_text(pull.title)}</a></li>\n")
    out.append("</ul>\n")
    out.append(f'<p class="panel-inbox">Inbox: {panel.inbox_unread} '
               f"unread</p>\n</section>\n")
    return "".join(out)
