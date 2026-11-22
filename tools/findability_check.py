#!/usr/bin/env python3
"""Findability release check (S-382).

Every release must pass: mint a token, create a repo and
add a mirror must each be findable from home inside the
step and time budgets. Exits 0 when all three pass, 1
with the failing tasks named otherwise.

Run: python3 tools/findability_check.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk.layout_shell import audit_shell, run_findability


def main():
    problems = audit_shell()
    for problem in problems:
        print(f"shell: {problem}")
    failed = list(problems)
    for task, result in sorted(run_findability().items()):
        if result["ok"]:
            print(f"{task}: ok ({result['steps']} steps, "
                  f"{result['seconds']}s, {' > '.join(result['path'])})")
        else:
            print(f"{task}: FAIL ({result['reason']})")
            failed.append(task)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
