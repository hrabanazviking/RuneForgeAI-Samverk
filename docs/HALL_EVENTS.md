# Repo events into halls (S-367)

Pushes, pull requests, issues, and releases post into a chosen
Samtal hall as concise cards with links (`HallEventService.post_event`
/ `render_card`), under the frozen S-361 event-bridge contract.

**Per-hall opt-in and mute.** A hall hears nothing about a repo until
it opts in (`opt_in`, optionally naming the event kinds it wants);
`opt_out` ends it. `mute` silences a repo in a hall — all kinds, or
one named kind — and wins over opt-in until `unmute`.

**Exactly-once at the seam.** Every envelope carries an idempotency
key (S-226's rule, judged by S-361's `validate_event_envelope`);
re-posting a key that already landed returns the standing card
instead of a second card. Envelopes are privacy-filtered by the
contract itself: a private repo's event aimed at an open hall is
refused (`privacy_leak`); it may post only into a restricted hall.

Guards: seam disabled refuses (`seam_disabled`); unknown kinds and
missing keys carry the contract's own reasons. No migration and no
new taxonomy event — subscriptions, mutes, cards, and the delivery
ledger ride the settings table.
