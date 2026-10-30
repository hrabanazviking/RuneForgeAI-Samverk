"""Ref listing, resolution and updates (S-052, S-053).

Refs are git's own data; Samverk reads and writes them only
through plumbing (`for-each-ref`, `symbolic-ref`, `rev-parse`,
`update-ref`) under S-014, so packed-refs and every other
storage detail stay git's problem, never ours.

- **Listing (S-052).** One `for-each-ref` spawn returns every
  ref with its object id, type, and peeled id for annotated
  tags. HEAD is read through `symbolic-ref` — the indirection
  itself is the answer, not a guess from the default branch.
- **Updates (S-053).** Branch create / delete / rename and
  general ref updates go through `update-ref` with
  compare-and-swap discipline: a caller that names the
  expected old value gets an atomic check-and-set from git's
  own lock, so two writers racing the same ref cannot tear
  it — exactly one wins, the other is refused by name
  (`stale_ref`). Rename is a create+delete pair in a single
  `update-ref --stdin` invocation (one lock batch), verified
  against the old value.
- Ref names are validated before they reach git (no leading
  dash, no `..`, no empty components), so a name can never be
  read as a flag.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .proc import run_git_in

_REF_RE = re.compile(r"^(?!-)[A-Za-z0-9][A-Za-z0-9._/-]*$")
_OID_RE = re.compile(r"^[0-9a-f]{40}$|^[0-9a-f]{64}$")
ZERO_OIDS = frozenset({"0" * 40, "0" * 64})


class RefError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def validate_ref_name(name: object, *, full: bool = False) -> str:
    if (not isinstance(name, str) or not name or len(name) > 255
            or not _REF_RE.match(name) or ".." in name or "//" in name
            or name.endswith("/") or name.endswith(".")
            or name.endswith(".lock") or "@{" in name):
        raise RefError("ref_invalid", f"Not a ref name: {name!r}")
    if full and not name.startswith("refs/"):
        raise RefError("ref_invalid", f"Full ref must start with refs/: {name!r}")
    return name


def branch_ref(short_name: object) -> str:
    validate_ref_name(short_name)
    return f"refs/heads/{short_name}"


def tag_ref(short_name: object) -> str:
    validate_ref_name(short_name)
    return f"refs/tags/{short_name}"


@dataclass(frozen=True)
class Ref:
    name: str                 # full, e.g. refs/heads/main
    oid: str
    type: str                 # commit | tree | blob | tag
    peeled_oid: str | None = None

    @property
    def short(self) -> str:
        for prefix in ("refs/heads/", "refs/tags/", "refs/remotes/"):
            if self.name.startswith(prefix):
                return self.name[len(prefix):]
        return self.name

    @property
    def is_branch(self) -> bool:
        return self.name.startswith("refs/heads/")

    @property
    def is_tag(self) -> bool:
        return self.name.startswith("refs/tags/")


class RefStore:
    def __init__(self, repo_path: Path):
        self._repo = Path(repo_path)

    # -- S-052: listing and resolution ---------------------------
    def list_refs(self) -> list[Ref]:
        result = run_git_in(
            self._repo,
            ["for-each-ref",
             "--format=%(refname)%00%(objectname)%00%(objecttype)%00%(*objectname)"],
            timeout=30.0)
        if result.returncode != 0:
            raise RefError(
                "list_failed",
                result.stderr.decode("utf-8", "replace").strip()[:200])
        refs: list[Ref] = []
        for line in result.stdout.decode("utf-8", "surrogateescape").splitlines():
            if not line:
                continue
            name, oid, obj_type, peeled = (line.split("\x00") + ["", "", "", ""])[:4]
            refs.append(Ref(
                name=name, oid=oid, type=obj_type,
                peeled_oid=peeled or None))
        return refs

    def list_branches(self) -> list[Ref]:
        return [r for r in self.list_refs() if r.is_branch]

    def list_tags(self) -> list[Ref]:
        return [r for r in self.list_refs() if r.is_tag]

    def resolve(self, name: object) -> str | None:
        """The object id a name points at today, or None."""
        validate_ref_name(name)  # type: ignore[arg-type]
        result = run_git_in(
            self._repo, ["rev-parse", "--verify", "--quiet", f"{name}^{{object}}"],
            timeout=15.0)
        if result.returncode != 0:
            return None
        return result.stdout.decode().strip() or None

    def head_ref(self) -> str | None:
        """HEAD's symbolic target (e.g. refs/heads/main), or
        None when HEAD is detached."""
        result = run_git_in(
            self._repo, ["symbolic-ref", "--quiet", "HEAD"], timeout=15.0)
        if result.returncode != 0:
            return None
        return result.stdout.decode().strip() or None

    def head_oid(self) -> str | None:
        return self.resolve("HEAD")
