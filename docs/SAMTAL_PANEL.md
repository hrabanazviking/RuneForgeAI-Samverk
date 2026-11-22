# Samverk surface in Samtal (S-368)

A Samverk panel inside Samtal's UI — the viewer's repos, their open
pull requests, and their inbox count — served by Samverk's API
(`SamtalPanelService.payload_for`), under the frozen S-361 embed
contract: **Samtal renders, Samverk decides.**

The payload is computed entirely on the Samverk side from the
standing stores — `RepositoryStore` for the viewer's repos,
`PullRequestStore` (over the real Git refs) for open pull requests,
`NotificationStore` for the unread inbox count — judged for the
viewer themself, and stamped `decided_by: samverk`. Samtal's
reference renderer (`render_panel`) draws exactly that payload and
nothing else; a deployment's Samtal UI may restyle it but may not
widen it.

The panel is a read, never a grant: holding the payload confers no
access, and every link in it lands on Samverk's own
permission-checked pages. Guards: seam disabled refuses
(`seam_disabled`); a panel needs its signed-in viewer
(`actor_required`). No migration and no new taxonomy event — the
panel stores nothing.
