"""Corruption behaviour (S-075).

A damaged repository must read as **damaged** — an honest
error naming the damage — never as empty, never as healthy,
and never as silently missing content. The distinction
matters because the remedies are opposites: an empty repo
waits for a first push; a damaged repo needs its backup
(S-074) and its operator.

`assess_repository` is the one health seam:

- **missing** — no directory at the path at all.
- **not_a_repository** — a directory, but no bare-repo
  layout (no HEAD / objects).
- **empty** — a sound bare repository with no refs yet:
  healthy, waiting, *not* damage.
- **healthy** — refs exist and `git fsck --full` is clean.
- **damaged** — fsck reports errors, or HEAD itself is
  unreadable: the report carries fsck's own lines as its
  detail, and `ensure_readable` raises `RepoDamagedError`
  for callers that need the exception shape.

fsck runs through S-014 (the `fsck` subcommand was admitted
there for this slice, read-only). Nothing here repairs:
repair is restore-from-backup, a deliberate operator act.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .proc import run_git_in
from .refs import RefStore


class RepoDamagedError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class HealthReport:
    status: str            # missing|not_a_repository|empty|healthy|damaged
    detail: str = ""
    ref_count: int = 0

    @property
    def readable(self) -> bool:
        return self.status in {"empty", "healthy"}


def assess_repository(repo_path: Path) -> HealthReport:
    path = Path(repo_path)
    if not path.exists():
        return HealthReport("missing", f"no directory at {path}")
    if not path.is_dir() or not (path / "HEAD").is_file() \
            or not (path / "objects").is_dir():
        return HealthReport(
            "not_a_repository",
            "directory lacks a bare repository's HEAD/objects layout")
    try:
        refs = RefStore(path).list_refs()
    except Exception as exc:
        return HealthReport("damaged", f"ref listing failed: {exc}"[:300])
    result = run_git_in(path, ["fsck", "--full"], timeout=120.0)
    fsck_lines = (result.stderr + result.stdout).decode(
        "utf-8", "replace").strip()
    if result.returncode != 0:
        return HealthReport(
            "damaged",
            (fsck_lines.splitlines()[0] if fsck_lines
             else "git fsck failed without detail")[:300],
            ref_count=len(refs))
    if not refs:
        return HealthReport("empty", "sound repository, no refs yet", 0)
    return HealthReport("healthy", "fsck clean", ref_count=len(refs))


def ensure_readable(repo_path: Path) -> HealthReport:
    """Return the report for a readable repository; raise
    `RepoDamagedError` (reason = the status) for any other."""
    report = assess_repository(repo_path)
    if not report.readable:
        raise RepoDamagedError(
            report.status,
            f"Repository reads as {report.status}: {report.detail}")
    return report
