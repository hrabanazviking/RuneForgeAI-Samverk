"""S-415 -- Battery port: Linux on ARM.

The Linux x ARM64 support-matrix cell (S-405 cell id
``linux-arm64-pi5``, proving slice S-415) flips to PROVEN only
when the full battery (S-394, samverk.battery_v1) has executed
green on the Raspberry Pi 5 and the counted run is recorded
here. This module is that record and its judge: it carries no
run of its own, invents no numbers, and refuses to carry the
ARM run to any other cell. A counted run whose unit leg is not
green is recorded as what it is and the cell stays NOT PROVEN.
"""
from __future__ import annotations

CELL_ID = "linux-arm64-pi5"
CELL_OS = "Linux"
CELL_CPU = "ARM64"
FLOOR = "Raspberry Pi 5"
BATTERY_ANCHOR = "S-394"
TREE_BASE = "080cf8ef9a261d6d1ce843cf1de58952cd277d5d"

# The counted run, filled only from a real execution of
# tools/run_battery_v1.py on the Pi 5 against this tree.
# None means: no counted run recorded; cell NOT PROVEN.
COUNTED_RUN = {
    "host": "purpleviking1", "arch": "aarch64",
    "date": "2026-11-22", "wall_seconds": 4837.8,
    "log_dir": "hidden_files (Mimir tree ~/samverk-s415-pi-fresh)",
    "legs": (
        {"name": "build", "ran": 1, "skipped": 0, "fails": 0, "ok": True},
        {"name": "plumbing-interop", "ran": 6, "skipped": 0,
         "fails": 0, "ok": True},
        {"name": "transports", "ran": 14, "skipped": 0, "fails": 1,
         "ok": False},
        {"name": "security", "ran": 9, "skipped": 0, "fails": 0,
         "ok": True},
        {"name": "security-adversarial", "ran": 15, "skipped": 0,
         "fails": 0, "ok": True},
        {"name": "seam", "ran": 3, "skipped": 0, "fails": 0, "ok": True},
        {"name": "unit", "ran": 6209, "skipped": 3, "fails": 60,
         "ok": False},
    ),
    "ran": 6257, "skipped": 3, "fails": 61, "ok": False,
}


class BatteryPortRefusal(Exception):
    def __init__(self, reason, message=""):
        super().__init__(message or reason)
        self.reason = reason


def cell_status(run=COUNTED_RUN) -> str:
    """PROVEN only for a complete, green, on-ARM counted run."""
    if run is None:
        return "not_proven"
    if run.get("arch") != "aarch64":
        return "not_proven"
    if run.get("fails", 1) != 0 or not run.get("ok"):
        return "not_proven"
    return "proven"


def status_reasons(run=COUNTED_RUN) -> tuple:
    if run is None:
        return ("no counted run recorded",)
    reasons = []
    if run.get("arch") != "aarch64":
        reasons.append("run arch is %r, not aarch64" % run.get("arch"))
    if run.get("fails", 1) != 0 or not run.get("ok"):
        reasons.append("counted run not green: fails=%s"
                       % run.get("fails"))
    return tuple(reasons)


def cross_cell_verdict(target_cell: str, run=COUNTED_RUN) -> str:
    """The ARM counted run proves this cell and no other."""
    if target_cell != CELL_ID:
        raise BatteryPortRefusal(
            "cross_cell_claim",
            "the Linux x ARM64 counted run claims nothing about %s"
            % target_cell)
    return cell_status(run)


def record_consistency(run=COUNTED_RUN) -> tuple:
    """Problems with the recorded run; empty means consistent."""
    if run is None:
        return ()
    problems = []
    legs = run.get("legs", ())
    if not legs:
        problems.append("counted run records no legs")
    ran = sum(l.get("ran", 0) for l in legs)
    skipped = sum(l.get("skipped", 0) for l in legs)
    fails = sum(l.get("fails", 0) for l in legs)
    if run.get("ran") != ran:
        problems.append("total ran %r != leg sum %r" % (run.get("ran"), ran))
    if run.get("skipped") != skipped:
        problems.append("total skipped mismatch")
    if run.get("fails") != fails:
        problems.append("total fails %r != leg sum %r" % (run.get("fails"), fails))
    if run.get("ok") != (fails == 0 and ran > 0):
        problems.append("ok flag disagrees with counts")
    for key in ("host", "arch", "date", "wall_seconds", "log_dir"):
        if not run.get(key):
            problems.append("counted run missing %s" % key)
    return tuple(problems)


def register() -> dict:
    run = COUNTED_RUN
    return {
        "cell_id": CELL_ID, "os": CELL_OS, "cpu": CELL_CPU,
        "floor": FLOOR, "battery": BATTERY_ANCHOR,
        "tree_base": TREE_BASE, "status": cell_status(run),
        "status_words": ("PROVEN" if cell_status(run) == "proven"
                         else "NOT PROVEN"),
        "reasons": status_reasons(run), "run": run,
    }


def render_register_log(data=None) -> str:
    d = data if data is not None else register()
    lines = ["S-415 battery port: Linux on ARM",
             "cell: %s (%s x %s, floor %s)" % (d["cell_id"], d["os"],
             d["cpu"], d["floor"]), "status: %s" % d["status_words"]]
    for r in d["reasons"]:
        lines.append("reason: %s" % r)
    run = d["run"]
    if run:
        lines.append("counted run: host=%s arch=%s date=%s ran=%s "
                     "skipped=%s fails=%s wall=%ss log=%s"
                     % (run["host"], run["arch"], run["date"],
                        run["ran"], run["skipped"], run["fails"],
                        run["wall_seconds"], run["log_dir"]))
        for leg in run["legs"]:
            lines.append("  leg %-20s ran=%s skipped=%s fails=%s %s"
                         % (leg["name"], leg["ran"], leg["skipped"],
                            leg["fails"], "OK" if leg["ok"] else "FAILED"))
    return "\n".join(lines) + "\n"
