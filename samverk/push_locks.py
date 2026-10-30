"""Concurrent push behaviour (S-092).

Two pushes racing the same ref must never tear it. Git's own
ref locks already make a single ref update atomic (S-053's
compare-and-swap rides them); this slice decides the
*behaviour a pusher experiences* when Samverk-level work —
the S-089 gate, quota measurement, event recording — wraps
that update:

**Fail fast, with a clear message.** A second push to a ref
that is already being pushed to is refused immediately,
naming the repository and the ref and telling the pusher to
retry in a moment. It never waits in a queue (a queued push
is a hung client), and because the refusal happens *before*
the pack program runs, no objects land and no ref moves for
the loser — the winner's update is the only one, whole.

The lock is a **file**, not a memory flag: SSH sessions are
separate processes (study 02), so an in-process lock would be
invisible to exactly the races that matter. One lock file per
(repository, ref) lives under `<data_root>/locks/`, created
with `O_CREAT|O_EXCL` — the filesystem is the arbiter, and
creation either wholly succeeds or wholly fails. The file
carries the holder's pid and acquisition time (debuggable,
never secret).

**Stale locks heal.** A holder that died without releasing
(crashes happen) must not lock a ref forever: a lock older
than `stale_after_seconds` (default 600 — longer than S-091's
default wall clock, so a live push is never mistaken for a
dead one) is removed once and acquisition retried once. A
lock younger than that is always honoured.

The transports wire it per-repository (a receive-pack run
holds the repo-wide key `*` — the pack's target refs are
git's business until they land); direct callers may lock a
single named ref.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

DEFAULT_STALE_AFTER_SECONDS = 600.0
REPO_WIDE = "*"


class PushBusyError(ValueError):
    """The ref is already being pushed to; fail fast."""

    def __init__(self, full_name: str, ref: str):
        message = (
            f"Another push to {full_name} ({ref}) is already in "
            f"progress. Nothing was changed by this attempt — "
            f"wait a moment and push again.")
        super().__init__(message)
        self.reason = "push_in_progress"
        self.message = message
        self.full_name = full_name
        self.ref = ref


class PushLockManager:
    def __init__(self, data_root: Path,
                 stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
                 time_fn: Callable[[], float] = time.time):
        if stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be positive")
        self._locks_dir = Path(data_root) / "locks"
        self._stale_after = float(stale_after_seconds)
        self._now = time_fn

    def _lock_path(self, full_name: str, ref: str) -> Path:
        digest = hashlib.sha256(
            f"{full_name}\n{ref}".encode("utf-8")).hexdigest()
        return self._locks_dir / f"push-{digest}.lock"

    def _try_create(self, path: Path, full_name: str, ref: str) -> bool:
        self._locks_dir.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"repo": full_name, "ref": ref, "pid": os.getpid(),
                       "acquired_at": self._now()}, fh)
        return True

    def _is_stale(self, path: Path) -> bool:
        try:
            age = self._now() - path.stat().st_mtime
        except FileNotFoundError:
            return True   # vanished between checks: retry creation
        return age > self._stale_after

    @contextmanager
    def hold(self, full_name: str, ref: str = REPO_WIDE
             ) -> Iterator[None]:
        """Hold the push lock for (repo, ref) or raise
        PushBusyError immediately. Always released on exit,
        including on exceptions — a failed push frees the ref."""
        if not full_name or "/" not in full_name:
            raise ValueError(f"Not a repository name: {full_name!r}")
        if not ref:
            raise ValueError("A push lock needs a ref (or '*').")
        path = self._lock_path(full_name, ref)
        if not self._try_create(path, full_name, ref):
            if self._is_stale(path):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                if not self._try_create(path, full_name, ref):
                    raise PushBusyError(full_name, ref)
            else:
                raise PushBusyError(full_name, ref)
        try:
            yield
        finally:
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def is_held(self, full_name: str, ref: str = REPO_WIDE) -> bool:
        path = self._lock_path(full_name, ref)
        return path.exists() and not self._is_stale(path)
