#!/usr/bin/env python3
"""S-397 — Documentation completeness walk runner.

Stands up a real instance from this tree (S-349 install
walk), boots the tree's own server, walks the four
guides' claims against it, and writes the walk log —
the release artifact — as markdown plus raw JSON.

Usage: python3 tools/run_docs_walk.py --out-md PATH
       [--out-json PATH] [--work DIR]
Exit code 0 only when the walk verdict is PASSED.
"""
import argparse, json, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from samverk.docs_completeness import render_walk_log, walk_live_instance

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-md", required=True)
    ap.add_argument("--out-json")
    ap.add_argument("--work")
    args = ap.parse_args()
    if args.work:
        work = Path(args.work); work.mkdir(parents=True, exist_ok=True)
        log = walk_live_instance(ROOT, work)
    else:
        with tempfile.TemporaryDirectory() as td:
            log = walk_live_instance(ROOT, Path(td))
    Path(args.out_md).write_text(render_walk_log(log), encoding="utf-8")
    if args.out_json:
        Path(args.out_json).write_text(json.dumps(log, indent=2, sort_keys=True), encoding="utf-8")
    print(log["verdict"])
    for c in log["checks"]:
        print(f"{'ok' if c['ok'] else 'FAILED'} {c['name']}: {c['detail']}")
    return 0 if log["passed"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
