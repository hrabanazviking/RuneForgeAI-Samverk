"""Commit detail (S-103).

One commit in full: its message, author, parents, the
per-file diff, and a "browse at this point" door into
S-098's file browser.

- **The diff is per-file, collapsible, and counted.**
  `git diff-tree -p --root` is split on its `diff --git`
  boundaries; each file carries its old/new paths (a
  rename shows both), its counted additions/deletions,
  and its patch lines. Binary changes are named binary
  with no patch — never a byte dump. The page renders
  each file inside a `<details>` element, so collapse is
  the browser's own, honest mechanism; S-104 owns the
  shared, richer diff engine this view will adopt.
- **Parents are links, and the root says so.** A commit
  with parents lists each as a commit link; a root commit
  is named a root in words, not shown as a broken link.
- **Browse at this point** links to the file browser at
  this commit's oid (`/{owner}/{repo}/tree/{oid}`), so
  the link keeps meaning after branches move.
- The requested identifier must resolve to a commit:
  a tag pointing at one is peeled; a blob/tree/ref that
  is not a commit answers `not_a_commit` / `ref_not_found`.
  All text renders through S-010's escaping seam.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .accounts import User
from .escaping import escape_html_text
from .objects import ObjectReader
from .permissions import can_read
from .proc import run_git_in
from .repo_home import RepoHomeError, validate_ref
from .repositories import RepositoryStore

_AUTHOR_RE = re.compile(r"^(.*?) <(.*?)> (\d+) [+-]\d{4}$")


class CommitDetailError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class FileDiff:
    old_path: str | None    # None when the file is new
    new_path: str | None    # None when the file is deleted
    additions: int
    deletions: int
    is_binary: bool
    patch_lines: tuple[str, ...]

    @property
    def path(self) -> str:
        return self.new_path or self.old_path or ""


@dataclass(frozen=True)
class CommitDetail:
    full_name: str
    oid: str
    tree_oid: str
    parents: tuple[str, ...]
    author_name: str
    author_email: str
    author_time: int
    message: str
    files: tuple[FileDiff, ...]
    browse_url: str

    @property
    def subject(self) -> str:
        return self.message.split("\n", 1)[0] if self.message else ""

    @property
    def total_additions(self) -> int:
        return sum(f.additions for f in self.files)

    @property
    def total_deletions(self) -> int:
        return sum(f.deletions for f in self.files)


def _split_diff(text: str) -> list[FileDiff]:
    files: list[FileDiff] = []
    chunks: list[str] = []
    current: list[str] | None = None
    for line in text.split("\n"):
        if line.startswith("diff --git "):
            if current is not None:
                chunks.append("\n".join(current))
            current = [line]
        elif current is not None:
            current.append(line)
    if current is not None:
        chunks.append("\n".join(current))
    for chunk in chunks:
        lines = chunk.split("\n")
        old_path: str | None = None
        new_path: str | None = None
        # Paths start from the `diff --git a/X b/Y` header:
        # binary files have no ---/+++ lines at all, and a
        # header is the only place their names appear.
        header = lines[0] if lines else ""
        if header.startswith("diff --git a/"):
            rest = header[len("diff --git a/"):]
            left, sep, right = rest.rpartition(" b/")
            if sep:
                old_path, new_path = left, right
        additions = deletions = 0
        is_binary = False
        patch: list[str] = []
        in_patch = False
        for line in lines:
            if line.startswith("--- "):
                value = line[4:]
                old_path = None if value == "/dev/null" else value[2:] \
                    if value.startswith("a/") else value
                in_patch = True
                continue
            if line.startswith("+++ "):
                value = line[4:]
                new_path = None if value == "/dev/null" else value[2:] \
                    if value.startswith("b/") else value
                continue
            if line.startswith("Binary files ") or line == "GIT binary patch":
                is_binary = True
            if in_patch:
                patch.append(line)
                if line.startswith("+") and not line.startswith("+++"):
                    additions += 1
                elif line.startswith("-") and not line.startswith("---"):
                    deletions += 1
        if old_path is None and new_path is None:
            # Rename/copy headers carry their paths on
            # rename from/to lines instead of ---/+++ hunks.
            for line in lines:
                if line.startswith("rename from "):
                    old_path = line[len("rename from "):]
                elif line.startswith("rename to "):
                    new_path = line[len("rename to "):]
                elif line.startswith("copy from "):
                    old_path = line[len("copy from "):]
                elif line.startswith("copy to "):
                    new_path = line[len("copy to "):]
        files.append(FileDiff(
            old_path=old_path, new_path=new_path, additions=additions,
            deletions=deletions, is_binary=is_binary,
            patch_lines=tuple(patch)))
    return files


class CommitDetailService:
    def __init__(self, repositories: RepositoryStore):
        self._repos = repositories

    def detail(self, viewer: User | None, owner: object, repo: object,
               commit_ref: object) -> CommitDetail:
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise CommitDetailError("repo_not_found", "No such repository.")
        repo_path = self._repos.path_for(current.owner, current.name)
        try:
            ref_name = validate_ref(commit_ref)
        except RepoHomeError as exc:
            raise CommitDetailError(exc.reason, str(exc)) from None
        peeled = run_git_in(
            repo_path, ["rev-parse", f"{ref_name}^{{commit}}"], timeout=15.0)
        if peeled.returncode != 0:
            raise CommitDetailError(
                "ref_not_found", f"No such commit: {ref_name!r}")
        oid = peeled.stdout.decode().strip().lower()
        reader = ObjectReader(repo_path)
        commit = reader.read_commit(oid)
        match = _AUTHOR_RE.match(commit.author)
        if match:
            name, email, when = match.group(1), match.group(2), int(match.group(3))
        else:
            name, email, when = commit.author, "", 0
        diff = run_git_in(
            repo_path,
            ["diff-tree", "-p", "--root", "--find-renames", "-r", oid],
            timeout=30.0)
        if diff.returncode != 0:
            raise CommitDetailError("object_unreadable",
                                    "That commit's diff cannot be read.")
        files = tuple(_split_diff(diff.stdout.decode("utf-8", "replace")))
        return CommitDetail(
            full_name=current.full_name, oid=oid, tree_oid=commit.tree,
            parents=commit.parents, author_name=name, author_email=email,
            author_time=when, message=commit.message.rstrip("\n"),
            files=files,
            browse_url=f"/{current.owner}/{current.name}/tree/{oid}")


def render_commit_page(detail: CommitDetail) -> str:
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{escape_html_text(detail.full_name)} — "
        f"{escape_html_text(detail.oid[:12])} — Samverk</title></head>",
        "<body>",
        f"<h1>{escape_html_text(detail.subject)}</h1>",
        f'<p class="meta">{escape_html_text(detail.full_name)} · '
        f"commit {escape_html_text(detail.oid)} · "
        f"{escape_html_text(detail.author_name)} · "
        f"+{detail.total_additions} −{detail.total_deletions} "
        f"across {len(detail.files)} files</p>",
    ]
    if detail.message:
        parts.append(
            f'<pre class="message">'
            f"{escape_html_text(detail.message)}</pre>")
    if detail.parents:
        links = " ".join(
            f'<a href="/{escape_html_text(detail.full_name)}/commit/'
            f'{escape_html_text(parent)}">{escape_html_text(parent[:12])}</a>'
            for parent in detail.parents)
        parts.append(f'<p class="parents">Parents: {links}</p>')
    else:
        parts.append('<p class="parents">Root commit — no parents.</p>')
    parts.append(
        f'<p class="browse"><a href="{escape_html_text(detail.browse_url)}">'
        "Browse files at this point</a></p>")
    for file_diff in detail.files:
        parts.append('<details class="file-diff">')
        label = escape_html_text(file_diff.path)
        if file_diff.old_path and file_diff.new_path \
                and file_diff.old_path != file_diff.new_path:
            label = (f"{escape_html_text(file_diff.old_path)} → "
                     f"{escape_html_text(file_diff.new_path)}")
        parts.append(
            f"<summary>{label} "
            f"+{file_diff.additions} −{file_diff.deletions}</summary>")
        if file_diff.is_binary:
            parts.append('<p class="binary">Binary file — no patch shown.</p>')
        else:
            body = "\n".join(escape_html_text(line) for line in file_diff.patch_lines)
            parts.append(f'<pre class="patch">{body}</pre>')
        parts.append("</details>")
    parts.append("</body></html>")
    return "\n".join(parts)
