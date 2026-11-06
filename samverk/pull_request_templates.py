"""Pull request templates (S-162).

A repository may carry pull request templates as files;
this slice finds them and puts them on the creation
road — a single template whose text fills the new pull
request's description automatically, or a directory of
named templates the author picks from on creation.

- **Templates are files in the repository, read from
  the base branch of the base repository** — the
  S-151 CODEOWNERS trust law carried to templates.
  The pull request's author does not get to choose
  the menu by editing a copy on the head branch: the
  templates are whatever the branch being proposed
  *into* carries today. For a cross-fork pull request
  that is still the base repository's base branch,
  never the fork's.
- **Two shapes, the GitHub-class conventions.**
  A single template is the first hit in the public
  order — `pull_request_template.md`,
  `PULL_REQUEST_TEMPLATE.md`,
  `docs/pull_request_template.md`,
  `docs/PULL_REQUEST_TEMPLATE.md`,
  `.samverk/pull_request_template.md`,
  `.samverk/PULL_REQUEST_TEMPLATE.md`,
  `.github/pull_request_template.md`,
  `.github/PULL_REQUEST_TEMPLATE.md`.
  Per-directory templates are the Markdown files
  directly inside the first directory that holds any,
  in the order `PULL_REQUEST_TEMPLATE/`,
  `docs/PULL_REQUEST_TEMPLATE/`,
  `.samverk/PULL_REQUEST_TEMPLATE/`,
  `.github/PULL_REQUEST_TEMPLATE/`; each file's name
  without its `.md` suffix is the template's name,
  listed in name order. Non-Markdown files, nested
  directories, binary files, and files over the size
  cap are not templates and are skipped silently.
  When a directory holds templates the author picks
  (there is no automatic fill); when only a single
  template exists its text is the default body; when
  neither exists the description starts blank, exactly
  as before this slice. No template file anywhere is
  an empty menu, never an error.
- **Creation threads the choice through.** This
  store's `create_pull_request` and
  `create_cross_fork_pull_request` ride S-141/S-142's
  stores unchanged underneath: an explicit `body`
  always wins; naming a template applies that
  template's text; naming none applies the single
  template when there is one. An unknown template
  name is refused (`template_not_found`) before any
  number is claimed, so a refused opening burns
  nothing. Which template filled the body is recorded
  in the existing `repo.pull_request.create` audit
  detail under `template` — never the template's text.
- **No stored state, no new audit event.** Templates
  are derived from the repository's own files at read
  time, so this slice claims no migration (the schema
  stays at 57) and appends no taxonomy event (the
  taxonomy stays at 110 events); the picker is data
  on the creation preview, and `render_creation_page`
  / `render_cross_fork_page` show it — with the
  description textarea this slice adds — only when a
  caller passes the choice in, so every existing page
  and battery is unchanged by default.
- **Reading is a reader act, using is the creation
  road's act** (S-054): listing and reading templates
  needs only read standing on the repository, and a
  stranger to a private repository gets the uniform
  `repo_not_found`. Creating still requires exactly
  the standing S-141/S-142 require.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .issues import IssueStore
from .objects import ObjectError, ObjectReader
from .permissions import can_read
from .pull_request_forks import ForkPullRequestStore
from .pull_requests import PullRequestStore
from .refs import RefStore, branch_ref
from .repositories import RepositoryStore

__all__ = [
    "SINGLE_TEMPLATE_PATHS", "TEMPLATE_DIR_PATHS",
    "TEMPLATE_MAX_BYTES", "PullRequestTemplate",
    "PullRequestTemplateError", "PullRequestTemplateStore",
    "TemplateChoice", "render_template_picker",
]

# Where a single pull request template may live, in
# lookup order — the first hit wins.
SINGLE_TEMPLATE_PATHS = (
    "pull_request_template.md",
    "PULL_REQUEST_TEMPLATE.md",
    "docs/pull_request_template.md",
    "docs/PULL_REQUEST_TEMPLATE.md",
    ".samverk/pull_request_template.md",
    ".samverk/PULL_REQUEST_TEMPLATE.md",
    ".github/pull_request_template.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
)

# Where a directory of named pull request templates
# may live, in lookup order — the first directory
# holding at least one usable template wins.
TEMPLATE_DIR_PATHS = (
    "PULL_REQUEST_TEMPLATE",
    "docs/PULL_REQUEST_TEMPLATE",
    ".samverk/PULL_REQUEST_TEMPLATE",
    ".github/PULL_REQUEST_TEMPLATE",
)

# A template is prose for a description box (S-141's
# body cap is 65,536 characters); anything larger or
# binary is not a template and is skipped, never read
# into a page whole.
TEMPLATE_MAX_BYTES = 131072


class PullRequestTemplateError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class PullRequestTemplate:
    name: str        # the picker's name for this template
    path: str        # its path in the repository
    body: str        # the template text, verbatim
    kind: str        # 'single' | 'directory'

    @property
    def words(self) -> str:
        if self.kind == "single":
            return (f"The single pull request template at "
                    f"{self.path}; its text fills the "
                    "description automatically.")
        return (f"Pull request template {self.name!r} "
                f"at {self.path}.")


@dataclass(frozen=True)
class TemplateChoice:
    """Every template one branch offers, as picker data."""
    branch: str                 # the branch read from
    single: PullRequestTemplate | None
    templates: tuple            # of PullRequestTemplate (directory)
    directory: str | None       # the directory they came from

    @property
    def mode(self) -> str:
        """'multiple' | 'single' | 'none' — what creation
        offers for this branch, in one word."""
        if self.templates:
            return "multiple"
        if self.single is not None:
            return "single"
        return "none"

    @property
    def default_body(self) -> str:
        """The body creation starts from when the author
        names no template: the single template's text,
        else blank."""
        if self.mode == "single" and self.single is not None:
            return self.single.body
        return ""

    def find(self, name: object) -> PullRequestTemplate | None:
        """The named template, matched case-insensitively
        over the directory names and the single
        template's name — None when it is not on offer."""
        if not isinstance(name, str):
            return None
        wanted = name.strip().lower()
        if not wanted:
            return None
        for template in self.templates:
            if template.name.lower() == wanted:
                return template
        if self.single is not None \
                and self.single.name.lower() == wanted:
            return self.single
        return None

    @property
    def words(self) -> str:
        """The offer, in plain words — never a colour
        or a bare count alone."""
        if self.mode == "multiple":
            names = ", ".join(t.name for t in self.templates)
            return (f"{len(self.templates)} pull request "
                    f"templates on branch {self.branch} in "
                    f"{self.directory} ({names}); pick one "
                    "when opening, or start with a blank "
                    "description.")
        if self.mode == "single" and self.single is not None:
            return (f"One pull request template on branch "
                    f"{self.branch} at {self.single.path}; "
                    "its text fills the description "
                    "automatically.")
        return (f"No pull request templates on branch "
                f"{self.branch}; the description starts "
                "blank.")


def _find_entry(reader: ObjectReader, tree_oid: str,
                parts: list[str]):
    """The tree entry at a path, or None — the S-151
    tree walk, shared by every lookup in this module."""
    entries = reader.read_tree(tree_oid)
    for entry in entries:
        if entry.name != parts[0]:
            continue
        if len(parts) == 1:
            return entry
        if entry.type == "tree":
            return _find_entry(reader, entry.oid, parts[1:])
        return None
    return None


def _read_template_text(reader: ObjectReader, entry) -> str | None:
    """A blob's text when it can honestly be a template
    — small enough and not binary — else None."""
    raw = reader.read_blob(entry.oid)
    if len(raw) > TEMPLATE_MAX_BYTES or b"\x00" in raw:
        return None
    return raw.decode("utf-8", "replace")


def _discover(reader: ObjectReader, commit_oid: str,
              branch: str) -> TemplateChoice:
    """The whole template offer of one commit: the
    single template by first hit, and the named
    templates of the first directory that holds any."""
    commit = reader.read_commit(commit_oid)
    single = None
    for candidate in SINGLE_TEMPLATE_PATHS:
        entry = _find_entry(reader, commit.tree,
                            candidate.split("/"))
        if entry is None or entry.type != "blob":
            continue
        text = _read_template_text(reader, entry)
        if text is None:
            continue
        name = candidate.rsplit("/", 1)[-1]
        if name.lower().endswith(".md"):
            name = name[:-3]
        single = PullRequestTemplate(
            name=name, path=candidate, body=text, kind="single")
        break
    templates: list[PullRequestTemplate] = []
    directory = None
    for candidate_dir in TEMPLATE_DIR_PATHS:
        entry = _find_entry(reader, commit.tree,
                            candidate_dir.split("/"))
        if entry is None or entry.type != "tree":
            continue
        found: list[PullRequestTemplate] = []
        seen: set[str] = set()
        entries = sorted(reader.read_tree(entry.oid),
                         key=lambda e: e.name.lower())
        for child in entries:
            if child.type != "blob" \
                    or not child.name.lower().endswith(".md"):
                continue
            name = child.name[:-3]
            if not name or name.lower() in seen:
                continue
            text = _read_template_text(reader, child)
            if text is None:
                continue
            seen.add(name.lower())
            found.append(PullRequestTemplate(
                name=name, path=f"{candidate_dir}/{child.name}",
                body=text, kind="directory"))
        if found:
            templates = found
            directory = candidate_dir
            break
    return TemplateChoice(branch=branch, single=single,
                          templates=tuple(templates),
                          directory=directory)


class PullRequestTemplateStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        issues: IssueStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._issues = issues
        self._audit = audit
        self._now = time_fn
        self._prs = PullRequestStore(
            conn, repositories, accounts, issues,
            audit=audit, time_fn=time_fn)
        self._forks = ForkPullRequestStore(
            conn, repositories, accounts, issues,
            audit=audit, time_fn=time_fn)

    # -- internals ---------------------------------------------------
    def _require_readable(self, viewer, owner, repo):
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise PullRequestTemplateError(
                "repo_not_found", "No such repository.")
        return current

    def _choice_for(self, current, branch: str) -> TemplateChoice:
        empty = TemplateChoice(branch=branch, single=None,
                               templates=(), directory=None)
        path = self._repos.path_for(current.owner, current.name)
        commit_oid = RefStore(path).resolve(branch_ref(branch))
        if commit_oid is None:
            return empty
        try:
            return _discover(ObjectReader(path), commit_oid, branch)
        except ObjectError:
            return empty

    def _resolve_body(self, actor, owner, repo, base_branch,
                      template_name, body):
        """(body, audit template name) for a creation:
        an explicit body wins outright; a named template
        must exist or the whole opening is refused here,
        before any number is claimed; no name applies
        the single template when there is one."""
        if body is not None:
            return body, None
        choice = self.list_templates(
            actor, owner, repo, base_branch=base_branch)
        if template_name is not None:
            template = choice.find(template_name)
            if template is None:
                raise PullRequestTemplateError(
                    "template_not_found",
                    f"No pull request template named "
                    f"{template_name!r} on branch "
                    f"{choice.branch}.")
            return template.body, template.name
        if choice.single is not None:
            return choice.single.body, choice.single.name
        return "", None

    # -- reads ---------------------------------------------------------
    def list_templates(self, viewer: User | None, owner: object,
                       repo: object, *,
                       base_branch: str | None = None
                       ) -> TemplateChoice:
        """Every template the branch offers, as picker
        data. The branch defaults to the repository's
        default branch; creation passes the pull
        request's base branch, which is the branch the
        templates are read from."""
        current = self._require_readable(viewer, owner, repo)
        branch = base_branch if base_branch is not None \
            else current.default_branch
        return self._choice_for(current, branch)

    def get_template(self, viewer: User | None, owner: object,
                     repo: object, name: object, *,
                     base_branch: str | None = None
                     ) -> PullRequestTemplate:
        """One template by name, matched
        case-insensitively; a name that is not on offer
        is `template_not_found`."""
        choice = self.list_templates(
            viewer, owner, repo, base_branch=base_branch)
        template = choice.find(name)
        if template is None:
            raise PullRequestTemplateError(
                "template_not_found",
                f"No pull request template named {name!r} "
                f"on branch {choice.branch}.")
        return template

    def body_for(self, viewer: User | None, owner: object,
                 repo: object, template_name: object = None, *,
                 base_branch: str | None = None) -> str:
        """The starting description for a creation: the
        named template's text, else the single
        template's text, else blank."""
        choice = self.list_templates(
            viewer, owner, repo, base_branch=base_branch)
        if template_name is not None:
            template = choice.find(template_name)
            if template is None:
                raise PullRequestTemplateError(
                    "template_not_found",
                    f"No pull request template named "
                    f"{template_name!r} on branch "
                    f"{choice.branch}.")
            return template.body
        return choice.default_body

    def picker_for_creation(self, viewer: User | None,
                            owner: object, repo: object,
                            base_branch: object,
                            head_branch: object):
        """(CreationPreview, TemplateChoice) for one
        candidate pair: S-141's preview unchanged, plus
        the picker data read from the preview's base
        branch — everything the creation page needs."""
        preview = self._prs.preview_creation(
            viewer, owner, repo, base_branch, head_branch)
        choice = self.list_templates(
            viewer, owner, repo, base_branch=preview.base_branch)
        return preview, choice

    # -- creation ------------------------------------------------------
    def create_pull_request(self, actor: User, owner: object,
                            repo: object, *, base_branch: object,
                            head_branch: object,
                            template_name: object = None,
                            title: object = None,
                            body: object = None,
                            draft: bool = False,
                            source_ip: str | None = None):
        """Open a same-repository pull request through
        S-141's store, with the template choice applied
        to the body first (see `_resolve_body`)."""
        body, audit_name = self._resolve_body(
            actor, owner, repo, base_branch, template_name, body)
        return self._prs.create_pull_request(
            actor, owner, repo, base_branch=base_branch,
            head_branch=head_branch, title=title, body=body,
            draft=draft, source_ip=source_ip,
            template_name=audit_name)

    def create_cross_fork_pull_request(
            self, actor: User, base_owner: object,
            base_repo: object, *, base_branch: object,
            head_owner: object, head_repo: object,
            head_branch: object, template_name: object = None,
            title: object = None, body: object = None,
            maintainer_can_edit: bool = True,
            draft: bool = False,
            source_ip: str | None = None):
        """Open a cross-fork pull request through
        S-142's store; the templates are read from the
        *base* repository's base branch, never the
        fork's."""
        body, audit_name = self._resolve_body(
            actor, base_owner, base_repo, base_branch,
            template_name, body)
        return self._forks.create_cross_fork_pull_request(
            actor, base_owner, base_repo, base_branch=base_branch,
            head_owner=head_owner, head_repo=head_repo,
            head_branch=head_branch, title=title, body=body,
            maintainer_can_edit=maintainer_can_edit,
            draft=draft, source_ip=source_ip,
            template_name=audit_name)


def render_template_picker(choice: TemplateChoice, *,
                           selected: str | None = None) -> str:
    """The template picker, in plain words: what is on
    offer, each named template as a `?template=` link,
    and the blank start said out loud. Never a colour
    alone; every value escapes through S-010."""
    if choice.mode == "none":
        return ('<p class="pr-template-picker">'
                f"{escape_html_text(choice.words)}</p>")
    if choice.mode == "single":
        return ('<p class="pr-template-picker">'
                f"{escape_html_text(choice.words)}</p>")
    items = []
    for template in choice.templates:
        mark = (' <span class="selected">(chosen)</span>'
                if selected is not None
                and template.name.lower() == selected.lower()
                else "")
        items.append(
            '<li class="pr-template">'
            f'<a href="?template='
            f'{escape_html_text(quote(template.name, safe=""))}">'
            f"{escape_html_text(template.name)}</a> — "
            f"{escape_html_text(template.path)}{mark}</li>")
    return ('<fieldset class="pr-template-picker">'
            "<legend>Pull request template</legend>"
            f"<p>{escape_html_text(choice.words)}</p>"
            f'<ul class="pr-templates">{"".join(items)}</ul>'
            '<p class="pr-template-blank">You may also '
            "start with a blank description.</p></fieldset>")
