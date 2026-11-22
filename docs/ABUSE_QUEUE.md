# Abuse queue (S-355)

One admin queue for user reports on content and accounts.

## What a user does

A signed-in, active user reports a **repository**, an
**issue**, an **issue comment**, or an **account** through
`AbuseQueue.file_report`, giving a reason in plain words.
The target must exist; a user cannot report their own
account. While an earlier report by the same user on the
same target is still live (open or acknowledged), a second
one is refused as a duplicate -- a different reporter, or a
fresh report after the earlier one closed, is fine.

## What lands in the queue

Every report is one row in `abuse_reports` (migration 140,
schema 140) in state `open`. At filing time the report
captures its **audit context**: the sequence numbers of the
audit-log entries that concern its target, gathered from
the standing AuditLog by target kind and id. The report
carries references into the hash chain, never copies of it;
the queue view resolves them live and shows whether the
chain still verifies whole (S-007).

## Working the queue

Only instance admins can read the queue (`AbuseQueue.queue`)
or work it:

- `acknowledge` -- open -> acknowledged.
- `resolve` -- open/acknowledged -> resolved; a reason in
  plain words is required and kept on the report.
- `dismiss` -- open/acknowledged -> dismissed; a reason is
  required and kept.

Resolved and dismissed are terminal. Every filing and every
queue action is audit-logged under S-355's events:
`auth.abuse_report.filed`, `admin.abuse_report.acknowledged`,
`admin.abuse_report.resolved`, `admin.abuse_report.dismissed`
(taxonomy 138 -> 142).

## What the reporter sees

A reporter can list their own reports (`my_reports`) and
read each one's state in plain words (`state_in_words`):
waiting, being looked into, acted on, or closed with no
action needed. Nobody can read another user's reports, and
non-admins cannot see the queue at all. `render_queue`
draws the admin page; `render_my_reports` draws the
reporter's page; all user text is HTML-escaped.
