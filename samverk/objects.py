"""Object reading (S-051).

Reads git objects out of a bare repository through one
`cat-file --batch` process per call (S-014 subprocess law) —
never one spawn per object, which is what makes a 10k-object
repository stay inside its latency budget: the batch protocol
answers many lookups over a single pipe.

- Object ids are validated as hex before they reach git, so a
  caller-supplied id can never become a flag or a path.
- A missing object is a named refusal (`object_not_found`),
  never an empty result pretending to be content: a damaged or
  empty answer must read as damaged (S-075's law, honoured
  early).
- Tree and commit payloads are parsed into plain data here —
  the raw tree format (mode, name, 20/32-byte id) and the
  commit header block are git's stable plumbing formats.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .proc import run_git_in

_OID_RE = re.compile(r"^[0-9a-f]{4,64}$")
OBJECT_TYPES = frozenset({"blob", "tree", "commit", "tag"})


class ObjectError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class GitObject:
    oid: str
    type: str
    size: int
    data: bytes


@dataclass(frozen=True)
class TreeEntry:
    mode: str
    name: str
    oid: str

    @property
    def type(self) -> str:
        if self.mode == "40000":
            return "tree"
        if self.mode == "160000":
            return "commit"  # submodule gitlink
        return "blob"


@dataclass(frozen=True)
class Commit:
    oid: str
    tree: str
    parents: tuple[str, ...] = ()
    author: str = ""
    committer: str = ""
    message: str = ""
    extra_headers: dict = field(default_factory=dict)


def _validate_oid(oid: object) -> str:
    if not isinstance(oid, str) or not _OID_RE.match(oid.lower()):
        raise ObjectError("oid_invalid", f"Not an object id: {oid!r}")
    return oid.lower()


class ObjectReader:
    def __init__(self, repo_path: Path):
        self._repo = Path(repo_path)

    def read_objects(self, oids: list[str]) -> list[GitObject]:
        """Batch-read many objects in one git spawn, in order."""
        wanted = [_validate_oid(o) for o in oids]
        if not wanted:
            return []
        result = run_git_in(
            self._repo, ["cat-file", "--batch"],
            input_bytes=("\n".join(wanted) + "\n").encode(), timeout=60.0)
        if result.returncode != 0:
            raise ObjectError(
                "cat_file_failed",
                result.stderr.decode("utf-8", "replace").strip()[:200])
        out = result.stdout
        objects: list[GitObject] = []
        pos = 0
        for oid in wanted:
            nl = out.find(b"\n", pos)
            if nl < 0:
                raise ObjectError("object_not_found", f"{oid} not found")
            header = out[pos:nl].decode("ascii", "replace")
            pos = nl + 1
            parts = header.split(" ")
            if len(parts) < 2 or parts[1] == "missing":
                raise ObjectError("object_not_found", f"{oid} not found")
            obj_type, size = parts[1], int(parts[2])
            data = out[pos:pos + size]
            if len(data) != size:
                raise ObjectError("object_truncated", f"{oid} truncated")
            pos += size + 1  # payload + its trailing LF
            objects.append(GitObject(
                oid=parts[0], type=obj_type, size=size, data=data))
        return objects

    def read_object(self, oid: str) -> GitObject:
        return self.read_objects([oid])[0]

    def object_type(self, oid: str) -> str:
        return self.read_object(oid).type

    def read_blob(self, oid: str) -> bytes:
        obj = self.read_object(oid)
        if obj.type != "blob":
            raise ObjectError("wrong_type", f"{oid} is a {obj.type}, not a blob")
        return obj.data

    def read_tree(self, oid: str) -> list[TreeEntry]:
        obj = self.read_object(oid)
        if obj.type != "tree":
            raise ObjectError("wrong_type", f"{oid} is a {obj.type}, not a tree")
        entries: list[TreeEntry] = []
        data, pos = obj.data, 0
        # Loose-object ids are SHA-1 (20 bytes) or SHA-256 (32);
        # the id width follows the remaining framing — entry size
        # is proven by the NUL-delimited header before each id.
        id_len = 20
        # Detect SHA-256 repos: a tree whose parse at 20 bytes
        # does not consume exactly is retried at 32.
        parsed = _parse_tree(data, id_len)
        if parsed is None:
            parsed = _parse_tree(data, 32)
        if parsed is None:
            raise ObjectError("tree_unparsable", f"Tree {oid} did not parse")
        return parsed

    def read_commit(self, oid: str) -> Commit:
        obj = self.read_object(oid)
        if obj.type != "commit":
            raise ObjectError("wrong_type", f"{oid} is a {obj.type}, not a commit")
        head, _, message = obj.data.partition(b"\n\n")
        tree, parents, author, committer, extra = "", [], "", "", {}
        for line in head.decode("utf-8", "replace").splitlines():
            key, _, value = line.partition(" ")
            if key == "tree":
                tree = value
            elif key == "parent":
                parents.append(value)
            elif key == "author":
                author = value
            elif key == "committer":
                committer = value
            else:
                extra[key] = value
        return Commit(
            oid=obj.oid, tree=tree, parents=tuple(parents),
            author=author, committer=committer,
            message=message.decode("utf-8", "replace"),
            extra_headers=extra)


def _parse_tree(data: bytes, id_len: int) -> list[TreeEntry] | None:
    entries: list[TreeEntry] = []
    pos = 0
    while pos < len(data):
        sp = data.find(b" ", pos)
        if sp < 0:
            return None
        # Tree modes are stored as bare ASCII octal: directories
        # are exactly "40000", blobs "100644"/"100755"/"120000".
        mode = data[pos:sp].decode("ascii", "replace")
        nul = data.find(b"\x00", sp)
        if nul < 0 or nul + 1 + id_len > len(data):
            return None
        name = data[sp + 1:nul].decode("utf-8", "surrogateescape")
        oid = data[nul + 1:nul + 1 + id_len].hex()
        entries.append(TreeEntry(mode=mode, name=name, oid=oid))
        pos = nul + 1 + id_len
    return entries if pos == len(data) else None
