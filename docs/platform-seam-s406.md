# Platform seam audit -- S-406

The seam audit, judged at 402/416 against the tree as it
stands (S-402, the founder walk, still open in roadmap
order; S-403..S-405 held by their teams). The full
inventory ships at `docs/PLATFORM_SEAM.md`; this is its
counted log.

Files scanned outside the seam: 367

- process: 49 (all in the 4 named inventory files)
- permissions: 0
- platform_id: 0
- signals: 0
- locking: 0
- uninventoried strays: 0

Routed at this slice: 6 modules' platform identity calls
and 8 chmod sites in 6 modules now go through the seam;
the seam gained `platform_string()`, `restrict_to_owner()`,
and `make_owner_executable()`.

Verdict: **AUDIT CLEAN of uninventoried strays -- 49
process touchpoints inventoried as named remainders in
proc.py (the S-014 home), reference_runner.py,
seam_battery.py, and upgrade_drill.py**

NOT PROVEN:

- lock_file(): no file locking exists in the tree; the
  seam's named FUTURE primitive is unlanded.
- Service management routing: no service-manager code
  exists in samverk/ to route; the Windows/macOS/Linux
  service cells are S-410/S-411/S-412, all NOT PROVEN.
- Windows/macOS behaviour of the new seam helpers:
  coded as no-ops on Windows per the seam's existing
  convention, exercised only on Linux in this battery.
