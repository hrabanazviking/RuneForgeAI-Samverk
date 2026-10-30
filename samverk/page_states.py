"""Empty and error states (S-113).

Every list and page has a designed state for "there is
nothing here yet" and for "something went wrong", and
every such state says what to do next (the
user-friendliness law). A blank page, a bare spinner, or
a raw error code alone are all failures of this law.

- **One registry, frozen.** `EMPTY_STATES` names every
  empty surface the web experience has built so far
  (repository home, file browser, commit list, compare,
  contributors, file finder, blob, blame) and the
  designed words for each: a title, an honest explanation
  of *why* it is empty, the next step in words, and one
  action that takes the user there. Adding a surface
  without its empty state is a registry edit a reviewer
  can see; asking for an unregistered surface is a
  programming error and raises, never a silent blank.
- **Errors speak plainly and leak nothing.** Error
  states are built from S-019's registered public codes
  alone — `error_state` takes a code and an optional
  opaque error id, and *no other detail*: there is no
  parameter through which an exception message, a path,
  or a stack trace could reach the page, so leaking one
  is structurally impossible here, not merely avoided.
  The id is shown with the words to quote it when asking
  for help — it is the whole bridge to the server log
  (S-019), and it identifies nothing else.
- **Not-found stays uniform.** The `not_found` words
  cover a repository that does not exist and one the
  viewer may not see in exactly the same sentence
  (S-054's uniform shape): the page never confirms which.
- **Every state has a next step.** A state without
  `next_step` text cannot be constructed — the dataclass
  refuses an empty one — so "you are stuck here" is not
  a state this module can express.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import ERROR_CODES
from .escaping import escape_html_attr, escape_html_text


class PageStateError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class PageState:
    surface: str            # registry key, or the error code
    kind: str               # 'empty' | 'error'
    title: str
    message: str
    next_step: str
    action_label: str
    action_href: str        # may be "" only when kind == 'error'
                            # and no safe destination exists

    def __post_init__(self):
        if not self.title or not self.message or not self.next_step:
            raise PageStateError(
                "state_incomplete",
                "A page state needs a title, an explanation, and "
                "a next step (S-113).")
        if self.kind == "empty" and not (self.action_label
                                         and self.action_href):
            raise PageStateError(
                "state_incomplete",
                "An empty state needs an action that takes the "
                "user to its next step (S-113).")


# surface -> (title, message, next_step, action label,
#             href suffix under the repository base)
_EMPTY_TABLE = {
    "repo_home": (
        "This repository is empty",
        "No commits have been pushed yet, so there is no code "
        "to browse.",
        "Push a first commit — the repository home shows the "
        "exact commands for this repository.",
        "See the first-push instructions", ""),
    "file_browser": (
        "Nothing here yet",
        "This folder has no files at the chosen revision.",
        "Choose another folder or revision above, or add files "
        "with a commit.",
        "Back to the repository root", ""),
    "commit_list": (
        "No commits yet",
        "This revision has no history to list.",
        "Push a first commit, or choose a different branch or "
        "tag above.",
        "Back to the repository home", ""),
    "compare": (
        "No differences",
        "The two revisions you compared have the same files — "
        "nothing changed between them.",
        "Choose a different pair of branches, tags, or commits "
        "to compare.",
        "Back to the repository home", ""),
    "contributors": (
        "No contributors yet",
        "Nobody has committed to this repository, so there is "
        "nothing to count.",
        "Push a first commit and it will be counted here.",
        "Back to the repository home", ""),
    "file_finder": (
        "No files match",
        "No path in this repository matches what you typed.",
        "Shorten what you typed, check the spelling, or browse "
        "the tree instead.",
        "Browse all files", ""),
    "blob": (
        "This file is empty",
        "The file exists, but it holds no content at this "
        "revision.",
        "Open a different revision above, or give the file "
        "content with a commit.",
        "Back to the repository home", ""),
    "blame": (
        "Nothing to attribute",
        "This file has no lines at the chosen revision, so "
        "there is no authorship to show.",
        "Choose another revision, or open the file itself.",
        "Back to the repository home", ""),
}

EMPTY_SURFACES = frozenset(_EMPTY_TABLE)


def empty_state(surface: object, *, base: str = "") -> PageState:
    """The designed empty state for *surface*. *base* is
    the repository's root path (``/{owner}/{repo}``); the
    action href is built under it. An unregistered surface
    raises — a new page must bring its state with it."""
    key = surface if isinstance(surface, str) else None
    if key not in _EMPTY_TABLE:
        raise PageStateError(
            "surface_unknown",
            f"No empty state is designed for {surface!r}; add one "
            "to the S-113 registry with the surface itself.")
    title, message, next_step, label, suffix = _EMPTY_TABLE[key]
    root = "/" + str(base).strip("/")
    if root == "/":
        root = ""
    return PageState(
        surface=key, kind="empty", title=title, message=message,
        next_step=next_step, action_label=label,
        action_href=f"{root}{suffix}" or "/")


# S-019 public code -> (title, message, next step)
_ERROR_TABLE = {
    "bad_request": (
        "That request could not be understood",
        "Something about the request was malformed, so nothing "
        "was changed.",
        "Go back and try again; if it keeps happening, note "
        "the error id below and ask for help."),
    "csrf_failed": (
        "That form could not be accepted",
        "The form's safety token did not check out, so nothing "
        "was changed. This can happen if the page sat open a "
        "long while.",
        "Reload the page and submit the form again."),
    "internal": (
        "Something went wrong on our side",
        "The server hit an unexpected problem and could not "
        "finish. Your data was not changed by this failure.",
        "Try again in a moment; if it keeps happening, note "
        "the error id below and ask for help."),
    "method_not_allowed": (
        "That action is not available here",
        "The address is real, but it does not accept the kind "
        "of request that was sent to it.",
        "Go back and use the links and buttons the page "
        "offers."),
    "not_found": (
        "That page could not be found",
        "It may not exist, or it may belong to a repository "
        "you do not have permission to see — the answer is the "
        "same either way.",
        "Check the address for typos, or go back to the home "
        "page and navigate from there."),
    "rate_limited": (
        "Too many requests just now",
        "This instance limits how fast requests may arrive, "
        "and that limit was reached. Nothing was changed.",
        "Wait a little while, then try again."),
    "unauthorized": (
        "Sign-in needed",
        "This page or action needs a signed-in account, or "
        "the sign-in has expired.",
        "Sign in, then return to what you were doing."),
}


def error_state(code: object, *, error_id: str | None = None) -> PageState:
    """The designed error state for an S-019 public *code*.
    Only the code and the opaque error id are accepted —
    no caller-supplied message exists to leak through."""
    key = code if isinstance(code, str) else None
    if key not in ERROR_CODES or key not in _ERROR_TABLE:
        raise PageStateError(
            "error_code_unknown",
            f"No error state is designed for code {code!r} "
            "(S-019's registry governs).")
    title, message, next_step = _ERROR_TABLE[key]
    label, href = ("Sign in", "/login") if key == "unauthorized" \
        else ("Back to the home page", "/")
    return PageState(
        surface=key, kind="error", title=title,
        message=message if error_id is None else
        f"{message} Error id: {error_id} — quote this id when "
        "you ask for help; it is how the failure can be found "
        "in the server log.",
        next_step=next_step, action_label=label, action_href=href)


def render_state_page(state: PageState) -> str:
    """The page for a state: title, honest explanation,
    next step in words, and the one action. Every value
    passes S-010; no script is ever emitted."""
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{escape_html_text(state.title)} — Samverk</title></head>",
        "<body>",
        f'<main class="page-state page-state-{escape_html_attr(state.kind)}" '
        f'data-surface="{escape_html_attr(state.surface)}">',
        f"<h1>{escape_html_text(state.title)}</h1>",
        f'<p class="state-message">{escape_html_text(state.message)}</p>',
        f'<p class="state-next">What to do next: '
        f"{escape_html_text(state.next_step)}</p>",
    ]
    if state.action_label and state.action_href:
        parts.append(
            f'<p class="state-action"><a href="'
            f'{escape_html_attr(state.action_href)}">'
            f"{escape_html_text(state.action_label)}</a></p>")
    parts.append("</main></body></html>")
    return "\n".join(parts)
