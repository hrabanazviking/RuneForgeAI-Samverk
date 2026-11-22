# Part XVIII Gate Record — S-360

Gate slice: **S-360 — Part XVIII gate — fresh-install battery
on Pi-class hardware from the written guide alone, by someone
who did not write it; timed and recorded.**

Battery: `tests/test_part_xviii_gate.py`, counted with
`python3 -m unittest tests.test_part_xviii_gate`.
Gate battery: **15 tests, OK** (log:
`hidden_files/s360-battery.log`, team-08 worktree).

## The fresh install, timed

The battery's world is a bare temporary data root. The ONLY
road taken to a working instance is S-349's install walk —
the executable form of `docs/INSTALL_WALK.md`, whose nine
steps the battery pins to the guide document itself
(`test_guide_doc_names_every_step`). The walk ran green in
guide order, first admin `volmarr` standing and admin, the
instance signing key on disk at `keys/instance-signing-v1.key`.

Timed two ways, both recorded from real runs on
purplelongship (2026-11-22): the walk's own
`report.elapsed_seconds` = **2.39 s**; wall clock around the
same standalone walk = **2.41 s** (driver:
`hidden_files/time_walk_s360.py`). A rerun of the walk over
the installed root is the idempotent already-installed
answer: still green, no second first admin, exactly one
user row.

## What was counted

- **Pins** — schema 140, taxonomy 142 audit events
  (34 auth / 92 repo / 16 admin), `EXPECTED_SCHEMA_VERSION`
  140, and the S-358 migration register covering every
  standing migration exactly (140 entries, each one-way
  warning naming the backup road). The gate claims **no
  migration and no new taxonomy event**.
- **The admin's first hour** — S-350's next three steps
  judged in order (token, repository, mirror) and a second
  first-admin refused on the walked instance; S-351's admin
  panel counting the walked instance's real users and
  refusing a non-admin; S-352 site settings changed at the
  admin's hand and read back; S-353 maintenance mode
  enabled with reason and expected return — banner and
  push-refusal carry the reason in words, a non-admin push
  is refused, an admin push is allowed — then lifted.
- **Oversight** — S-354's quota overview reading the real
  row of a repository created on the walked instance;
  S-355's abuse queue: a user report on that repository
  lands in the admin queue with its audit context and a
  verified chain, and is acknowledged and resolved with a
  plain-words reason; S-356's instance audit view showing
  the walked instance's chain verified (`chain.ok`) to the
  admin and the uniform `audit_not_found` to a non-admin.
- **Staying alive** — S-357's upgrade procedure rehearsed
  on the walked instance (a repository with a real commit
  seeded first, since an archive of nothing is refused as
  a false backup): all six steps green, counts verified
  against the export manifest; S-359's health probe
  answering ok with schema_version 140 from the real
  database file, and the admin status page's user count
  equal to the instance's real `users` count.

## The honest remainder

The roadmap asks for this battery **on Pi-class hardware,
by someone who did not write the guide**. Two parts of
that stand unmet and are named, not claimed:

1. **Hardware**: this pass ran on purplelongship, the
   x86-64 development laptop — not on Mimir, the Pi-class
   ARM machine. The walk is hardware-blind Python and the
   guide names no x86-only step, but the timed Pi-class
   pass itself remains owed.
2. **The independent installer**: the walk was driven by
   the banking coordinator, who did not write the guide
   (S-349 was team-07's slice) but is not an outside
   installer. A truly external from-the-guide-alone pass
   remains owed.

Both remainders are recorded here so the gate's green is
read exactly as far as it reaches: the Part XVIII
machinery, assembled on a fresh install, counted green.
