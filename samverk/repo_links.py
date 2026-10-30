"""Repo-relative links (S-108).

Markdown written inside a repository speaks in repo-relative
paths — `[guide](docs/guide.md)`, `![diagram](img/flow.png)` —
and a reader expects those words to land on the file they name,
in the repository they are reading, at the ref they are
reading it on. This module is the resolver S-107's pipeline
calls through its `link_resolver` seam to make that true.

- **Resolution is against the file's directory and the pinned
  ref.** A link in `docs/deep/page.md` resolves against
  `docs/deep/`; the URL carries the commit oid the page was
  rendered from (the same pinning S-099's permalinks use), so
  a link copied into an issue still lands on the same content
  after the branch moves. Links go to the blob view
  (`/{owner}/{repo}/blob/{ref}/{path}`); images go to the raw
  view (`/{owner}/{repo}/raw/{ref}/{path}`), the shape S-100's
  service answers.
- **Only relative references are rewritten.** Absolute
  http/https/mailto URLs, in-page `#anchors`, query-only
  references, and instance-root `/paths` pass through S-010's
  `safe_url` untouched — the author said exactly where those
  go. Anything `safe_url` refuses (dangerous schemes,
  protocol-relative, obfuscated schemes) is refused here too.
- **A path can never climb out of the repository.** `.` and
  empty segments collapse; a `..` that would rise above the
  repo root refuses the link (the pipeline then renders the
  link text as plain text — visible, never silently wrong).
  Segments are percent-encoded for the URL, so names with
  spaces or non-ASCII characters land where they should.
  Query strings and fragments ride along unchanged.
"""

from __future__ import annotations

import re
from urllib.parse import quote

from .escaping import safe_url

_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def _encode_path(path: str) -> str:
    return "/".join(quote(seg, safe="-._~") for seg in path.split("/"))


def resolve_repo_link(url: object, kind: str, *, owner: str, name: str,
                      ref: str, base_dir: str = "") -> str | None:
    """Resolve one Markdown destination in repo context.

    Returns the URL to emit, or None to refuse the link (the
    pipeline degrades it to plain text). *kind* is 'link' or
    'image'; *base_dir* is the repo-relative directory of the
    Markdown file ('' at the root); *ref* is the pinned ref
    (a commit oid in the home's use)."""
    if url is None:
        return None
    text = str(url).strip()
    if not text:
        return None
    if _SCHEME_RE.match(text) or text.startswith(("#", "?", "/")):
        return safe_url(text)
    if safe_url(text) is None:
        return None
    # Split the suffix (query/fragment) off the path part.
    cut = len(text)
    for mark in ("#", "?"):
        idx = text.find(mark)
        if idx != -1:
            cut = min(cut, idx)
    path_part, suffix = text[:cut], text[cut:]
    if not path_part:
        return safe_url(text)
    segments: list[str] = []
    base = [seg for seg in base_dir.split("/") if seg not in ("", ".")]
    for seg in base + path_part.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if not segments:
                return None  # would climb out of the repository
            segments.pop()
            continue
        segments.append(seg)
    if not segments:
        return None
    view = "raw" if kind == "image" else "blob"
    resolved = (
        f"/{quote(str(owner), safe='-._~')}/{quote(str(name), safe='-._~')}"
        f"/{view}/{quote(str(ref), safe='/-._~')}/{_encode_path('/'.join(segments))}")
    return resolved + suffix


def make_link_resolver(*, owner: str, name: str, ref: str,
                       base_dir: str = ""):
    """The S-107 pipeline seam, bound to one repo context."""
    def resolver(url: str, kind: str) -> str | None:
        return resolve_repo_link(url, kind, owner=owner, name=name,
                                 ref=ref, base_dir=base_dir)
    return resolver
