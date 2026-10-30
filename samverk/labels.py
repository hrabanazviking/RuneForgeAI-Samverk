"""Labels (S-124).

A label is a named, coloured tag on issues in one
repository, under three laws:

- **Text is mandatory; colour is decoration.** A label
  must carry a name — a colour with no name is refused
  (`label_name_required`), because colour alone can
  never be the meaning (the design law: no colour-only
  status, ever). The colour is a strict `#rrggbb` value,
  stored normalised, and `render_label` always prints
  the name (and the colour value as text) beside any
  swatch a surface draws — a reader who cannot see the
  colour loses nothing.
- **Names are unique per repository, case-insensitively**
  (`bug` and `Bug` are one label), so a name typed in
  prose or a filter names exactly one label. CRUD is a
  repository-writer act; reading follows S-054 like
  everything else, and a stranger to a private
  repository gets the uniform `repo_not_found`.
- **New repositories are born labelled.**
  `DEFAULT_LABELS` — the customary starter set (bug,
  documentation, enhancement, and kin, studied from
  public forge behaviour) — is seeded inside the same
  transaction that creates the repository row (wired in
  `repositories.create_repository`), and
  `seed_default_labels` repairs older repositories
  idempotently: it adds only the names still missing.

Assigning a label to an issue is a writer act (or the
issue author's own act on their own issue); the
assignment rows live in `issue_labels` and die with
the label if the label is deleted, in the same
transaction, so no dangling tag can survive its label.
"""

from __future__ import annotations

import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_attr, escape_html_text
from .issues import IssueError, IssueStore
from .permissions import can_read, can_write
from .repositories import Repository, RepositoryStore

NAME_MAX = 50
DESCRIPTION_MAX = 200
_COLOUR_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")

# The starter set for new repositories: (name, colour,
# description). Public forge behaviour, clean-room.
DEFAULT_LABELS: tuple[tuple[str, str, str], ...] = (
    ("bug", "#d73a4a", "Something isn't working"),
    ("documentation", "#0075ca",
     "Improvements or additions to documentation"),
    ("duplicate", "#cfd3d7", "This issue or pull request already exists"),
    ("enhancement", "#a2eeef", "New feature or request"),
    ("good first issue", "#7057ff", "Good for newcomers"),
    ("help wanted", "#008672", "Extra attention is needed"),
    ("invalid", "#e4e669", "This doesn't seem right"),
    ("question", "#d876e3", "Further information is requested"),
    ("wontfix", "#ffffff", "This will not be worked on"),
)


class LabelError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class Label:
    id: int
    repo_id: int
    name: str            # display case
    name_lower: str      # canonical, unique per repository
    colour: str          # normalised '#rrggbb'
    description: str
    created_at: int
    updated_at: int

    @property
    def colour_text(self) -> str:
        """The colour as words a screen reader can say."""
        return self.colour


def _row_to_label(row: sqlite3.Row) -> Label:
    return Label(
        id=row["id"], repo_id=row["repo_id"], name=row["name"],
        name_lower=row["name_lower"], colour=row["colour"],
        description=row["description"], created_at=row["created_at"],
        updated_at=row["updated_at"])


def validate_colour(colour: object) -> str:
    if not isinstance(colour, str):
        raise LabelError("colour_invalid", "A colour is '#rrggbb'.")
    match = _COLOUR_RE.match(colour.strip())
    if match is None:
        raise LabelError(
            "colour_invalid",
            "Colours are six hex digits, like #d73a4a — and a "
            "colour is never a label on its own: it needs a name.")
    return "#" + match.group(1).lower()


def _validate_name(name: object) -> str:
    if not isinstance(name, str) or not name.strip():
        raise LabelError(
            "label_name_required",
            "A label needs a name — colour alone is never the "
            "meaning.")
    text = name.strip()
    if len(text) > NAME_MAX or any(
            ord(c) < 0x20 or ord(c) == 0x7F for c in text):
        raise LabelError(
            "label_name_invalid",
            f"Label names are at most {NAME_MAX} characters of "
            "plain text.")
    return text


def _validate_description(description: object) -> str:
    if description is None:
        return ""
    if not isinstance(description, str):
        raise LabelError(
            "description_invalid", "A description must be text.")
    text = description.strip()
    if len(text) > DESCRIPTION_MAX or any(
            ord(c) < 0x20 or ord(c) == 0x7F for c in text):
        raise LabelError(
            "description_invalid",
            f"Descriptions are at most {DESCRIPTION_MAX} characters "
            "of plain text.")
    return text


def seed_defaults_tx(conn: sqlite3.Connection, repo_id: int,
                     now: int) -> int:
    """Insert any missing default labels inside the caller's
    transaction. Returns how many were added."""
    added = 0
    for name, colour, description in DEFAULT_LABELS:
        cur = conn.execute(
            "INSERT OR IGNORE INTO labels (repo_id, name, name_lower,"
            " colour, description, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (repo_id, name, name.lower(), colour, description, now, now))
        added += cur.rowcount
    return added


def render_label(label: Label) -> str:
    """One label as HTML: the name as text, the colour named
    as text — meaning never rides on colour alone."""
    return (
        '<span class="label" data-colour="'
        + escape_html_attr(label.colour) + '">'
        + escape_html_text(label.name)
        + ' <span class="label-colour">'
        + escape_html_text(label.colour) + "</span></span>")


class LabelStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        issues: IssueStore | None = None,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._issues = issues
        self._audit = audit
        self._now = time_fn

    # -- guards -----------------------------------------------------
    def _repo_for_read(self, viewer: User | None, owner: object,
                       repo: object) -> Repository:
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise LabelError("repo_not_found", "No such repository.")
        return current

    def _repo_for_write(self, actor: User, owner: object,
                        repo: object) -> Repository:
        current = self._repo_for_read(actor, owner, repo)
        if not can_write(actor, current):
            raise LabelError(
                "permission_denied",
                "Only a repository writer can manage labels.")
        return current

    # -- CRUD ---------------------------------------------------------
    def create_label(self, actor: User, owner: object, repo: object,
                     name: object, colour: object,
                     description: object = "",
                     *, source_ip: str | None = None) -> Label:
        current = self._repo_for_write(actor, owner, repo)
        text = _validate_name(name)
        colour_ok = validate_colour(colour)
        desc = _validate_description(description)
        now = int(self._now())
        with self._conn:  # commits before the answer
            try:
                cur = self._conn.execute(
                    "INSERT INTO labels (repo_id, name, name_lower,"
                    " colour, description, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (current.id, text, text.lower(), colour_ok, desc,
                     now, now))
            except sqlite3.IntegrityError:
                raise LabelError(
                    "label_taken",
                    f"A label named {text!r} already exists in "
                    "this repository.") from None
        label = self._by_id(int(cur.lastrowid))
        assert label is not None
        self._emit(actor, "repo.label.create", current,
                   {"label": label.name}, source_ip)
        return label

    def get_label(self, viewer: User | None, owner: object,
                  repo: object, name: object) -> Label:
        current = self._repo_for_read(viewer, owner, repo)
        label = self._by_name(current.id, name)
        if label is None:
            raise LabelError("label_not_found", "No such label.")
        return label

    def list_labels(self, viewer: User | None, owner: object,
                    repo: object) -> list[Label]:
        current = self._repo_for_read(viewer, owner, repo)
        rows = self._conn.execute(
            "SELECT * FROM labels WHERE repo_id = ?"
            " ORDER BY name_lower", (current.id,)).fetchall()
        return [_row_to_label(r) for r in rows]

    def update_label(self, actor: User, owner: object, repo: object,
                     name: object, *, new_name: object = None,
                     colour: object = None,
                     description: object = None,
                     source_ip: str | None = None) -> Label:
        current = self._repo_for_write(actor, owner, repo)
        label = self._by_name(current.id, name)
        if label is None:
            raise LabelError("label_not_found", "No such label.")
        text = label.name if new_name is None else _validate_name(new_name)
        colour_ok = (label.colour if colour is None
                     else validate_colour(colour))
        desc = (label.description if description is None
                else _validate_description(description))
        now = int(self._now())
        with self._conn:
            try:
                self._conn.execute(
                    "UPDATE labels SET name = ?, name_lower = ?,"
                    " colour = ?, description = ?, updated_at = ?"
                    " WHERE id = ?",
                    (text, text.lower(), colour_ok, desc, now, label.id))
            except sqlite3.IntegrityError:
                raise LabelError(
                    "label_taken",
                    f"A label named {text!r} already exists in "
                    "this repository.") from None
        updated = self._by_id(label.id)
        assert updated is not None
        self._emit(actor, "repo.label.update", current,
                   {"label": updated.name}, source_ip)
        return updated

    def delete_label(self, actor: User, owner: object, repo: object,
                     name: object,
                     *, source_ip: str | None = None) -> Label:
        current = self._repo_for_write(actor, owner, repo)
        label = self._by_name(current.id, name)
        if label is None:
            raise LabelError("label_not_found", "No such label.")
        with self._conn:  # label and its assignments die together
            self._conn.execute(
                "DELETE FROM issue_labels WHERE label_id = ?",
                (label.id,))
            self._conn.execute(
                "DELETE FROM labels WHERE id = ?", (label.id,))
        self._emit(actor, "repo.label.delete", current,
                   {"label": label.name}, source_ip)
        return label

    def seed_default_labels(self, actor: User, owner: object,
                            repo: object) -> list[Label]:
        """Idempotently add any missing defaults (the repair
        road for repositories created before S-124)."""
        current = self._repo_for_write(actor, owner, repo)
        now = int(self._now())
        with self._conn:
            seed_defaults_tx(self._conn, current.id, now)
        return self.list_labels(actor, owner, repo)

    # -- assignment to issues -----------------------------------------
    def add_to_issue(self, actor: User, owner: object, repo: object,
                     number: object, label_name: object,
                     *, source_ip: str | None = None) -> list[Label]:
        issue, current = self._issue_for_label_change(
            actor, owner, repo, number)
        label = self._by_name(current.id, label_name)
        if label is None:
            raise LabelError("label_not_found", "No such label.")
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO issue_labels (issue_id,"
                " label_id, created_at) VALUES (?, ?, ?)",
                (issue.id, label.id, now))
        self._emit(actor, "repo.issue.label_add", current,
                   {"number": issue.number, "label": label.name},
                   source_ip)
        return self.labels_for_issue(actor, owner, repo, number)

    def remove_from_issue(self, actor: User, owner: object,
                          repo: object, number: object,
                          label_name: object,
                          *, source_ip: str | None = None
                          ) -> list[Label]:
        issue, current = self._issue_for_label_change(
            actor, owner, repo, number)
        label = self._by_name(current.id, label_name)
        if label is None:
            raise LabelError("label_not_found", "No such label.")
        with self._conn:
            self._conn.execute(
                "DELETE FROM issue_labels WHERE issue_id = ?"
                " AND label_id = ?", (issue.id, label.id))
        self._emit(actor, "repo.issue.label_remove", current,
                   {"number": issue.number, "label": label.name},
                   source_ip)
        return self.labels_for_issue(actor, owner, repo, number)

    def labels_for_issue(self, viewer: User | None, owner: object,
                         repo: object, number: object) -> list[Label]:
        if self._issues is None:
            raise LabelError(
                "issues_unavailable", "No issue store is wired.")
        issue = self._issues.get_issue(viewer, owner, repo, number)
        rows = self._conn.execute(
            "SELECT l.* FROM labels l JOIN issue_labels il"
            " ON il.label_id = l.id WHERE il.issue_id = ?"
            " ORDER BY l.name_lower", (issue.id,)).fetchall()
        return [_row_to_label(r) for r in rows]

    # -- internals ------------------------------------------------------
    def _issue_for_label_change(self, actor: User, owner: object,
                                repo: object, number: object):
        if self._issues is None:
            raise LabelError(
                "issues_unavailable", "No issue store is wired.")
        # get_issue enforces read access + the uniform private
        # answer; labelling then needs write, or authorship.
        issue = self._issues.get_issue(actor, owner, repo, number)
        current = self._repos.get_repository(owner, repo)
        assert current is not None
        if actor.id != issue.author_id and not can_write(actor, current):
            raise LabelError(
                "permission_denied",
                "Only a repository writer or the issue's author "
                "can change its labels.")
        return issue, current

    def _by_id(self, label_id: int) -> Label | None:
        row = self._conn.execute(
            "SELECT * FROM labels WHERE id = ?", (label_id,)).fetchone()
        return _row_to_label(row) if row else None

    def _by_name(self, repo_id: int, name: object) -> Label | None:
        if not isinstance(name, str) or not name.strip():
            return None
        row = self._conn.execute(
            "SELECT * FROM labels WHERE repo_id = ? AND name_lower = ?",
            (repo_id, name.strip().lower())).fetchone()
        return _row_to_label(row) if row else None

    def _emit(self, actor: User, action: str, current: Repository,
              detail: dict, source_ip: str | None) -> None:
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id, action=action,
                target_kind="repo", target_id=current.full_name,
                outcome="success", source_ip=source_ip, detail=detail)
