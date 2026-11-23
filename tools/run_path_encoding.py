#!/usr/bin/env python3
"""S-409 — Path and encoding discipline runner (pure stdlib).
Usage: python3 tools/run_path_encoding.py [directory]
Audits a source tree (default: this repo's samverk/ package) for
CRLF bytes, invalid UTF-8, and non-NFC text; demonstrates the
canonicalisation seam and the deterministic refusals; exits 0
only when the audited tree is clean. Windows separator behaviour
is proven by the pure law (backslash inputs), not by a Windows
run — no Windows run is claimed.
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pathlib import Path
from samverk.path_encoding import (PathEncodingError, audit_source_tree,
    canonical_path, check_stored_path)

def main():
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(ROOT) / "samverk"
    r = audit_source_tree(target)
    print(f"directory: {target}")
    print(f"files scanned: {r['files_scanned']}")
    for label, key in (("CRLF/CR bytes", "crlf_files"),
                       ("invalid UTF-8", "non_utf8_files"),
                       ("non-NFC text", "non_nfc_files")):
        for name in r[key]:
            print(f"  DIRT ({label}): {name}")
        if not r[key]:
            print(f"  {label}: none")
    print(f"seam demo: 'refs\\heads\\main' -> {canonical_path('refs\\heads\\main')!r}")
    try:
        check_stored_path("refs\\heads\\main")
        print("DEFECT: backslash stored path was accepted")
        return 1
    except PathEncodingError as e:
        print(f"backslash stored path refused at check seam: {e.reason}")
    for bad in ("/abs/path", "a/../b", "a//b"):
        try:
            canonical_path(bad)
            print(f"DEFECT: {bad!r} was accepted")
            return 1
        except PathEncodingError as e:
            print(f"refused {bad!r}: {e.reason}")
    print("VERDICT:", "CLEAN — tree bytes canonical; seam normalises, check seam refuses"
          if r["clean"] else "DIRT PRESENT in audited tree")
    return 0 if r["clean"] else 1

if __name__ == "__main__":
    sys.exit(main())
