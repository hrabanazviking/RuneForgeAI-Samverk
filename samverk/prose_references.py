"""Mentions and references in prose (S-109).

`@user`, `#issue`, and commit SHAs autolink everywhere
Markdown renders — but only when the thing they name is
*proven to exist*. That is the honesty law applied to prose:
a forge that links every hex-looking word to a commit page
that then 404s teaches its readers not to trust its links.
S-107's pipeline therefore detects the shapes and asks this
module's resolver to confirm each one before it becomes a
link; unconfirmed references render as the plain text the
author wrote.

- **Mentions** resolve through the account store: the name
  must be a registered account (case-insensitive, the store's
  own lookup), and the link uses the account's canonical
  display case (`/{username}`, the profile home S-029 built).
- **Commits** resolve through git itself: `rev-parse --verify
  <sha>^{commit}` must succeed in the repository the prose
  belongs to, and the link carries the full oid it resolved
  to (`/{owner}/{repo}/commit/{oid}`, S-103's surface) — a
  short SHA in prose lands on the exact commit, and a hex
  word that names no commit stays text.
- **Issues** take an `issue_exists` callable: Part VI has not
  built the issue store yet, so with no callable wired a
  `#number` honestly stays text today, and the day Part VI
  lands, the same seam lights the links up with no pipeline
  change. Linking to issue pages that cannot exist yet would
  be the dishonest option.

A resolver failure (git error, timeout, a store that raises)
answers None — plain text — never an exception into a page
render and never a guessed link.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable
from urllib.parse import quote

from .proc import run_git_in


def _enc(value: object) -> str:
    return quote(str(value), safe="-._~")


def make_reference_resolver(*, accounts=None, owner: str | None = None,
                            name: str | None = None,
                            repo_path: Path | None = None,
                            issue_exists: Callable[[int], bool] | None = None):
    """The S-107 pipeline's `reference_resolver` seam, bound
    to the stores a rendering surface actually has. Any piece
    left unwired simply never confirms its kind."""

    def resolver(kind: str, value: str) -> str | None:
        try:
            if kind == "mention":
                if accounts is None:
                    return None
                user = accounts.get_by_username(value)
                if user is None:
                    return None
                return f"/{_enc(user.username)}"
            if kind == "issue":
                if issue_exists is None or owner is None or name is None:
                    return None
                number = int(value)
                if number <= 0 or not issue_exists(number):
                    return None
                return f"/{_enc(owner)}/{_enc(name)}/issues/{number}"
            if kind == "commit":
                if repo_path is None or owner is None or name is None:
                    return None
                result = run_git_in(
                    Path(repo_path),
                    ["rev-parse", "--verify", "--quiet",
                     f"{value.lower()}^{{commit}}"],
                    timeout=10.0)
                if result.returncode != 0:
                    return None
                oid = result.stdout.decode("utf-8", "replace").strip().lower()
                if not oid.startswith(value.lower()) \
                        or len(oid) not in (40, 64):
                    return None
                return f"/{_enc(owner)}/{_enc(name)}/commit/{oid}"
        except Exception:
            return None
        return None

    return resolver
