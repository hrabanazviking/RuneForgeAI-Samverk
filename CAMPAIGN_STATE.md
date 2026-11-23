# S-415 -- team-15 campaign state

Slice: S-415 Battery port: Linux on ARM (roadmap Part XXII).
Base/parent: 080cf8ef9a261d6d1ce843cf1de58952cd277d5d (verified
via git ls-remote in ~/samverk-forge at build start).
Status: HELD -- unpushed, unmerged; banks only after S-402
(founder-only) and S-403..S-414 in roadmap order.
Built fresh in ~/samverk-team-15; team-14 untouched (raw
material only, its Mimir tree copy not trusted or reused).

Files: samverk/battery_port_arm.py (register + counted-run
record), tests/test_battery_port_arm.py, tools/
run_battery_port_arm.py, docs/BATTERY_PORT_ARM.md,
docs/battery-port-arm-s415.md.

Own battery (purplelongship): tests.test_battery_port_arm
Ran 8 OK. Neighbours: test_battery_v1 + test_seam_battery +
test_transport_battery + test_security_battery +
test_adversarial_battery Ran 37 OK (skipped=1, named real-sshd
cell). Logs: hidden_files/ on purplelongship team-15.

Counted run: full S-394 battery (tools/run_battery_v1.py)
executed on Mimir (purpleviking1, Raspberry Pi 5, aarch64)
against the team-15 tree transferred by tarball over the
tailnet (sha256 98d64f962c59645304845c40bf51f0d41760edcbc1
de0283ac3a24e2b5523a4d, verified identical on Mimir).
FINAL VERIFIED RESULT (replacement worker, 2026-11-22
~23:52 EST): the counted run COMPLETED on Mimir.
BATTERY V1 TOTAL legs=7 ran=6257 skipped=3 fails=61
FAILED. Legs: build 1 OK; plumbing-interop 6 OK;
transports 14 fails=1 FAILED (named real-sshd cell:
sshd present on Mimir, fails by design; skipped=1 in
the purplelongship neighbours); security 9 OK;
security-adversarial 15 OK; seam 3 OK; unit 6209
skipped=3 fails=60 FAILED (taxonomy/schema pins --
reproduce identically on purplelongship x86_64, so
pre-existing in 080cf8e, not ARM; plus a git
rebase/revert cluster erroring "git could not test
the rebase" on the Pi, git 2.39.5 vs 2.53.0).
Cell verdict: NOT PROVEN (run not green, per the
slice's own honesty rules). The counted run is
recorded in samverk/battery_port_arm.py COUNTED_RUN
and docs/BATTERY_PORT_ARM.md. Tree identity: .py
hash-of-hashes identical both machines
(1d4b15bd1069e0c61e6fa7c07eedaafc07378f9459c053d29f4efa0c343b2a99).
Own battery + neighbours re-verified by the
replacement worker on purplelongship: Ran 8 OK;
Ran 37 OK (skipped=1).
