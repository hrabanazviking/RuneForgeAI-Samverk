# Code in conversation (S-370)

Pasting a Samverk link in Samtal unfurls to a card — repo, file,
pull request, or issue — via `LinkUnfurlService.unfurl`, rendered
from Samverk's API under the frozen S-361 embed contract (section
2): **Samtal renders, Samverk decides**.

The decision is judged at request time against the *viewer's* own
Samverk rights through S-190's `PermissionEngine` (read role).
The card names only what the viewer may read; a viewer without
read rights gets `permission_denied` and the refusal leaks
nothing — no title, no description, no target details. An unfurl
is a read, never a grant: the card confers no access and its link
still lands on Samverk's own permission-checked pages.

Link shapes are the frozen embed kinds (`repo`, `file`,
`pull_request`, `issue`); anything else is `link_unknown`.
Missing repos or targets are `not_found`. Guards: seam disabled
refuses (`seam_disabled`). No migration and no new taxonomy
event: the unfurl stores nothing. Samtal's side is the reference
renderer (`render_card`), which draws exactly the decided card.
