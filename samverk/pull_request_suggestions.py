"""Pull request suggested changes (S-150).

A suggestion is a reviewer's committable patch: not a
comment *about* a change, but the change itself, offered
in a form the pull request's author can land with one
act.

- **Anchored like a line comment, carrying a patch.**
  A suggestion names one file in the pull request's
  current diff and a contiguous range of lines on the
  new side of that diff (migration 55,
  `pull_request_suggestions`). Anchoring validates
  whole against S-145's diff, exactly as S-146 anchors
  a line comment: a file not in the diff is refused
  `file_not_found`; a range that is not a contiguous
  run of new-side lines in the diff is refused
  `line_not_found`; a malformed range is refused
  `range_invalid`. The exact lines being replaced —
  read from the head commit's own content, never from
  the proposer's say-so — are stored with the
  suggestion (`original_text`), together with the
  replacement text and the head oid the suggestion was
  written against. A suggestion whose replacement is
  the text already there is refused
  `suggestion_no_change`: it proposes nothing. Binary
  or non-text files refuse `file_not_text` — a patch
  nobody can read is not a suggestion.
- **Application is the author's act, in signed-off
  commits.** `apply_suggestion` lands one suggestion;
  `apply_suggestions` lands a batch; *each application
  is exactly one commit*. The commit's parent is the
  head as it stands when the application begins, its
  author and committer are the applier (the S-064
  identity shape), and its message carries the
  sign-off record in trailers: one `Suggested-by:` per
  proposer whose work the commit lands and a
  `Signed-off-by:` for the applier who took
  responsibility for landing it. The head branch moves
  by compare-and-swap (S-053), so a head that raced the
  application refuses `stale_head` instead of tearing.
  Who may apply: the pull request's author, or — on a
  cross-fork pull request whose author allowed
  maintainer edits — a base-repository writer through
  S-142's `maintainer_edit_allowed` seam; the commit
  then lands on the fork's head branch, which is where
  the head lives. Anyone else is refused
  `permission_denied`, and a closed pull request takes
  neither proposals nor applications
  (`pull_request_closed`).
- **A batch validates whole before anything lands.**
  Every suggestion in the batch must belong to this
  pull request, still be pending, and still match the
  head as it stands now — its stored lines still
  sitting at its stored range in the current head
  content — and no two suggestions in one batch may
  overlap on the same file (`suggestion_overlap`).
  One bad member refuses the whole batch and the head
  does not move: there is no half-applied batch. The
  per-file edits are computed against the one head the
  batch started from, ranges applied bottom-up so
  earlier edits never shift later ranges.
- **Outdated is judged on read, never stored** (the
  S-146 law). A pending suggestion reads as outdated
  when the current head no longer carries its stored
  lines at its stored range — the lines moved, changed,
  or the file left the head — and an outdated
  suggestion cannot be applied (`suggestion_outdated`);
  the record stays at its original anchor so what the
  reviewer proposed remains provable. An application
  that lands one suggestion does not by itself stale
  a neighbour whose lines it never touched.
- **Audited under its own events** (taxonomy
  append-only +2: `repo.pull_request.suggestion_propose`
  / `repo.pull_request.suggestion_apply`, 106 events;
  carried by S-139's outbox under its
  `repo.pull_request.*` verb rule). The proposal
  detail names the anchor, never the replacement; the
  application detail names the suggestion ids and the
  commit it landed. Every surface reads through
  S-141's seam, so a stranger to a private repository
  gets the uniform `pull_request_not_found`.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .issues import IssueError, IssueStore, _validate_body
from .proc import run_git_in
from .pull_request_files import PullRequestFilesStore
from .pull_request_forks import ForkPullRequestStore
from .pull_requests import PullRequestError, PullRequestStore
from .refs import RefError, RefStore, branch_ref
from .repositories import RepositoryStore

__all__ = [
    "AppliedSuggestions", "PullRequestSuggestionStore",
    "Suggestion", "render_suggestion", "render_suggestions",
]

REPLACEMENT_MAX = 20000


@dataclass(frozen=True)
class Suggestion:
    id: int
    pull_request_id: int     # pull_requests row id
    number: int              # the pull request's #n
    proposer_id: int
    file_path: str
    start_line: int          # new-side, 1-based, inclusive
    end_line: int            # new-side, 1-based, inclusive
    original_text: str       # the lines being replaced, \n-joined
    replacement_text: str    # the proposed lines ('' deletes)
    body: str                # the proposer's note, may be ''
    head_oid: str            # head as it stood at proposal
    state: str               # 'pending' | 'applied'
    applied_commit_oid: str  # '' while pending
    applied_by: int          # 0 while pending
    created_at: int
    applied_at: int          # 0 while pending
    is_outdated: bool = False

    @property
    def is_applied(self) -> bool:
        return self.state == "applied"

    @property
    def anchor_words(self) -> str:
        if self.start_line == self.end_line:
            return f"{self.file_path}, line {self.start_line}"
        return (f"{self.file_path}, lines {self.start_line}"
                f"–{self.end_line}")

    @property
    def state_words(self) -> str:
        """The state in words — never a colour alone."""
        if self.is_applied:
            return "Applied"
        if self.is_outdated:
            return ("Outdated — the lines this suggestion "
                    "would replace have moved or changed")
        return "Pending"


@dataclass(frozen=True)
class AppliedSuggestions:
    commit_oid: str
    suggestions: tuple       # of Suggestion, as applied
    head_branch: str

    @property
    def count(self) -> int:
        return len(self.suggestions)

    @property
    def words(self) -> str:
        noun = "change" if self.count == 1 else "changes"
        return (f"{self.count} suggested {noun} applied "
                f"in commit {self.commit_oid[:12]}.")


def _row_to_suggestion(row: sqlite3.Row, number: int) -> Suggestion:
    return Suggestion(
        id=row["id"], pull_request_id=row["pull_request_id"],
        number=number, proposer_id=row["proposer_id"],
        file_path=row["file_path"],
        start_line=int(row["start_line"]),
        end_line=int(row["end_line"]),
        original_text=row["original_text"],
        replacement_text=row["replacement_text"],
        body=row["body"], head_oid=row["head_oid"],
        state=row["state"],
        applied_commit_oid=row["applied_commit_oid"],
        applied_by=int(row["applied_by"] or 0),
        created_at=row["created_at"],
        applied_at=int(row["applied_at"] or 0))


def _split_lines(text: str) -> tuple[list[str], bool]:
    """File text -> (lines, had-trailing-newline). The
    phantom element a trailing newline would leave in a
    naive split is not a line."""
    if text == "":
        return [], False
    trailing = text.endswith("\n")
    lines = text.split("\n")
    if trailing:
        lines.pop()
    return lines, trailing


def _join_lines(lines: list[str], trailing: bool) -> str:
    if not lines:
        return ""
    return "\n".join(lines) + ("\n" if trailing else "")


def _replacement_lines(replacement: str) -> list[str]:
    if replacement == "":
        return []
    lines, _trailing = _split_lines(replacement)
    return lines


class PullRequestSuggestionStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        issues: IssueStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._issues = issues
        self._audit = audit
        self._now = time_fn
        self._prs = PullRequestStore(
            conn, repositories, accounts, issues, audit=audit,
            time_fn=time_fn)
        self._files = PullRequestFilesStore(
            conn, repositories, accounts, issues, audit=audit,
            time_fn=time_fn)
        self._forks = ForkPullRequestStore(
            conn, repositories, accounts, issues, audit=audit,
            time_fn=time_fn)

    # -- internals ---------------------------------------------------
    def _require_open(self, pr) -> None:
        if pr.state == "closed":
            raise PullRequestError(
                "pull_request_closed",
                "A closed pull request takes no suggested "
                "changes; reopen it first.")

    def _head_target(self, viewer, owner, repo, pr):
        """The repository and branch the head lives in:
        the base repository for a same-repository pull
        request, the fork for a cross-fork one."""
        base = self._repos.get_repository(owner, repo)
        assert base is not None
        fork = self._forks.get_cross_fork(viewer, owner, repo, pr.number)
        if fork is None:
            return base, base
        row = self._conn.execute(
            "SELECT head_repo_id FROM pull_request_forks"
            " WHERE pull_request_id = ?", (pr.id,)).fetchone()
        head = self._repos.get_by_id(int(row["head_repo_id"]))
        assert head is not None
        return base, head

    def _head_oid(self, head_repo, head_branch: str) -> str:
        path = self._repos.path_for(head_repo.owner, head_repo.name)
        oid = RefStore(path).resolve(branch_ref(head_branch))
        if oid is None:
            raise PullRequestError(
                "head_not_found",
                "The head branch no longer exists.")
        return oid

    def _read_file(self, repo_path: Path, commit_oid: str,
                   file_path: str):
        """(lines, trailing_newline, mode) for one file
        at one commit, read through plumbing. A missing
        file and a non-text file are named refusals."""
        listing = run_git_in(
            repo_path, ["ls-tree", commit_oid, "--", file_path],
            timeout=15.0)
        if listing.returncode != 0:
            raise PullRequestError(
                "file_not_found", "No such file in this pull request.")
        text = listing.stdout.decode("utf-8", "replace").strip()
        if not text:
            raise PullRequestError(
                "file_not_found", "No such file in this pull request.")
        meta, _, _name = text.partition("\t")
        parts = meta.split()
        if len(parts) != 3 or parts[1] != "blob":
            raise PullRequestError(
                "file_not_text",
                "A suggested change needs a text file.")
        mode, blob_oid = parts[0], parts[2]
        blob = run_git_in(
            repo_path, ["cat-file", "blob", blob_oid], timeout=15.0)
        if blob.returncode != 0:
            raise PullRequestError(
                "file_not_found", "No such file in this pull request.")
        try:
            content = blob.stdout.decode("utf-8")
        except UnicodeDecodeError:
            raise PullRequestError(
                "file_not_text",
                "A suggested change needs a text file.") from None
        if "\x00" in content:
            raise PullRequestError(
                "file_not_text",
                "A suggested change needs a text file.")
        lines, trailing = _split_lines(content)
        return lines, trailing, mode

    def _validate_replacement(self, replacement: object) -> str:
        if replacement is None:
            replacement = ""
        if not isinstance(replacement, str):
            raise PullRequestError(
                "replacement_invalid",
                "A suggested change's replacement is text.")
        if len(replacement) > REPLACEMENT_MAX or any(
                (ord(c) < 0x20 and c not in "\n\t") or ord(c) == 0x7F
                for c in replacement):
            raise PullRequestError(
                "replacement_invalid",
                f"A replacement is at most {REPLACEMENT_MAX} "
                "characters of plain text.")
        return replacement

    def _validate_body(self, body: object) -> str:
        if body is None or body == "":
            return ""
        try:
            return _validate_body(body)
        except IssueError as exc:
            raise PullRequestError(exc.reason, str(exc)) from None

    def _suggestion_by_id(self, suggestion_id,
                          number: int) -> Suggestion | None:
        row = self._conn.execute(
            "SELECT * FROM pull_request_suggestions WHERE id = ?",
            (suggestion_id,)).fetchone()
        return _row_to_suggestion(row, number) if row else None

    def _emit(self, actor: User, action: str, owner, repo,
              number: int, detail: dict,
              source_ip: str | None) -> None:
        if self._audit is not None:
            current = self._repos.get_repository(owner, repo)
            target = (f"{current.full_name}#{number}"
                      if current is not None else f"#{number}")
            self._audit.append(
                actor_kind="user", actor_id=actor.id, action=action,
                target_kind="repo", target_id=target,
                outcome="success", source_ip=source_ip, detail=detail)

    # -- propose -------------------------------------------------------
    def propose_suggestion(self, actor: User, owner: object,
                           repo: object, number: object,
                           file_path: object, start_line: object,
                           end_line: object, replacement: object,
                           *, body: object = "",
                           source_ip: str | None = None) -> Suggestion:
        """Propose one committable patch: a replacement
        for a contiguous range of new-side lines in one
        file of the pull request's current diff. The
        anchor validates whole before anything is
        stored."""
        pr = self._prs.get_pull_request(actor, owner, repo, number)
        self._require_open(pr)
        if not isinstance(start_line, int) \
                or isinstance(start_line, bool) \
                or not isinstance(end_line, int) \
                or isinstance(end_line, bool) \
                or start_line <= 0 or end_line < start_line:
            raise PullRequestError(
                "range_invalid",
                "A suggested change covers a line range: a "
                "first line and a last line at or after it.")
        diff, _base_oid, _diff_head = self._files._diff_for(
            actor, owner, repo, pr)
        file = None
        for entry in diff.files:
            if entry.path == file_path:
                file = entry
                break
        if file is None or not isinstance(file_path, str) \
                or not file_path:
            raise PullRequestError(
                "file_not_found",
                f"{file_path!r} is not one of the files this "
                "pull request changes.")
        if file.is_binary:
            raise PullRequestError(
                "file_not_text",
                "A suggested change needs a text file.")
        in_diff = {line.new_number for line in file.lines
                   if line.new_number is not None}
        if any(n not in in_diff
               for n in range(start_line, end_line + 1)):
            raise PullRequestError(
                "line_not_found",
                f"Lines {start_line}–{end_line} of {file_path} "
                "are not all in this pull request's diff.")
        _base_repo, head_repo = self._head_target(
            actor, owner, repo, pr)
        head_path = self._repos.path_for(head_repo.owner, head_repo.name)
        head_oid = self._head_oid(head_repo, pr.head_branch)
        lines, _trailing, _mode = self._read_file(
            head_path, head_oid, file_path)
        if end_line > len(lines):
            raise PullRequestError(
                "line_not_found",
                f"There is no line {end_line} in {file_path} "
                "as the head now stands.")
        original = lines[start_line - 1:end_line]
        text = self._validate_replacement(replacement)
        if _replacement_lines(text) == original:
            raise PullRequestError(
                "suggestion_no_change",
                "That replacement is the text already there; "
                "a suggestion must change something.")
        note = self._validate_body(body)
        now = int(self._now())
        with self._conn:  # commits before the answer
            cur = self._conn.execute(
                "INSERT INTO pull_request_suggestions"
                " (pull_request_id, proposer_id, file_path,"
                " start_line, end_line, original_text,"
                " replacement_text, body, head_oid, state,"
                " applied_commit_oid, applied_by, created_at,"
                " applied_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?,"
                " ?, 'pending', '', 0, ?, 0)",
                (pr.id, actor.id, file_path, start_line, end_line,
                 "\n".join(original), text, note, head_oid, now))
        suggestion = self._suggestion_by_id(int(cur.lastrowid), pr.number)
        assert suggestion is not None
        self._emit(actor, "repo.pull_request.suggestion_propose",
                   owner, repo, pr.number,
                   {"number": pr.number,
                    "suggestion_id": suggestion.id,
                    "file": suggestion.file_path,
                    "start_line": suggestion.start_line,
                    "end_line": suggestion.end_line}, source_ip)
        return suggestion

    # -- reads ------------------------------------------------------------
    def _judge_outdated(self, suggestion: Suggestion, head_repo,
                        head_branch: str, cache: dict) -> bool:
        if suggestion.is_applied:
            return False
        key = suggestion.file_path
        if key not in cache:
            head_path = self._repos.path_for(
                head_repo.owner, head_repo.name)
            try:
                head_oid = self._head_oid(head_repo, head_branch)
                cache[key] = self._read_file(
                    head_path, head_oid, suggestion.file_path)[0]
            except PullRequestError:
                cache[key] = None
        lines = cache[key]
        if lines is None or suggestion.end_line > len(lines):
            return True
        original = suggestion.original_text.split("\n") \
            if suggestion.original_text else []
        return lines[suggestion.start_line - 1:suggestion.end_line] \
            != original

    def suggestions_for(self, viewer: User | None, owner: object,
                        repo: object, number: object
                        ) -> list[Suggestion]:
        """Every suggestion on this pull request, oldest
        first, each pending one judged against the head
        as it stands now."""
        pr = self._prs.get_pull_request(viewer, owner, repo, number)
        _base_repo, head_repo = self._head_target(viewer, owner, repo, pr)
        rows = self._conn.execute(
            "SELECT * FROM pull_request_suggestions"
            " WHERE pull_request_id = ? ORDER BY id",
            (pr.id,)).fetchall()
        cache: dict = {}
        out = []
        for row in rows:
            suggestion = _row_to_suggestion(row, pr.number)
            out.append(replace(
                suggestion,
                is_outdated=self._judge_outdated(
                    suggestion, head_repo, pr.head_branch, cache)))
        return out

    def get_suggestion(self, viewer: User | None, owner: object,
                       repo: object, number: object,
                       suggestion_id: int) -> Suggestion:
        for suggestion in self.suggestions_for(
                viewer, owner, repo, number):
            if suggestion.id == suggestion_id:
                return suggestion
        raise PullRequestError(
            "suggestion_not_found", "No such suggested change.")

    # -- application ---------------------------------------------------
    def _can_apply(self, actor: User, owner, repo, pr) -> bool:
        if actor.id == pr.author_id:
            return True
        return self._forks.maintainer_edit_allowed(
            actor, owner, repo, pr.number)

    def _rebuild_tree(self, repo_path: Path, tree_oid: str,
                      parts: list[str], new_blob_oid: str) -> str:
        """A new tree oid: `parts`' file repointed at the
        new blob, every other entry — and the file's own
        mode — exactly as it stood. Recurses into
        subtrees; mktree builds each level from its
        ls-tree listing, order preserved."""
        listing = run_git_in(
            repo_path, ["ls-tree", tree_oid], timeout=15.0)
        if listing.returncode != 0:
            raise PullRequestError(
                "apply_failed", "git could not read the head tree.")
        entries: list[str] = []
        found = False
        for raw in listing.stdout.decode(
                "utf-8", "surrogateescape").splitlines():
            if not raw:
                continue
            meta, _, name = raw.partition("\t")
            fields = meta.split()
            if len(fields) != 3:
                continue
            mode, obj_type, oid = fields
            if name == parts[0]:
                found = True
                if len(parts) == 1:
                    if obj_type != "blob":
                        raise PullRequestError(
                            "file_not_text",
                            "A suggested change needs a text file.")
                    entries.append(f"{mode} blob {new_blob_oid}\t{name}")
                else:
                    if obj_type != "tree":
                        raise PullRequestError(
                            "file_not_found",
                            "No such file in this pull request.")
                    rebuilt = self._rebuild_tree(
                        repo_path, oid, parts[1:], new_blob_oid)
                    entries.append(f"{mode} tree {rebuilt}\t{name}")
            else:
                entries.append(raw)
        if not found:
            raise PullRequestError(
                "file_not_found", "No such file in this pull request.")
        built = run_git_in(
            repo_path, ["mktree"],
            input_bytes=("\n".join(entries) + "\n").encode(
                "utf-8", "surrogateescape"),
            timeout=15.0)
        if built.returncode != 0:
            raise PullRequestError(
                "apply_failed", "git could not rebuild the tree.")
        return built.stdout.decode().strip()

    def apply_suggestions(self, actor: User, owner: object,
                          repo: object, number: object,
                          suggestion_ids: object,
                          *, source_ip: str | None = None
                          ) -> AppliedSuggestions:
        """Apply one suggestion or a batch of them as
        exactly one signed-off commit on the head
        branch. The batch validates whole — membership,
        pending state, freshness, non-overlap — before
        any git object is written, so a refused batch
        moves nothing."""
        pr = self._prs.get_pull_request(actor, owner, repo, number)
        self._require_open(pr)
        if not self._can_apply(actor, owner, repo, pr):
            raise PullRequestError(
                "permission_denied",
                "Only the pull request's author can apply "
                "suggested changes (or a base-repository "
                "writer the author allowed maintainer edits).")
        if not isinstance(suggestion_ids, (list, tuple)) \
                or not suggestion_ids:
            raise PullRequestError(
                "no_suggestions",
                "Name at least one suggested change to apply.")
        ids: list[int] = []
        for value in suggestion_ids:
            if not isinstance(value, int) or isinstance(value, bool):
                raise PullRequestError(
                    "suggestion_not_found", "No such suggested change.")
            if value not in ids:
                ids.append(value)
        chosen: list[Suggestion] = []
        for value in ids:
            suggestion = self._suggestion_by_id(value, pr.number)
            if suggestion is None \
                    or suggestion.pull_request_id != pr.id:
                raise PullRequestError(
                    "suggestion_not_found",
                    "No such suggested change on this pull request.")
            if suggestion.is_applied:
                raise PullRequestError(
                    "suggestion_not_pending",
                    "That suggested change has already been applied.")
            chosen.append(suggestion)
        _base_repo, head_repo = self._head_target(actor, owner, repo, pr)
        head_path = self._repos.path_for(head_repo.owner, head_repo.name)
        head_oid = self._head_oid(head_repo, pr.head_branch)
        # Freshness + overlap, validated whole against
        # the head as it stands now.
        by_file: dict[str, list[Suggestion]] = {}
        for suggestion in chosen:
            by_file.setdefault(suggestion.file_path, []).append(
                suggestion)
        contents: dict[str, tuple[list[str], bool]] = {}
        for file_path, group in by_file.items():
            lines, trailing, _mode = self._read_file(
                head_path, head_oid, file_path)
            contents[file_path] = (lines, trailing)
            ordered = sorted(group, key=lambda s: s.start_line)
            for earlier, later in zip(ordered, ordered[1:]):
                if later.start_line <= earlier.end_line:
                    raise PullRequestError(
                        "suggestion_overlap",
                        "Two suggested changes in this batch "
                        f"overlap in {file_path}; apply them "
                        "one at a time.")
            for suggestion in group:
                original = suggestion.original_text.split("\n") \
                    if suggestion.original_text else []
                if suggestion.end_line > len(lines) or lines[
                        suggestion.start_line - 1:suggestion.end_line
                        ] != original:
                    raise PullRequestError(
                        "suggestion_outdated",
                        "That suggested change no longer matches "
                        "the head as it stands; ask the reviewer "
                        "to propose it again.")
        # Compute every file's new content, ranges
        # bottom-up per file so no edit shifts another.
        new_blobs: dict[str, str] = {}
        for file_path, group in by_file.items():
            lines, trailing = contents[file_path]
            edited = list(lines)
            for suggestion in sorted(
                    group, key=lambda s: s.start_line, reverse=True):
                edited[suggestion.start_line - 1:suggestion.end_line] \
                    = _replacement_lines(suggestion.replacement_text)
            blob = run_git_in(
                head_path, ["hash-object", "-w", "--stdin"],
                input_bytes=_join_lines(edited, trailing).encode(
                    "utf-8"),
                timeout=15.0)
            if blob.returncode != 0:
                raise PullRequestError(
                    "apply_failed", "git could not store the change.")
            new_blobs[file_path] = blob.stdout.decode().strip()
        root = run_git_in(
            head_path, ["rev-parse", f"{head_oid}^{{tree}}"],
            timeout=15.0)
        if root.returncode != 0:
            raise PullRequestError(
                "apply_failed", "git could not read the head tree.")
        tree_oid = root.stdout.decode().strip()
        for file_path in sorted(new_blobs):
            tree_oid = self._rebuild_tree(
                head_path, tree_oid, file_path.split("/"),
                new_blobs[file_path])
        proposers: list[User] = []
        for suggestion in chosen:
            proposer = self._accounts.get_by_id(suggestion.proposer_id)
            if proposer is not None and proposer.id not in {
                    p.id for p in proposers}:
                proposers.append(proposer)
        subject = ("Apply suggested change"
                   if len(chosen) == 1 else
                   f"Apply {len(chosen)} suggested changes")
        message_lines = [subject, ""]
        for proposer in proposers:
            message_lines.append(
                f"Suggested-by: {proposer.username} "
                f"<{proposer.username_lower}@samverk.invalid>")
        message_lines.append(
            f"Signed-off-by: {actor.username} "
            f"<{actor.username_lower}@samverk.invalid>")
        env = {
            "GIT_AUTHOR_NAME": actor.username,
            "GIT_AUTHOR_EMAIL": f"{actor.username_lower}@samverk.invalid",
            "GIT_COMMITTER_NAME": actor.username,
            "GIT_COMMITTER_EMAIL":
                f"{actor.username_lower}@samverk.invalid",
        }
        commit = run_git_in(
            head_path, ["commit-tree", tree_oid, "-p", head_oid],
            input_bytes=("\n".join(message_lines) + "\n").encode(),
            timeout=15.0, env_extra=env)
        if commit.returncode != 0:
            raise PullRequestError(
                "apply_failed", "git could not commit the change.")
        commit_oid = commit.stdout.decode().strip()
        try:
            RefStore(head_path).update_ref(
                branch_ref(pr.head_branch), commit_oid,
                expected_old=head_oid)
        except RefError:
            raise PullRequestError(
                "stale_head",
                "The head branch moved while the change was "
                "being applied; nothing was applied.") from None
        now = int(self._now())
        try:
            with self._conn:  # the marks land together
                for suggestion in chosen:
                    self._conn.execute(
                        "UPDATE pull_request_suggestions"
                        " SET state = 'applied',"
                        " applied_commit_oid = ?, applied_by = ?,"
                        " applied_at = ? WHERE id = ?",
                        (commit_oid, actor.id, now, suggestion.id))
        except Exception:
            # The commit landed but its record did not:
            # move the branch back (compare-and-swap, so a
            # head that raced on again is left alone) and
            # say the application failed, never claim it.
            try:
                RefStore(head_path).update_ref(
                    branch_ref(pr.head_branch), head_oid,
                    expected_old=commit_oid)
            except RefError:
                pass
            raise PullRequestError(
                "apply_failed",
                "The application could not be recorded; the "
                "head branch was restored.") from None
        applied = tuple(
            replace(s, state="applied",
                    applied_commit_oid=commit_oid,
                    applied_by=actor.id, applied_at=now,
                    is_outdated=False)
            for s in chosen)
        self._emit(actor, "repo.pull_request.suggestion_apply",
                   owner, repo, pr.number,
                   {"number": pr.number,
                    "suggestion_ids": [s.id for s in chosen],
                    "commit": commit_oid,
                    "count": len(chosen)}, source_ip)
        return AppliedSuggestions(
            commit_oid=commit_oid, suggestions=applied,
            head_branch=pr.head_branch)

    def apply_suggestion(self, actor: User, owner: object,
                         repo: object, number: object,
                         suggestion_id: int,
                         *, source_ip: str | None = None
                         ) -> AppliedSuggestions:
        """Apply exactly one suggested change — the
        one-member road of the batch seam, so single and
        batch applications are the same act with the
        same law and the same one-commit shape."""
        return self.apply_suggestions(
            actor, owner, repo, number, [suggestion_id],
            source_ip=source_ip)


def render_suggestion(suggestion: Suggestion) -> str:
    """One suggestion: its anchor and state in words,
    the lines it replaces and its replacement shown as
    text, its note through S-010."""
    return (
        '<div class="suggestion">'
        f'<p class="anchor">{escape_html_text(suggestion.anchor_words)}'
        f" · {escape_html_text(suggestion.state_words)}</p>"
        f'<pre class="original">'
        f"{escape_html_text(suggestion.original_text)}</pre>"
        f'<pre class="replacement">'
        f"{escape_html_text(suggestion.replacement_text)}</pre>"
        + (f'<p class="note">{escape_html_text(suggestion.body)}</p>'
           if suggestion.body else "")
        + "</div>")


def render_suggestions(suggestions: list[Suggestion]) -> str:
    """Every suggestion on a pull request. An empty
    list says so plainly."""
    if not suggestions:
        return ('<p class="empty">No suggested changes on this '
                "pull request yet.</p>")
    parts = ['<div class="suggestions">']
    for suggestion in suggestions:
        parts.append(render_suggestion(suggestion))
    parts.append("</div>")
    return "\n".join(parts)
