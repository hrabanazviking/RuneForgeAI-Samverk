"""Large-repository budgets (S-073).

A forge that is lovely on a toy repo and unusable on a real
one has failed its founding test. This slice states the
clone budget plainly, per hardware class, and measures it:

- The **reference repository** is defined in code, not by
  pointing at whatever happens to be on disk: 1,000 commits,
  2,000 blobs, ~4 MiB of object data — the shape the battery
  builds with `git fast-import` (test-side tooling) and the
  shape Part XXI re-measures on real hardware.
- `measure_local_clone` times a clone through S-055's
  dedicated local seam, measures the result with S-058's
  walk, and answers whether it landed inside the budget
  *for the hardware class it ran on*.
- **CPU honesty (Part XXII's law, honoured early):** a
  budget proven on one class claims nothing about another.
  This VM is x86-64 server-class; its measured number is
  recorded for that class only. The Pi-class budget is
  *stated* here (60 s) and remains **NOT PROVEN** until
  Part XXI/XXII runs the same measurement on Pi-class
  hardware.
"""

from __future__ import annotations

import platform
import time
from dataclasses import dataclass
from pathlib import Path

from .proc import run_git_clone_local
from .repo_size import measure_path

# The reference repository's shape (see module docstring).
REFERENCE_COMMITS = 1000
REFERENCE_BLOBS = 2000

# Stated clone budgets, seconds, per hardware class. Only a
# class whose measurement actually ran may claim its budget.
CLONE_BUDGETS_SECONDS = {
    "server_x86_64": 30.0,
    "laptop_x86_64": 60.0,
    "pi_class_arm": 60.0,
}


def hardware_class() -> str:
    """The class of the machine this code is running on.

    Deliberately coarse and honest: an ARM board is reported
    as Pi-class *shape* only — a server-class ARM machine
    measuring here would still need Part XXII's cell proof
    before claiming the Pi budget, which is why measurements
    record the machine string alongside the class.
    """
    machine = platform.machine().lower()
    if machine in {"aarch64", "arm64", "armv7l", "armv6l"}:
        return "pi_class_arm"
    return "server_x86_64"


@dataclass(frozen=True)
class CloneMeasurement:
    source: str
    dest: str
    seconds: float
    total_bytes: int
    file_count: int
    hardware_class: str
    machine: str
    budget_seconds: float
    within_budget: bool


def measure_local_clone(source: Path, dest: Path, *,
                        budget_seconds: float | None = None,
                        timeout: float = 300.0) -> CloneMeasurement:
    """Clone `source` to `dest` (both trusted Paths, S-055's
    seam) and measure time + size against the class budget."""
    cls = hardware_class()
    budget = (CLONE_BUDGETS_SECONDS[cls] if budget_seconds is None
              else budget_seconds)
    started = time.monotonic()
    result = run_git_clone_local(Path(source), Path(dest), timeout=timeout)
    seconds = time.monotonic() - started
    if result.returncode != 0:
        raise ValueError(
            "clone_failed: " + result.stderr.decode(
                "utf-8", "replace").strip()[:200])
    size = measure_path(Path(dest))
    return CloneMeasurement(
        source=str(source), dest=str(dest), seconds=seconds,
        total_bytes=size.total_bytes, file_count=size.file_count,
        hardware_class=cls, machine=platform.machine(),
        budget_seconds=budget, within_budget=seconds <= budget)
