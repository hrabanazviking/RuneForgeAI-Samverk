#!/usr/bin/env python3
"""S-398 -- Research corpus audit runner.

Reads every study file in research/, judges the corpus
against the S-398 census in samverk/research_corpus_audit.py,
and writes the audit log -- the release artifact -- as
markdown plus raw JSON.

Usage: python3 tools/run_research_audit.py --out-md PATH [--out-json PATH]
Exit code 0 only when the audit verdict is PASSED.
"""
import argparse, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from samverk.research_corpus_audit import render_audit_log, run_audit

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-md", required=True)
    ap.add_argument("--out-json")
    args = ap.parse_args()
    log = run_audit(ROOT)
    Path(args.out_md).write_text(render_audit_log(log), encoding="utf-8")
    if args.out_json:
        Path(args.out_json).write_text(json.dumps(log, indent=2, sort_keys=True), encoding="utf-8")
    print(log["verdict"])
    print(f"corpus: {log['total']} files, {log['complete']} complete, {len(log['open'])} open")
    for o in log["open"]:
        print(f"open {o['file']} owner {o['owner']}")
    for p in log["problems"]:
        print(f"FAILED {p}")
    return 0 if log["passed"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
