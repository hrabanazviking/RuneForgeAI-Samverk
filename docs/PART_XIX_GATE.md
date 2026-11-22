# Part XIX Gate Record — S-380

Gate slice: **S-380 — Part XIX gate — seam counted battery +
boundary doc + kill-switch drill recorded.**

Battery: `tests/test_part_xix_gate.py`, counted with
`python3 -m unittest tests.test_part_xix_gate`.
Gate battery: **7 tests, OK** on purplelongship, 2026-11-22.
**PART XIX GATE PASSED.**

## The seam counted battery

Three counted batteries, re-run assembled at the gate:

- **S-374 end-to-end walk** (SeamWalk): 12 steps, all green —
  link identity, SSO entry, push, hall sees push, panel,
  PR from Samtal, hall sees PR, review, mention crosses,
  unfurl, merge, hall sees merge.
- **S-373 permissions matrix**: 90 cells (3 Samtal roles ×
  6 Samverk roles × 5 surfaces) — 68 allowed / 22 denied.
  Both collapses re-counted at the gate: seam disabled
  denies all 90; unlinked identity denies all 90.
- **S-379 security review**: 34 attacks, all held —
  token_exchange 15/15, link_unfurling 10/10,
  event_posting 9/9. Its register stands: one finding
  FIXED (F-1, attribute breakout in both card renderers,
  closed with escape_html_attr) and one NAMED (N-1, file
  unfurl does not verify the file stands; the card is a
  link and grants no access).

## The boundary doc

S-375's boundary verified standing at the gate:
`check_boundary` green on the live code; the boundary
carries exactly **3 statements**, counted — `no_federation`,
`no_cross_village_identity`, `no_samtal_requirement` — and
`docs/SEAM_BOUNDARY.md` stands where operators will read
it, saying what the seam is NOT.

## The kill-switch drill, recorded

Executed in the gate battery (KillSwitchDrillTests),
2026-11-22, against the real S-372 switch:

1. **Disable from the Samtal side** — record enabled=false,
   side=samtal. Unfurl refused `seam_disabled`; SSO exchange
   refused `seam_disabled`. Standalone Samverk stood whole:
   a fresh account registered and created a private repo
   with the seam off.
2. **Re-enable from the Samverk side** — enabled=true,
   side=samverk; unfurl answered again.
3. **Disable from the Samverk side** — enabled=false,
   side=samverk; unfurl refused `seam_disabled` again.
4. **Re-enable from the Samtal side** — enabled=true,
   side=samtal; the drill ends with the seam on.

The record verifies three ways: the standing flip is the
last Samtal-side enable; the Samtal-side seam ledger holds
all 4 flips in order (sides samtal/samverk/samverk/samtal,
enabled false/true/false/true); Samverk's audit chain
holds exactly 4 `admin.settings.change` entries targeting
the seam.

## The pins

Schema **140**; taxonomy **142** audit events
(34 auth / 92 repo / 16 admin). The gate claims no
migration and no taxonomy event of its own.

## The honest remainder

No Samtal codebase stands on this seat (S-361's standing
honesty, carried since the seam was ratified). This gate
judges Samverk's side of the seam and the shared seam
ledger — the Samtal-side log the kill switch keeps — and
does not claim a Samtal-side run. Part XIX closes on
Samverk's side; the Samtal-side gate belongs to Samtal's
own house when it stands.
