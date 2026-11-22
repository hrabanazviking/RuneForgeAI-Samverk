# What the seam is NOT — the honest boundary (S-375)

For operators. Part XIX joins Samtal and Samverk; this
page states, plainly, the lines that join never crosses.
If a future change crosses one, it is a contract change
and must be named as such (S-361).

## No federation

Villages do not federate. Samverk never takes another
village's word for who someone is, which hall they
belong to, or what they may do. Every seam door — the
panel, the unfurl, the mentions bridge, hall events —
decides locally, on Samverk's own stores and roles.
There is no federation protocol, no village-to-village
trust, and none is planned.

## No cross-village identity

The identity link (S-362) is one Samverk account
holding one external identifier, created by that
account's own signed act and removable the same way.
The external id is an identifier, never a credential:
it cannot sign anyone in. There is no global villager,
no identity that travels between villages, and an
unlinked account is a whole account, not a lesser one.

## No Samtal requirement for Samverk

Samverk runs whole on its own: accounts, login,
repositories, reviews, merges, and whole-instance
export never touch the seam. The seam is disabled by
default and stays disabled until an operator turns it
on; the kill switch (S-366) closes it again without
disturbing anything standalone. A village with no
Samtal at all loses nothing of Samverk.

## Holding the line

`samverk/seam_boundary.py` declares these statements
in code and `check_boundary()` re-verifies the
load-bearing claims against the standing code; the
S-375 battery (`tests/test_seam_boundary.py`) runs
that check and confirms this document carries every
statement.
