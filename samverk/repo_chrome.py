"""Permission-aware chrome (S-112).

Tabs and buttons a user cannot use are absent, not
greyed-out teasers; the API enforces regardless (S-054).

- **Chrome is a view of the role, nothing more.**
  `chrome_for` asks S-054's `role_for` once and builds
  the repository's navigation (tabs) and actions from
  that single answer: the Code tab for anyone who can
  read, Issues/Pull requests for readers too (reading
  them is a read act — Part VI/VII own their stores and
  their own write gates), Settings only for admins,
  and write actions (New issue is a read-role act in
  later parts; the write actions named here — Fork
  needs read, Edit settings needs admin) exactly at
  their role. A stranger to a private repository gets
  NO chrome at all (`repo_not_found` shape, S-054's
  uniform answer) — not a page of disabled buttons.
- **Absent means absent.** The renderer emits only the
  items in the chrome object; there is no `disabled`
  rendering path in this module at all, so a forbidden
  control cannot appear greyed, hidden-by-CSS, or
  present-but-inert. The battery greps the rendered
  HTML for forbidden labels and for `disabled`.
- **The page is not the gate.** Every action href names
  a route whose handler must re-check through S-054
  (`require_role`); chrome hiding is findability and
  honesty, never the security boundary — a hand-typed
  URL meets the same role law at the handler.
"""

from __future__ import annotations

from dataclasses import dataclass

from .accounts import User
from .escaping import escape_html_attr, escape_html_text
from .permissions import can_admin, can_read, can_write, role_for
from .repositories import Repository, RepositoryStore


class ChromeError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class ChromeItem:
    label: str
    href: str
    kind: str               # 'tab' | 'action'


@dataclass(frozen=True)
class RepoChrome:
    full_name: str
    owner: str
    name: str
    role: str               # the viewer's role, in words
    visibility: str
    tabs: tuple[ChromeItem, ...]
    actions: tuple[ChromeItem, ...]


def chrome_for(viewer: User | None, repo: Repository,
               *, collaborator_role: str | None = None) -> RepoChrome:
    """The chrome *viewer* may see on *repo*. Raises
    ChromeError('repo_not_found') when the viewer cannot
    read the repository — the uniform S-054 shape."""
    if not can_read(viewer, repo, collaborator_role=collaborator_role):
        raise ChromeError("repo_not_found", "No such repository.")
    role = role_for(viewer, repo, collaborator_role=collaborator_role)
    assert role is not None  # can_read just proved it
    base = f"/{repo.owner}/{repo.name}"
    tabs = [
        ChromeItem("Code", f"{base}", "tab"),
        ChromeItem("Issues", f"{base}/issues", "tab"),
        ChromeItem("Pull requests", f"{base}/pulls", "tab"),
    ]
    if can_admin(viewer, repo, collaborator_role=collaborator_role):
        tabs.append(ChromeItem("Settings", f"{base}/settings", "tab"))
    actions = [
        ChromeItem("Find a file", f"{base}/find", "action"),
        ChromeItem("Fork", f"{base}/fork", "action"),
    ]
    if can_write(viewer, repo, collaborator_role=collaborator_role):
        actions.append(ChromeItem("Upload files", f"{base}/upload", "action"))
    if can_admin(viewer, repo, collaborator_role=collaborator_role):
        actions.append(
            ChromeItem("Edit repository settings", f"{base}/settings", "action"))
    return RepoChrome(
        full_name=repo.full_name, owner=repo.owner, name=repo.name,
        role=role, visibility=repo.visibility,
        tabs=tuple(tabs), actions=tuple(actions))


def chrome_for_names(repositories: RepositoryStore,
                     viewer: User | None, owner: object, repo: object,
                     **kw) -> RepoChrome:
    current = repositories.get_repository(owner, repo)
    if current is None:
        raise ChromeError("repo_not_found", "No such repository.")
    return chrome_for(viewer, current, **kw)


def render_repo_chrome(chrome: RepoChrome) -> str:
    """The repository header chrome: name, visibility and
    role in words, then only the tabs/actions the viewer
    may use. Every value passes S-010."""
    parts = [
        '<header class="repo-chrome">',
        f"<h1>{escape_html_text(chrome.full_name)}</h1>",
        f'<p class="visibility">{escape_html_text(chrome.visibility)} '
        f"repository — your role: {escape_html_text(chrome.role)}</p>",
        '<nav class="repo-tabs" aria-label="Repository">',
    ]
    for item in chrome.tabs:
        parts.append(
            f'<a href="{escape_html_attr(item.href)}">'
            f"{escape_html_text(item.label)}</a>")
    parts.append("</nav>")
    parts.append('<div class="repo-actions">')
    for item in chrome.actions:
        parts.append(
            f'<a href="{escape_html_attr(item.href)}">'
            f"{escape_html_text(item.label)}</a>")
    parts.append("</div></header>")
    return "\n".join(parts)
