#!/usr/bin/env python3
"""S-405 runner: judge the support matrix as data,
write the matrix document and its counted log, lay
the ratified matrix section into research file 45
(between the S-405 markers, refreshed in place), and
record the census in hidden_files.

Usage: python3 tools/run_support_matrix.py
Writes: docs/SUPPORT_MATRIX.md,
        docs/support-matrix-s405.md,
        research/45-cross-platform-architecture.md
          (S-405 section only),
        hidden_files/s405-matrix.json
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from samverk.support_matrix import (  # noqa: E402
    MATRIX_CELLS, RESEARCH_FILE, SECTION_BEGIN,
    SECTION_END, audit_matrix, judge_matrix,
    matrix_counts, render_matrix, render_matrix_log,
    render_matrix_section)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def lay_section_into_research45():
    path = os.path.join(ROOT, RESEARCH_FILE)
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    section = render_matrix_section()
    if SECTION_BEGIN in text and SECTION_END in text:
        head, rest = text.split(SECTION_BEGIN, 1)
        _, tail = rest.split(SECTION_END, 1)
        text = head + section + tail
    else:
        if not text.endswith("\n"):
            text += "\n"
        text += "\n" + section + "\n"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def main():
    problems = list(judge_matrix())
    if problems:
        print("MATRIX DATA PROBLEMS:")
        for p in problems:
            print("- %s" % p)
        return 2
    with open(os.path.join(ROOT, "docs",
              "SUPPORT_MATRIX.md"), "w") as fh:
        fh.write(render_matrix())
    with open(os.path.join(ROOT, "docs",
              "support-matrix-s405.md"), "w") as fh:
        fh.write(render_matrix_log())
    lay_section_into_research45()
    problems = list(audit_matrix(ROOT))
    counts = matrix_counts()
    record = {"counts": counts, "problems": problems,
              "cells": [c.cell_id for c in MATRIX_CELLS]}
    out = os.path.join(ROOT, "hidden_files")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "s405-matrix.json"), "w") as fh:
        json.dump(record, fh, indent=2, sort_keys=True)
    print(json.dumps(record, indent=2, sort_keys=True))
    if problems:
        print("MATRIX AUDIT PROBLEMS:")
        for p in problems:
            print("- %s" % p)
        return 2
    print("SUPPORT MATRIX RATIFIED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
