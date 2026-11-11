"""Gist embedding (S-281).

Roadmap S-281: Gist embedding -- a script-free embed
snippet (iframe-free by default, CSP-safe) for blogs
and Samtal posts.

GitHub's gist embed is a ``<script>`` tag: the host
page loads foreign JavaScript that rewrites the page
around it. That shape is refused here whole -- it
cannot survive S-016's Content-Security-Policy (no
inline or foreign scripts on a Samverk page), and a
sovereign forge does not ask a blog to run its code
to quote a gist. This slice, standing on S-277's
model, S-278's visibility law and the faces in
``samverk/gists.py`` / ``samverk/gist_web.py``, gives
a gist three embed forms instead, all of them plain
text a host pastes once:

- **HTML (the default).** A static, self-contained
  HTML fragment: a ``<section>`` carrying the gist's
  one description, every embedded file's body as
  escaped plain text in ``<pre><code>``, and a footer
  link back to the gist. No ``<script>``, no
  ``<iframe>``, no event-handler attributes, no
  inline styles, no ``javascript:`` URLs -- nothing
  a strict CSP (S-016's included) refuses, and
  nothing left to fetch: the snippet still reads
  whole if the instance is down. File bodies render
  as text, never through a markup pipeline, exactly
  as the gist view renders them (S-278), so a gist
  holding HTML embeds as visible HTML text.
- **Markdown (for Samtal posts).** The same content
  as a Markdown quote: the description and owner as
  one quoted line, each file under its name in a
  fenced block (the fence grows past any fence the
  body itself contains), and the gist's link. A
  Samtal post -- or any Markdown blog -- carries the
  gist's words with no HTML at all.
- **Iframe (explicit opt-in only).** For a host that
  wants the gist framed live instead of quoted, one
  ``<iframe>`` naming the standalone embed document
  this slice renders (``render_gist_embed_document``:
  a complete page whose only payload is the HTML
  embed, served under ``default-src 'none'`` in its
  own meta policy, needing no script, style or
  fetch). The iframe carries a ``title``, ``loading=
  "lazy"`` and ``sandbox="allow-same-origin"`` -- no
  scripts are granted, because the document has none
  -- and stands beside a plain link, so a host that
  refuses iframes still leaves a working reference.
  This form exists only when a caller names it; the
  default never emits an iframe.

The laws:

- **Embedding is a read.** It follows S-278's read
  law whole, through ``GistStore``'s own doors: a
  public or a secret gist is embeddable by anyone
  who reaches it by its id, signed in or not, and an
  unknown id is the uniform ``gist_not_found`` for
  every embed operation. Embedding a secret gist is
  sharing its link -- the snippet for a secret gist
  carries S-278's not-private words on its face, so
  the honesty travels with the quote. An embed is a
  snapshot or a frame of what the gist's readers may
  already read; it widens nothing.
- **Standing or pinned.** By default the HTML and
  Markdown snippets quote the gist's standing files.
  A caller may pin ``revision`` (one commit of the
  gist's own history, judged by the store, so an oid
  outside the history is ``revision_not_found``) and
  the snippet quotes that revision and says so,
  naming the pinned oid -- a blog post can quote the
  gist as it stood and not drift as the gist moves.
  A caller may also name one ``file`` to embed alone
  (the store's filename law; a missing file is
  ``file_not_found``).
- **The base is judged.** Snippet links are built on
  a caller-named ``base_url`` -- the instance's own
  address as the host knows it. Empty means
  instance-relative links (``/gists/<id>``), the
  right shape on the instance itself and in Samtal.
  A named base must pass S-010's ``safe_url`` and be
  ``http``/``https`` or instance-relative; anything
  else (``javascript:``, ``data:``, protocol-relative,
  a ``mailto:`` wearing a base's clothes) is refused
  ``base_url_invalid`` before any link is built.
- **Unwitnessed, as every gist act is.** Embedding
  carries no verb of its own in the frozen taxonomy
  vocabulary (S-277's law, unchanged): the store
  accepts an audit handle for house symmetry and
  appends nothing -- no new taxonomy event, 133
  stand (33 auth / 87 repo / 13 admin).

Storage: none of its own. The embed is rendered at
read time from the gist's git storage and migration
108's metadata row; the schema stands at 111. The
web face lives in ``samverk/gist_web.py``.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_attr, escape_html_text, safe_url
from .gists import Gist, GistError, GistFile, GistStore, visibility_words

FORM_HTML = "html"
FORM_MARKDOWN = "markdown"
FORM_IFRAME = "iframe"
EMBED_FORMS = (FORM_HTML, FORM_MARKDOWN, FORM_IFRAME)

__all__ = [
    "EMBED_FORMS", "FORM_HTML", "FORM_IFRAME",
    "FORM_MARKDOWN", "GistEmbed", "GistEmbedStore",
    "embed_to_dict", "gist_embed_url",
    "gist_embed_document_url", "render_embed_html",
    "render_embed_iframe", "render_embed_markdown",
    "render_embed_panel", "render_gist_embed_document",
    "validate_base_url", "validate_embed_form",
]


def validate_base_url(base_url: object) -> str:
    """The embed base, judged: empty (instance-relative
    links), an ``http``/``https`` absolute base, or an
    instance-relative path base, with no trailing
    slash. Anything S-010's ``safe_url`` refuses -- and
    anything that is not a place a gist can live, such
    as a ``mailto:`` -- is ``base_url_invalid``."""
    if base_url is None:
        return ""
    if not isinstance(base_url, str):
        raise GistError(
            "base_url_invalid", "An embed base is text.")
    base = base_url.strip().rstrip("/")
    if not base:
        return ""
    if any(c.isspace() for c in base):
        raise GistError(
            "base_url_invalid",
            "An embed base carries no whitespace.")
    if safe_url(base) is None:
        raise GistError(
            "base_url_invalid",
            "An embed base is an http(s) address or an "
            "instance-relative path.")
    if base.startswith("/"):
        return base
    lowered = base.lower()
    if lowered.startswith(("http://", "https://")):
        return base
    raise GistError(
        "base_url_invalid",
        "An embed base is an http(s) address or an "
        "instance-relative path.")


def validate_embed_form(form: object) -> str:
    """The embed form, judged: exactly one of
    ``EMBED_FORMS`` -- the default is the iframe-free
    HTML snippet, and the iframe exists only when it
    is named."""
    if form not in EMBED_FORMS:
        raise GistError(
            "embed_form_invalid",
            "An embed is html, markdown or iframe; "
            "html is the default.")
    return str(form)


def gist_embed_url(gist_id: int, base_url: str = "") -> str:
    """The gist's own address on *base_url* (already
    judged): where every embed form links back to."""
    return f"{base_url}/gists/{gist_id}"


def gist_embed_document_url(gist_id: int,
                            base_url: str = "") -> str:
    """The standalone embed document's address: the
    one URL the opt-in iframe form names."""
    return f"{base_url}/gists/{gist_id}/embed"


@dataclass(frozen=True)
class GistEmbed:
    gist: Gist
    files: tuple[GistFile, ...]  # embedded bodies, name order
    url: str                     # the gist's own address
    document_url: str            # the embed document's address
    revision: str | None = None  # pinned oid, None = standing
    single_file: str | None = None  # the one file named, if any

    @property
    def is_pinned(self) -> bool:
        return self.revision is not None


def embed_to_dict(embed: GistEmbed) -> dict:
    return {
        "gist_id": embed.gist.id,
        "owner": embed.gist.owner,
        "description": embed.gist.description,
        "visibility": embed.gist.visibility,
        "url": embed.url,
        "document_url": embed.document_url,
        "revision": embed.revision,
        "single_file": embed.single_file,
        "files": [f.name for f in embed.files],
    }


def render_embed_html(embed: GistEmbed) -> str:
    """The default snippet: a static ``<section>`` --
    description, honest visibility words, every file
    as escaped plain text, a pinned note when pinned,
    and the footer link home. No script, no iframe,
    no handler, no inline style: CSP-safe by
    construction, and every user-supplied value
    reaches it only through S-010."""
    gist = embed.gist
    sections = "".join(
        f'<section class="gist-embed-file" data-file="'
        f'{escape_html_attr(f.name)}">'
        f"<h4>{escape_html_text(f.name)}</h4>"
        f"<pre><code>{escape_html_text(f.content)}"
        f"</code></pre></section>"
        for f in embed.files)
    pinned = (
        f'<p class="gist-embed-pinned">Pinned at revision '
        f"{escape_html_text(embed.revision or '')}</p>"
        if embed.is_pinned else "")
    return (
        f'<section class="gist-embed" data-gist="{gist.id}">'
        f'<p class="gist-embed-description">'
        f"{escape_html_text(gist.description)}</p>"
        f'<p class="gist-embed-owner">Gist {gist.id} by '
        f"{escape_html_text(gist.owner)}</p>"
        f'<p class="gist-embed-visibility">'
        f"{escape_html_text(visibility_words(gist.visibility))}"
        f"</p>"
        f"{sections}{pinned}"
        f'<p class="gist-embed-link"><a href="'
        f'{escape_html_attr(embed.url)}">View gist '
        f"{gist.id} on Samverk</a></p></section>")


def _markdown_fence(body: str) -> str:
    fence = "```"
    while fence in body:
        fence += "`"
    return fence


def _markdown_line(text: str) -> str:
    """One line of Markdown prose: newlines fold to
    spaces, so a description cannot break the quote
    it rides in."""
    return " ".join(text.splitlines()).strip()


def _markdown_url(url: str) -> str:
    return (url.replace(" ", "%20")
            .replace("(", "%28").replace(")", "%29"))


def render_embed_markdown(embed: GistEmbed) -> str:
    """The Samtal form: the gist as a Markdown quote --
    description and owner on one quoted line, the
    honest visibility words, each file fenced under
    its name, a pinned note when pinned, and the
    gist's link. No HTML rides in this form at all."""
    gist = embed.gist
    lines = [
        f"> **Gist {gist.id}** by {_markdown_line(gist.owner)}"
        f" \u2014 {_markdown_line(gist.description)}",
        f"> {visibility_words(gist.visibility)}",
    ]
    for f in embed.files:
        fence = _markdown_fence(f.content)
        lines += ["", f"**{f.name}**", fence,
                  f.content, fence]
    if embed.is_pinned:
        lines += ["", f"Pinned at revision {embed.revision}."]
    lines += ["", f"[View gist {gist.id} on Samverk]"
                  f"({_markdown_url(embed.url)})"]
    return "\n".join(lines)


def render_embed_iframe(embed: GistEmbed) -> str:
    """The opt-in framed form, and the only form that
    ever emits an ``<iframe>``: sandboxed to
    same-origin with no script grant (the document it
    names has no scripts), lazily loaded, titled for
    assistive technology, and followed by the plain
    link for hosts that refuse iframes."""
    gist = embed.gist
    return (
        f'<iframe class="gist-embed-frame" src="'
        f'{escape_html_attr(embed.document_url)}" '
        f'title="Gist {gist.id} by '
        f'{escape_html_attr(gist.owner)}" loading="lazy" '
        f'sandbox="allow-same-origin"></iframe>'
        f'<p class="gist-embed-link"><a href="'
        f'{escape_html_attr(embed.url)}">View gist '
        f"{gist.id} on Samverk</a></p>")


def render_gist_embed_document(embed: GistEmbed) -> str:
    """The standalone embed document: a complete page
    whose only payload is the HTML embed, declaring
    ``default-src 'none'`` in its own meta policy --
    it needs no script, no style and no fetch, and it
    says so to the browser in those words."""
    gist = embed.gist
    return (
        "<!DOCTYPE html>"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta http-equiv="Content-Security-Policy" '
        'content="default-src \'none\'">'
        f"<title>Gist {gist.id} \u2014 Samverk embed</title>"
        "</head><body>"
        + render_embed_html(embed)
        + "</body></html>")


def render_embed_panel(snippet: str) -> str:
    """The gist view's embed panel: the default HTML
    snippet in a read-only text area -- escaped as
    text, so what the owner copies is the snippet
    itself, byte for byte -- under words that say
    plainly what it is: script-free, iframe-free."""
    return (
        '<section class="gist-embed-panel"><h2>Embed '
        "this gist</h2>"
        "<p>Paste this snippet into a blog or a Samtal "
        "post. It is plain HTML: no script and no "
        "iframe, safe under a strict "
        "Content-Security-Policy.</p>"
        f'<textarea class="gist-embed-snippet" readonly '
        f'rows="8" cols="80">{escape_html_text(snippet)}'
        "</textarea></section>")


_RENDERERS = {
    FORM_HTML: render_embed_html,
    FORM_MARKDOWN: render_embed_markdown,
    FORM_IFRAME: render_embed_iframe,
}


class GistEmbedStore:
    """The embed face over one `GistStore`: every read
    is the store's own (`get_gist` / `list_files` /
    `read_file`), so the read law, the filename law
    and the revision law are inherited whole and
    never re-judged."""

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
        self._audit = audit

    def build_embed(self, viewer: User | None, gist_id: object,
                    *, base_url: object = "",
                    file: object = None,
                    revision: object = None) -> GistEmbed:
        """Assemble one embed: the gist as *viewer* may
        read it (the uniform ``gist_not_found`` for an
        unknown id), its standing files or its files at
        the pinned ``revision``, whole or the one named
        ``file``, on the judged ``base_url``."""
        base = validate_base_url(base_url)
        gist = self._gists.get_gist(viewer, gist_id)
        if file is not None:
            found = self._gists.read_file(
                viewer, gist.id, file, revision=revision)
            files = (found,)
            single = found.name
            pinned = found.commit_oid if revision is not None else None
        else:
            files = tuple(
                self._gists.read_file(
                    viewer, gist.id, f.name, revision=revision)
                for f in self._gists.list_files(
                    viewer, gist.id, revision=revision))
            single = None
            pinned = (files[0].commit_oid if files
                      and revision is not None else None)
        return GistEmbed(
            gist=gist, files=files,
            url=gist_embed_url(gist.id, base),
            document_url=gist_embed_document_url(gist.id, base),
            revision=pinned, single_file=single)

    def snippet(self, viewer: User | None, gist_id: object, *,
                form: object = FORM_HTML,
                base_url: object = "",
                file: object = None,
                revision: object = None) -> str:
        """One embed snippet in the named form (the
        iframe-free HTML snippet by default)."""
        judged = validate_embed_form(form)
        embed = self.build_embed(
            viewer, gist_id, base_url=base_url, file=file,
            revision=revision)
        return _RENDERERS[judged](embed)

    def embed_document(self, viewer: User | None,
                       gist_id: object, *,
                       base_url: object = "",
                       file: object = None,
                       revision: object = None) -> str:
        """The standalone document the iframe form
        names, rendered for *viewer*'s read of the
        gist."""
        embed = self.build_embed(
            viewer, gist_id, base_url=base_url, file=file,
            revision=revision)
        return render_gist_embed_document(embed)
