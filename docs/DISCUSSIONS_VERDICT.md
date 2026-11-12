# Discussions — build (S-282)

Samverk will grow discussions, and this page is
the recorded verdict that says why, what is in
and what is out, and what the build must not
break. It concludes the study in research file 30
(`research/30-discussions.md`), which designs
forum-like discussion categories, accepted
answers and moderation for a village-scale forge.

## The verdict

**Build** the core. Categories and threads
(S-283), answer marking (S-284) and issue ↔
discussion conversion (S-285) are verdicted in.
Two pieces are **deferred**: polls — S-286
therefore takes its verdicted-out road, the
published refusal with the reasons recorded —
and rich badges, which no slice builds.

## Why build — the reasons

- `discussions-are-not-issues` — Discussions are
  not issues, and conflating them harms both.
  Research file 30 opens on the distinction:
  discussions are for open-ended knowledge
  exchange, whereas issues capture actionable
  work, and conflating both harms search and
  task closure.
- `the-machinery-already-stands` — The machinery
  a discussion surface needs already stands:
  S-123's comment timeline (reused whole by
  S-280's gist comments), the notification
  machinery of S-219 and the thread
  subscriptions beside it, S-190's permission
  engine on the owning repository, and Part X's
  permission-filtered search. The build is a
  composition of proven parts.
- `village-need-is-knowledge-exchange` — The
  village need is the knowledge exchange itself:
  the question with an answer a neighbour can
  find later, the announcement that is not a
  task, the open discussion that never has to
  pretend it can be closed. The work half of the
  forge stands banked; this is the knowledge
  half's home.
- `risks-are-named-and-bounded` — The risks are
  named in the study, and each has a stated law:
  multiple accepted answers, an author deleting
  the accepted post, the same question converted
  twice, a private discussion exposed by public
  search. Each maps to an invariant below and to
  research 30's own acceptance checks.
- `scope-can-be-cut-honestly` — The scope cuts
  honestly: the core in, polls and badges
  deferred. Research 30's own instruction is to
  defer polls or rich badges if they do not meet
  a village-scale real need, and no village need
  for either has been measured; polls also carry
  the fraud-honesty burden the study names.

## The pieces, judged one by one

- **Categories and threads**
  (`categories-and-threads`) — build. S-283
  builds the per-repository board: categories of
  question, announcement and open-discussion
  kinds with explicit allowed states and
  permissions, threads, and pinned posts.
- **Answer marking** (`answer-marking`) — build.
  S-284: the asker or a maintainer marks one
  reply as the answer; the mark is a reversible,
  attributable event, and conversion keeps the
  thread linked.
- **Issue ↔ discussion conversion**
  (`issue-discussion-conversion`) — build.
  S-285 converts both ways with a forwarding
  note both ways, the origin preserved, never
  silently, and exactly once.
- **Polls** (`polls`) — deferred. No village
  need has been measured, and honest poll rules
  must not pretend to establish voter identity
  beyond account scope. S-286 records the
  refusal on this verdict.
- **Rich badges** (`rich-badges`) — deferred.
  Research 30 names rich badges in the same
  deferral sentence as polls; a village trusts
  an answer because its author is known, and
  the answer mark is the one signal the board
  carries.

## What the build must not break

These invariants are recorded here and in the
module (`samverk/discussions_verdict.py`), as
the law S-283..S-285 build under and the seam
S-286 documents:

- `permissions-follow-the-repository` — a
  discussion belongs to its repository; create,
  reply, mark-answer and moderate are judged by
  S-190 exactly as the repository's acts are,
  and research 30's role matrix is proven per
  rung.
- `private-is-missing-everywhere` — a private
  discussion answers exactly as a missing one,
  in reads, lists, counts and above all in
  search; search joins discussions only through
  Part X's permission-filtered index (S-287).
- `answer-mark-is-an-event` — the mark is
  reversible and attributable, exactly one
  accepted answer per question at a time, never
  an edit to or replacement of the original
  reply; a deleted accepted reply leaves its
  tombstone and the mark's event on the
  timeline.
- `conversion-is-exactly-once-and-never-silent`
  — conversion preserves the origin, leaves a
  forwarding note both ways, and a second
  conversion — concurrently included — yields
  exactly one linked result and a refusal
  naming the first.
- `one-timeline-holds-the-conversation` — one
  timeline holds replies, revisions, answer
  marks, pins, conversions and moderation
  actions, each attributable and in order;
  moderation is shown on the thread itself, in
  words.
- `categories-carry-explicit-states-and-powers`
  — every category kind declares its allowed
  states and powers before any thread opens;
  announcement moderation and pinned items are
  owner-controlled.
- `subscriptions-share-notifications-with-own-controls`
  — topic subscriptions ride S-219's machinery
  (one inbox, one set of reasons) with their
  own digest and mute controls.
- `composer-and-search-stay-accessible` — the
  composer is mobile and keyboard first, search
  carries filters, and states are said in words,
  never by colour alone.

## How the build proceeds

- S-283 builds categories and threads first,
  reusing S-123's timeline machinery whole (the
  S-280 precedent), with research 30's
  role-matrix acceptance at its battery's core.
- S-284 and S-285 land as their own slices,
  carrying the study's acceptance checks: a
  stable audit trail for the mark, and double
  conversion yielding exactly one linked result.
- Polls stay deferred: S-286 is the published
  refusal built on this verdict, reconsidered
  only on measured village need with a
  fraud-honest design stated.
- The successor roadmap revisits the deferred
  pieces: S-403 names refused and deferred items
  among what its seed reconsiders.

## What does not exist — yet

No discussion endpoint, no discussion table, no
thread. The module
`samverk/discussions_verdict.py` inspects the
live instance and reports that absence — no
table, column or audit event carries a
discussion before its building slice — and its
battery plants a discussion-shaped table to
prove the inspection would catch one. A request
to use discussions today is answered
`discussions_build_queued` for a core piece
(build, queued for S-283..S-285) and
`discussions_deferred` for polls and rich
badges.

## Build progress

- S-283 (2026-11-11) landed the first piece:
  categories and threads, in
  samverk/discussions.py over migration 112
  (schema 111 -> 112), under the invariants
  above. The verdict audit now treats those six
  tables as the sanctioned build and still
  refuses any discussion-shaped name beyond
  them. Answer marking (S-284) and conversion
  (S-285) remain queued on this verdict; polls
  and rich badges remain deferred.

- S-285 (2026-11-11) landed the third piece:
  issue <-> discussion conversion, in
  samverk/discussion_conversion.py over
  migration 114 (schema 113 -> 114), under the
  invariants above -- both ways with a
  forwarding note both ways, the origin
  preserved (a converted question keeps its
  thread, mark and timeline as the linked
  origin), exactly once even under concurrency
  (UNIQUE backstops in the link table). The
  verdict audit now treats
  discussion_conversions as part of the
  sanctioned build and still refuses any
  discussion-shaped name beyond it. Polls and
  rich badges remain deferred.
