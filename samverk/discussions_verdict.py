"""Discussions verdict -- build the core, defer
polls and badges, with reasons (S-282).

Research file 30's study concludes build/defer/
refuse for a village-scale forge. This slice is
that conclusion, as a complete slice: the verdict
is data, the reasons are stated, the five pieces
research 30 names are judged one by one, and the
invariants the build must not break are recorded
here and in docs/DISCUSSIONS_VERDICT.md -- the law
S-283..S-285 build under, and the seam S-286
documents for the piece that stays out.

- **The verdict is BUILD the core.** Research 30
  opens with the distinction the whole verdict
  hangs on: discussions are for open-ended
  knowledge exchange, whereas issues capture
  actionable work, and conflating both harms
  search and task closure. Its recommended
  approach is an implementation approach --
  categories with explicit allowed states and
  permissions, one conversation timeline, answer
  marking as a reversible attributable event,
  conversion that preserves the discussion's
  origin -- not a deferral brief. Not refuse:
  nothing in the study argues the village is
  better served by forcing its questions into
  its task list. Not build everything: the
  study's own cut defers polls and rich badges
  where they do not meet a village-scale real
  need, and no such need has been measured for
  either, so both defer (polls take S-286's
  verdicted-out road).
- **The build is queued, not present.** There is
  no discussion route, table or event yet: a
  request to use discussions today is answered
  by the pure ``decide_discussion_request`` -- a
  core piece is refused
  ``discussions_build_queued`` (verdict: build; its slice
  S-283..S-285 has not landed), a
  deferred piece ``discussions_deferred``, and a
  shapeless or unknown request is
  ``discussions_request_invalid`` /
  ``discussions_feature_unknown``. The audit
  below proves the queue against the live
  instance -- no table, column or audit event
  carries a discussion yet -- and the battery
  plants a discussion-shaped table to prove the
  audit would catch one arriving ahead of its
  slice or by a back door.
- **What the build must not break is stated now,
  while stating it is cheap.** ``MUST_NOT_BREAK``
  states eight invariants, each grounded in
  research 30 or a standing slice's law:
  permissions following the repository through
  S-190, private indistinguishable from missing
  in search and lists alike (research 30's own
  named exposure), the answer mark as an event
  (reversible, attributable, never an edit),
  conversion exactly once and never silent,
  one timeline holding replies, revisions and
  moderation together, categories carrying
  explicit states and powers with announcement
  moderation and pins owner-controlled,
  subscriptions sharing S-219's notification
  machinery with their own digest and mute
  controls, and an accessible composer and
  search (mobile and keyboard first).
- **A pure read, like S-202, S-253 and S-264.**
  This module holds no store, writes no row and
  audits nothing: a verdict about a surface that
  S-283 has not built yet changes nothing by
  being read. No migration (schema stays 111),
  no taxonomy event (133 stand: 33 auth / 87
  repo / 13 admin). The full reasoning also lives
  in docs/DISCUSSIONS_VERDICT.md, where a person
  who never opens this module can read it.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from . import taxonomy
from .escaping import escape_html_text

__all__ = [
    "BUILD_CONDITIONS", "FEATURES", "MUST_NOT_BREAK",
    "REASONS", "VERDICT", "DiscussionsVerdictAudit",
    "DiscussionsVerdictError", "FeatureAssessment",
    "VerdictInvariant", "VerdictReason",
    "audit_discussions_verdict",
    "attempt_discussion_action",
    "decide_discussion_request", "get_feature",
    "get_invariant", "get_reason",
    "render_discussions_verdict_page",
]

VERDICT = "build"


class DiscussionsVerdictError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class VerdictReason:
    """One reason the verdict is build: a stable
    id, the plain title a reader sees, and the
    reasoning in full."""
    id: str
    title: str
    detail: str


REASONS: tuple[VerdictReason, ...] = (
    VerdictReason(
        id="discussions-are-not-issues",
        title="Discussions are not issues, and conflating them harms both",
        detail=(
            "Research 30's opening finding is the "
            "distinction this verdict hangs on: "
            "discussions are for open-ended "
            "knowledge exchange, whereas issues "
            "capture actionable work, and "
            "conflating both harms search and task "
            "closure. A village that must file its "
            "questions as tasks teaches its people "
            "to stop asking, and teaches its issue "
            "list to lie about what is work. The "
            "two shapes stay two shapes.")),
    VerdictReason(
        id="the-machinery-already-stands",
        title="The machinery a discussion surface needs already stands",
        detail=(
            "Unlike the deferred surfaces of "
            "S-253 and S-264, discussions need no "
            "new protocol and no new trust "
            "machinery: the conversation timeline "
            "is S-123's comment machinery, already "
            "reused whole by the gist comments of "
            "S-280 rather than duplicated; topic "
            "subscriptions share the notification "
            "machinery of S-219 and the thread "
            "subscriptions that stand beside it; "
            "permissions are S-190's engine, judged "
            "on the owning repository; search is "
            "Part X's permission-filtered index. "
            "The build is a composition of proven "
            "parts, at village cost.")),
    VerdictReason(
        id="village-need-is-knowledge-exchange",
        title="The village need is the knowledge exchange itself",
        detail=(
            "A village-scale forge exists so a "
            "small community can keep its work and "
            "its knowledge in one sovereign place. "
            "The work half stands: issues, pulls, "
            "releases, wikis and gists are banked. "
            "The knowledge half -- the question "
            "with an answer a neighbour can find "
            "next winter, the announcement that is "
            "not a task, the open discussion that "
            "never has to pretend it can be closed "
            "-- has no home today except the issue "
            "list it would corrupt. Research 30 "
            "designs exactly that home: categories "
            "of question, announcement and open "
            "discussion, each with its own "
            "semantics.")),
    VerdictReason(
        id="risks-are-named-and-bounded",
        title="The risks are named in the study, and each has a stated law",
        detail=(
            "Research 30 names its own threat "
            "list, and it is short enough to bind "
            "whole: multiple accepted answers, an "
            "author deleting the accepted post, "
            "the same question converted twice, a "
            "private discussion exposed by public "
            "search. Each maps to one of the "
            "must-not-break invariants below -- "
            "one accepted answer held as an event, "
            "conversion exactly once, private "
            "indistinguishable from missing in "
            "search -- and to the study's own "
            "acceptance checks, which the "
            "following slices carry as batteries. "
            "Nothing here ships ahead of its "
            "defences.")),
    VerdictReason(
        id="scope-can-be-cut-honestly",
        title="The scope cuts honestly: the core in, polls and badges deferred",
        detail=(
            "Research 30's own instruction is to "
            "defer polls or rich badges if they do "
            "not meet a village-scale real need -- "
            "and no village need for either has "
            "been measured. Polls carry an honesty "
            "burden of their own: fraud-resistant "
            "rules that do not pretend to establish "
            "voter identity beyond account scope. "
            "So the verdict builds the core the "
            "study designs (categories and "
            "threads, answer marking, conversion) "
            "and defers the two ornaments, polls "
            "taking S-286's verdicted-out road "
            "with the reasons recorded.")),
)


@dataclass(frozen=True)
class FeatureAssessment:
    """One piece research 30 names, judged on its
    own: what building it would mean, what the
    village need for it is today, what standing
    machinery it reuses (or what serves the need
    instead), and the judgement for that piece."""
    id: str
    title: str
    building_means: str
    village_need: str
    served_by: str
    judgement: str


FEATURES: tuple[FeatureAssessment, ...] = (
    FeatureAssessment(
        id="categories-and-threads",
        title="Discussion categories and threads (S-283)",
        building_means=(
            "A per-repository discussion board: "
            "categories of question, announcement "
            "and open-discussion kinds, each with "
            "explicit allowed states and "
            "permissions; threads opened in a "
            "category, pinned posts, and one "
            "conversation timeline per thread."),
        village_need=(
            "The core need, and research 30's "
            "centre: the village's questions and "
            "announcements have no home that is "
            "not a task list. Category kinds carry "
            "different semantics, moderation and "
            "notification policies, so the board "
            "is designed per kind, not as one "
            "undifferentiated stream."),
        served_by=(
            "Built on standing machinery: S-123's "
            "comment timeline (reused whole, as "
            "S-280 reused it for gists), S-190's "
            "permission engine on the owning "
            "repository, and Part X's search. "
            "Nothing serves this need today."),
        judgement="build"),
    FeatureAssessment(
        id="answer-marking",
        title="Answer marking (S-284)",
        building_means=(
            "The asker or a maintainer marks one "
            "reply in a question thread as the "
            "answer; the mark is a reversible, "
            "attributable event on the thread's "
            "timeline, never an edit to, or a "
            "replacement of, the marked reply."),
        village_need=(
            "What makes a question category worth "
            "having: the next neighbour with the "
            "same question finds the answer "
            "without re-asking it. Research 30 "
            "acceptance-checks the role matrix -- "
            "create, reply, mark-answer, moderate "
            "-- with a stable audit trail."),
        served_by=(
            "The thread timeline of S-283 and the "
            "event honesty of the issue timeline: "
            "a mark, an unmark and a re-mark are "
            "events with actors, witnessed like "
            "any other act on the thread."),
        judgement="build"),
    FeatureAssessment(
        id="issue-discussion-conversion",
        title="Issue and discussion conversion (S-285)",
        building_means=(
            "A discussion that turns out to be "
            "work becomes an issue, and an issue "
            "that turns out to be a question "
            "becomes a discussion, each with a "
            "forwarding note both ways and the "
            "origin preserved -- never silently, "
            "and exactly once even under "
            "concurrency."),
        village_need=(
            "The seam that keeps the two shapes "
            "honest: people will file questions as "
            "issues and work as discussions, and "
            "the correction must cost one act, "
            "not a copy-paste that orphans the "
            "conversation. Research 30's own "
            "acceptance check converts twice "
            "concurrently and demands exactly one "
            "linked result."),
        served_by=(
            "The issue store and the discussion "
            "store converting through each other's "
            "own doors, linked both ways; the "
            "one-conversion honesty of S-137's "
            "issue conversion is the standing "
            "precedent for refusing a second."),
        judgement="build"),
    FeatureAssessment(
        id="polls",
        title="Discussion polls (S-286)",
        building_means=(
            "A poll inside a discussion thread: "
            "options, one honest count per "
            "account, a close date, and results "
            "stated in words."),
        village_need=(
            "None measured: no village decision "
            "waits on a thread poll today, and "
            "research 30 defers polls exactly "
            "where they do not meet a "
            "village-scale real need. Polls also "
            "carry the study's honesty warning -- "
            "fraud-resistant rules that do not "
            "pretend to establish voter identity "
            "beyond account scope."),
        served_by=(
            "Nothing, because nothing needs "
            "serving; a village decision today is "
            "made in the open discussion itself, "
            "in words, by named people."),
        judgement="deferred"),
    FeatureAssessment(
        id="rich-badges",
        title="Rich badges and gamification",
        building_means=(
            "Reputation badges, answer scores and "
            "kindred ornaments layered over the "
            "discussion board."),
        village_need=(
            "None measured, and research 30 names "
            "rich badges in the same deferral "
            "sentence as polls. A village knows "
            "its neighbours by name; an answer is "
            "trusted because its author is known, "
            "not because a badge says so."),
        served_by=(
            "Nothing, by design: the answer mark "
            "itself (S-284) is the one signal the "
            "board carries, and it is an event by "
            "a named person, not a score."),
        judgement="deferred"),
)


@dataclass(frozen=True)
class VerdictInvariant:
    """One thing the discussions build must not
    break: a stable id, the standing slice or law
    it is grounded in, and the invariant stated."""
    id: str
    ground: str
    title: str
    statement: str


MUST_NOT_BREAK: tuple[VerdictInvariant, ...] = (
    VerdictInvariant(
        id="permissions-follow-the-repository",
        ground="S-190",
        title="Discussion permissions are the repository's, judged by S-190",
        statement=(
            "A discussion belongs to its "
            "repository, and creating, replying, "
            "marking, pinning and moderating are "
            "judged by S-190's permission engine "
            "exactly as the repository's own acts "
            "are judged. There is no "
            "discussion-only role, no board-level "
            "back door around the engine, and "
            "research 30's role matrix -- create, "
            "reply, mark-answer, moderate -- is "
            "proven per rung, not assumed.")),
    VerdictInvariant(
        id="private-is-missing-everywhere",
        ground="research 30",
        title="Private is indistinguishable from missing, in search too",
        statement=(
            "A discussion in a private repository "
            "or a private organization answers "
            "exactly as a discussion that does not "
            "exist: in direct reads, in lists, in "
            "counts, and above all in search -- "
            "research 30 names a private org "
            "discussion exposed by public search "
            "as a core failure mode. Search joins "
            "discussions only through Part X's "
            "permission-filtered index (S-287's "
            "road), and no snippet, title or count "
            "may confirm what the caller may not "
            "read.")),
    VerdictInvariant(
        id="answer-mark-is-an-event",
        ground="research 30",
        title="The answer mark is an event, never an edit",
        statement=(
            "Marking an answer is a reversible, "
            "attributable event: it names its "
            "actor, it can be undone by the same "
            "powers that made it, there is exactly "
            "one accepted answer per question at "
            "a time, and it never replaces, edits "
            "or silently outranks the original "
            "reply. If the accepted reply is "
            "deleted, the deletion is the "
            "tombstone S-123's law already states "
            "and the mark's event stays on the "
            "timeline saying what was marked and "
            "what became of it.")),
    VerdictInvariant(
        id="conversion-is-exactly-once-and-never-silent",
        ground="S-285",
        title="Conversion happens exactly once, and never silently",
        statement=(
            "Converting a discussion to an issue, "
            "or an issue to a discussion, "
            "preserves the origin, leaves a "
            "forwarding note both ways, and keeps "
            "the two threads linked. The same "
            "question converted twice -- "
            "concurrently included, research 30's "
            "own acceptance check -- yields "
            "exactly one linked result, and the "
            "second attempt is refused naming the "
            "first, as S-137's conversion refuses. "
            "No conversion deletes the source's "
            "history.")),
    VerdictInvariant(
        id="one-timeline-holds-the-conversation",
        ground="research 30",
        title="One timeline holds replies, revisions and moderation",
        statement=(
            "A discussion thread has one "
            "conversation timeline, and everything "
            "that happens in it lives there: "
            "replies, revisions, answer marks, "
            "pins, conversions and moderation "
            "actions, each attributable and in "
            "order. Moderation is not a side "
            "channel: a moderated thread shows, in "
            "words on its own timeline, that it "
            "was moderated, by whom, under the "
            "category's stated powers.")),
    VerdictInvariant(
        id="categories-carry-explicit-states-and-powers",
        ground="research 30",
        title="Categories carry explicit states and powers",
        statement=(
            "Every category kind -- question, "
            "announcement, open discussion -- "
            "declares its allowed states and who "
            "may do what in it, before any thread "
            "is opened. Announcement moderation "
            "and pinned items are owner-controlled, "
            "as research 30 requires; a kind's "
            "semantics are never smuggled in by "
            "convention, and a thread's kind "
            "cannot change except by the "
            "conversion road of S-285.")),
    VerdictInvariant(
        id="subscriptions-share-notifications-with-own-controls",
        ground="S-219",
        title="Subscriptions share the notification machinery, with their own controls",
        statement=(
            "Topic subscriptions ride the "
            "standing notification machinery "
            "(S-219 and the thread subscriptions "
            "beside it) -- one inbox, one set of "
            "reasons, no parallel discussion-only "
            "notifier -- while keeping their own "
            "digest and mute controls, as research "
            "30 specifies. Watching a category, "
            "watching a thread and muting either "
            "are the subscriber's own acts, "
            "stated in words, never inferred.")),
    VerdictInvariant(
        id="composer-and-search-stay-accessible",
        ground="research 30",
        title="The composer and the search stay accessible",
        statement=(
            "The discussion composer is mobile "
            "and keyboard first, and discussion "
            "search carries filters (category, "
            "kind, answered or unanswered, "
            "author), as research 30 requires and "
            "the WCAG reference it cites binds. "
            "States -- answered, pinned, locked, "
            "converted -- are said in words, "
            "never by colour alone, under the "
            "forge's standing accessibility law.")),
)

BUILD_CONDITIONS: tuple[str, ...] = (
    "S-283 builds categories and threads first, "
    "under the invariants above, reusing S-123's "
    "timeline machinery whole (the S-280 precedent) "
    "rather than duplicating it, with research 30's "
    "role-matrix acceptance as its battery's core.",
    "S-284 lands answer marking and S-285 lands "
    "conversion as their own slices, each carrying "
    "the study's acceptance checks: the mark's "
    "audit trail stable across roles, and "
    "double conversion -- concurrently -- yielding "
    "exactly one linked result.",
    "Polls stay deferred: S-286 takes its "
    "verdicted-out road, the published refusal "
    "built on this verdict, and a poll design is "
    "reconsidered only when a village need is "
    "measured and a fraud-honest design -- no "
    "identity claimed beyond account scope -- is "
    "stated with it.",
    "The successor roadmap revisits the deferred "
    "pieces: S-403 names refused and deferred "
    "items among what its seed reconsiders, and "
    "polls and rich badges are decided there, on "
    "measured need, not by drift.",
)


def get_reason(reason_id: object) -> VerdictReason:
    """One build reason by its id. An unknown id
    is refused reason_unknown -- the verdict does
    not invent a reason to answer with."""
    for reason in REASONS:
        if reason.id == reason_id:
            return reason
    raise DiscussionsVerdictError(
        "reason_unknown", "No such verdict reason "
        "is stated.")


def get_feature(feature_id: object) -> FeatureAssessment:
    """One assessed feature by its id. An unknown
    id is refused feature_unknown."""
    for feature in FEATURES:
        if feature.id == feature_id:
            return feature
    raise DiscussionsVerdictError(
        "feature_unknown", "No such feature was "
        "assessed.")


def get_invariant(invariant_id: object) -> VerdictInvariant:
    """One must-not-break invariant by its id. An
    unknown id is refused invariant_unknown."""
    for invariant in MUST_NOT_BREAK:
        if invariant.id == invariant_id:
            return invariant
    raise DiscussionsVerdictError(
        "invariant_unknown", "No such invariant "
        "is recorded.")


def decide_discussion_request(feature: object) -> str:
    """Pure discussions judgement: the answer for
    any request to use a discussion surface today,
    naming the feature asked for. A core piece is
    ``discussions_build_queued`` -- verdicted in
    by S-282, but its building slice has not
    landed, so no surface exists to use yet; a
    deferred piece is ``discussions_deferred``; a
    shapeless request (not text, or no text) is
    ``discussions_request_invalid`` and a worded
    but unassessed feature is
    ``discussions_feature_unknown``."""
    if not isinstance(feature, str) or not feature.strip():
        return "discussions_request_invalid"
    for assessed in FEATURES:
        if assessed.id == feature.strip():
            if assessed.judgement == "deferred":
                return "discussions_deferred"
            return "discussions_build_queued"
    return "discussions_feature_unknown"


@dataclass(frozen=True)
class DiscussionsVerdictAudit:
    """The build queue checked against one live
    instance: how much schema was inspected, and
    every discussion-shaped name found in it.
    The queue is clean only when every offender
    list is empty -- no discussion table, column
    or audit event exists before S-283 builds
    one."""
    verdict: str
    tables_scanned: int
    columns_scanned: int
    events_scanned: int
    offending_tables: tuple[str, ...]
    offending_columns: tuple[str, ...]
    offending_events: tuple[str, ...]

    @property
    def build_queued_cleanly(self) -> bool:
        return (self.verdict == "build"
                and not self.offending_tables
                and not self.offending_columns
                and not self.offending_events)


def audit_discussions_verdict(
        conn: sqlite3.Connection) -> DiscussionsVerdictAudit:
    """Check the build queue against the live
    instance: no table, column or audit event may
    carry a discussion yet -- a discussion surface
    arriving ahead of S-283, unnamed in any
    slice, would be the verdict bypassed by a
    back door. (The scan hunts the word
    discussion.) Pure read."""
    tables = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master"
        " WHERE type = 'table' ORDER BY name").fetchall()]
    offending_tables: list[str] = []
    offending_columns: list[str] = []
    columns_scanned = 0
    for table in tables:
        lowered = table.lower()
        if "discussion" in lowered:
            offending_tables.append(table)
        safe = table.replace('"', '""')
        for row in conn.execute(
                f'PRAGMA table_info("{safe}")').fetchall():
            columns_scanned += 1
            column = str(row[1]).lower()
            if "discussion" in column:
                offending_columns.append(f"{table}.{row[1]}")
    events = sorted(taxonomy.AUDIT_EVENTS)
    offending_events = [
        e for e in events if "discussion" in e.lower()]
    return DiscussionsVerdictAudit(
        verdict=VERDICT,
        tables_scanned=len(tables),
        columns_scanned=columns_scanned,
        events_scanned=len(events),
        offending_tables=tuple(offending_tables),
        offending_columns=tuple(offending_columns),
        offending_events=tuple(offending_events))


def attempt_discussion_action(feature: object) -> None:
    """Refuse a request to use a discussion
    surface, always -- for now: no discussion
    surface exists yet. Raises
    ``DiscussionsVerdictError`` carrying the pure
    decision's reason; writes nothing and audits
    nothing (there is no discussion event to
    write). Deferred features raise their
    deferral, pointing at the recorded reasons."""
    reason = decide_discussion_request(feature)
    if reason == "discussions_request_invalid":
        raise DiscussionsVerdictError(
            reason, "That discussion request is not valid.")
    if reason == "discussions_feature_unknown":
        raise DiscussionsVerdictError(
            reason,
            "Samverk assessed no such discussion "
            "feature: S-282 judged categories and "
            "threads, answer marking, conversion, "
            "polls and rich badges.")
    if reason == "discussions_deferred":
        raise DiscussionsVerdictError(
            reason,
            "That discussion feature is deferred: "
            "S-282 deferred polls and rich badges, "
            "with reasons, because no village-scale "
            "need for either has been measured. The "
            "record is docs/DISCUSSIONS_VERDICT.md.")
    raise DiscussionsVerdictError(
        reason,
        "Samverk has no discussion surface yet: "
        "S-282 verdicted discussions in, and the "
        "build is queued -- S-283 categories and "
        "threads, S-284 answer marking, S-285 "
        "conversion -- under the invariants in "
        "docs/DISCUSSIONS_VERDICT.md.")


def render_discussions_verdict_page(
        audit: DiscussionsVerdictAudit | None = None) -> str:
    """The verdict, rendered: build said plainly,
    the reasons, the five pieces judged one by
    one, the must-not-break invariants with the
    ground each hangs from, the build conditions,
    and the checked proof when an audit rides
    along -- every value escaped through S-010,
    the state said in words, never colour-only."""
    parts = [
        "<h1>Discussions -- build (S-282)</h1>",
        "<p>Verdict: <strong>build</strong>. "
        "Samverk will grow discussions: categories "
        "and threads (S-283), answer marking "
        "(S-284) and issue-discussion conversion "
        "(S-285). Polls and rich badges are "
        "deferred, with reasons. No discussion "
        "surface exists yet; the build is queued "
        "under the invariants below. This page is "
        "the study's conclusion (research file "
        "30), and the same words live in "
        "docs/DISCUSSIONS_VERDICT.md.</p>",
        "<h2>Why build</h2>",
        "<ul>",
    ]
    for reason in REASONS:
        parts.append(
            f"<li><strong>{escape_html_text(reason.title)}"
            f"</strong>: {escape_html_text(reason.detail)}"
            "</li>")
    parts.append("</ul>")
    parts.append("<h2>The pieces, judged</h2>")
    parts.append("<ul>")
    for feature in FEATURES:
        parts.append(
            f"<li><strong>{escape_html_text(feature.title)}"
            f"</strong> ({escape_html_text(feature.judgement)}): "
            f"building would mean {escape_html_text(feature.building_means)} "
            f"Village need: {escape_html_text(feature.village_need)} "
            f"Standing machinery: {escape_html_text(feature.served_by)}"
            "</li>")
    parts.append("</ul>")
    parts.append(
        "<h2>What the build must not break</h2>")
    parts.append("<ul>")
    for invariant in MUST_NOT_BREAK:
        parts.append(
            f"<li><strong>{escape_html_text(invariant.title)}"
            f"</strong> (grounded in: "
            f"{escape_html_text(invariant.ground)}): "
            f"{escape_html_text(invariant.statement)}</li>")
    parts.append("</ul>")
    parts.append("<h2>How the build proceeds</h2>")
    parts.append("<ul>")
    for condition in BUILD_CONDITIONS:
        parts.append(f"<li>{escape_html_text(condition)}</li>")
    parts.append("</ul>")
    if audit is not None:
        if audit.build_queued_cleanly:
            parts.append(
                "<p>Checked, not just claimed: this "
                "instance was inspected for a "
                "discussion surface -- "
                f"{audit.tables_scanned} tables, "
                f"{audit.columns_scanned} columns and "
                f"{audit.events_scanned} audit events "
                "-- and none was found: no discussion "
                "exists here before its building "
                "slice, exactly as the queue states.</p>")
        else:
            found = ", ".join(
                audit.offending_tables
                + audit.offending_columns
                + audit.offending_events)
            parts.append(
                "<p>Checked, and not clean: a "
                "discussion surface exists ahead of "
                "its building slice -- "
                f"{escape_html_text(found)} -- and "
                "that is a defect against S-282, to "
                "be fixed where it lies.</p>")
    parts.append(
        "<p>The invariants above are the law "
        "S-283..S-285 build under and the seam "
        "S-286 documents for polls: the deferred "
        "pieces stay out until measured village "
        "need reopens this verdict.</p>")
    return "\n".join(parts)
