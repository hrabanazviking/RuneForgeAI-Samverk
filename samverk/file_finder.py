"""File finder (S-110).

Fuzzy path search within a repository — the `t` habit:
press `t` on a repository page (S-111's keyboard baseline
owns the binding), type fragments of a path, land on the
file. Keyboard-first means the finder is a plain GET form
whose input carries `autofocus`, the results are ordinary
links in ranked order (so the first result is the first
Tab stop and Enter follows it), and no result ever needs
a mouse or a script to reach.

- **The file list is read from git, at the pinned ref.**
  One `git ls-tree -r --name-only -z` spawn through S-014
  lists every blob path at the commit the requested ref
  resolved to (S-097's `resolve_commit`); submodule
  gitlinks are not files a visitor can open here and are
  excluded by listing blobs only via `-r` on trees —
  ls-tree -r lists blobs and gitlinks alike, so entries
  are filtered through a second `--format` pass is avoided
  by using `-r` with type filtering in `list_file_paths`
  below (see its note).
- **Fuzzy means subsequence, scored honestly.** A query
  matches when its characters appear in order inside the
  path (case-insensitive). The score rewards what a human
  means: an exact basename, a basename prefix, a
  contiguous substring, matches at segment starts, and
  consecutive runs; it penalises length and depth so a
  short shallow file beats a long scattered one. Ties
  break by path, so ranking is deterministic.
- **Limits are named, never silent.** At most
  `MAX_RESULTS` (100) results return, with the true match
  total alongside; a truncated answer says so in its data
  and on its page. The repository walk itself is capped
  (`MAX_PATHS`); a repo past the cap answers
  `too_many_files` by name rather than timing out a page.
- Permission is S-054's one function through S-097's
  shared shape: an unreadable and a missing repository
  answer identically (`repo_not_found`).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .accounts import User
from .escaping import escape_html_attr, escape_html_text
from .permissions import can_read
from .proc import run_git_in
from .repo_home import RepoHomeError, resolve_commit
from .repositories import RepositoryStore

MAX_RESULTS = 100
DEFAULT_LIMIT = 50
MAX_PATHS = 100_000
MAX_QUERY_CHARS = 200


class FinderError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class FinderMatch:
    path: str
    score: int


@dataclass(frozen=True)
class FinderResult:
    full_name: str
    owner: str
    name: str
    current_ref: str
    commit_oid: str
    query: str
    matches: tuple[FinderMatch, ...]
    total_matches: int
    total_files: int
    truncated: bool


def _wrap(fn):
    try:
        return fn()
    except RepoHomeError as exc:
        raise FinderError(exc.reason, str(exc)) from None


def score_path(query: str, path: str) -> int | None:
    """Fuzzy score of *path* for *query*, or None when the
    query is not a subsequence of the path. Both inputs are
    compared lowercased; the caller passes a normalised
    query (stripped, non-empty)."""
    q = query.lower()
    p = path.lower()
    # Subsequence check, recording positions.
    positions: list[int] = []
    start = 0
    for ch in q:
        idx = p.find(ch, start)
        if idx < 0:
            return None
        positions.append(idx)
        start = idx + 1
    basename = p.rsplit("/", 1)[-1]
    score = 100
    # Contiguity: a single contiguous run is the strongest
    # signal after exactness.
    if q in p:
        score += 400
    if q in basename:
        score += 300
    if basename == q:
        score += 1000
    elif basename.startswith(q):
        score += 500
    # Segment-start and consecutive bonuses.
    for i, pos in enumerate(positions):
        if pos == 0 or p[pos - 1] == "/":
            score += 40
        if i and pos == positions[i - 1] + 1:
            score += 25
    # Spread penalty: scattered matches rank below tight ones.
    if positions:
        score -= (positions[-1] - positions[0] + 1 - len(q)) * 3
    # Shorter and shallower paths win ties of intent.
    score -= len(p)
    score -= p.count("/") * 5
    return score


def rank_paths(query: str, paths: list[str]) -> list[FinderMatch]:
    """Every matching path, best first; ties break by path
    so the order is deterministic across runs."""
    scored: list[FinderMatch] = []
    for path in paths:
        s = score_path(query, path)
        if s is not None:
            scored.append(FinderMatch(path=path, score=s))
    scored.sort(key=lambda m: (-m.score, m.path))
    return scored


class FileFinder:
    def __init__(self, repositories: RepositoryStore):
        self._repos = repositories

    def list_file_paths(self, repo_path: Path, commit_oid: str) -> list[str]:
        """Every blob path at *commit_oid*, sorted. Uses
        `ls-tree -r -z` with `--format` carrying the object
        type so gitlinks (mode 160000) can be excluded —
        a submodule is not a file this finder can open."""
        result = run_git_in(
            repo_path,
            ["ls-tree", "-r", "-z",
             "--format=%(objecttype)%x00%(path)", commit_oid],
            timeout=60.0)
        if result.returncode != 0:
            raise FinderError(
                "tree_read_failed",
                result.stderr.decode("utf-8", "replace").strip()[:200])
        paths: list[str] = []
        # With -z the stream is: type NUL path NUL type NUL
        # path … — split on NUL and walk the fields in pairs.
        fields = result.stdout.split(b"\x00")
        # Trailing empty field after the final NUL.
        if fields and fields[-1] == b"":
            fields.pop()
        if len(fields) % 2 != 0:
            raise FinderError("tree_read_failed", "ls-tree output did not parse")
        for i in range(0, len(fields), 2):
            obj_type = fields[i].decode("ascii", "replace")
            raw = fields[i + 1]
            # The first field of the stream may carry a
            # leading newline-free type; paths decode lossily
            # only for display — git paths are bytes, and the
            # surrogateescape round-trip keeps them exact for
            # later URL building in this slice's own tests.
            path = raw.decode("utf-8", "surrogateescape")
            if obj_type == "blob":
                paths.append(path)
            if len(paths) > MAX_PATHS:
                raise FinderError(
                    "too_many_files",
                    f"This repository has more than {MAX_PATHS} files; "
                    "the finder cannot list them all.")
        paths.sort()
        return paths

    def find(self, viewer: User | None, owner: object, repo: object,
             query: object = "", ref: object = None,
             limit: object = None) -> FinderResult:
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise FinderError("repo_not_found", "No such repository.")
        text = "" if query is None else str(query)
        if len(text) > MAX_QUERY_CHARS:
            raise FinderError(
                "query_too_long",
                f"A finder query is at most {MAX_QUERY_CHARS} characters.")
        if any(ord(c) < 0x20 or ord(c) == 0x7F for c in text):
            raise FinderError("query_invalid", "The query carries control characters.")
        text = text.strip()
        try:
            lim = DEFAULT_LIMIT if limit is None else int(limit)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise FinderError("limit_invalid", "The result limit is not a number.") from None
        lim = max(1, min(MAX_RESULTS, lim))
        repo_path = self._repos.path_for(current.owner, current.name)
        requested = current.default_branch if ref is None else ref
        ref_name, commit_oid = _wrap(lambda: resolve_commit(repo_path, requested))
        paths = self.list_file_paths(repo_path, commit_oid)
        if not text:
            ranked = [FinderMatch(path=p, score=0) for p in paths]
        else:
            ranked = rank_paths(text, paths)
        total = len(ranked)
        shown = tuple(ranked[:lim])
        return FinderResult(
            full_name=current.full_name, owner=current.owner,
            name=current.name, current_ref=ref_name,
            commit_oid=commit_oid, query=text, matches=shown,
            total_matches=total, total_files=len(paths),
            truncated=total > len(shown))


def render_finder_page(result: FinderResult) -> str:
    """The finder page: a GET form (autofocused, labelled),
    then the ranked results as ordinary blob links pinned
    at the viewed ref. Every user value passes S-010."""
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Find a file in {escape_html_text(result.full_name)} — Samverk</title></head>",
        "<body>",
        f"<h1>Find a file in {escape_html_text(result.full_name)}</h1>",
        '<p class="hint">Keyboard: press <kbd>t</kbd> on a repository '
        "page to come here, type part of a path, then Tab to the "
        "results and Enter to open one. Matching is fuzzy: the "
        "letters you type must appear in order in the path.</p>",
        f'<form method="get" action="/{escape_html_attr(result.owner)}/'
        f'{escape_html_attr(result.name)}/find/{escape_html_attr(result.current_ref)}" '
        'role="search">',
        '<label for="finder-q">File path</label> ',
        f'<input id="finder-q" name="q" type="search" autofocus '
        f'value="{escape_html_attr(result.query)}" '
        f'maxlength="{MAX_QUERY_CHARS}"> ',
        '<button type="submit">Find</button></form>',
    ]
    if result.total_files == 0:
        parts.append(
            '<p class="empty">This repository has no files at this '
            "ref yet. Push a first commit, then come back to search.</p>")
    elif result.total_matches == 0:
        parts.append(
            f'<p class="empty">No file matches '
            f"{escape_html_text(result.query)!r}. Try fewer letters, "
            "or the start of the file name.</p>")
    else:
        parts.append(
            f"<p>Showing {len(result.matches)} of "
            f"{result.total_matches} matching files "
            f"(of {result.total_files} files in this repository).</p>")
        if result.truncated:
            parts.append(
                "<p>More files match than are shown. Add more "
                "letters to narrow the search.</p>")
        parts.append('<ul class="finder-results">')
        for match in result.matches:
            href = (f"/{result.owner}/{result.name}/blob/"
                    f"{result.current_ref}/{match.path}")
            parts.append(
                f'<li><a href="{escape_html_attr(href)}">'
                f"{escape_html_text(match.path)}</a></li>")
        parts.append("</ul>")
    parts.append("</body></html>")
    return "\n".join(parts)
