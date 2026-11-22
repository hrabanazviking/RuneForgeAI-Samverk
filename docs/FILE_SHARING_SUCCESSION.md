# File-sharing succession (S-366)

Samtal file uploads gain a "keep in Samverk" path: a file shared in a
hall message becomes a Samverk gist (S-277) — a mini-repository with
full revision history — owned by the uploader, created through the
standing GistStore door, and the Samtal message links to it
(`link_for` / `render_message_link`).

**Old files stay readable.** Keeping is a copy, never a move: the
shared file record is read-only to this service and is never deleted
or mutated, so un-kept uploads keep working exactly as before — no
migration by breakage. Keeping the same message twice returns the
standing link instead of minting a duplicate gist.

Guards: seam disabled refuses (`seam_disabled`); only the uploader
or a site admin may keep a file (`not_file_owner`); the gist file
law judges the name and body, and its refusals surface unchanged.
No migration and no new taxonomy event — the message-to-gist link
rides the settings table.
