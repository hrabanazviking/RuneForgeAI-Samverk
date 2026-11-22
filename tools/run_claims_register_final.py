#!/usr/bin/env python3
"""S-399 -- Claims register final runner.

Judges every final claim in samverk/claims_register_final.py
against the tree and writes the counted final register log --
the release artifact -- as markdown plus raw JSON.

Usage: python3 tools/run_claims_register_final.py --out-md PATH [--out-json PATH]
Exit code 0 only when the verdict is PASSED.
"""
import argparse, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from samverk.claims_register_final import render_register_log, run_audit

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-md", required=True)
    ap.add_argument("--out-json")
    args = ap.parse_args()
    log = run_audit(ROOT)
    Path(args.out_md).write_text(render_register_log(log), encoding="utf-8")
    if args.out_json:
        Path(args.out_json).write_text(json.dumps(log, indent=2, sort_keys=True), encoding="utf-8")
    print(log["verdict"])
    print(f"final claims: {log['total']}, counts: {log['counts']}")
    for p in log["problems"]:
        print(f"FAILED {p}")
    return 0 if log["passed"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
