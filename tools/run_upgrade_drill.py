#!/usr/bin/env python3
"""S-396 — Upgrade drill runner (pure stdlib + samverk).

Builds RC instances with real-shaped data, upgrades them
per S-357 (leg A: stand-in next migration, verified;
leg B: destructive migration, rolled back and verified),
and writes the drill log — the release artifact — as
markdown plus the raw JSON record.

Usage: python3 tools/run_upgrade_drill.py --out-md PATH
       [--out-json PATH] [--work DIR]
Exit code 0 only when the drill verdict is PASSED.
"""
import argparse, json, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from samverk.upgrade_drill import render_drill_log, run_drill


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-md", required=True)
    ap.add_argument("--out-json")
    ap.add_argument("--work")
    args = ap.parse_args()
    if args.work:
        work = Path(args.work); work.mkdir(parents=True, exist_ok=True)
        log = run_drill(work)
    else:
        with tempfile.TemporaryDirectory() as td:
            log = run_drill(Path(td))
    Path(args.out_md).write_text(render_drill_log(log), encoding="utf-8")
    if args.out_json:
        Path(args.out_json).write_text(
            json.dumps(log, indent=2, sort_keys=True), encoding="utf-8")
    print(f"UPGRADE DRILL {log['verdict']}")
    for leg in log["legs"]:
        print(f"{leg['leg']}: ok={leg['ok']} "
              f"elapsed={leg['elapsed_seconds']}s")
    return 0 if log["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
