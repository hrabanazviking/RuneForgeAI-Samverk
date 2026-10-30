"""Deep links (S-117).

Every view is URL-addressable, so a link pasted into
chat, an issue, or a document lands exactly where its
author was looking: file at ref at line, one commit,
a comparison.

- **One canonical shape per view, built and parsed by
  this one module.** The builders mint the shapes the
  views already emit (S-099's line permalinks are
  `blob_url(..., line=n)` byte for byte; the finder's
  address is S-112's chrome href) and `parse_deep_link`
  reads them back into a structured `DeepLink`. A link
  that does not round-trip is a bug in this module,
  proven by the battery over every kind.
- **Anchors are line-exact.** A blob link may carry
  `#L{n}` or a range `#L{a}-L{b}`; the grammar is
  strict (positive numbers, a range's end at or after
  its start) and no other view accepts a fragment —
  a fragment on a commit link is refused, not ignored,
  because silently dropping part of a link is how
  links stop landing exactly.
- **The slash limit is named, not hidden.** A branch
  named `feature/x` cannot be told apart from a path
  by URL shape alone, so for the path views (tree,
  blob, raw, blame) the parser takes the first segment
  after the view word as the ref, and the builders
  refuse a ref containing `/` rather than mint a link
  that parses back to something else. Commit-oid
  links — the permalinks — are always unambiguous,
  and the views that take a bare ref with nothing
  after it (commits, compare) accept slashes freely:
  compare's `...` separator cannot appear inside a
  git ref at all, so it is unambiguous by git's own
  law.
- Names ride S-013's law and paths ride S-098's:
  builders validate through `validate_owner_name` /
  `validate_repo_name` / `validate_repo_path` instead
  of inventing a second, weaker shape, and every
  segment is percent-encoded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote, unquote

from .repo_home import RepoHomeError, validate_repo_path
from .repo_paths import RepoPathError, validate_owner_name, validate_repo_name

_OID_RE = re.compile(r"^[0-9a-f]{40}$")
_ANCHOR_RE = re.compile(r"^L(\d+)(?:-L(\d+))?$")
_REF_FORBIDDEN = frozenset(" #?")

PATH_VIEWS = frozenset({"tree", "blob", "raw", "blame"})
PLAIN_VIEWS = frozenset({"summary", "find", "insights"})


class DeepLinkError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class DeepLink:
    kind: str               # home|tree|blob|raw|blame|commit|
                            # commits|compare|summary|find|insights
    owner: str
    repo: str
    ref: str | None = None          # tree/blob/raw/blame/commits
    path: str | None = None         # tree (may be "")/blob/raw/blame
    commit: str | None = None       # commit
    base: str | None = None         # compare
    head: str | None = None         # compare
    line_start: int | None = None   # blob anchor
    line_end: int | None = None     # blob anchor (== start if single)


def _names(owner: object, repo: object) -> tuple[str, str]:
    try:
        return validate_owner_name(owner), validate_repo_name(repo)
    except RepoPathError as exc:
        raise DeepLinkError("name_invalid", str(exc)) from None


def _path(path: object, *, required: bool) -> str:
    try:
        parts = validate_repo_path(path)
    except RepoHomeError as exc:
        raise DeepLinkError("path_invalid", str(exc)) from None
    if required and not parts:
        raise DeepLinkError("path_invalid", "A file path is required.")
    return "/".join(parts)


def _ref(ref: object, *, allow_slash: bool) -> str:
    text = ref if isinstance(ref, str) else ""
    if not text or any(c in _REF_FORBIDDEN or ord(c) < 32 for c in text):
        raise DeepLinkError("ref_invalid", f"Not a usable ref: {ref!r}")
    if not allow_slash and "/" in text:
        raise DeepLinkError(
            "ref_ambiguous",
            f"Ref {text!r} contains a slash; a path-view link "
            "cannot tell it apart from the path. Link by commit "
            "id instead — permalinks are unambiguous.")
    return text


def _enc(segment: str) -> str:
    return quote(segment, safe="-._~")


def _base(owner: object, repo: object) -> tuple[str, str, str]:
    owner_name, repo_name = _names(owner, repo)
    return owner_name, repo_name, f"/{_enc(owner_name)}/{_enc(repo_name)}"


def _anchor(line: object, line_end: object) -> str:
    if line is None:
        if line_end is not None:
            raise DeepLinkError("anchor_invalid",
                                "A range end needs a start line.")
        return ""
    if not isinstance(line, int) or isinstance(line, bool) or line < 1:
        raise DeepLinkError("anchor_invalid",
                            f"Not a line number: {line!r}")
    if line_end is None:
        return f"#L{line}"
    if not isinstance(line_end, int) or isinstance(line_end, bool) \
            or line_end < line:
        raise DeepLinkError("anchor_invalid",
                            "A line range must end at or after it starts.")
    return f"#L{line}-L{line_end}"


def home_url(owner: object, repo: object) -> str:
    return _base(owner, repo)[2]


def tree_url(owner: object, repo: object, ref: object,
             path: object = "") -> str:
    _, _, base = _base(owner, repo)
    ref_name = _ref(ref, allow_slash=False)
    joined = _path(path, required=False)
    url = f"{base}/tree/{_enc(ref_name)}"
    return f"{url}/{_enc_path(joined)}" if joined else url


def _enc_path(joined: str) -> str:
    return "/".join(_enc(seg) for seg in joined.split("/"))


def blob_url(owner: object, repo: object, ref: object, path: object,
             *, line: object = None, line_end: object = None) -> str:
    _, _, base = _base(owner, repo)
    ref_name = _ref(ref, allow_slash=False)
    joined = _path(path, required=True)
    return (f"{base}/blob/{_enc(ref_name)}/{_enc_path(joined)}"
            f"{_anchor(line, line_end)}")


def raw_url(owner: object, repo: object, ref: object, path: object) -> str:
    _, _, base = _base(owner, repo)
    ref_name = _ref(ref, allow_slash=False)
    joined = _path(path, required=True)
    return f"{base}/raw/{_enc(ref_name)}/{_enc_path(joined)}"


def blame_url(owner: object, repo: object, ref: object, path: object) -> str:
    _, _, base = _base(owner, repo)
    ref_name = _ref(ref, allow_slash=False)
    joined = _path(path, required=True)
    return f"{base}/blame/{_enc(ref_name)}/{_enc_path(joined)}"


def commit_url(owner: object, repo: object, commit: object) -> str:
    _, _, base = _base(owner, repo)
    oid = commit if isinstance(commit, str) else ""
    if not _OID_RE.match(oid):
        raise DeepLinkError("commit_invalid",
                            f"Not a commit id: {commit!r}")
    return f"{base}/commit/{oid}"


def commits_url(owner: object, repo: object, ref: object) -> str:
    _, _, base = _base(owner, repo)
    ref_name = _ref(ref, allow_slash=True)
    return f"{base}/commits/{quote(ref_name, safe='-._~/')}"


def compare_url(owner: object, repo: object, base_ref: object,
                head_ref: object) -> str:
    _, _, base = _base(owner, repo)
    base_name = _ref(base_ref, allow_slash=True)
    head_name = _ref(head_ref, allow_slash=True)
    return (f"{base}/compare/"
            f"{quote(base_name, safe='-._~/')}..."
            f"{quote(head_name, safe='-._~/')}")


def plain_url(owner: object, repo: object, kind: object) -> str:
    """summary / find / insights — the repo-scoped pages
    with no ref or path of their own."""
    _, _, base = _base(owner, repo)
    if kind not in PLAIN_VIEWS:
        raise DeepLinkError("kind_unknown", f"Not a plain view: {kind!r}")
    return f"{base}/{kind}"


def parse_file_shorthand(text: object, *, owner: object,
                         repo: object) -> str:
    """The chat form — `docs/guide.md@main#L12` or
    `src/app.py@<commit>` — expanded to the canonical
    blob URL inside one repository. The last `@` is the
    separator (a path may carry earlier ones); the ref
    is required, because the ref is the shorthand's
    whole point."""
    raw = text if isinstance(text, str) else ""
    fragment = ""
    if "#" in raw:
        raw, fragment = raw.split("#", 1)
        fragment = "#" + fragment
    path_part, at, ref = raw.rpartition("@")
    if not at or not path_part or not ref:
        raise DeepLinkError(
            "shorthand_invalid",
            "Expected the form path@ref, e.g. docs/guide.md@main#L12.")
    line = line_end = None
    if fragment:
        match = _ANCHOR_RE.match(fragment[1:])
        if not match:
            raise DeepLinkError("anchor_invalid",
                                f"Not a line anchor: {fragment!r}")
        line = int(match.group(1))
        line_end = int(match.group(2)) if match.group(2) else None
        if line < 1 or (line_end is not None and line_end < line):
            raise DeepLinkError("anchor_invalid",
                                "A line range must start at line 1 or "
                                "later and end at or after it starts.")
    return blob_url(owner, repo, ref, path_part,
                    line=line, line_end=line_end)


def parse_deep_link(url: object) -> DeepLink:
    """Parse a canonical Samverk URL back into its parts.
    Anything that is not exactly one of the builders'
    shapes is refused with its reason — a parser that
    guesses is how deep links stop landing exactly."""
    raw = url if isinstance(url, str) else ""
    if not raw.startswith("/") or raw.startswith("//") \
            or "?" in raw or "://" in raw:
        raise DeepLinkError("url_invalid",
                            "A deep link is an instance-relative path.")
    path_part, hash_mark, fragment = raw.partition("#")
    segments = [unquote(seg) for seg in path_part.split("/") if seg != ""]
    if len(segments) < 2:
        raise DeepLinkError("url_invalid", "A deep link names a repository.")
    owner, repo = _names(segments[0], segments[1])
    rest = segments[2:]
    anchor = (line_start, line_end) = (None, None)
    if hash_mark:
        match = _ANCHOR_RE.match(fragment)
        if not match:
            raise DeepLinkError("anchor_invalid",
                                f"Not a line anchor: #{fragment}")
        line_start = int(match.group(1))
        line_end = int(match.group(2)) if match.group(2) else line_start
        if line_start < 1 or line_end < line_start:
            raise DeepLinkError("anchor_invalid",
                                "A line range must start at line 1 or "
                                "later and end at or after it starts.")
        anchor = (line_start, line_end)
    if not rest:
        kind = "home"
        link = DeepLink(kind=kind, owner=owner, repo=repo)
    elif rest[0] in PATH_VIEWS:
        kind = rest[0]
        if len(rest) < 2:
            raise DeepLinkError("url_invalid",
                                f"A {kind} link names a ref.")
        ref = _ref(rest[1], allow_slash=False)
        joined = "/".join(rest[2:])
        if kind == "tree":
            checked = _path(joined, required=False)
            link = DeepLink(kind=kind, owner=owner, repo=repo,
                            ref=ref, path=checked)
        else:
            checked = _path(joined, required=True)
            link = DeepLink(kind=kind, owner=owner, repo=repo,
                            ref=ref, path=checked)
    elif rest[0] == "commit":
        if len(rest) != 2 or not _OID_RE.match(rest[1]):
            raise DeepLinkError("commit_invalid",
                                "A commit link names one full commit id.")
        link = DeepLink(kind="commit", owner=owner, repo=repo,
                        commit=rest[1])
    elif rest[0] == "commits":
        if len(rest) < 2:
            raise DeepLinkError("url_invalid",
                                "A commits link names a ref.")
        link = DeepLink(kind="commits", owner=owner, repo=repo,
                        ref=_ref("/".join(rest[1:]), allow_slash=True))
    elif rest[0] == "compare":
        joined_refs = "/".join(rest[1:])
        if "..." not in joined_refs:
            raise DeepLinkError("url_invalid",
                                "A compare link is compare/base...head.")
        base_name, _, head_name = joined_refs.partition("...")
        link = DeepLink(kind="compare", owner=owner, repo=repo,
                        base=_ref(base_name, allow_slash=True),
                        head=_ref(head_name, allow_slash=True))
    elif rest[0] in PLAIN_VIEWS and len(rest) == 1:
        link = DeepLink(kind=rest[0], owner=owner, repo=repo)
    else:
        raise DeepLinkError("kind_unknown",
                            f"No Samverk view is named {rest[0]!r}.")
    if anchor != (None, None):
        if link.kind != "blob":
            raise DeepLinkError(
                "anchor_invalid",
                "Only a file (blob) link may carry a line anchor.")
        link = DeepLink(kind=link.kind, owner=link.owner, repo=link.repo,
                        ref=link.ref, path=link.path,
                        line_start=anchor[0], line_end=anchor[1])
    return link
