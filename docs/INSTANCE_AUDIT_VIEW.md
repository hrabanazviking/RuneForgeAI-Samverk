# Instance Audit View (S-356)

The instance audit view is the operator's face on Samverk's witness:
every audit event recorded anywhere in the instance, on one page, for
site administrators only, with the hash chain verified fresh on every
read and the verdict shown in words.

It is S-309's audit log UI at instance scope (roadmap S-356:
"S-309 at instance scope, chain-verified"), built in
`samverk/instance_audit_view.py` over S-309's `AuditLogUIStore` and
S-007's `verify_chain`. It stores nothing and records nothing: reading
the witness is not an act the witness records. Schema stays **140** (moved by S-355 after this face was built);
the taxonomy stays **142** events (34 auth / 92 repo / 16 admin).

## The door

Site admins only. A non-admin, and an anonymous reader, hear the
uniform `audit_not_found` — the same word S-309's instance view uses.
The whole instance's history is its most sensitive read, so the view
never confirms anything to anyone else.

## What the page shows

- **Every event across the instance** — all actors, all objects (repos,
  organizations, users, the instance itself), in chain order.
- **Filters** (S-309's law, judged purely): by actor (account), by
  event kind (the recorded action — it must name a standing taxonomy
  event; an unknown name is refused `filter_invalid`, never a silently
  empty page), by object (target kind, plus the plain-text query that
  matches across action, target, actor name and detail), by outcome,
  and by time window.
- **Windowing.** A long chain is read in windows: `offset` + `limit`
  (1–1000, default 50) over the *filtered* rows. The page states the
  filtered total, which entries the window holds, and whether entries
  stand before or after it. An offset past the end is an empty window,
  stated as such. A malformed window is refused `window_invalid`.
- **Breakdowns.** Counts over the filtered rows — by actor, by action,
  by target kind, by outcome — so the shape of a find is visible
  without reading every row. They describe the find, not the window.
- **Export.** The whole filtered view as JSON or CSV, through the same
  admin door and the same filters (S-309's export). There is no second,
  wider road out.

## Chain verification — honest, always

Every read recomputes S-007's `verify_chain` over the **whole** chain
from genesis, whatever the filter or window. The page, and the data
behind it, carry the verdict in words:

- **Verified:** "Chain verified: N entries checked, no break found."
- **Broken:** "Chain broken at entry K: N entries checked before the
  break. The audit record cannot be trusted past that entry until it
  is investigated."

A filter can hide a break from the list; it can never hide it from the
verdict. A tampered or deleted row reads broken at the first touched
entry — never a false green. The battery proves this by tampering a
real row and reading the break at exactly that sequence number.

## The honesty re-proof

`audit_instance_audit_view(conn)` re-proves what the face claims:
S-309's row proofs (every action in the taxonomy, sequence numbers
unbroken from 1, both hashes on every row, every named actor standing),
the schema pin (140), the taxonomy pin (142 = 34/92/16), and no
instance-audit table of its own — this face stores nothing.
