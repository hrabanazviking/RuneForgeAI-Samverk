"""File-sharing succession (S-366).

Samtal's file uploads gain a \"keep in Samverk\" path: a
file shared in a hall message becomes a Samverk gist
(S-277) — a mini-repository with full revision history —
and the Samtal message links to it. The old file stays
readable: keeping is a copy, never a move. This service
never deletes, mutates, or re-reads destructively from
the Samtal side; the shared file record it is handed is
treated as read-only, and the battery proves the source
bytes are untouched after a keep.

The link record rides the settings table (message id ->
gist id, owner, file name) — no migration, no new
taxonomy event. Keeping the same message twice returns
the standing link rather than minting a second gist
(already_kept is reported on the record, not an error:
the succession already happened). The kept gist is
owned by the file's uploader, created through the
standing GistStore door, under the gist file law — so a
shared file whose name or body the gist law refuses is
refused here with the gist's own reason, honestly.

Guards: the seam must be enabled (seam_disabled); only
the uploader or a site admin may keep a file
(not_file_owner); a message id and a file are required
(message_required / file_required).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .gists import GistStore
from .seam_contract import seam_enabled


class FileSuccessionError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class SharedFile:
    """A Samtal shared file, as the seam hands it over.
    Read-only by contract: succession copies, never moves."""
    message_id: str
    uploader_id: int
    filename: str
    content: str


@dataclass(frozen=True)
class KeptFile:
    message_id: str
    gist_id: int
    owner: str
    filename: str
    already_kept: bool

    @property
    def link_path(self) -> str:
        return f"/gists/{self.gist_id}"

    def link_label(self) -> str:
        return f"{self.filename} — kept in Samverk (gist {self.gist_id})"


class FileSuccessionService:
    def __init__(self, conn, data_root: Path, accounts: AccountStore,
                 *, settings: dict | None = None, audit: AuditLog | None = None,
                 time_fn=None):
        self._conn = conn
        self._accounts = accounts
        self._settings = settings
        self._gists = GistStore(conn, data_root, accounts, audit=audit,
                                time_fn=time_fn)

    def _key(self, message_id: str) -> str:
        return f"seam.file.{message_id}.kept"

    def link_for(self, message_id: object) -> KeptFile | None:
        """The standing keep-link for a Samtal message, if any."""
        if not isinstance(message_id, str) or not message_id.strip():
            return None
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            (self._key(message_id.strip()),)).fetchone()
        if row is None:
            return None
        data = json.loads(row["value"])
        return KeptFile(message_id=message_id.strip(), gist_id=data["gist_id"],
                        owner=data["owner"], filename=data["filename"],
                        already_kept=True)

    def keep_in_samverk(self, actor: User | None, shared: SharedFile) -> KeptFile:
        """Copy a shared file into a gist and link the message.

        The source record is never mutated; the uploader
        becomes the gist's owner through the standing
        GistStore door.
        """
        if not seam_enabled(self._settings):
            raise FileSuccessionError(
                "seam_disabled", "The Samtal seam is not enabled.")
        if not isinstance(shared.message_id, str) or not shared.message_id.strip():
            raise FileSuccessionError(
                "message_required", "A keep needs the Samtal message it succeeds.")
        if not isinstance(shared.filename, str) or not shared.filename.strip() \
                or not isinstance(shared.content, str) or not shared.content:
            raise FileSuccessionError(
                "file_required", "A keep needs the shared file's name and content.")
        if actor is None or (actor.id != shared.uploader_id and not actor.is_admin):
            raise FileSuccessionError(
                "not_file_owner",
                "Only the file's uploader (or a site admin) may keep it in Samverk.")
        existing = self.link_for(shared.message_id)
        if existing is not None:
            return existing
        uploader = self._accounts.get_by_id(shared.uploader_id)
        if uploader is None:
            raise FileSuccessionError(
                "no_such_user", "The file's uploader holds no Samverk account.")
        gist = self._gists.create_gist(
            uploader, f"Kept from Samtal message {shared.message_id.strip()}",
            {shared.filename.strip(): shared.content})
        kept = KeptFile(message_id=shared.message_id.strip(), gist_id=gist.id,
                        owner=uploader.username, filename=shared.filename.strip(),
                        already_kept=False)
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (self._key(kept.message_id),
                 json.dumps({"gist_id": kept.gist_id, "owner": kept.owner,
                             "filename": kept.filename}, sort_keys=True)))
        return kept


def render_message_link(kept: KeptFile) -> str:
    """The link a Samtal message shows for its kept file."""
    return (
        f'<p class="kept-file"><a href="{escape_html_text(kept.link_path)}">'
        f"{escape_html_text(kept.link_label())}</a></p>\n")
