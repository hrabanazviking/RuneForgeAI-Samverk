#!/usr/bin/env python3
"""S-413 -- CPU honesty register printer (pure stdlib).
Usage: python3 tools/run_cpu_honesty.py
Prints the full budget register: every budget kind x
every hardware class, its stated budget, source slice,
and proof status in words. This tool measures nothing:
measured numbers printed are S-395's published ones,
and laptop x86-64 prints NOT PROVEN (see
docs/CPU_HONESTY.md).
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from samverk.cpu_honesty import budget_register, class_status
from samverk.search_budgets import HARDWARE_CLASSES

def main():
    for cls in HARDWARE_CLASSES:
        print(f"{cls}: {class_status(cls)}")
    for e in budget_register():
        num = (f"measured {e.measured} {e.unit} on {e.machine}"
               if e.status == "measured" else "NOT PROVEN")
        print(f"{e.kind} [{e.hardware_class}] budget "
              f"{e.budget} {e.unit} ({e.source}) -- {num}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
