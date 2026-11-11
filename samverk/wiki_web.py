"""Wiki web experience (S-274).

Roadmap S-274: Wiki web experience -- page list,
sidebar and footer pages, edit-in-browser with
preview, history via the wiki repo's own log.

This slice is the browsing and editing face over
S-273's storage (`samverk/wiki_storage.py`:
`WikiStore`). Storage stays the only writer: every
save here is `WikiStore.write_page`, every read is
`WikiStore.read_page` / `list_pages`, so the parent
repository's S-054 answers, the one page-name law,
the page cap, and the optimistic expected-tip
conflict (`page_conflict`) are inherited whole and
never re-judged. A private repository's wiki is
`repo_not_found` on every face here, together with
the repository.

The laws:

- **Page list.** The index lists the wiki's ordinary
  pages in S-273's canonical order. The sidebar and
  footer (below) are not ordinary pages and never
  appear in that list; the index names them in their
  own slots instead. A repository whose wiki does
  not stand yet answers an honest empty index --
  listing, viewing the index, previewing and reading
  history never create the wiki.
- **Sidebar and footer pages.** The conventional
  pages are named `Sidebar` and `Footer`, matched
  case-insensitively under S-273's identity law.
  JUDGEMENT CALL, recorded: GitHub spells these
  `_Sidebar` / `_Footer`, but S-273's one-name law
  refuses a leading underscore (a page name opens
  with a letter or digit), so the underscore forms
  cannot be stored at all; Samverk's convention is
  the same pages without the underscore. A standing
  sidebar renders in an aside on every page view and
  a standing footer in the page footer; a missing
  one renders nothing -- no empty furniture is
  dressed up as a sidebar. Both are ordinary pages
  for writing: a writer creates or edits them
  through the same save door as any page.
- **Home.** The page named `Home` is the wiki's
  landing page: a view with no page named shows it.
  A wiki with no Home answers `page_not_found` for
  the landing view, in words -- no home is invented.
- **Edit in browser, preview first.** `preview_page`
  renders a draft through S-107's Markdown pipeline
  and **writes nothing**: it creates no wiki, adds
  no page, and moves no tip -- the battery proves
  all three against the disk and the tip. Preview is
  judged by *read* access (any reader may draft;
  rendering is the sanitised pipeline, so a draft is
  as safe as a standing page); the *save* is the
  write door, judged by S-273's writer law, carrying
  the editor's `expected_oid` so a page that moved
  under the editor answers `page_conflict` and the
  draft is refused whole, never merged silently.
- **History is the wiki repo's own log.** History
  rows are read from `git log` **in the wiki
  repository** (`<repo>.wiki`), newest first --
  never from the parent code repository, whose
  commits are a different history and never appear
  here. Each row names the pages that commit
  changed, from `git diff-tree --name-status`
  against the same wiki repository. A filter names
  one page (under the one-name law) and keeps only
  the commits that touched its file, so a deleted
  page's history still reads. Pagination is honest
  in S-102's shape: the total is the true filtered
  count and a page past the end answers empty with
  the true totals. One honest limit: a merge commit
  (none can arise from S-273's plumbing writes;
  S-275 pushes could bring one) lists no changed
  pages, because `diff-tree` without `-m` diffs no
  merge -- the row itself, its message and author
  still stand.
- **Rendering.** Page bodies, the sidebar and the
  footer render through S-107's `render_markdown`
  -- the one sanitised pipeline, so stored raw HTML
  is visible text and dangerous URLs are no link at
  all. Everything else (titles, names, messages,
  authors) reaches the page only through S-010's
  escaping seam.

Wiki acts carry no verb of their own in the frozen
taxonomy vocabulary and are not witnessed (S-273's
law, unchanged): no new taxonomy event -- 133 stand
(33 auth / 87 repo / 13 admin). No migration: the
web experience stores nothing of its own and the
schema stays 106.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import User
from .audit import AuditLog
from .escaping import escape_html_attr, escape_html_text
from .markdown_pipeline import render_markdown
from .proc import run_git_in
from .repositories import Repository, RepositoryStore
from .wiki_storage import (
    PAGE_MAX, WikiError, WikiPage, WikiStore,
    normalize_page_title, wiki_path_for)

HOME_PAGE = "Home"
SIDEBAR_PAGE = "Sidebar"
FOOTER_PAGE = "Footer"
SPECIAL_PAGES = (SIDEBAR_PAGE, FOOTER_PAGE)
_SPECIAL_LOWER = frozenset(p.lower() for p in SPECIAL_PAGES)

DEFAULT_HISTORY_PER_PAGE = 30
MAX_HISTORY_PER_PAGE = 100

__all__ = [
    "DEFAULT_HISTORY_PER_PAGE", "FOOTER_PAGE", "HOME_PAGE",
    "MAX_HISTORY_PER_PAGE", "SIDEBAR_PAGE", "SPECIAL_PAGES",
    "WikiHistory", "WikiHistoryEntry", "WikiIndex",
    "WikiPageView", "WikiPreview", "WikiWeb",
    "WikiWebError", "render_wiki_edit_form",
    "render_wiki_history_page", "render_wiki_index_page",
    "render_wiki_page_view", "render_wiki_preview",
]


class WikiWebError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def _web_error(exc: WikiError) -> WikiWebError:
    return WikiWebError(exc.reason, str(exc))


@dataclass(frozen=True)
class WikiIndex:
    full_name: str
    pages: tuple[WikiPage, ...]      # ordinary pages only
    sidebar: WikiPage | None         # standing Sidebar, if any
    footer: WikiPage | None          # standing Footer, if any

    @property
    def has_pages(self) -> bool:
        return bool(self.pages or self.sidebar or self.footer)


@dataclass(frozen=True)
class WikiPageView:
    full_name: str
    page: WikiPage                   # the viewed page, body included
    body_html: str                   # S-107 rendering of the body
    pages: tuple[WikiPage, ...]      # ordinary pages, for navigation
    sidebar: WikiPage | None
    sidebar_html: str                # "" when no sidebar stands
    footer: WikiPage | None
    footer_html: str                 # "" when no footer stands


@dataclass(frozen=True)
class WikiPreview:
    full_name: str
    name: str                        # canonical page name
    content: str                     # the draft, verbatim
    body_html: str                   # S-107 rendering of the draft


@dataclass(frozen=True)
class WikiHistoryEntry:
    oid: str
    parents: tuple[str, ...]
    author_name: str
    author_email: str
    author_time: int
    subject: str
    message: str
    pages: tuple[str, ...]           # page names this commit changed


@dataclass(frozen=True)
class WikiHistory:
    full_name: str
    page_title: str | None           # canonical filter, or None
    total_commits: int
    page: int
    per_page: int
    total_pages: int
    entries: tuple[WikiHistoryEntry, ...]

    @property
    def has_previous(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages

_SEP = "\x1f"
_REC = "\x1e"
_LOG_FORMAT = _SEP.join(
    ["%H", "%P", "%an", "%ae", "%at", "%s", "%b"]) + _REC


class WikiWeb:
    """The wiki web experience over one `WikiStore`.

    Constructed like the store itself; pass a standing
    `WikiStore` to share one, or let this face build
    its own from the same seams."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        wiki: WikiStore | None = None,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._repos = repositories
        self._wiki = wiki or WikiStore(
            conn, repositories, audit=audit, time_fn=time_fn)

    # -- plumbing ---------------------------------------

    def _call(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except WikiError as exc:
            raise _web_error(exc) from None

    @staticmethod
    def _split(pages: list[WikiPage]):
        regular = tuple(
            p for p in pages if p.name.lower() not in _SPECIAL_LOWER)
        sidebar = next(
            (p for p in pages
             if p.name.lower() == SIDEBAR_PAGE.lower()), None)
        footer = next(
            (p for p in pages
             if p.name.lower() == FOOTER_PAGE.lower()), None)
        return regular, sidebar, footer

    def _read_special(self, viewer, owner, repo, standing):
        """A standing special page's body, or None when
        it does not stand. Any other storage refusal
        (above all `repo_not_found`) propagates."""
        if standing is None:
            return None
        try:
            return self._wiki.read_page(
                viewer, owner, repo, standing.name)
        except WikiError as exc:
            if exc.reason == "page_not_found":
                return None
            raise _web_error(exc) from None

    # -- the page list ------------------------------------

    def index(self, viewer: User | None, owner: object,
              repo: object) -> WikiIndex:
        """The wiki's page list: ordinary pages in
        canonical order, the sidebar and footer named
        apart. Read-gated through S-273 (a private
        repository answers `repo_not_found`); listing
        never creates the wiki."""
        pages = self._call(
            self._wiki.list_pages, viewer, owner, repo)
        regular, sidebar, footer = self._split(pages)
        repository = self._repos.get_repository(owner, repo)
        full = repository.full_name if repository else ""
        return WikiIndex(
            full_name=full, pages=regular,
            sidebar=sidebar, footer=footer)

    # -- viewing -------------------------------------------

    def view_page(self, viewer: User | None, owner: object,
                  repo: object,
                  title: object = None) -> WikiPageView:
        """One page rendered for reading, with the
        standing sidebar and footer rendered beside
        it. No title names the landing page (`Home`).
        A missing page -- including a missing Home --
        answers `page_not_found`."""
        wanted = HOME_PAGE if title is None else title
        page = self._call(
            self._wiki.read_page, viewer, owner, repo, wanted)
        pages = self._call(
            self._wiki.list_pages, viewer, owner, repo)
        regular, sidebar_row, footer_row = self._split(pages)
        sidebar = self._read_special(viewer, owner, repo, sidebar_row)
        footer = self._read_special(viewer, owner, repo, footer_row)
        repository = self._repos.get_repository(owner, repo)
        full = repository.full_name if repository else ""
        return WikiPageView(
            full_name=full, page=page,
            body_html=render_markdown(page.content),
            pages=regular, sidebar=sidebar,
            sidebar_html=(render_markdown(sidebar.content)
                          if sidebar is not None else ""),
            footer=footer,
            footer_html=(render_markdown(footer.content)
                         if footer is not None else ""))

    # -- editing: preview, then save ------------------------

    def preview_page(self, viewer: User | None, owner: object,
                     repo: object, title: object,
                     content: object) -> WikiPreview:
        """Render a draft **without writing anything**.
        Judged by read access through S-273's listing
        (which creates nothing); the draft is validated
        by the same title and size law a save would
        meet, so a preview never promises what a save
        would refuse."""
        self._call(self._wiki.list_pages, viewer, owner, repo)
        try:
            name = normalize_page_title(title)
        except WikiError as exc:
            raise _web_error(exc) from None
        if not isinstance(content, str):
            raise WikiWebError(
                "page_invalid", "A wiki page body is Markdown text.")
        if len(content.encode("utf-8")) > PAGE_MAX:
            raise WikiWebError(
                "page_too_large",
                f"A wiki page is at most {PAGE_MAX} bytes of "
                "Markdown text.")
        repository = self._repos.get_repository(owner, repo)
        full = repository.full_name if repository else ""
        return WikiPreview(
            full_name=full, name=name, content=content,
            body_html=render_markdown(content))

    def save_page(self, actor: User | None, owner: object,
                  repo: object, title: object, content: object,
                  *, message: object = None,
                  expected_oid: object = None) -> WikiPage:
        """The edit-in-browser save door: S-273's
        `write_page` itself, with its writer law and
        its `page_conflict` for a tip that moved under
        the editor. Returns the standing page."""
        return self._call(
            self._wiki.write_page, actor, owner, repo, title,
            content, message=message, expected_oid=expected_oid)

    # -- history: the wiki repo's own log -------------------

    def _changed_pages(self, path, oid: str) -> tuple[str, ...]:
        result = run_git_in(
            path, ["diff-tree", "--no-commit-id",
                   "--name-status", "-r", "--root", oid],
            timeout=15.0)
        if result.returncode != 0:
            return ()
        names: list[str] = []
        for line in result.stdout.decode(
                "utf-8", "surrogateescape").splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            for filename in parts[1:]:
                if filename.lower().endswith(".md"):
                    name = filename[: -len(".md")]
                    if name not in names:
                        names.append(name)
        return tuple(names)

    def history(self, viewer: User | None, owner: object,
                repo: object, title: object = None,
                page: object = 1,
                per_page: object = DEFAULT_HISTORY_PER_PAGE
                ) -> WikiHistory:
        """The wiki's history, read from the wiki
        repository's own `git log`, newest first.
        `title` filters to one page's commits (a
        deleted page's history still reads). A wiki
        that does not stand yet answers an honest
        empty history; reading it creates nothing."""
        # Read gate first (S-273): an unreadable
        # repository's wiki history is repo_not_found,
        # and the gate itself creates nothing.
        self._call(self._wiki.list_pages, viewer, owner, repo)
        current = self._repos.get_repository(owner, repo)
        assert current is not None
        full = current.full_name
        wanted: str | None = None
        if title is not None:
            try:
                wanted = normalize_page_title(title)
            except WikiError as exc:
                raise _web_error(exc) from None
        try:
            page_no = max(1, int(page))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            page_no = 1
        try:
            page_size = int(per_page)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            page_size = DEFAULT_HISTORY_PER_PAGE
        page_size = min(MAX_HISTORY_PER_PAGE, max(1, page_size))

        def _empty() -> WikiHistory:
            return WikiHistory(
                full_name=full, page_title=wanted,
                total_commits=0, page=page_no,
                per_page=page_size, total_pages=0, entries=())

        path = wiki_path_for(self._repos, current)
        if not WikiStore._is_bare_wiki(path):
            return _empty()
        head = run_git_in(
            path, ["rev-parse", "--verify", "--quiet",
                   f"refs/heads/{current.default_branch}"],
            timeout=15.0)
        if head.returncode != 0:
            return _empty()
        tip = head.stdout.decode("utf-8", "replace").strip()
        result = run_git_in(
            path, ["log", f"--format={_LOG_FORMAT}", tip],
            timeout=30.0)
        if result.returncode != 0:
            raise WikiWebError(
                "wiki_unreadable",
                "git could not read the wiki history.")
        entries: list[WikiHistoryEntry] = []
        for record in result.stdout.decode(
                "utf-8", "replace").split(_REC):
            record = record.strip("\n")
            if not record:
                continue
            fields = record.split(_SEP)
            if len(fields) != 7:
                raise WikiWebError(
                    "wiki_unreadable",
                    "Wiki history output could not be read.")
            oid, parents, name, email, when, subject, body = fields
            entries.append(WikiHistoryEntry(
                oid=oid,
                parents=tuple(parents.split()) if parents else (),
                author_name=name, author_email=email,
                author_time=int(when or 0), subject=subject,
                message=(subject + ("\n\n" + body.strip("\n")
                                    if body.strip("\n") else "")),
                pages=()))
        if wanted is not None:
            lowered = wanted.lower()
            entries = [
                e for e in entries
                if lowered in {
                    p.lower()
                    for p in self._changed_pages(path, e.oid)}]
            entries = [
                WikiHistoryEntry(
                    oid=e.oid, parents=e.parents,
                    author_name=e.author_name,
                    author_email=e.author_email,
                    author_time=e.author_time, subject=e.subject,
                    message=e.message,
                    pages=self._changed_pages(path, e.oid))
                for e in entries]
        total = len(entries)
        total_pages = (
            (total + page_size - 1) // page_size if total else 0)
        start = (page_no - 1) * page_size
        window = entries[start:start + page_size]
        if wanted is None:
            window = [
                WikiHistoryEntry(
                    oid=e.oid, parents=e.parents,
                    author_name=e.author_name,
                    author_email=e.author_email,
                    author_time=e.author_time, subject=e.subject,
                    message=e.message,
                    pages=self._changed_pages(path, e.oid))
                for e in window]
        return WikiHistory(
            full_name=full, page_title=wanted,
            total_commits=total, page=page_no,
            per_page=page_size, total_pages=total_pages,
            entries=tuple(window))


def _page_href(full_name: str, page_name: str) -> str:
    return (
        f"/{escape_html_attr(full_name)}/wiki/"
        f"{escape_html_attr(page_name)}")


def _nav_html(view: WikiPageView) -> str:
    if not view.pages:
        return ""
    items = "".join(
        f'<li><a href="{_page_href(view.full_name, p.name)}">'
        f"{escape_html_text(p.name)}</a></li>"
        for p in view.pages)
    return f'<nav class="wiki-pages"><ul>{items}</ul></nav>'


def render_wiki_index_page(index: WikiIndex) -> str:
    """The page-list page (S-010-escaped): ordinary
    pages as links, the sidebar and footer named in
    their own slots, and the honest empty state."""
    full = escape_html_text(index.full_name)
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{full} \u2014 wiki \u2014 Samverk</title></head>",
        "<body>",
        f"<h1>Wiki \u2014 {full}</h1>",
    ]
    if not index.has_pages:
        parts.append(
            '<p class="empty">This wiki has no pages yet. '
            "Its wiki is its own git repository, created "
            "lazily on the first page.</p>")
    else:
        if index.pages:
            items = "".join(
                f'<li data-page="{escape_html_attr(p.name)}">'
                f'<a href="{_page_href(index.full_name, p.name)}">'
                f"{escape_html_text(p.name)}</a> "
                f"({p.size} bytes)</li>"
                for p in index.pages)
            parts.append(f'<ul class="wiki-page-list">{items}</ul>')
        else:
            parts.append(
                '<p class="empty">No ordinary pages yet.</p>')
        if index.sidebar is not None:
            parts.append(
                f'<p class="wiki-special">Sidebar page: '
                f'<a href="{_page_href(index.full_name, index.sidebar.name)}">'
                f"{escape_html_text(index.sidebar.name)}</a></p>")
        if index.footer is not None:
            parts.append(
                f'<p class="wiki-special">Footer page: '
                f'<a href="{_page_href(index.full_name, index.footer.name)}">'
                f"{escape_html_text(index.footer.name)}</a></p>")
    parts.append("</body></html>")
    return "\n".join(parts)


def render_wiki_page_view(view: WikiPageView) -> str:
    """One wiki page for reading: the S-107-rendered
    body, the standing sidebar in an aside and the
    standing footer in the footer when they stand,
    and the ordinary-page navigation."""
    full = escape_html_text(view.full_name)
    title = escape_html_text(view.page.name)
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{title} \u2014 {full} wiki \u2014 Samverk</title></head>",
        "<body>",
        _nav_html(view),
        f"<h1>{title}</h1>",
        f'<article class="wiki-body">{view.body_html}</article>',
    ]
    if view.sidebar is not None:
        parts.append(
            f'<aside class="wiki-sidebar">{view.sidebar_html}</aside>')
    if view.footer is not None:
        parts.append(
            f'<footer class="wiki-footer">{view.footer_html}</footer>')
    parts.append(
        '<p class="wiki-history-link"><a href="'
        + f"/{escape_html_attr(view.full_name)}/wiki/history"
        + '">History</a></p>')
    parts.append("</body></html>")
    return "\n".join(parts)


def render_wiki_preview(preview: WikiPreview) -> str:
    """The preview fragment: the draft rendered, and
    the words that it is a preview -- nothing saved."""
    return (
        f'<section class="wiki-preview" data-page="'
        f'{escape_html_attr(preview.name)}">'
        '<p class="preview-note">Preview — nothing has '
        "been saved.</p>"
        f'<article class="wiki-body">{preview.body_html}</article>'
        "</section>")


def render_wiki_edit_form(full_name: str, page_name: str,
                          content: str,
                          expected_oid: str | None) -> str:
    """The edit-in-browser form: the standing body in
    a textarea (S-010-escaped) and the tip the editor
    read carried as the expected oid, so the save
    meets S-273's conflict law."""
    expected = (
        f'<input type="hidden" name="expected_oid" value="'
        f'{escape_html_attr(expected_oid)}">'
        if expected_oid else "")
    return (
        f'<form class="wiki-edit" method="post" action="'
        f"/{escape_html_attr(full_name)}/wiki/"
        f'{escape_html_attr(page_name)}/edit">'
        f"<h1>Edit {escape_html_text(page_name)}</h1>"
        f"{expected}"
        f'<textarea name="content" rows="20" cols="80">'
        f"{escape_html_text(content)}</textarea>"
        '<label>Commit message <input type="text" '
        'name="message"></label>'
        '<button type="submit" name="action" '
        'value="preview">Preview</button>'
        '<button type="submit" name="action" '
        'value="save">Save</button>'
        "</form>")


def render_wiki_history_page(history: WikiHistory) -> str:
    """The history page: rows from the wiki repo's
    own log, each naming its commit, subject, author
    and the pages it changed, with honest totals."""
    full = escape_html_text(history.full_name)
    heading = "Wiki history"
    if history.page_title is not None:
        heading += f" \u2014 {escape_html_text(history.page_title)}"
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{heading} \u2014 {full} \u2014 Samverk</title></head>",
        "<body>",
        f"<h1>{heading} \u2014 {full}</h1>",
        f'<p class="meta">{history.total_commits} commits</p>',
    ]
    if not history.entries:
        parts.append(
            '<p class="empty">No commits on this page. '
            "The wiki's history starts at its first page.</p>")
    else:
        parts.append('<ol class="wiki-history">')
        for entry in history.entries:
            changed = ", ".join(
                escape_html_text(p) for p in entry.pages)
            changed_html = (
                f' <span class="changed-pages">{changed}</span>'
                if changed else "")
            parts.append(
                f'<li class="commit"><span class="oid">'
                f"{escape_html_text(entry.oid[:12])}</span> "
                f'<span class="subject">'
                f"{escape_html_text(entry.subject)}</span> "
                f'<span class="author">'
                f"{escape_html_text(entry.author_name)}</span>"
                f"{changed_html}</li>")
        parts.append("</ol>")
    parts.append("</body></html>")
    return "\n".join(parts)
