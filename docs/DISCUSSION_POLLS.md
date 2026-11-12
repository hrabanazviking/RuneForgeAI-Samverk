# Discussion polls — the published refusal (S-286)

Samverk has **no discussion polls**. The roadmap
asked for polls — discussion polls with honest
counts and close dates — if S-282 verdicted them
in. S-282 verdicted polls DEFERRED
(`docs/DISCUSSIONS_VERDICT.md`,
`samverk/discussions_verdict.py`): no village
need for thread polls has been measured, and
polls carry research 30's honesty warning —
fraud-resistant rules that do not pretend to
establish voter identity beyond account scope.
So this slice, S-286, is the published refusal
the roadmap names for the verdicted-out road,
with the seam documented. The face's standing
shape lives in `samverk/discussion_polls.py`;
this page is the same refusal for a reader who
never opens the code.

## A poll belongs to its thread

A poll is named whole: the owner and name of
the repository its discussion thread stands in,
the thread's per-repository number, a question,
its options in order, and a close date — for
example the question "Tea or mead?" with the
options Tea and Mead, closing in a week, on
thread `volmarr/anvil#7`. The poll belongs to
that thread and its repository. There is no
poll-only ownership and no poll apart from the
thread it would stand in.

## The four doors, and the rung each is judged at

- `create` — requires **read** on the owning
  repository. Would fix a question, its options
  and a close date onto one discussion thread,
  one poll standing in a thread at a time, its
  state said in words on the thread. Today it
  refuses.
- `vote` — requires **read** on the owning
  repository. Would record one honest count per
  account for one option, changeable until the
  close date and never after, claiming no
  identity beyond account scope. Today it
  refuses.
- `results` — requires **read** on the owning
  repository. Would state the count per option
  in words and numbers together, the close date
  and whether the poll stands open or closed,
  to any reader of the thread. Today it refuses.
- `close` — requires **maintain** on the owning
  repository, or the thread's own author (the
  curation hands S-284 trusts). Would end
  voting at the author's word or a maintainer's,
  before the close date if need be, leaving the
  final counts standing on the thread in words.
  Today it refuses.

## How a request is answered

In one order, always:

1. **Shape first, storing nothing.** A question
   that is not plain text of at most 200
   characters is `poll_question_invalid`, a set
   of options that is not 2 to 6 distinct texts
   is `poll_options_invalid`, a close date that
   is not a time still ahead is
   `poll_close_invalid`, a vote that names no
   option is `poll_choice_invalid`, and an act
   the face does not carry is
   `poll_action_invalid`. A shapeless thread
   reference answers at S-283's own door, as the
   board answers it.
2. **Then the thread, and S-190's permissions**
   on the owning repository, judged through
   S-283's `DiscussionStore` doors. A signed-in
   act (create, vote, close) by the anonymous
   is `authentication_required`. A missing
   thread — and a thread in a repository the
   caller may not read — answers as one
   `discussion_not_found`, so the refusal itself
   leaks nothing about what the caller may not
   read. A close by hands that are neither the
   thread's author nor a holder of the maintain
   rung is `permission_denied`.
3. **Only then the verdict.** A caller who
   passes the permission door meets S-282's
   answer for the polls feature, delegated to
   the verdict's own decision so the two slices
   can never drift: `discussions_deferred`.

## The seam a future poll builds under

The seam is S-282's eight must-not-break
invariants, imported whole by this face —
stated once in `samverk/discussions_verdict.py`,
never forked:

- `permissions-follow-the-repository` —
  discussion permissions are the repository's,
  judged by S-190; a poll inherits its thread's
  repository and has no powers of its own.
- `private-is-missing-everywhere` — private is
  indistinguishable from missing, in direct
  reads, lists, counts and search — and, by
  this slice, in the refusal itself.
- `answer-mark-is-an-event` — the answer mark
  stays an event, never an edit; a poll is no
  substitute for it and no second signal beside
  it.
- `conversion-is-exactly-once-and-never-silent`
  — conversion keeps its law; a converted
  thread carries no poll with it, because no
  poll stands to carry.
- `one-timeline-holds-the-conversation` — one
  timeline holds replies, revisions and
  moderation; a future poll's opening, closing
  and counts would stand there too, in words.
- `categories-carry-explicit-states-and-powers`
  — every kind declares its states and powers
  before any thread opens; a poll adds no
  undeclared power to any kind.
- `subscriptions-share-notifications-with-own-controls`
  — subscriptions ride the standing
  notification machinery with their own
  controls; a poll creates no parallel
  notifier.
- `composer-and-search-stay-accessible` — the
  composer and the search stay accessible, and
  a poll's state — open, closed, its counts —
  would be said in words, never by colour
  alone.

## What exists instead, and when this reopens

A village decision today is made in the open
discussion itself, in words, by named people —
the thread is the poll's honest substitute at
village scale, and the answer mark (S-284) is
the one signal the board carries. The verdict
reopens only on S-282's recorded conditions for
polls: a village need is measured, and a
fraud-honest design — one honest count per
account, a close date stated in words, no
identity claimed beyond account scope — is
stated with it; the successor roadmap revisits
the deferred pieces at S-403.

## What does not exist

No poll table, no vote, no count, no close
date. The face inspects the live instance and
reports that absence — S-282 still defers the
polls feature and its verdict audit still
refuses any discussion-shaped name beyond its
sanctioned build, and no table, column or audit
event carries a poll — and its battery plants a
poll-shaped table to prove the inspection would
catch one. This refusal writes and audits
nothing, because no act here can succeed: there
is nothing to witness yet, and the battery
proves the silence by row and audit counts.
No migration (schema stays 114), no taxonomy
event (133 stand: 33 auth / 87 repo / 13 admin).
