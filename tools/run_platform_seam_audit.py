#!/usr/bin/env python3
"""S-406 — Platform seam audit runner (pure stdlib).

Usage: python3 tools/run_platform_seam_audit.py
Prints the touchpoint counts, the named inventory remainders, and
any uninventoried strays. Exit 0 only when no uninventoried stray
exists; the audit is honest — inventoried remainders are reported,
never hidden.
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pathlib import Path
from samverk.platform_seam_audit import INVENTORY, audit_tree

def main():
    r = audit_tree(Path(ROOT))
    print(f"files scanned (outside the seam): {r['files_scanned']}")
    for cat, n in sorted(r["per_category"].items()):
        print(f"  {cat}: {n}")
    print(f"inventoried remainders: {len(r['inventoried'])}")
    for f, cats in sorted(INVENTORY.items()):
        for cat, why in sorted(cats.items()):
            print(f"  samverk/{f} [{cat}]: {why}")
    print(f"uninventoried strays: {len(r['strays'])}")
    for s in r["strays"]:
        print(f"  STRAY {s['file']}:{s['line']} [{s['category']}] {s['text']}")
    print("VERDICT:", "CLEAN of uninventoried strays" if r["clean"] else "STRAYS PRESENT")
    return 0 if r["clean"] else 1

if __name__ == "__main__":
    sys.exit(main())
