# Seam permissions audit (S-373)

The full seam matrix, re-run with linked identities and
counted: Samtal role (owner / member / none — S-365's hall
roles plus the linked villager in no hall) x Samverk role
(read / triage / write / maintain / admin / none — S-189's
ladder plus no role) x surface (panel S-368, unfurl S-370,
mentions bridge S-369, hall events S-367, village
repositories S-365) = **90 cells: 68 allowed, 22 denied**
(`run_audit` in `samverk/seam_permissions_audit.py`).

Per surface (18 cells each): panel 15 allowed, unfurl 15,
mentions 18, hall events 10, village repositories 10. The
panel and the unfurl judge by the viewer's Samverk rights
alone (read is the floor). Hall events and village
repositories additionally require hall membership — a
linked villager outside the hall is denied
(`not_hall_member`) whatever their Samverk role. The
mentions bridge is the one door needing no repo role: it
delivers S-223's own notification to the linked principal
(S-369), so the link is its whole requirement.

Two collapses are counted, not assumed: with the seam
disabled every cell denies (`seam_disabled`), and for an
unlinked identity every cell denies (`not_linked`). No
cell is allowed on a Samtal role alone — the seam grants
nothing Samverk's own ladder does not already hold. The
audit stores nothing and adds no taxonomy event.
