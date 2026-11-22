"""S-394 — Battery v1, assembled.

One reproducible battery assembling the standing component
suites named by the roadmap: build, unit, plumbing interop
(S-076), transports (S-095), security (S-022 + S-311), and the
seam walk (S-374). This module is the single manifest every
runner reads: tools/run_battery_v1.py executes the legs in
order and reports per-leg counts; nothing here re-implements
a component suite — the battery assembles, it does not fork.

The unit leg is the full test discovery, executed through
tools/run_suite_sharded.py (the S-393 counted master run is
that leg executed at the 392/416 base). The build leg is a
real compile + import of the whole samverk package.
"""
from __future__ import annotations

import compileall
import importlib
import pkgutil

# (leg name, roadmap anchor, unittest modules) — order is the
# execution order: cheapest certainty first, the full unit
# discovery last.
LEGS = (
    ("build", "build", ()),
    ("plumbing-interop", "S-076", ("tests.test_git_core_battery",)),
    ("transports", "S-095", ("tests.test_transport_battery",
                             "tests.test_ssh_upload_routing")),
    ("security", "S-022", ("tests.test_security_battery",)),
    ("security-adversarial", "S-311", ("tests.test_adversarial_battery",)),
    ("seam", "S-374", ("tests.test_seam_battery",)),
    ("unit", "unit", ()),
)

REQUIRED_ANCHORS = ("build", "S-076", "S-095", "S-022",
                    "S-311", "S-374", "unit")


def leg_names() -> tuple:
    return tuple(name for name, _anchor, _mods in LEGS)


def leg_modules(name: str) -> tuple:
    for leg, _anchor, mods in LEGS:
        if leg == name:
            return mods
    raise KeyError(name)


def run_build_leg() -> list:
    """Compile every samverk module and import the package.

    Returns a list of problems; empty means the build leg
    passes. Compilation writes bytecode beside the sources,
    exactly as a normal import would.
    """
    problems = []
    import samverk
    if not compileall.compile_dir(
            samverk.__path__[0], quiet=1, force=False):
        problems.append("compileall reported failures")
    for info in pkgutil.iter_modules(samverk.__path__):
        try:
            importlib.import_module("samverk." + info.name)
        except Exception as exc:  # a build break is a finding
            problems.append("%s: %r" % (info.name, exc))
    return problems


def summarize(results: list) -> dict:
    """Aggregate per-leg result dicts (ran/skipped/fails/ok)."""
    total = {"legs": len(results), "ran": 0, "skipped": 0,
             "fails": 0, "ok": True}
    for r in results:
        total["ran"] += r["ran"]
        total["skipped"] += r["skipped"]
        total["fails"] += r["fails"]
        total["ok"] = total["ok"] and bool(r["ok"])
    return total
