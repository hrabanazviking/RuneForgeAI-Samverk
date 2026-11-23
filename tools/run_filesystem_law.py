#!/usr/bin/env python3
"""S-408 — Filesystem law runner (pure stdlib).
Usage: python3 tools/run_filesystem_law.py [directory]
Probes the directory's filesystem kind (default: a fresh temp
dir), audits it for case collisions, demonstrates the
deterministic refusal, and exits 0 only when the audited
directory is clean. The insensitive kind is shown through the
honest simulation, labelled as simulation.
"""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pathlib import Path
from samverk.filesystem_law import (FilesystemLawError, SimulatedInsensitiveDirectory,
    audit_directory, check_names, probe_case_sensitive)

def main():
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="s408-"))
    r = audit_directory(target)
    kind = "case-sensitive" if r["case_sensitive"] else "case-insensitive"
    print(f"directory: {target}")
    print(f"probed kind: {kind} (probed, not guessed)")
    print(f"entries: {len(r['names'])}")
    for g in r["collisions"]:
        print(f"  COLLISION: {' vs '.join(g)}")
    try:
        check_names(["ReadMe", "readme"])
        print("DEFECT: colliding pair was accepted")
        return 1
    except FilesystemLawError as e:
        print(f"collision pair refused deterministically: {e.reason}")
    sim = SimulatedInsensitiveDirectory()
    sim.store("ReadMe", "1"); merged = sim.store("readme", "2")
    print(f"simulated insensitive dir merges case variants: {merged} (SIMULATION, not a real insensitive-FS run)")
    print("VERDICT:", "CLEAN — no case collisions on disk; collisions refused deterministically" if r["clean"] else "COLLISIONS PRESENT")
    return 0 if r["clean"] else 1

if __name__ == "__main__":
    sys.exit(main())
