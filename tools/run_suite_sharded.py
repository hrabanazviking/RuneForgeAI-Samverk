#!/usr/bin/env python3
"""Sharded test-suite runner for Samverk (pure stdlib).

Discovers tests/test_*.py, balances modules across N worker subprocesses
(round-robin over modules sorted by file size descending), runs each shard
as `python3 -m unittest <modules>` with its own disk-backed TMPDIR, streams
per-shard logs to hidden_files/shards-<label>/, then aggregates counts.
Exit 0 only if every shard (and the optional serial tail) is OK.

Usage: python3 tools/run_suite_sharded.py [--workers 8] [--label wave337]
       [--serial-tail mod1,mod2] [--modules modA,modB] 
"""
import argparse, os, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def discover():
    tdir = os.path.join(ROOT, "tests")
    mods = []
    for name in os.listdir(tdir):
        if name.startswith("test_") and name.endswith(".py"):
            mods.append((name[:-3], os.path.getsize(os.path.join(tdir, name))))
    mods.sort(key=lambda t: -t[1])
    return [m for m, _ in mods]

def parse_log(text):
    ran = 0; skipped = 0; ok = False
    m = re.search(r"Ran (\d+) tests", text)
    if m: ran = int(m.group(1))
    m = re.search(r"skipped=(\d+)", text)
    if m: skipped = int(m.group(1))
    tail = text.strip().splitlines()[-1] if text.strip() else ""
    ok = tail.startswith("OK")
    fails = len(re.findall(r"^(FAIL|ERROR): ", text, re.M))
    return ran, skipped, ok, fails

def run_shard(idx, mods, label, base_tmp):
    logdir = os.path.join(ROOT, "hidden_files", "shards-" + label)
    os.makedirs(logdir, exist_ok=True)
    tmpdir = os.path.join(ROOT, "hidden_files", "tmp-shards", "shard-%d" % idx)
    os.makedirs(tmpdir, exist_ok=True)
    env = dict(os.environ); env["TMPDIR"] = tmpdir; env["PYTHONDONTWRITEBYTECODE"] = "1"
    cmd = [sys.executable, "-m", "unittest"] + ["tests." + m for m in mods]
    t0 = time.time()
    with open(os.path.join(logdir, "shard-%02d.log" % idx), "w") as lf:
        p = subprocess.run(cmd, cwd=ROOT, env=env, stdout=lf, stderr=subprocess.STDOUT)
    wall = time.time() - t0
    with open(os.path.join(logdir, "shard-%02d.log" % idx)) as lf:
        text = lf.read()
    ran, skipped, ok, fails = parse_log(text)
    return dict(idx=idx, mods=len(mods), ran=ran, skipped=skipped,
                ok=ok and p.returncode == 0, fails=fails, wall=wall, rc=p.returncode)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--label", default="run")
    ap.add_argument("--serial-tail", default="", help="comma-separated module names (no tests. prefix) run sequentially after shards")
    ap.add_argument("--modules", default="", help="comma-separated subset to run instead of full discovery")
    a = ap.parse_args()
    tail = [m.strip() for m in a.serial_tail.split(",") if m.strip()]
    if a.modules:
        allmods = [m.strip() for m in a.modules.split(",") if m.strip()]
    else:
        allmods = discover()
    shard_mods = [m for m in allmods if m not in tail]
    shards = [[] for _ in range(a.workers)]
    for i, m in enumerate(shard_mods):
        shards[i % a.workers].append(m)
    shards = [s for s in shards if s]
    t0 = time.time()
    results = []
    with ThreadPoolExecutor(max_workers=len(shards)) as ex:
        futs = [ex.submit(run_shard, i, s, a.label, None) for i, s in enumerate(shards)]
        for f in futs: results.append(f.result())
    tail_res = None
    if tail:
        tail_res = run_shard(99, tail, a.label, None)
        results.append(tail_res)
    wall = time.time() - t0
    results.sort(key=lambda r: -r["wall"])
    tran = sum(r["ran"] for r in results); tskip = sum(r["skipped"] for r in results)
    tfail = sum(r["fails"] for r in results); allok = all(r["ok"] for r in results)
    print("=== SHARDED SUITE label=%s workers=%d wall=%.1fs ===" % (a.label, a.workers, wall))
    for r in results:
        print("shard %02d: mods=%d ran=%d skipped=%d fails=%d wall=%.1fs %s" % (
            r["idx"], r["mods"], r["ran"], r["skipped"], r["fails"], r["wall"], "OK" if r["ok"] else "FAILED rc=%d" % r["rc"]))
    print("SUMMARY label=%s Ran=%d skipped=%d fails=%d wall=%.1fs %s" % (
        a.label, tran, tskip, tfail, wall, "OK" if allok else "FAILED"))
    return 0 if allok else 1

if __name__ == "__main__":
    sys.exit(main())
