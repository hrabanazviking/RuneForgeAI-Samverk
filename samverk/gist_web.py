"""Gist web editor (S-278).

Roadmap S-278: Gist create and edit -- web editor,
public or secret (unlisted-but-linkable, honestly
named -- "secret" gists are not private and the UI
says so).

This slice is the creating and editing face over
S-277's model (`samverk/gists.py`: `GistStore`).
The store stays the only writer: every save here is
`GistStore.create_gist` / `update_gist`, every read
is `get_gist` / `list_files` / `read_file` /
`list_gists`, so the one filename law, the file-set
law, the expected-tip conflict (`gist_conflict`)
and the owner-only write doors are inherited whole
and never re-judged.

The laws:

- **The choice, in honest words.** The create and
  edit forms offer exactly the store's two
  visibilities as radio choices, each labelled with
  the store's own words (`PUBLIC_WORDS` /
  `SECRET_WORDS`): public means anyone can find and
  read the gist; secret means unlisted but **not
  private** -- anyone who has the link can read it.
  No face anywhere in this slice calls a secret
  gist private, hidden-from-readers, or protected,
  and the standing view of a secret gist repeats
  the warning, so the honesty is not only at the
  moment of choosing. The form's offered default is
  public, matching the store's create default.
- **Create.** A signed-in user creates a gist from
  the editor: one description, the visibility
  choice, and one or more files, each a name and a
  text body. The editor's file list is a list of
  (name, body) pairs -- a form may carry two rows
  with colliding names, and the collision reaches
  the store as a mapping with a case-insensitive
  duplicate only if the rows truly name one file;
  two rows naming the same file (case-insensitively)
  are refused here as `file_duplicate` before the
  store is asked, so no row is ever silently
  dropped. An anonymous visitor is refused
  `permission_denied` by the store, unchanged.
- **Edit.** The edit face loads the standing gist
  whole: description, visibility, and every file's
  standing body, together with the tip the editor
  read (`expected_oid`). A save names the full
  standing file set -- a file the editor removes
  is removed by the save's one new revision, in
  the open, exactly as the store's update law
  states -- plus any description or visibility
  change as metadata. A gist that moved under the
  editor answers `gist_conflict` and the draft is
  refused whole, never merged silently. Changing
  only the description or only the visibility
  writes no revision (the store's metadata act).
- **View.** The standing view shows the one
  description, the visibility in its honest words,
  and every file's body as escaped text. Reading
  is the store's S-278 read law: public and secret
  alike are readable by link, by anyone; the view
  of a secret gist carries the not-private warning
  on its face.
- **Rendering.** Everything a user supplied
  (descriptions, file names, file bodies) reaches
  the page only through S-010's escaping seam, in
  text and in attribute places alike; file bodies
  render as plain escaped text in a <pre>, never
  through a markup pipeline, so a gist holding
  HTML shows that HTML as text.

Gist acts carry no verb of their own in the frozen
taxonomy vocabulary and are not witnessed (S-277's
law, unchanged): no new taxonomy event -- 133
stand (33 auth / 87 repo / 13 admin). The editor
stores nothing of its own; the visibility choice
is migration 109's column, and the schema stands
at 109.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_attr, escape_html_text
from .gists import (
    PUBLIC_WORDS, SECRET_WORDS, VISIBILITY_PUBLIC,
    VISIBILITY_SECRET, Gist, GistError, GistFile,
    GistStore, visibility_words,
)

__all__ = [
    "GistEditView", "GistView", "GistWeb", "GistWebError",
    "editor_files_to_mapping", "render_gist_create_form",
    "render_gist_edit_form", "render_gist_list_page",
    "render_gist_view_page",
]


class GistWebError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def _web_error(exc: GistError) -> GistWebError:
    return GistWebError(exc.reason, str(exc))


def editor_files_to_mapping(
        pairs: object) -> dict[str, str]:
    """The editor's file rows, judged as a set: a list
    of (name, body) pairs becomes the store's mapping.
    Two rows naming one file case-insensitively are
    refused `file_duplicate` -- no row is dropped in
    silence. Anything that is not a list of pairs is
    `file_invalid`; the store judges the rest."""
    if not isinstance(pairs, (list, tuple)):
        raise GistWebError(
            "file_invalid", "A gist file body is text.")
    out: dict[str, str] = {}
    seen: set[str] = set()
    for pair in pairs:
        if (not isinstance(pair, (list, tuple))
                or len(pair) != 2):
            raise GistWebError(
                "file_invalid", "A gist file body is text.")
        name, body = pair
        if not isinstance(name, str) or not isinstance(body, str):
            raise GistWebError(
                "file_invalid", "A gist file body is text.")
        key = name.strip().lower()
        if key in seen:
            raise GistWebError(
                "file_duplicate",
                f"Two gist files share the name {name!r} "
                "(file names are judged case-insensitively).")
        seen.add(key)
        out[name] = body
    return out


@dataclass(frozen=True)
class GistView:
    gist: Gist
    files: tuple[GistFile, ...]   # standing bodies, name order
    can_edit: bool                # viewer owns it (or is admin)


@dataclass(frozen=True)
class GistEditView:
    gist: Gist
    files: tuple[GistFile, ...]   # standing bodies, name order
    expected_oid: str | None      # the tip the editor read


class GistWeb:
    """The gist editor face over one `GistStore`."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        data_root: Path,
        accounts: AccountStore,
        gists: GistStore | None = None,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._gists = gists or GistStore(
            conn, data_root, accounts, audit=audit,
            time_fn=time_fn)

    def _call(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except GistError as exc:
            raise _web_error(exc) from None

    # -- create --------------------------------------

    def create_gist(self, actor: User | None,
                    description: object, visibility: object,
                    pairs: object, *,
                    message: object = None) -> Gist:
        """Create from the editor: the (name, body) rows
        become the store's file mapping, the choice is
        the store's judged visibility."""
        files = editor_files_to_mapping(pairs)
        return self._call(
            self._gists.create_gist, actor, description,
            files, message=message, visibility=visibility)

    # -- read -----------------------------------------

    def view_gist(self, viewer: User | None,
                  gist_id: object) -> GistView:
        gist = self._call(self._gists.get_gist, viewer, gist_id)
        files = tuple(
            self._call(self._gists.read_file, viewer, gist.id, f.name)
            for f in self._call(
                self._gists.list_files, viewer, gist.id))
        can_edit = (viewer is not None
                    and (viewer.id == gist.owner_id
                         or viewer.is_admin))
        return GistView(gist=gist, files=files, can_edit=can_edit)

    def list_gists(self, viewer: User | None,
                   owner: object) -> list[Gist]:
        return self._call(self._gists.list_gists, viewer, owner)

    # -- edit ------------------------------------------

    def edit_view(self, actor: User | None,
                  gist_id: object) -> GistEditView:
        """The editor's load: only a writer may open the
        editor -- a non-owner signed-in user is refused
        permission_denied here, not merely at the save."""
        gist = self._call(self._gists.get_gist, actor, gist_id)
        if not (actor is not None
                and (actor.id == gist.owner_id or actor.is_admin)):
            raise GistWebError(
                "permission_denied",
                "Only the gist's owner can change this gist.")
        files = tuple(
            self._call(self._gists.read_file, actor, gist.id, f.name)
            for f in self._call(
                self._gists.list_files, actor, gist.id))
        return GistEditView(
            gist=gist, files=files, expected_oid=gist.head_oid)

    def save_gist(self, actor: User | None, gist_id: object, *,
                  description: object = None,
                  visibility: object = None,
                  pairs: object = None,
                  message: object = None,
                  expected_oid: object = None) -> Gist:
        """Save from the editor. `pairs` names the full
        standing file set (None leaves the files as
        they stand); description and visibility ride
        as the store's metadata acts."""
        files = (editor_files_to_mapping(pairs)
                 if pairs is not None else None)
        return self._call(
            self._gists.update_gist, actor, gist_id,
            description=description, files=files,
            message=message, expected_oid=expected_oid,
            visibility=visibility)


# -- rendering -------------------------------------------


def _visibility_radios(selected: str) -> str:
    pub = ' checked' if selected == VISIBILITY_PUBLIC else ''
    sec = ' checked' if selected == VISIBILITY_SECRET else ''
    return (
        '<fieldset class="gist-visibility-choice">'
        '<legend>Visibility</legend>'
        f'<label><input type="radio" name="visibility" '
        f'value="public"{pub}> '
        f'{escape_html_text(PUBLIC_WORDS)}</label>'
        f'<label><input type="radio" name="visibility" '
        f'value="secret"{sec}> '
        f'{escape_html_text(SECRET_WORDS)}</label>'
        '</fieldset>')


def render_gist_create_form() -> str:
    """The create form: one description, the honest
    visibility choice (public offered first and
    selected, the store's default), and file rows of
    name + body."""
    return (
        '<form class="gist-create" method="post" action="/gists">'
        '<h1>New gist</h1>'
        '<label>Description <input type="text" '
        'name="description"></label>'
        + _visibility_radios(VISIBILITY_PUBLIC)
        + '<div class="gist-file-row">'
        '<label>File name <input type="text" '
        'name="filename"></label>'
        '<textarea name="content" rows="10" cols="80"></textarea>'
        '</div>'
        '<button type="submit">Create gist</button>'
        '</form>')


def render_gist_edit_form(view: GistEditView) -> str:
    """The edit form: the standing description, the
    standing visibility choice in its honest words,
    every standing file as a name + body row, and the
    tip the editor read carried as the expected oid,
    so the save meets the store's conflict law."""
    gist = view.gist
    expected = (
        f'<input type="hidden" name="expected_oid" value="'
        f'{escape_html_attr(view.expected_oid)}">'
        if view.expected_oid else '')
    rows = ''.join(
        '<div class="gist-file-row">'
        f'<label>File name <input type="text" name="filename" '
        f'value="{escape_html_attr(f.name)}"></label>'
        f'<textarea name="content" rows="10" cols="80">'
        f'{escape_html_text(f.content)}</textarea></div>'
        for f in view.files)
    return (
        f'<form class="gist-edit" method="post" '
        f'action="/gists/{gist.id}/edit">'
        f'<h1>Edit gist {gist.id}</h1>'
        f'{expected}'
        f'<label>Description <input type="text" '
        f'name="description" value="'
        f'{escape_html_attr(gist.description)}"></label>'
        + _visibility_radios(gist.visibility)
        + rows
        + '<label>Commit message <input type="text" '
        'name="message"></label>'
        '<button type="submit">Save gist</button>'
        '</form>')


def render_gist_view_page(view: GistView) -> str:
    """One gist for reading: the one description, the
    visibility in its honest words (a secret gist's
    not-private warning stands on its face), and every
    file body as escaped plain text."""
    gist = view.gist
    desc = escape_html_text(gist.description)
    words = escape_html_text(visibility_words(gist.visibility))
    sections = ''.join(
        f'<section class="gist-file" data-file="'
        f'{escape_html_attr(f.name)}">'
        f'<h3>{escape_html_text(f.name)}</h3>'
        f'<pre>{escape_html_text(f.content)}</pre></section>'
        for f in view.files)
    edit = (f'<p class="gist-edit-link"><a href="/gists/'
            f'{gist.id}/edit">Edit this gist</a></p>'
            if view.can_edit else '')
    return (
        '<!DOCTYPE html>'
        '<html lang="en"><head><meta charset="utf-8">'
        f'<title>Gist {gist.id} \u2014 Samverk</title></head>'
        '<body>'
        f'<h1>Gist {gist.id}</h1>'
        f'<p class="gist-owner">by '
        f'{escape_html_text(gist.owner)}</p>'
        f'<p class="gist-description">{desc}</p>'
        f'<p class="gist-visibility">{words}</p>'
        f'{sections}'
        f'<p class="gist-revisions">{gist.revision_count} '
        f'revision(s)</p>'
        f'{edit}'
        '</body></html>')


def render_gist_list_page(owner: str, gists: list[Gist]) -> str:
    """An owner's listed gists as the viewer may see
    them (the store already judged which list): each
    gist named with its visibility, honestly."""
    if not gists:
        items = ('<p class="empty">No gists listed. A secret '
                 'gist is unlisted: it does not appear here '
                 'for anyone but its owner.</p>')
    else:
        items = '<ul>' + ''.join(
            f'<li data-gist="{g.id}">'
            f'<a href="/gists/{g.id}">'
            f'{escape_html_text(g.description)}</a> '
            f'[{escape_html_text(g.visibility)}] '
            f'({g.revision_count} revision(s))</li>'
            for g in gists) + '</ul>'
    return (
        '<!DOCTYPE html>'
        '<html lang="en"><head><meta charset="utf-8">'
        f'<title>{escape_html_text(owner)} \u2014 gists \u2014 '
        'Samverk</title></head><body>'
        f'<h1>Gists \u2014 {escape_html_text(owner)}</h1>'
        f'{items}</body></html>')
