"""Repository home (S-097) — Part V opens.

The repository home is the page a visitor lands on: the root
file listing, the README rendered at the root, a branch/tag
switcher, and the clone addresses for both transports with
copy buttons. Four laws shape it — the same laws every Part V
surface inherits:

- **Permission first, one shape for missing.** S-054's
  `can_read` gates the home exactly as it gates the
  transports: a repository the viewer cannot read and one
  that does not exist answer identically (`repo_not_found`),
  so a private repo's existence never leaks through its home
  page.
- **Refs are resolved, never trusted.** The requested ref
  (branch, tag, HEAD, full ref, or object id) is validated
  (no leading dash, no `..`) and resolved through S-052
  before any object is read; an unknown ref is refused by
  name (`ref_not_found`). The home reports the commit oid
  the ref resolved to, so later slices can pin permalinks
  to it.
- **Rendering goes through the one seam.** Every
  user-controlled value — repo name, description, file
  names, README text — reaches HTML only via S-010's
  escaping functions. The README renders through S-107's
  full Markdown pipeline (`samverk/markdown_pipeline.py`),
  which replaced this module's interim renderer without
  changing the home's shape, exactly as S-097 promised;
  S-108 wires repo-relative links into it through the
  pipeline's resolver seam.
- **Transports are told honestly.** Clone addresses are
  built from the instance's configured transport bases,
  exactly as S-065's empty state builds them: a transport
  the instance has not configured produces no address at
  all and is named in `unavailable_transports`, never a
  guessed address. Copy buttons are plain buttons carrying
  a `data-copy-target` hook for the client script S-111's
  keyboard baseline brings — no inline script (S-016's CSP
  forbids it), and the address itself is always visible in
  a read-only field so copying by hand always works.

An empty repository still has a home: it reports
`is_empty`, lists nothing, carries no README, and its page
says what to do next (S-065's instructions own the detail).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .accounts import User
from .escaping import escape_html_attr, escape_html_text
from .objects import ObjectReader, TreeEntry
from .permissions import can_read
from .refs import RefError, RefStore
from .repositories import RepositoryStore

_OID_RE = re.compile(r"^[0-9a-f]{40}$|^[0-9a-f]{64}$")

# README candidates at the repository root, in the order a
# visitor expects them tried. Matching is case-insensitive.
README_CANDIDATES = ("readme.md", "readme.markdown", "readme.txt",
                     "readme.rst", "readme")


class RepoHomeError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


# -- shared Part V helpers (S-098..S-100 build on these) -----------

def validate_ref(ref: object) -> str:
    """A ref as S-063 validates it: HEAD, a full refs/… name,
    a branch/tag short name, or a full object id. Anything
    git could read as a flag is refused."""
    if ref is None:
        return "HEAD"
    text = str(ref)
    if _OID_RE.match(text.lower()):
        return text.lower()
    if text == "HEAD" or text.startswith("refs/"):
        try:
            from .refs import validate_ref_name
            return validate_ref_name(text, full=text.startswith("refs/"))
        except RefError:
            raise RepoHomeError(
                "ref_invalid", f"Not a ref name: {text!r}") from None
    try:
        from .refs import validate_ref_name
        return validate_ref_name(text)
    except RefError:
        raise RepoHomeError(
            "ref_invalid", f"Not a ref name: {text!r}") from None


def resolve_commit(repo_path: Path, ref: object) -> tuple[str, str]:
    """(requested_ref, commit_oid) — resolved through S-052,
    refusing an unknown ref by name."""
    ref_name = validate_ref(ref)
    oid = RefStore(repo_path).resolve(ref_name)
    if oid is None:
        raise RepoHomeError(
            "ref_not_found", f"No such ref in this repository: {ref_name!r}")
    return ref_name, oid


def validate_repo_path(path: object) -> tuple[str, ...]:
    """A repo-relative path as path components. Empty means the
    root. Absolute paths, `..`, empty components, backslashes
    and control characters are refused — a path can never
    climb out of the tree it names."""
    if path is None:
        return ()
    text = str(path)
    if text in ("", "/"):
        return ()
    if text.startswith("/") or "\\" in text or any(
            ord(c) < 0x20 or ord(c) == 0x7F for c in text):
        raise RepoHomeError("path_invalid", f"Not a repository path: {text!r}")
    parts = tuple(p for p in text.split("/"))
    if any(p in ("", ".", "..") for p in parts):
        raise RepoHomeError("path_invalid", f"Not a repository path: {text!r}")
    return parts


def tree_at(reader: ObjectReader, commit_oid: str,
            parts: tuple[str, ...]) -> list[TreeEntry]:
    """The entries of the tree at *parts* under *commit_oid*,
    walking tree objects only. A missing component is
    `path_not_found`; a component that is a file where a
    directory was needed is the same answer."""
    commit = reader.read_commit(commit_oid)
    entries = reader.read_tree(commit.tree)
    for part in parts:
        match = next((e for e in entries if e.name == part), None)
        if match is None or match.type != "tree":
            raise RepoHomeError(
                "path_not_found", f"No such directory: {'/'.join(parts)!r}")
        entries = reader.read_tree(match.oid)
    return entries


def blob_at(reader: ObjectReader, commit_oid: str,
            parts: tuple[str, ...]) -> TreeEntry:
    """The blob entry at *parts*, resolved by walking to its
    parent tree — never by trusting a caller-supplied oid."""
    if not parts:
        raise RepoHomeError("path_invalid", "A file path is required.")
    parent = tree_at(reader, commit_oid, parts[:-1])
    match = next((e for e in parent if e.name == parts[-1]), None)
    if match is None:
        raise RepoHomeError(
            "path_not_found", f"No such file: {'/'.join(parts)!r}")
    if match.type != "blob":
        raise RepoHomeError(
            "not_a_file", f"That path is not a file: {'/'.join(parts)!r}")
    return match


# -- the home --------------------------------------------------------

@dataclass(frozen=True)
class CloneOption:
    transport: str          # 'https' | 'ssh'
    url: str


@dataclass(frozen=True)
class Readme:
    name: str               # as it appears at the root
    text: str               # raw source, decoded lossily
    html: str               # rendered through the S-010 seam


@dataclass(frozen=True)
class RepoHome:
    full_name: str
    owner: str
    name: str
    description: str
    visibility: str
    default_branch: str
    current_ref: str
    commit_oid: str | None        # None only for an empty repo
    branches: tuple[str, ...]
    tags: tuple[str, ...]
    entries: tuple[TreeEntry, ...]
    readme: Readme | None
    clone_options: tuple[CloneOption, ...]
    unavailable_transports: tuple[str, ...]
    is_empty: bool


def render_readme_html(text: str, *,
                       link_resolver=None,
                       reference_resolver=None) -> str:
    """README rendering, owned by S-107's Markdown pipeline
    since that slice replaced the interim renderer this
    function used to carry. The signature's shape is S-097's;
    the resolver seams are the pipeline's own (S-108/S-109)."""
    from .markdown_pipeline import render_markdown
    return render_markdown(text, link_resolver=link_resolver,
                           reference_resolver=reference_resolver)


class RepoHomeService:
    def __init__(self, repositories: RepositoryStore, *,
                 http_base: str | None = None,
                 ssh_host: str | None = None,
                 ssh_user: str = "git"):
        self._repos = repositories
        self._http_base = self._clean_http_base(http_base)
        self._ssh_host = self._clean_ssh_host(ssh_host)
        if not ssh_user or any(c in ssh_user for c in " @/:"):
            raise RepoHomeError("ssh_user_invalid", "Bad SSH user.")
        self._ssh_user = ssh_user

    def home_for(self, viewer: User | None, owner: object,
                 repo: object, ref: object = None) -> RepoHome:
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise RepoHomeError("repo_not_found", "No such repository.")
        path = self._repos.path_for(current.owner, current.name)
        ref_store = RefStore(path)
        branches = tuple(r.short for r in ref_store.list_branches())
        tags = tuple(r.short for r in ref_store.list_tags())
        clone_options, unavailable = self._clone_options(current)
        head_oid = ref_store.head_oid()
        if head_oid is None and not ref_store.list_refs():
            # Empty repo: a home with no ref to resolve yet. An
            # explicitly requested ref is still an honest refusal.
            if ref is not None:
                raise RepoHomeError(
                    "ref_not_found",
                    f"No such ref in this repository: {ref!r}")
            return RepoHome(
                full_name=current.full_name, owner=current.owner,
                name=current.name, description=current.description,
                visibility=current.visibility,
                default_branch=current.default_branch,
                current_ref=current.default_branch, commit_oid=None,
                branches=branches, tags=tags, entries=(), readme=None,
                clone_options=clone_options,
                unavailable_transports=unavailable, is_empty=True)
        requested = current.default_branch if ref is None else ref
        ref_name, commit_oid = resolve_commit(path, requested)
        reader = ObjectReader(path)
        entries = tuple(tree_at(reader, commit_oid, ()))
        readme = self._readme(reader, entries, current, commit_oid, path)
        return RepoHome(
            full_name=current.full_name, owner=current.owner,
            name=current.name, description=current.description,
            visibility=current.visibility,
            default_branch=current.default_branch,
            current_ref=ref_name, commit_oid=commit_oid,
            branches=branches, tags=tags, entries=entries,
            readme=readme, clone_options=clone_options,
            unavailable_transports=unavailable, is_empty=False)

    # -- pieces -----------------------------------------------------
    def _readme(self, reader: ObjectReader,
                entries: tuple[TreeEntry, ...], current,
                commit_oid: str, repo_path: Path) -> Readme | None:
        by_lower = {e.name.lower(): e for e in entries if e.type == "blob"}
        for candidate in README_CANDIDATES:
            entry = by_lower.get(candidate)
            if entry is None:
                continue
            raw = reader.read_blob(entry.oid)
            text = raw.decode("utf-8", "replace")
            # S-108: the README lives at the root, and its
            # relative links resolve against the pinned commit.
            # S-109: mentions and commit SHAs in its prose link
            # only where the account store / this repository
            # prove the target exists; #issues stay text until
            # Part VI wires its store into the same seam.
            from .prose_references import make_reference_resolver
            from .repo_links import make_link_resolver
            resolver = make_link_resolver(
                owner=current.owner, name=current.name, ref=commit_oid)
            references = make_reference_resolver(
                accounts=getattr(self._repos, "_accounts", None),
                owner=current.owner, name=current.name,
                repo_path=repo_path)
            return Readme(name=entry.name, text=text,
                          html=render_readme_html(
                              text, link_resolver=resolver,
                              reference_resolver=references))
        return None

    def _clone_options(self, current) -> tuple[tuple[CloneOption, ...],
                                               tuple[str, ...]]:
        options: list[CloneOption] = []
        unavailable: list[str] = []
        if self._http_base:
            options.append(CloneOption(
                "https",
                f"{self._http_base}/{current.owner}/{current.name}.git"))
        else:
            unavailable.append("https")
        if self._ssh_host:
            options.append(CloneOption(
                "ssh",
                f"ssh://{self._ssh_user}@{self._ssh_host}/"
                f"{current.owner}/{current.name}.git"))
        else:
            unavailable.append("ssh")
        return tuple(options), tuple(unavailable)

    # -- configuration hygiene (S-065's rules, restated) -------------
    @staticmethod
    def _clean_http_base(value: str | None) -> str | None:
        if value is None:
            return None
        text = str(value).strip().rstrip("/")
        if not (text.startswith("https://") or text.startswith("http://")) \
                or any(c in text for c in " \t\r\n"):
            raise RepoHomeError(
                "http_base_invalid", "The HTTP base must be an http(s) URL.")
        authority = text.split("://", 1)[1].split("/", 1)[0]
        if "@" in authority:
            raise RepoHomeError(
                "http_base_invalid",
                "The HTTP base must not carry credentials.")
        return text

    @staticmethod
    def _clean_ssh_host(value: str | None) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text or any(c in text for c in " \t\r\n/@"):
            raise RepoHomeError(
                "ssh_host_invalid", "The SSH host must be a host[:port].")
        return text


def render_repo_home_page(home: RepoHome) -> str:
    """The repository home page. Every user-controlled value
    passes the S-010 seam; clone buttons are hooks, not inline
    scripts, and every clone address is visible as text."""
    who = escape_html_text(home.full_name)
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{who} — Samverk</title></head>",
        "<body>",
        f"<h1>{who}</h1>",
        f'<p class="visibility">{escape_html_text(home.visibility)}</p>',
    ]
    if home.description:
        parts.append(
            f'<p class="description">{escape_html_text(home.description)}</p>')
    # Branch/tag switcher: one link per ref, the current one
    # marked in words (never colour alone).
    parts.append('<nav class="ref-switcher" aria-label="Branch or tag">')
    parts.append(
        f"<p>Showing: {escape_html_text(home.current_ref)}</p><ul>")
    for label, kind in [(b, "tree") for b in home.branches] + \
            [(t, "tree") for t in home.tags]:
        current = " (current)" if label == home.current_ref else ""
        href = escape_html_attr(f"/{home.owner}/{home.name}/{kind}/{label}")
        parts.append(
            f'<li><a href="{href}">{escape_html_text(label)}</a>'
            f"{escape_html_text(current)}</li>")
    parts.append("</ul></nav>")
    # Clone addresses with copy buttons.
    parts.append('<section class="clone"><h2>Clone</h2>')
    for idx, option in enumerate(home.clone_options):
        field_id = f"clone-url-{idx}"
        parts.append(
            f'<p><label for="{field_id}">'
            f"{escape_html_text(option.transport)}</label> "
            f'<input id="{field_id}" readonly '
            f'value="{escape_html_attr(option.url)}"> '
            f'<button type="button" data-copy-target="{field_id}">'
            "Copy</button></p>")
    for name in home.unavailable_transports:
        parts.append(
            f"<p>The {escape_html_text(name)} transport is not "
            "configured on this instance.</p>")
    parts.append("</section>")
    if home.is_empty:
        parts.append(
            '<p class="empty">This repository is empty. Create the '
            "first commit locally and push it to one of the clone "
            "addresses above.</p>")
    else:
        parts.append('<ul class="entries">')
        for entry in home.entries:
            kind = "directory" if entry.type == "tree" else "file"
            parts.append(
                f'<li class="entry-{escape_html_attr(entry.type)}">'
                f"{escape_html_text(entry.name)} "
                f"<span>({kind})</span></li>")
        parts.append("</ul>")
        if home.readme is not None:
            parts.append('<section class="readme">')
            parts.append(
                f"<h2>{escape_html_text(home.readme.name)}</h2>")
            parts.append(home.readme.html)
            parts.append("</section>")
    parts.append("</body></html>")
    return "\n".join(parts)
