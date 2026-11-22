#!/usr/bin/env python3
"""S-394 — Battery v1 runner (pure stdlib).

Executes the assembled battery from samverk/battery_v1.py:
each leg runs as its own subprocess with a disk-backed
TMPDIR, logs land in hidden_files/battery-v1-<leg>.log, and
per-leg + total counts are printed at the end. Exit 0 only
if every executed leg is OK. The unit leg delegates to
tools/run_suite_sharded.py (full discovery).

Usage: python3 tools/run_battery_v1.py [--legs a,b,c]
"""
import argparse, os, re, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from samverk.battery_v1 import LEGS, run_build_leg, summarize


def parse_log(text):
    ran = 0; skipped = 0; fails = 0
    m = re.search(r"Ran (\d+) tests", text)
    if m: ran = int(m.group(1))
    m = re.search(r"skipped=(\d+)", text)
    if m: skipped = int(m.group(1))
    fails = len(re.findall(r"^(FAIL|ERROR): ", text, re.M))
    ok = fails == 0 and ran > 0
    return ran, skipped, fails, ok


def run_leg(name, mods):
    logdir = os.path.join(ROOT, "hidden_files")
    os.makedirs(logdir, exist_ok=True)
    tmpdir = os.path.join(ROOT, "hidden_files", "tmp-battery", name)
    os.makedirs(tmpdir, exist_ok=True)
    env = dict(os.environ); env["TMPDIR"] = tmpdir
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if name == "build":
        problems = run_build_leg()
        with open(os.path.join(logdir, "battery-v1-build.log"), "w") as lf:
            lf.write("build problems: %r\n" % (problems,))
        return dict(name=name, ran=1 if not problems else 0,
                    skipped=0, fails=len(problems), ok=not problems,
                    wall=0.0)
    if name == "unit":
        cmd = [sys.executable, "tools/run_suite_sharded.py",
               "--workers", "8", "--label", "battery-v1-unit"]
    else:
        cmd = [sys.executable, "-m", "unittest"] + list(mods)
    t0 = time.time()
    logpath = os.path.join(logdir, "battery-v1-%s.log" % name)
    with open(logpath, "w") as lf:
        p = subprocess.run(cmd, cwd=ROOT, env=env, stdout=lf,
                           stderr=subprocess.STDOUT)
    wall = time.time() - t0
    with open(logpath) as lf:
        text = lf.read()
    if name == "unit":
        m = re.search(r"SUMMARY label=\S+ Ran=(\d+) skipped=(\d+) fails=(\d+)",
                      text)
        if m:
            ran, skipped, fails = (int(m.group(1)), int(m.group(2)),
                                   int(m.group(3)))
            return dict(name=name, ran=ran, skipped=skipped,
                        fails=fails, ok=fails == 0 and p.returncode == 0,
                        wall=wall)
    ran, skipped, fails, ok = parse_log(text)
    return dict(name=name, ran=ran, skipped=skipped, fails=fails,
                ok=ok and p.returncode == 0, wall=wall)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--legs", default="",
                    help="comma-separated subset of legs to run")
    args = ap.parse_args()
    wanted = [s.strip() for s in args.legs.split(",") if s.strip()]
    results = []
    for name, anchor, mods in LEGS:
        if wanted and name not in wanted:
            continue
        r = run_leg(name, mods)
        r["anchor"] = anchor
        results.append(r)
        print("leg %-20s (%s): ran=%d skipped=%d fails=%d %s wall=%.1fs"
              % (name, anchor, r["ran"], r["skipped"], r["fails"],
                 "OK" if r["ok"] else "FAILED", r["wall"]), flush=True)
    total = summarize(results)
    print("BATTERY V1 TOTAL: legs=%d ran=%d skipped=%d fails=%d %s"
          % (total["legs"], total["ran"], total["skipped"],
             total["fails"], "OK" if total["ok"] else "FAILED"))
    return 0 if total["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
