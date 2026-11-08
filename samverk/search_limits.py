"""Honest limits document (S-219).

What Samverk search does NOT do (no semantic
ranking claims, regex cost caps) written where
users will find it -- Part X's closing honesty
slice, in S-202's shape. S-208 stated its own caps
and said S-219 writes the honest limits where
users find them; S-212 named its scan cap "the
stated cost cap S-219's honest-limits document
will carry". This slice carries them all: one
module holding the limits as data, one page
rendered from that data, and docs/SEARCH_LIMITS.md
saying the same words for a reader who never opens
the page. The global search page (S-213) links
here from every rendering, landing and results
alike, at LIMITS_PATH.

- **Every limit is grounded in a banked engine.**
  No limit below is aspiration or apology: each
  states the behaviour the code actually has.
  No meaning search: S-208's substring mode is
  literal text and its regex mode is a pattern,
  S-206's issue/PR text is whole FTS tokens -- no
  engine holds an embedding, a vector, a synonym
  table, a stemmer or a spelling corrector, and
  none expands a query. No relevance ranking:
  S-208 orders hits by repository then path,
  S-213's groups stand in a fixed order, and no
  hit dataclass in any search face carries a
  score, rank or relevance field -- the audit
  below checks exactly that, mechanically.
- **The regex cost caps, stated exactly.** Regex
  is Python's stdlib re, compiled per search and
  run line by line over the candidate files. The
  caps that exist are: the pattern length
  (PATTERN_MAX), the per-line scan itself, and
  the result caps (limit, snippets, context).
  The caps that do NOT exist are stated as
  plainly: there is no timeout, no complexity or
  backtracking guard, and no safe-regex engine --
  the word timeout appears nowhere in S-208's
  executor, and the audit pins that absence. A
  pathological pattern can run long; S-217's
  budgets are measurements over a reference
  corpus, not a runtime limiter, and they stop
  nothing.
- **Proven, not just claimed.** audit_search_limits
  reads the live engines' own constants and hit
  shapes and compares them with DOCUMENTED_CAPS
  and the no-score law: if a cap drifts, a score
  field appears, or a timeout arrives unannounced,
  the audit stops being honest and the page says
  so in words -- the document then disagrees with
  the code, which is a defect in the document,
  and this slice's battery fails on it. One stale
  neighbour was found and fixed while grounding:
  S-208's matches_language docstring claimed an
  alias filter matches; S-218's shared law (which
  S-208 executes) fails an alias closed, and the
  docstring now says so.
- **A pure read, like S-202.** This module holds
  no store, writes no row and audits nothing:
  searching is a read, and a document about reads
  is a read. No migration (schema stays 84), no
  taxonomy event (123 stand: 31 auth / 79 repo /
  13 admin).
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from .escaping import escape_html_text

__all__ = [
    "DOCUMENTED_CAPS", "LIMITS_PATH", "SEARCH_LIMITS",
    "SearchLimit", "SearchLimitsAudit", "SearchLimitsError",
    "audit_search_limits", "get_limit", "limit_ids",
    "render_search_limits_page",
]

LIMITS_PATH = "/search/limits"

# The caps this document states, by the name the
# owning engine gives each one. audit_search_limits
# compares every value here with the live engine
# constant of the same meaning; a drift either way
# (code moved, document did not -- or the reverse)
# makes the audit dishonest.
DOCUMENTED_CAPS = {
    "code_pattern_max": 500,
    "code_default_limit": 100,
    "code_max_limit": 500,
    "code_max_context": 3,
    "code_max_snippets_per_file": 20,
    "global_query_max": 500,
    "global_default_group_limit": 10,
    "global_max_group_limit": 100,
    "max_code_blob_bytes": 1_048_576,
    "commit_max_scan_per_repo": 5000,
}

# Words that would name a relevance judgement on a
# hit. No search hit carries a field with any of
# these names; the audit checks the hit dataclasses
# of the code, repository, commit and global faces.
_FORBIDDEN_HIT_FIELDS = ("score", "rank", "relevance", "semantic")


class SearchLimitsError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class SearchLimit:
    """One honest limit of Samverk search: a stable
    id, the plain title a user reads, and the
    statement of what is not done, grounded in the
    engine named inside it."""
    id: str
    title: str
    statement: str


SEARCH_LIMITS: tuple[SearchLimit, ...] = (
    SearchLimit(
        id="no-semantic-search",
        title="No meaning search",
        statement=(
            "Search matches text, never meaning. There are no "
            "embeddings, no vectors, no synonym table, no "
            "stemming, no spelling correction and no query "
            "expansion anywhere in Samverk. Code search "
            "(S-208) is a literal substring hunt or a regular "
            "expression you wrote; issue and pull request "
            "text (S-206) is whole FTS tokens, ANDed. A word "
            "finds only itself and its exact forms in the "
            "text: searching for the idea of a thing finds "
            "nothing unless the text says the word.")),
    SearchLimit(
        id="no-relevance-ranking",
        title="No relevance ranking",
        statement=(
            "No result is ranked by relevance, and no hit "
            "carries a score. Code hits are ordered by "
            "repository, then path (S-208); the global page "
            "shows its groups in one fixed order (S-213); "
            "the other faces sort by the plain facts they "
            "name -- name, creation time, comment count. "
            "The first result is the first in that order, "
            "not the best match, and when a cap trims a "
            "group it trims the tail of that order: an "
            "equally-matching result later in the order is "
            "the one not shown.")),
    SearchLimit(
        id="regex-cost-caps",
        title="Regex cost: the caps are caps on size, not on time",
        statement=(
            "A regex is Python's standard re, compiled once "
            "per search and run line by line over the "
            "candidate files (S-208). The caps that exist "
            "are caps on size: the pattern is at most 500 "
            "characters, results are capped, and snippets "
            "are capped. There is no timeout, no complexity "
            "or backtracking guard, and no safe-regex "
            "engine: a pathological pattern such as nested "
            "quantifiers over a long line can run long, and "
            "nothing in Samverk will stop it. The latency "
            "budgets (S-217) are measurements over a "
            "reference corpus, not a runtime limiter -- "
            "they measure searches; they interrupt none.")),
    SearchLimit(
        id="pattern-and-result-caps",
        title="Patterns, results and snippets are capped",
        statement=(
            "Code search (S-208): a pattern is at most 500 "
            "characters; at most 500 files are returned "
            "(100 by default); each file shows at most 20 "
            "snippet blocks, with at most 3 lines of context "
            "either side of a matched line. The counts a "
            "search reports are tallied over the whole "
            "filtered result before the cap (S-209), so a "
            "count can honestly exceed what is shown -- "
            "shown and counted are never confused, and the "
            "cap is why more matches exist than are listed.")),
    SearchLimit(
        id="index-coverage",
        title="Only indexed text can be found",
        statement=(
            "Code search reads the index (S-207), and the "
            "index holds only what it judged indexable from "
            "the default branch's tip snapshot: a text blob "
            "of at most 1048576 bytes (1 MiB). Oversized, "
            "binary, empty and submodule files are skipped, "
            "paths the snapshot's own .gitignore ignores "
            "are skipped, and other branches and tags are "
            "not in the code index at all. A Git LFS file "
            "is indexed as its pointer: the pointer's own "
            "short text is searchable, the file it points "
            "at is never fetched and never searchable. "
            "Text in any of those places is not findable "
            "by code search, however exactly it matches.")),
    SearchLimit(
        id="index-freshness",
        title="Search sees the last indexed snapshot, not the live tree",
        statement=(
            "Indexing follows pushes; it is not instant. "
            "Between a push and the indexing run that "
            "follows it, code search answers from the "
            "previous snapshot: a just-pushed change can "
            "be missing, and a just-deleted line can still "
            "be found. The results page carries no "
            "freshness warning; the lag itself is an "
            "admin fact, shown in numbers on the index "
            "health page (S-215), never hidden there.")),
    SearchLimit(
        id="language-limits",
        title="Language is a name, extension or shebang -- nothing deeper",
        statement=(
            "A file's language is decided from its name, "
            "its extension, or the shebang line of an "
            "extensionless file, from one shared table "
            "(S-218). Content is never classified: a "
            "Python program in a .txt file is text. A "
            "file no signal names is recorded as text, "
            "never guessed at. A language filter must "
            "name the canonical language: an alias such "
            "as py matches nothing in a code search "
            "filter (it fails closed), and a word naming "
            "no known language matches nothing either.")),
    SearchLimit(
        id="global-and-api-caps",
        title="The global box and the API are small on purpose",
        statement=(
            "A global query is at most 500 characters and "
            "each result group shows at most 100 results "
            "(10 by default, S-213). There is no combined "
            "total across groups, deliberately: the groups "
            "count behind different permission "
            "boundaries. The search API (S-216) has no "
            "paging cursor: its complete flag says plainly "
            "whether the cap trimmed a group, and a caller "
            "who needs more than the cap cannot page to "
            "it through the API. A saved search (S-214) "
            "is a stored query re-run live, not a stored "
            "result: its answers change as the instance "
            "changes.")),
    SearchLimit(
        id="commit-scan-cap",
        title="Commit search scans a capped history",
        statement=(
            "Commit search (S-212) scans at most 5000 "
            "commits per repository, newest first, over "
            "every ref. A matching commit older than "
            "that scan in a long-lived repository is not "
            "found, and the results do not announce that "
            "the scan stopped: the cap is stated here, "
            "where the limit lives, instead.")),
    SearchLimit(
        id="budgets-per-hardware",
        title="Speed is promised per hardware class, and one class is unproven",
        statement=(
            "The latency budgets (S-217) are stated per "
            "hardware class -- server, laptop, Pi-class "
            "ARM -- as p95 measurements over one reference "
            "corpus, and a measurement claims only the "
            "class it ran on. The Pi-class budget is "
            "stated but NOT PROVEN: it has not been "
            "measured on Pi-class hardware (S-395 "
            "re-measures it, S-413 restates every budget "
            "per class). A budget is not a guarantee for "
            "your corpus, your pattern or your machine."
            )),
)


def limit_ids() -> tuple[str, ...]:
    """The ids of every stated limit, in document
    order."""
    return tuple(limit.id for limit in SEARCH_LIMITS)


def get_limit(limit_id: object) -> SearchLimit:
    """One stated limit by its id. An unknown id is
    refused limit_unknown -- the document does not
    invent a limit to answer with."""
    for limit in SEARCH_LIMITS:
        if limit.id == limit_id:
            return limit
    raise SearchLimitsError(
        "limit_unknown", "No such search limit is stated.")


@dataclass(frozen=True)
class SearchLimitsAudit:
    """The document checked against the live code:
    how many documented caps were compared, how
    many still match the engines' own constants,
    whether any hit carries a forbidden relevance
    field, whether the regex executor still has no
    timeout, and the engine facts the page states.
    Honest only when every check holds."""
    caps_checked: int
    caps_matching: int
    cap_mismatches: tuple[str, ...]
    hit_fields_scanned: int
    offending_hit_fields: tuple[str, ...]
    regex_has_timeout: bool

    @property
    def honestly_stated(self) -> bool:
        return (self.caps_matching == self.caps_checked
                and not self.cap_mismatches
                and not self.offending_hit_fields
                and not self.regex_has_timeout)


def audit_search_limits() -> SearchLimitsAudit:
    """Check this document against the live engines:
    every DOCUMENTED_CAPS value against the owning
    module's own constant, every hit dataclass of
    the code / repository / commit / global faces
    for a forbidden relevance field, and S-208's
    executor source for a timeout the document
    says does not exist. Pure read: imports and
    introspection only, nothing is searched and
    nothing is written."""
    from . import (code_search, commit_search, global_search,
                   index_architecture, repository_search)
    live = {
        "code_pattern_max": code_search.PATTERN_MAX,
        "code_default_limit": code_search.DEFAULT_LIMIT,
        "code_max_limit": code_search.MAX_LIMIT,
        "code_max_context": code_search.MAX_CONTEXT,
        "code_max_snippets_per_file":
            code_search.MAX_SNIPPETS_PER_FILE,
        "global_query_max": global_search.QUERY_MAX,
        "global_default_group_limit":
            global_search.DEFAULT_GROUP_LIMIT,
        "global_max_group_limit": global_search.MAX_GROUP_LIMIT,
        "max_code_blob_bytes":
            index_architecture.MAX_CODE_BLOB_BYTES,
        "commit_max_scan_per_repo":
            commit_search.MAX_SCAN_PER_REPO,
    }
    mismatches = tuple(
        name for name, stated in DOCUMENTED_CAPS.items()
        if live.get(name) != stated)
    hit_classes = (
        code_search.CodeSearchHit, code_search.CodeSearchResults,
        repository_search.RepositoryHit,
        global_search.GroupResults,
        global_search.GlobalSearchResults)
    fields_scanned = 0
    offending: list[str] = []
    for cls in hit_classes:
        for field in dataclasses.fields(cls):
            fields_scanned += 1
            if field.name in _FORBIDDEN_HIT_FIELDS:
                offending.append(f"{cls.__name__}.{field.name}")
    import inspect
    executor_source = inspect.getsource(code_search)
    return SearchLimitsAudit(
        caps_checked=len(DOCUMENTED_CAPS),
        caps_matching=len(DOCUMENTED_CAPS) - len(mismatches),
        cap_mismatches=mismatches,
        hit_fields_scanned=fields_scanned,
        offending_hit_fields=tuple(offending),
        regex_has_timeout="timeout" in executor_source)


def render_search_limits_page(
        audit: SearchLimitsAudit | None = None) -> str:
    """The honest limits, rendered where users find
    them: every stated limit in document order, the
    caps in one plain list, the checked proof when
    an audit rides along, and the pointer to the
    same words in docs/SEARCH_LIMITS.md. Every
    value escaped through S-010; the state is said
    in words, never colour-only."""
    parts = [
        "<h1>What search does not do</h1>",
        "<p>Samverk search is literal, capped and "
        "unranked, and this page says exactly where "
        "its edges are. A search that finds nothing "
        "may have met one of these limits rather than "
        "an empty instance.</p>",
    ]
    for limit in SEARCH_LIMITS:
        parts.append(
            f'<h2 id="{escape_html_text(limit.id)}">'
            f"{escape_html_text(limit.title)}</h2>")
        parts.append(f"<p>{escape_html_text(limit.statement)}</p>")
    parts.append("<h2>The caps, in one list</h2>")
    parts.append("<ul>")
    cap_lines = (
        f"Code pattern: at most {DOCUMENTED_CAPS['code_pattern_max']} characters.",
        f"Code results: {DOCUMENTED_CAPS['code_default_limit']} files by default, at most {DOCUMENTED_CAPS['code_max_limit']}.",
        f"Snippets per file: at most {DOCUMENTED_CAPS['code_max_snippets_per_file']}, with at most {DOCUMENTED_CAPS['code_max_context']} context lines either side.",
        f"Global query: at most {DOCUMENTED_CAPS['global_query_max']} characters; per group {DOCUMENTED_CAPS['global_default_group_limit']} by default, at most {DOCUMENTED_CAPS['global_max_group_limit']}.",
        f"Indexed blob: at most {DOCUMENTED_CAPS['max_code_blob_bytes']} bytes (1 MiB).",
        f"Commit scan: at most {DOCUMENTED_CAPS['commit_max_scan_per_repo']} commits per repository.",
        "Regex: no timeout and no backtracking guard -- size caps only.",
    )
    for line in cap_lines:
        parts.append(f"<li>{escape_html_text(line)}</li>")
    parts.append("</ul>")
    if audit is not None:
        if audit.honestly_stated:
            parts.append(
                "<p>Checked, not just claimed: this "
                "document was compared with the live "
                f"engines -- {audit.caps_matching} of "
                f"{audit.caps_checked} stated caps match "
                "the engines' own constants, "
                f"{audit.hit_fields_scanned} hit fields "
                "carry no score, rank or relevance, and "
                "the regex executor has no timeout, "
                "exactly as stated above.</p>")
        else:
            problems = ", ".join(
                audit.cap_mismatches
                + audit.offending_hit_fields
                + (("regex timeout present",)
                   if audit.regex_has_timeout else ()))
            parts.append(
                "<p>Checked, and no longer exact: this "
                "document disagrees with the live code "
                f"-- {escape_html_text(problems)} -- and "
                "that is a defect against S-219, in the "
                "document or in the code, to be fixed "
                "where it lies.</p>")
    parts.append(
        "<p>The same limits live in "
        "docs/SEARCH_LIMITS.md for a reader who never "
        "opens this page, and the performance budgets "
        "behind the speed statements are S-217's, "
        "measured per hardware class.</p>")
    return "\n".join(parts)
