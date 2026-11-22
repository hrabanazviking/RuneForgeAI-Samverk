#!/usr/bin/env python3
"""S-404 runner: judge the final census as data,
write the census document and its counted log, and
record the census in hidden_files.

Usage: python3 tools/run_final_census.py
Writes: docs/FINAL_CENSUS.md,
        docs/final-census-s404.md,
        hidden_files/s404-census.json
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from samverk.final_census import (  # noqa: E402
    ALL_ROWS, audit_census, census_counts, judge_census,
    render_census, render_census_log, slice_accounting)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    problems = list(judge_census())
    if problems:
        print("CENSUS DATA PROBLEMS:")
        for p in problems:
            print("- %s" % p)
        return 2
    with open(os.path.join(ROOT, "docs",
              "FINAL_CENSUS.md"), "w") as fh:
        fh.write(render_census())
    with open(os.path.join(ROOT, "docs",
              "final-census-s404.md"), "w") as fh:
        fh.write(render_census_log())
    problems = list(audit_census(ROOT))
    record = {"counts": census_counts(),
              "accounting": slice_accounting(),
              "problems": problems,
              "rows": [r.row_id for r in ALL_ROWS]}
    out = os.path.join(ROOT, "hidden_files")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "s404-census.json"), "w") as fh:
        json.dump(record, fh, indent=2, sort_keys=True)
    print(json.dumps(record, indent=2, sort_keys=True))
    if problems:
        print("CENSUS AUDIT PROBLEMS:")
        for p in problems:
            print("- %s" % p)
        return 2
    print("FINAL CENSUS COUNTED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
