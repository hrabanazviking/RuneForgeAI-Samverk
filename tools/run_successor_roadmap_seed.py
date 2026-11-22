#!/usr/bin/env python3
"""S-403 runner: judge the successor roadmap seed as
data, write the seed document and its counted log,
and record the census in hidden_files.

Usage: python3 tools/run_successor_roadmap_seed.py
Writes: docs/SUCCESSOR_ROADMAP_SEED.md,
        docs/successor-roadmap-seed-s403.md,
        hidden_files/s403-seed.json
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from samverk.successor_roadmap_seed import (  # noqa: E402
    SEED_ITEMS, audit_seed, judge_seed, render_seed,
    render_seed_log, seed_counts)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    problems = list(judge_seed())
    if problems:
        print("SEED DATA PROBLEMS:")
        for p in problems:
            print("- %s" % p)
        return 2
    with open(os.path.join(ROOT, "docs",
              "SUCCESSOR_ROADMAP_SEED.md"), "w") as fh:
        fh.write(render_seed())
    with open(os.path.join(ROOT, "docs",
              "successor-roadmap-seed-s403.md"), "w") as fh:
        fh.write(render_seed_log())
    problems = list(audit_seed(ROOT))
    counts = seed_counts()
    record = {"counts": counts, "problems": problems,
              "items": [it.item_id for it in SEED_ITEMS]}
    out = os.path.join(ROOT, "hidden_files")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "s403-seed.json"), "w") as fh:
        json.dump(record, fh, indent=2, sort_keys=True)
    print(json.dumps(record, indent=2, sort_keys=True))
    if problems:
        print("SEED AUDIT PROBLEMS:")
        for p in problems:
            print("- %s" % p)
        return 2
    print("SUCCESSOR ROADMAP SEEDED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
