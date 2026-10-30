"""Search box in repo scope (S-118).

A search box that lives inside a repository and jumps
to the instance's code search already filtered to that
repository — the reader never has to know a qualifier
exists to search just this code, and can see exactly
how the filter is written when they want to change it.

- **The jump contract is fixed here; Part X owns the
  results.** The box is a plain GET form (no script)
  submitting to the search page (S-213's global UI,
  over S-208's code search) with `type=code` and a `q`
  whose first qualifier is `repo:{owner}/{name}`.
  `extract_repo_scope` is the other half of the
  contract — the seam Part X consumes to turn a query
  back into (scope, remaining terms). This slice does
  not build a results page and does not pretend to.
- **The scope is visible, never magic.** The input is
  prefilled with the qualifier itself and the hint
  under the box names the repository and says how to
  search everywhere instead (delete the qualifier).
  A filter the user cannot see is a filter they cannot
  correct.
- **A malformed scope refuses, never silently
  unscopes.** `extract_repo_scope` raises on a `repo:`
  token that does not name exactly one valid
  owner/name pair: quietly dropping it would widen the
  search past what the user asked for, and widening is
  the dangerous direction. Permission filtering of the
  results themselves is Part X's law (S-209); this
  box grants nothing — like S-112's chrome, whose
  placement decision it inherits, the permission-aware
  entry point (`search_box_for`) answers a stranger to
  a private repository with the uniform `repo_not_found`
  and renders no box at all.
- Terms are hygiene-cleaned, not interpreted: control
  characters are stripped and whitespace collapsed, so
  what the box submits is one line a human typed.
  Names ride S-013's law, as everywhere.
"""

from __future__ import annotations

from urllib.parse import quote_plus

from .accounts import User
from .escaping import escape_html_attr, escape_html_text
from .permissions import can_read
from .repo_paths import RepoPathError, validate_owner_name, validate_repo_name
from .repositories import RepositoryStore

SEARCH_PATH = "/search"
SCOPE_PREFIX = "repo:"


class SearchBoxError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def _names(owner: object, repo: object) -> tuple[str, str]:
    try:
        return validate_owner_name(owner), validate_repo_name(repo)
    except RepoPathError as exc:
        raise SearchBoxError("name_invalid", str(exc)) from None


def clean_terms(terms: object) -> str:
    """One typed line: controls stripped, whitespace
    collapsed. Anything else is the search engine's to
    interpret (Part X), not this box's."""
    text = terms if isinstance(terms, str) else ""
    kept = "".join(c for c in text if c == " " or (ord(c) >= 32 and ord(c) != 127))
    return " ".join(kept.split())


def scoped_query(owner: object, repo: object, terms: object = "") -> str:
    """The pre-filtered query: the repo qualifier first,
    then the reader's own words."""
    owner_name, repo_name = _names(owner, repo)
    words = clean_terms(terms)
    qualifier = f"{SCOPE_PREFIX}{owner_name}/{repo_name}"
    return f"{qualifier} {words}" if words else qualifier


def repo_search_url(owner: object, repo: object, terms: object = "") -> str:
    """Where the box jumps: the instance search page,
    code type, pre-filtered to this repository."""
    query = quote_plus(scoped_query(owner, repo, terms))
    return f"{SEARCH_PATH}?q={query}&type=code"


def extract_repo_scope(query: object) -> tuple[str, str, str] | None:
    """The Part X seam: pull the `repo:` qualifier out of
    a query. Returns (owner, repo, remaining terms), or
    None when the query carries no scope. A malformed
    qualifier raises `scope_invalid` — it is never
    dropped silently (see the module docstring)."""
    text = query if isinstance(query, str) else ""
    tokens = text.split()
    for index, token in enumerate(tokens):
        if not token.startswith(SCOPE_PREFIX):
            continue
        value = token[len(SCOPE_PREFIX):]
        owner, slash, repo = value.partition("/")
        if not slash or "/" in repo:
            raise SearchBoxError(
                "scope_invalid",
                f"The repo: qualifier {value!r} does not name "
                "exactly one repository (owner/name).")
        owner_name, repo_name = _names(owner, repo)
        rest = " ".join(tokens[:index] + tokens[index + 1:])
        return owner_name, repo_name, rest
    return None


def render_repo_search_box(owner: object, repo: object,
                           *, terms: object = "") -> str:
    """The box itself: a labelled GET form, the qualifier
    visible in the input, and the widening instruction
    in plain words under it. Every value passes S-010."""
    owner_name, repo_name = _names(owner, repo)
    full = f"{owner_name}/{repo_name}"
    value = scoped_query(owner_name, repo_name, terms)
    if not clean_terms(terms):
        value += " "  # caret lands after the qualifier, ready to type
    return "\n".join([
        f'<form class="repo-search" method="get" action="{SEARCH_PATH}" '
        'role="search">',
        f'<label>Search this repository '
        f'<input type="search" name="q" '
        f'value="{escape_html_attr(value)}"></label>',
        '<input type="hidden" name="type" value="code">',
        '<button type="submit">Search</button>',
        f'<p class="search-scope">Searching only '
        f"{escape_html_text(full)} — to search everywhere, "
        f"delete the {SCOPE_PREFIX}{escape_html_text(full)} "
        "part.</p>",
        "</form>",
    ])


def search_box_for(repositories: RepositoryStore, viewer: User | None,
                   owner: object, repo: object, *,
                   terms: object = "") -> str:
    """The permission-aware entry point: the box for a
    repository the viewer may read, and the uniform
    `repo_not_found` (no box, no hint the repository
    exists) for everyone else — S-112's placement law."""
    current = repositories.get_repository(owner, repo)
    if current is None or not can_read(viewer, current):
        raise SearchBoxError("repo_not_found", "No such repository.")
    return render_repo_search_box(current.owner, current.name, terms=terms)
