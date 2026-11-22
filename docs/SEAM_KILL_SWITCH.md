# Kill switch (S-372)

The seam disables cleanly from either side's admin
(`SeamKillSwitchService.disable`, side `samtal` or `samverk`) —
the S-361 contract's sovereignty section made real. One call
flips the one switch every seam service already judges by
(`seam.samtal.enabled`, via S-361's `seam_enabled`): from that
moment the panel, the unfurl, the mentions bridge, the village
backup bundle and every other seam door refuse with their
standing `seam_disabled` reason — cleanly, by their own guards.

Both applications continue whole: the switch touches nothing
else. Samverk's standalone doors (accounts, repositories,
notifications, Git) never read the seam setting; Samtal keeps
its halls and talk — only the crossing stops.

The disablement is audit-logged on both sides. Samverk side:
the standing audit chain gains `admin.settings.change`
(target `seam`) naming the side and actor, chain-verifiable.
Samtal side: the entry is kept in the seam ledger
(`seam.kill_switch.samtal_log`) — the record Samtal's own log
carries; no Samtal codebase stands on this seat, so the ledger
is the honest shared record of that side's logging (the S-361
honesty pattern). Re-enabling is the same door in reverse,
likewise admin-only and logged on both sides.

Guards: site admin required (`permission_denied`); the side
must be one of the two (`side_invalid`); disabling an off seam
refuses (`already_disabled`) and enabling an on seam refuses
(`already_enabled`), so the log never records a change that
did not happen. No migration and no new taxonomy event.
