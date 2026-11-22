# Never colour-only (S-387)

Every status — checks, alerts, protection, visibility — carries
icon + text, always. `samverk/never_colour_only.py` enforces the
law two ways over S-383's carrier registry: `audit_statuses`
names any status carrier missing its icon or its text, and
`grep_ui` greps the shipped UI sources — a file that uses a status
colour must also contain that status's text and icon, so a new
renderer cannot borrow the colour and drop the meaning.

In-slice fix (bug law): the stricter audit caught S-383's
`branch_unprotected` carrier standing icon-less; it now carries
the `shield_off` icon in `samverk/grayscale_coherence.py`, and
S-383's own battery still passes.
