"""CODEOWNERS parsing and matching (S-151).

The pure half of the CODEOWNERS slice: a CODEOWNERS
file is plain text naming, line by line, a path pattern
and the owners responsible for matching paths. This
module parses that text and answers, for any one path,
which owners the file names — nothing here touches a
database or a repository, so the behaviour is provable
in isolation and the store in
`pull_request_codeowners.py` only has to read the file
honestly.

- **Parsing is honest about bad lines.** Blank lines
  and lines whose first non-space character is `#` are
  skipped. Every other line is a pattern followed by
  zero or more owner tokens. A pattern with no owners
  is a real rule: it *unassigns* — paths it matches
  have no owners, clearing whatever an earlier rule
  said (public CODEOWNERS behaviour). An owner token
  must look like `@name`, `@owner/team`, or an email
  address; a line carrying any other token is not a
  rule at all — it is recorded, verbatim, as a parse
  warning and skipped, never silently dropped and
  never silently kept.
- **Matching is gitignore-style.** `*` matches any run
  of characters except `/`; `**` crosses directories;
  a pattern with no `/` matches the basename at any
  depth; a leading `/` anchors the pattern at the
  repository root (as does any `/` in the middle of a
  pattern); a trailing `/` matches everything under
  that directory. When several rules match a path,
  the **last** matching rule wins — including an
  unassign rule, whose empty owner set is the answer.
- Clean-room: this is public CODEOWNERS behaviour
  only, studied from documentation, never copied.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "CodeownersFile", "CodeownersRule", "ParseWarning",
    "matches_pattern", "owners_for_path", "parse_codeowners",
]

_OWNER_RE = re.compile(
    r"^@[A-Za-z0-9][A-Za-z0-9._-]*"
    r"(?:/[A-Za-z0-9][A-Za-z0-9._-]*)?$")
_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def _is_owner_token(token: str) -> bool:
    return bool(_OWNER_RE.match(token) or _EMAIL_RE.match(token))


@dataclass(frozen=True)
class CodeownersRule:
    pattern: str
    owners: tuple            # of str, verbatim owner tokens
    line_no: int             # 1-based, in the source text

    def __iter__(self):
        # A rule unpacks as (pattern, owners, line_no),
        # the shape the design names.
        yield self.pattern
        yield self.owners
        yield self.line_no


@dataclass(frozen=True)
class ParseWarning:
    line_no: int
    token: str               # the malformed token, verbatim
    line: str                # the whole line, verbatim

    @property
    def message(self) -> str:
        return (f"line {self.line_no}: {self.token!r} is not "
                "an owner (@name, @owner/team, or an email "
                "address); the line was skipped")

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class CodeownersFile:
    rules: tuple             # of CodeownersRule, in file order
    warnings: tuple          # of ParseWarning, in file order


def parse_codeowners(text: str) -> CodeownersFile:
    """Parse CODEOWNERS text into its rules and its
    warnings. A bad owner token warns and skips its
    whole line; everything else is a rule, including
    a pattern standing alone (the unassign rule)."""
    rules: list[CodeownersRule] = []
    warnings: list[ParseWarning] = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        pattern, tokens = parts[0], parts[1:]
        bad = next((t for t in tokens if not _is_owner_token(t)), None)
        if bad is not None:
            warnings.append(ParseWarning(
                line_no=line_no, token=bad, line=raw))
            continue
        rules.append(CodeownersRule(
            pattern=pattern, owners=tuple(tokens), line_no=line_no))
    return CodeownersFile(rules=tuple(rules), warnings=tuple(warnings))


def _glob_regex(pattern: str) -> str:
    """One anchored glob pattern -> a regex string.
    `**/` is zero or more directories, `**` any run
    including `/`, `*` any run except `/`."""
    out: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern[i:i + 3] == "**/":
            out.append("(?:.*/)?")
            i += 3
        elif pattern[i:i + 2] == "**":
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        elif pattern[i] == "[":
            end = pattern.find("]", i + 1)
            if end < 0:
                out.append(re.escape(pattern[i]))
                i += 1
            else:
                out.append(pattern[i:end + 1])
                i = end + 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return "^" + "".join(out) + "$"


def _segment_matches(pattern_segment: str, segment: str) -> bool:
    return re.match(_glob_regex(pattern_segment), segment) is not None


def matches_pattern(pattern: str, path: str) -> bool:
    """Whether one CODEOWNERS pattern matches one
    repository-relative path (posix separators)."""
    path = path.strip("/")
    if not pattern or not path:
        return False
    if pattern.endswith("/"):
        core = pattern[:-1]
        if not core:
            return False
        if core.startswith("/"):
            core = core[1:]
            return bool(re.match(_glob_regex(core + "/**"), path))
        if "/" in core:
            return bool(re.match(_glob_regex(core + "/**"), path))
        # A bare directory name matches that directory
        # at any depth: any directory component of the
        # path (never the file's own basename) may be it.
        return any(_segment_matches(core, segment)
                   for segment in path.split("/")[:-1])
    if pattern.startswith("/"):
        return bool(re.match(_glob_regex(pattern[1:]), path))
    if "/" in pattern:
        return bool(re.match(_glob_regex(pattern), path))
    # No slash at all: the basename, at any depth.
    return _segment_matches(pattern, path.rsplit("/", 1)[-1])


def owners_for_path(rules, path: str) -> tuple:
    """The owners a parsed file names for one path:
    the owners of the last matching rule, or the empty
    tuple when no rule matches — or when the last
    matching rule is an unassign rule. `rules` may be
    a CodeownersFile or any sequence of rules."""
    sequence = rules.rules if isinstance(rules, CodeownersFile) else rules
    owners: tuple = ()
    for rule in sequence:
        if matches_pattern(rule.pattern, path):
            owners = tuple(rule.owners)
    return owners
