# Battery port: Linux on ARM (S-415)

The S-405 support matrix promises the server on Linux x ARM64
with the Raspberry Pi 5 as the floor (cell `linux-arm64-pi5`,
proving slice S-415). A cell is PROVEN only when its battery
has run in that cell. This slice executes the full battery
(S-394, `samverk.battery_v1` via `tools/run_battery_v1.py`)
on the Raspberry Pi 5 and records the counted run in
`samverk/battery_port_arm.py`.

## The counted run

Counted run executed 2026-11-22 on Mimir (purpleviking1,
Raspberry Pi 5, aarch64, Python 3.11.2, git 2.39.5) against
this tree (team-15, parent 080cf8e + S-415 files). Tree
identity verified: hash-of-hashes over every .py under
samverk/, tests/, tools/ identical on both machines
(1d4b15bd1069e0c61e6fa7c07eedaafc07378f9459c053d29f4efa0c343b2a99).
Tarball sha256 (prior worker, as transferred):
98d64f962c59645304845c40bf51f0d41760edcbc1de0283ac3a24e2b5523a4d.

Result: BATTERY V1 TOTAL legs=7 ran=6257 skipped=3
fails=61 FAILED (wall 4837.8s summed leg walls; unit leg
4787.5s). Legs: build 1 OK; plumbing-interop 6 OK;
transports 14 fails=1 FAILED; security 9 OK;
security-adversarial 15 OK; seam 3 OK; unit 6209
skipped=3 fails=60 FAILED.

Verdict: NOT PROVEN -- the counted run is not green, so
by this slice's own rules the cell stays NOT PROVEN.

Failure classes, named honestly:
- transports: test_real_sshd_cell_is_named -- sshd is
  present on Mimir, so the named real-sshd cell fails by
  design (on purplelongship the same cell is the
  neighbours' skipped=1).
- unit taxonomy/schema pins (~15): counts read higher
  than the pins (e.g. auth 34 vs 33, admin 16 vs 13).
  The identical failure reproduces on purplelongship
  x86_64 in this same tree -- pre-existing in the
  080cf8e tree, NOT an ARM port failure.
- unit rebase/revert cluster (~25 ERROR/FAIL):
  "git could not test the rebase" on the Pi; the same
  tests pass on purplelongship (git 2.53.0 vs Pi
  2.39.5 -- version gap is a named suspect, unproven).
- remaining unit fails are in the same two clusters
  (schema/taxonomy pins and git rebase/revert roads).
Logs: hidden_files/ in the Mimir tree
~/samverk-s415-pi-fresh (s415-counted-run.log,
battery-v1-*.log, shards-battery-v1-unit/).

## Honesty rules

- PROVEN requires: arch aarch64, every battery leg executed,
  zero fails. Anything less stays NOT PROVEN, in those words.
- The ARM run claims nothing about any other cell
  (`cross_cell_verdict` refuses by name: `cross_cell_claim`).
- Hardware weaker than a Pi 5 is outside the promise.
- No Docker was used anywhere in this port.
