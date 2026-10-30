"""Cross-references (S-127).

Mentioning ``#n`` or a commit in prose links *both ways*:
the text that mentions carries the forward link (S-109's
pipeline already renders those, resolver-gated), and the
thing mentioned gains a back-reference — *mentioned in
#5*, *referenced by commit abc1234* — so a reader standing
on an issue can find every conversation that points at
it. This module is the record those back-references are
read from, plus the closing-keyword law:

- **Only proven targets are recorded.** The honesty law
  of S-109 carries over from rendering to recording: a
  ``#n`` is recorded only when `IssueStore.resolve_number`
  proves the number is claimed in the target repository,
  and a commit SHA only when the caller's resolver
  confirms it names a real commit there. A reference to
  nothing is prose, not a link, and enters no row.
- **Code is not prose.** References inside fenced code
  blocks or inline code spans are never recorded — the
  author quoted them, they did not say them (the same
  law S-107's renderer follows).
- **Closing keywords are parsed, and shown before
  merge.** `closes`, `fixes`, `resolves` and their
  inflections, directly governing a reference (`Fixes
  #3`, `closes owner/repo#4, #5`), mark that reference
  closing. `closing_references` / `closing_notice` are
  the seam a pull-request surface reads *before* merge
  to say in plain words what merging will close — no
  closing ever comes as a surprise after the fact.
  (Acting on the mark — actually closing the issue at
  merge — is Part VII's, where merges live.)
- **The record follows the text.** Recording is a sync,
  not an append: re-syncing a source replaces its rows
  with what its current text actually says, so an edit
  that removes a mention removes the back-reference too.
  A deleted (tombstoned) comment's references die with
  its body. Self-references (an issue mentioning its own
  number) are not cross-references and are never rows.
- **Permissions ride the repositories'.** Reading either
  direction requires read access to the repository the
  reader is standing on, under S-054's uniform answer;
  a back-reference whose *source* lives in a repository
  the viewer cannot read is hidden, so a private repo's
  conversations never leak through a public target.
- **No audit event of its own.** A cross-reference is
  derived data, recomputed from prose whose creation and
  edits are already audited (S-122/S-123); deriving it
  again invents no act to witness.
"""

from __future__ import annotations

import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .issues import IssueError, IssueStore
from .permissions import can_read
from .repositories import Repository, RepositoryStore

CLOSING_KEYWORDS = frozenset({
    "close", "closes", "closed",
    "fix", "fixes", "fixed",
    "resolve", "resolves", "resolved",
})

_KEYWORD = r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)"
_CROSS_REF = r"[A-Za-z0-9][A-Za-z0-9_-]*/[A-Za-z0-9][A-Za-z0-9_.-]*#\d+"
_REF_TOKEN = rf"(?:{_CROSS_REF}|#\d+)"
_CLOSING_RE = re.compile(
    rf"\b{_KEYWORD}\b\s*:?\s*({_REF_TOKEN}"
    rf"(?:\s*(?:,|and|&)\s*(?:{_KEYWORD}\b\s*:?\s*)?{_REF_TOKEN})*)",
    re.IGNORECASE)
_REF_IN_LIST_RE = re.compile(
    r"([A-Za-z0-9][A-Za-z0-9_-]*)/([A-Za-z0-9][A-Za-z0-9_.-]*)#(\d+)"
    r"|#(\d+)")
_SHA_RE = re.compile(r"\b([0-9a-fA-F]{7,40})\b")
_FENCE_RE = re.compile(r"^\s{0,3}(```+|~~~+)")
_INLINE_CODE_RE = re.compile(r"``.+?``|`[^`\n]+`", re.DOTALL)


@dataclass(frozen=True)
class ParsedReference:
    target_owner: str | None   # None = the prose's own repository
    target_repo: str | None
    target_number: int | None  # None for a commit reference
    target_sha: str | None     # as written, lowercased; None for #n
    is_closing: bool
    raw: str

    @property
    def is_commit(self) -> bool:
        return self.target_sha is not None


@dataclass(frozen=True)
class CrossReference:
    id: int
    repo_id: int               # source repository
    source_kind: str           # 'issue' | 'comment' | 'commit'
    source_number: int         # 0 for a commit source
    source_comment_id: int     # 0 unless source_kind == 'comment'
    source_sha: str            # '' unless source_kind == 'commit'
    source_author_id: int | None
    target_repo_id: int
    target_number: int         # 0 for a commit target
    target_sha: str            # '' unless a commit target (full oid)
    is_closing: bool
    created_at: int


def _prose_only(text: str) -> str:
    """The text with code removed: fenced blocks dropped
    line by line, inline spans blanked. What remains is
    what the author *said*."""
    kept: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        marker = _FENCE_RE.match(line)
        if marker:
            run = marker.group(1)
            if fence is None:
                fence = run[0]
                continue
            if run[0] == fence:
                fence = None
                continue
        if fence is None:
            kept.append(line)
    return _INLINE_CODE_RE.sub(" ", "\n".join(kept))


def _ref_from_match(match: re.Match, is_closing: bool) -> ParsedReference:
    if match.group(4) is not None:
        return ParsedReference(
            target_owner=None, target_repo=None,
            target_number=int(match.group(4)), target_sha=None,
            is_closing=is_closing, raw=f"#{match.group(4)}")
    return ParsedReference(
        target_owner=match.group(1), target_repo=match.group(2),
        target_number=int(match.group(3)), target_sha=None,
        is_closing=is_closing,
        raw=f"{match.group(1)}/{match.group(2)}#{match.group(3)}")


def parse_references(text: object) -> list[ParsedReference]:
    """Every reference a piece of prose makes, in the
    order it makes them, duplicates folded (a reference
    repeated with a closing keyword anywhere is closing).
    Pure: existence is the store's question, not the
    parser's."""
    if not isinstance(text, str) or not text:
        return []
    prose = _prose_only(text)
    closing_spans: list[tuple[int, int]] = []
    for match in _CLOSING_RE.finditer(prose):
        closing_spans.append((match.start(1), match.end(1)))
    candidates: list[tuple[int, int, ParsedReference]] = []
    covered: list[tuple[int, int]] = []
    for match in _REF_IN_LIST_RE.finditer(prose):
        covered.append((match.start(), match.end()))
        candidates.append((match.start(), match.end(),
                           _ref_from_match(match, False)))
    for match in _SHA_RE.finditer(prose):
        if any(match.start() >= lo and match.end() <= hi
               for lo, hi in covered):
            continue
        sha = match.group(1).lower()
        if sha.isdigit():
            continue  # a long number is a number, not a commit shape
        candidates.append((match.start(), match.end(), ParsedReference(
            target_owner=None, target_repo=None, target_number=None,
            target_sha=sha, is_closing=False, raw=match.group(1))))
    candidates.sort(key=lambda c: c[0])
    found: dict[tuple, ParsedReference] = {}
    for start, end, ref in candidates:
        if any(start >= lo and end <= hi for lo, hi in closing_spans):
            ref = ParsedReference(
                target_owner=ref.target_owner, target_repo=ref.target_repo,
                target_number=ref.target_number, target_sha=ref.target_sha,
                is_closing=True, raw=ref.raw)
        key = (ref.target_owner.lower() if ref.target_owner else None,
               ref.target_repo.lower() if ref.target_repo else None,
               ref.target_number, ref.target_sha)
        prior = found.get(key)
        if prior is None:
            found[key] = ref
        elif ref.is_closing and not prior.is_closing:
            found[key] = ref
    return list(found.values())


def parse_closing_references(text: object) -> list[ParsedReference]:
    """The references a text's closing keywords govern —
    the 'shown before merge' list, straight from prose."""
    return [r for r in parse_references(text) if r.is_closing]


class CrossReferenceStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        issues: IssueStore,
        commit_resolver: Callable[[str, str, str], str | None] | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._issues = issues
        # (owner, repo, sha-as-written) -> full oid, or None.
        # Unwired, commit mentions honestly record nothing.
        self._commit_resolver = commit_resolver
        self._now = time_fn

    # -- recording (sync) -------------------------------------------
    def sync_issue_references(self, actor: User, owner: object,
                              repo: object, number: object
                              ) -> list[CrossReference]:
        """(Re)record what an issue's title and body
        currently reference. The actor must be able to
        read the issue (S-054's uniform answer applies)."""
        issue = self._issues.get_issue(actor, owner, repo, number)
        current = self._require_repo(owner, repo)
        parsed = parse_references(f"{issue.title}\n{issue.body}")
        return self._sync(current, "issue", issue.number, 0, "",
                          issue.author_id, parsed)

    def sync_comment_references(self, actor: User, owner: object,
                                repo: object, number: object,
                                comment_id: int) -> list[CrossReference]:
        """(Re)record what one comment currently
        references. A tombstoned comment records nothing:
        its references die with its body."""
        issue = self._issues.get_issue(actor, owner, repo, number)
        current = self._require_repo(owner, repo)
        row = self._conn.execute(
            "SELECT * FROM issue_comments WHERE id = ? AND issue_id = ?",
            (comment_id, issue.id)).fetchone()
        if row is None:
            raise IssueError("comment_not_found", "No such comment.")
        parsed = ([] if row["deleted_at"] is not None
                  else parse_references(row["body"]))
        return self._sync(current, "comment", issue.number, int(row["id"]),
                          "", row["author_id"], parsed)

    def record_commit_references(self, owner: object, repo: object,
                                 sha: object, message: object,
                                 *, author_id: int | None = None
                                 ) -> list[CrossReference]:
        """(Re)record what a commit message references —
        the push-side seam (S-090's events are where a
        caller learns a commit arrived). The commit is
        named by its full oid; references in its message
        resolve in its own repository."""
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise IssueError("repo_not_found", "No such repository.")
        if not isinstance(sha, str) or not re.fullmatch(
                r"[0-9a-fA-F]{7,64}", sha.strip()):
            raise IssueError("commit_invalid", "No such commit.")
        parsed = parse_references(message if isinstance(message, str)
                                  else "")
        return self._sync(current, "commit", 0, 0, sha.strip().lower(),
                          author_id, parsed)

    # -- reads ---------------------------------------------------------
    def references_from(self, viewer: User | None, owner: object,
                        repo: object, number: object
                        ) -> list[CrossReference]:
        """The forward list: everything this numbered
        item's body and comments point at."""
        issue = self._issues.get_issue(viewer, owner, repo, number)
        rows = self._conn.execute(
            "SELECT * FROM cross_references WHERE repo_id = ?"
            " AND source_number = ? AND source_kind IN ('issue', 'comment')"
            " ORDER BY id", (issue.repo_id, issue.number)).fetchall()
        return [_row_to_ref(r) for r in rows
                if self._source_visible(viewer, r)]

    def references_to(self, viewer: User | None, owner: object,
                      repo: object, number: object
                      ) -> list[CrossReference]:
        """The back-references: every recorded mention of
        this numbered item, from any repository the viewer
        may read."""
        item = self._issues.resolve_number(owner, repo, number)
        current = self._repos.get_repository(owner, repo)
        if current is None or item is None or not can_read(viewer, current):
            raise IssueError("issue_not_found", "No such issue.")
        rows = self._conn.execute(
            "SELECT * FROM cross_references WHERE target_repo_id = ?"
            " AND target_number = ? ORDER BY id",
            (current.id, item.number)).fetchall()
        return [_row_to_ref(r) for r in rows
                if self._source_visible(viewer, r)]

    def references_to_commit(self, viewer: User | None, owner: object,
                             repo: object, sha: object
                             ) -> list[CrossReference]:
        """Back-references to a commit: every recorded
        mention of its oid (stored full; a short form the
        caller supplies is matched as a prefix, and an
        ambiguous or unknown prefix answers empty)."""
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise IssueError("repo_not_found", "No such repository.")
        if not isinstance(sha, str) or not re.fullmatch(
                r"[0-9a-fA-F]{7,64}", sha.strip()):
            return []
        rows = self._conn.execute(
            "SELECT * FROM cross_references WHERE target_sha != ''"
            " AND target_sha LIKE ? ORDER BY id",
            (sha.strip().lower() + "%",)).fetchall()
        return [_row_to_ref(r) for r in rows
                if self._source_visible(viewer, r)]

    def closing_references(self, viewer: User | None, owner: object,
                           repo: object, number: object
                           ) -> list[CrossReference]:
        """What merging/landing this item would close,
        from its recorded references — shown before merge,
        never discovered after it."""
        return [r for r in self.references_from(viewer, owner, repo, number)
                if r.is_closing]

    def closing_notice(self, viewer: User | None, owner: object,
                       repo: object, number: object) -> list[str]:
        """The closing list in plain words, one line per
        issue that would close, naming its repository."""
        lines = []
        for ref in self.closing_references(viewer, owner, repo, number):
            target = self._repos.get_by_id(ref.target_repo_id)
            name = target.full_name if target is not None else "?"
            lines.append(f"Will close {name}#{ref.target_number} on merge.")
        return lines

    # -- internals -------------------------------------------------------
    def _require_repo(self, owner: object, repo: object) -> Repository:
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise IssueError("repo_not_found", "No such repository.")
        return current

    def _sync(self, source_repo: Repository, source_kind: str,
              source_number: int, source_comment_id: int, source_sha: str,
              author_id: int | None,
              parsed: list[ParsedReference]) -> list[CrossReference]:
        now = int(self._now())
        rows: list[tuple] = []
        for ref in parsed:
            if ref.is_commit:
                if self._commit_resolver is None:
                    continue
                full = self._commit_resolver(
                    source_repo.owner, source_repo.name,
                    str(ref.target_sha))
                if not full:
                    continue
                rows.append((source_repo.id, source_kind, source_number,
                             source_comment_id, source_sha, author_id,
                             source_repo.id, 0, str(full).lower(), 0, now))
                continue
            if ref.target_owner is None:
                target_repo = source_repo
            else:
                target_repo = self._repos.get_repository(
                    ref.target_owner, ref.target_repo)
                if target_repo is None:
                    continue
            item = self._issues.resolve_number(
                target_repo.owner, target_repo.name, ref.target_number)
            if item is None:
                continue  # a reference to nothing is prose, not a link
            if (source_kind in ("issue", "comment")
                    and target_repo.id == source_repo.id
                    and ref.target_number == source_number):
                continue  # self-reference is not a cross-reference
            rows.append((source_repo.id, source_kind, source_number,
                         source_comment_id, source_sha, author_id,
                         target_repo.id, int(ref.target_number), "",
                         1 if ref.is_closing else 0, now))
        with self._conn:  # the source's set is replaced whole
            self._conn.execute(
                "DELETE FROM cross_references WHERE repo_id = ?"
                " AND source_kind = ? AND source_number = ?"
                " AND source_comment_id = ? AND source_sha = ?",
                (source_repo.id, source_kind, source_number,
                 source_comment_id, source_sha))
            self._conn.executemany(
                "INSERT OR IGNORE INTO cross_references (repo_id,"
                " source_kind, source_number, source_comment_id,"
                " source_sha, source_author_id, target_repo_id,"
                " target_number, target_sha, is_closing, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        return self._recorded(source_repo.id, source_kind, source_number,
                              source_comment_id, source_sha)

    def _recorded(self, repo_id: int, source_kind: str, source_number: int,
                  source_comment_id: int,
                  source_sha: str) -> list[CrossReference]:
        rows = self._conn.execute(
            "SELECT * FROM cross_references WHERE repo_id = ?"
            " AND source_kind = ? AND source_number = ?"
            " AND source_comment_id = ? AND source_sha = ? ORDER BY id",
            (repo_id, source_kind, source_number, source_comment_id,
             source_sha)).fetchall()
        return [_row_to_ref(r) for r in rows]

    def _source_visible(self, viewer: User | None,
                        row: sqlite3.Row) -> bool:
        source_repo = self._repos.get_by_id(row["repo_id"])
        return source_repo is not None and can_read(viewer, source_repo)


def _row_to_ref(row: sqlite3.Row) -> CrossReference:
    return CrossReference(
        id=row["id"], repo_id=row["repo_id"], source_kind=row["source_kind"],
        source_number=row["source_number"],
        source_comment_id=row["source_comment_id"],
        source_sha=row["source_sha"], source_author_id=row["source_author_id"],
        target_repo_id=row["target_repo_id"],
        target_number=row["target_number"], target_sha=row["target_sha"],
        is_closing=bool(row["is_closing"]), created_at=row["created_at"])
