#!/usr/bin/env python3
"""S-407 — Dependency replaceability register runner (pure stdlib).

Usage: python3 tools/run_dependency_replaceability.py
Prints every registered dependency with its per-OS replacement
path, cross-checks the register against the tree on disk, and
exits 0 only when no defect exists (a missing per-OS path or an
irreplaceable dependency is a defect — Never-Leave-A-Bug law).
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pathlib import Path
from samverk.dependency_replaceability import REGISTER, audit_tree

def main():
    r = audit_tree(Path(ROOT))
    print(f"dependencies registered: {r['dependencies']}")
    for d in REGISTER:
        print(f"- {d.name} [{d.kind}] used for: {d.used_for}")
        for os_name, path in d.per_os:
            print(f"    {os_name}: {path}")
        if d.risk:
            print(f"    risk: {d.risk}")
    print(f"non-stdlib imports on disk: {r['non_stdlib_imports']}")
    print(f"allowed external programs: {r['allowed_programs']}")
    print(f"defects: {len(r['defects'])}")
    for x in r["defects"]:
        print(f"  DEFECT {x}")
    print("VERDICT:", "CLEAN — every dependency names a per-OS replacement path" if r["clean"] else "DEFECTS PRESENT")
    return 0 if r["clean"] else 1

if __name__ == "__main__":
    sys.exit(main())
