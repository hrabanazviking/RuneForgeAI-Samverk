"""Keyboard baseline (S-111).

Global shortcuts for navigation and search, documented on
one help page, and never trapping keyboard users.

- **The registry is the law.** `SHORTCUTS` is a frozen
  tuple; every binding the client script may honour is
  named here with its action, its context, and a plain
  description. A binding not in the registry does not
  exist. Two bindings may not share a key in the same
  context (asserted by the battery and at import).
- **Never trapping is structural, not a promise.** Every
  shortcut carries `active_when_typing=False`: a binding
  fires only when focus is NOT in a text input, textarea,
  select, or content-editable element, so typing the
  letter `t` in a comment can never yank the author to
  the file finder. No shortcut uses a key the browser or
  a screen reader owns (no Ctrl/Alt system chords beyond
  the search-focus slash, which is inert while typing),
  and `Escape` always returns focus to the page body —
  that row is in the registry too, so the help page can
  promise it in words.
- **One help page.** `render_keyboard_help_page` lists
  every binding from the registry itself, grouped by
  context — the page cannot drift from the law because
  it is rendered *from* the law. The `?` key opens it
  (outside a text field, like every other binding).
- No inline script: the bindings ship as data attributes
  and a manifest (`shortcut_manifest`) for the external
  client script S-111's page shell loads under S-016's
  CSP; this module renders no `<script>` at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from .escaping import escape_html_text


@dataclass(frozen=True)
class Shortcut:
    keys: str               # e.g. "t", "/", "?", "Escape", "g h"
    action: str             # stable action name
    description: str        # plain words for the help page
    context: str            # 'global' | 'repository'
    active_when_typing: bool = False


SHORTCUTS: tuple[Shortcut, ...] = (
    Shortcut("?", "open_keyboard_help",
             "Open this keyboard shortcuts page.", "global"),
    Shortcut("/", "focus_search",
             "Move focus to the search box on the page, if it has one.",
             "global"),
    Shortcut("Escape", "release_focus",
             "Leave a menu, dialog, or text field and return focus "
             "to the page.", "global"),
    Shortcut("t", "open_file_finder",
             "Open the file finder for this repository (S-110).",
             "repository"),
    Shortcut("g c", "go_to_code",
             "Go to this repository's code (file browser).", "repository"),
    Shortcut("g i", "go_to_issues",
             "Go to this repository's issues.", "repository"),
    Shortcut("g p", "go_to_pull_requests",
             "Go to this repository's pull requests.", "repository"),
)

_CONTEXT_ORDER = ("global", "repository")
_CONTEXT_TITLES = {"global": "Everywhere",
                   "repository": "Inside a repository"}


def _check_registry() -> None:
    seen: set[tuple[str, str]] = set()
    for s in SHORTCUTS:
        key = (s.context, s.keys)
        if key in seen:
            raise ValueError(f"duplicate shortcut {key}")
        seen.add(key)
        if s.active_when_typing:
            raise ValueError(
                f"shortcut {s.keys!r} would fire while typing — "
                "the baseline forbids trapping keyboard users")


_check_registry()


def shortcuts_for(context: str | None = None) -> tuple[Shortcut, ...]:
    if context is None:
        return SHORTCUTS
    return tuple(s for s in SHORTCUTS
                 if s.context in ("global", context))


def shortcut_manifest(context: str | None = None) -> tuple[dict, ...]:
    """The bindings as plain data for the external client
    script — the same registry, never a second list."""
    return tuple(
        {"keys": s.keys, "action": s.action, "context": s.context,
         "active_when_typing": s.active_when_typing}
        for s in shortcuts_for(context))


def render_keyboard_help_page() -> str:
    """The one help page, rendered from the registry."""
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        "<title>Keyboard shortcuts — Samverk</title></head>",
        "<body>",
        "<h1>Keyboard shortcuts</h1>",
        "<p>Shortcuts work when you are not typing in a text "
        "field. While you are typing, every letter is yours — "
        "no shortcut fires. Press <kbd>Escape</kbd> at any "
        "time to leave a field, menu, or dialog and return "
        "focus to the page.</p>",
    ]
    for context in _CONTEXT_ORDER:
        group = [s for s in SHORTCUTS if s.context == context]
        if not group:
            continue
        parts.append(
            f"<h2>{escape_html_text(_CONTEXT_TITLES[context])}</h2>")
        parts.append('<table class="shortcuts"><thead><tr>'
                     "<th>Keys</th><th>What it does</th></tr>"
                     "</thead><tbody>")
        for s in group:
            keys_html = " then ".join(
                f"<kbd>{escape_html_text(k)}</kbd>"
                for k in s.keys.split(" "))
            parts.append(
                f"<tr><td>{keys_html}</td>"
                f"<td>{escape_html_text(s.description)}</td></tr>")
        parts.append("</tbody></table>")
    parts.append("</body></html>")
    return "\n".join(parts)
