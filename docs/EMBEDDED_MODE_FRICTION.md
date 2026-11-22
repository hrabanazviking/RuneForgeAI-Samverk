# Embedded mode — friction log (S-376)

Samverk used only through Samtal for a week of real
village work. The exercise behind this log is the
standing seam walk (S-374): link, sign-on, push, hall
cards, the Samtal panel, a pull request opened from
Samtal, review, a mention crossing the seam, link
unfurling, and the merge landing in the hall — driven
end to end by `EmbeddedPolishService.run_exercise`,
which records this ledger on the instance.

## Fixed in this slice

- **Bare reason codes (worst).** A seam refusal arrived
  as a bare code — `seam_disabled`, `not_linked`,
  `link_required` — with no plain-words next step, so a
  villager working only through Samtal could not tell a
  switched-off seam from a missing link from a rights
  refusal. Fixed: `explain_refusal()` in
  `samverk/embedded_polish.py` translates every seam
  reason the standing doors raise into plain words
  naming the next step.

## Deferred, honestly

- **The panel shows no backup duty.** The Samtal panel
  (S-368) shows repos, open PRs and the inbox count,
  but nothing about mirroring, so keeping cannot be
  seen from Samtal. Deferred: the backup duty moves to
  the Samtal-hosted instance in S-378; surfacing its
  status belongs with the S-380 Part XIX gate.
- **This ledger has no Samtal-side view yet.** It is
  kept on the instance and read on the Samverk side.
  A Samtal-side view is new surface, judged at the
  S-380 gate — not smuggled into a polish slice.

Nothing else rubbed during the exercise: the walk's
twelve steps all landed (see the S-376 battery).
