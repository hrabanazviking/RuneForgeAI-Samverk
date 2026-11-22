# Mentions bridge (S-369)

@mentions in Samverk notify the linked Samtal principal there too
(`MentionsBridgeService.bridge_mention`) — **one notification, two
doors**: S-226's exactly-once rule spans the seam.

The bridge creates the single S-223 notification (reason `mention`)
through the standing `NotificationStore` door and records the
Samtal door beside it in a settings-table ledger keyed by source +
recipient — the same source identity S-226's delivery ledger
enforces. Re-bridging a source that already crossed returns the
standing delivery and creates nothing: no duplicate Samverk
notification, no duplicate Samtal door. A different source is a
different mention and delivers its own notification.

The Samtal door exists only where S-362's identity link stands
(S-045's `IdentityLinkStore`, provider `samtal`); the delivery
names the linked principal. An unlinked recipient is notified
through the Samverk door alone, and the delivery says so. Nobody
is bridged a mention of their own act (`self_mention`, S-226's
author-removal law).

Guards: seam disabled refuses (`seam_disabled`); a source key and
a real recipient are required (`source_required` / `no_such_user`).
No migration and no new taxonomy event.
