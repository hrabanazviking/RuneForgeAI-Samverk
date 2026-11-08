# Search — what it does not do (S-219)

Samverk search is literal, capped and unranked.
This page exists because people arriving from other
forges expect search to understand them — to rank
by relevance, to find a concept by any of its
words, to keep digging until it finds something —
and in Samverk they should find the edges stated
plainly where they look, instead of mistaking a
limit for an empty instance. The same words render
in the app on the search limits page
(`samverk/search_limits.py`, linked from the global
search page itself), and that module checks this
document's caps against the live engines on every
test run: if a number below stops being true of
the code, the battery fails.

## No meaning search

Search matches text, never meaning. There are no
embeddings, no vectors, no synonym table, no
stemming, no spelling correction and no query
expansion anywhere in Samverk. Code search is a
literal substring hunt or a regular expression you
wrote; issue and pull request text is whole FTS
tokens, ANDed. A word finds only itself and its
exact forms in the text: searching for the idea of
a thing finds nothing unless the text says the
word.

## No relevance ranking

No result is ranked by relevance, and no hit
carries a score. Code hits are ordered by
repository, then path; the global page shows its
groups in one fixed order; the other faces sort by
the plain facts they name — name, creation time,
comment count. The first result is the first in
that order, not the best match, and when a cap
trims a group it trims the tail of that order: an
equally-matching result later in the order is the
one not shown.

## Regex cost: the caps are caps on size, not on time

A regex is Python's standard `re`, compiled once
per search and run line by line over the candidate
files. The caps that exist are caps on size: the
pattern is at most 500 characters, results are
capped, and snippets are capped. There is no
timeout, no complexity or backtracking guard, and
no safe-regex engine: a pathological pattern such
as nested quantifiers over a long line can run
long, and nothing in Samverk will stop it. The
latency budgets are measurements over a reference
corpus, not a runtime limiter — they measure
searches; they interrupt none.

## Patterns, results and snippets are capped

Code search: a pattern is at most 500 characters;
at most 500 files are returned (100 by default);
each file shows at most 20 snippet blocks, with at
most 3 lines of context either side of a matched
line. The counts a search reports are tallied over
the whole filtered result before the cap, so a
count can honestly exceed what is shown — shown
and counted are never confused, and the cap is why
more matches exist than are listed.

## Only indexed text can be found

Code search reads the index, and the index holds
only what it judged indexable from the default
branch's tip snapshot: a text blob of at most
1048576 bytes (1 MiB). Oversized, binary, empty
and submodule files are skipped, paths the
snapshot's own `.gitignore` ignores are skipped,
and other branches and tags are not in the code
index at all. A Git LFS file is indexed as its
pointer: the pointer's own short text is
searchable, the file it points at is never fetched
and never searchable. Text in any of those places
is not findable by code search, however exactly it
matches.

## Search sees the last indexed snapshot, not the live tree

Indexing follows pushes; it is not instant.
Between a push and the indexing run that follows
it, code search answers from the previous
snapshot: a just-pushed change can be missing,
and a just-deleted line can still be found. The
results page carries no freshness warning; the lag
itself is an admin fact, shown in numbers on the
index health page, never hidden there.

## Language is a name, extension or shebang — nothing deeper

A file's language is decided from its name, its
extension, or the shebang line of an
extensionless file, from one shared table.
Content is never classified: a Python program in
a `.txt` file is text. A file no signal names is
recorded as text, never guessed at. A language
filter must name the canonical language: an alias
such as `py` matches nothing in a code search
filter (it fails closed), and a word naming no
known language matches nothing either.

## The global box and the API are small on purpose

A global query is at most 500 characters and each
result group shows at most 100 results (10 by
default). There is no combined total across
groups, deliberately: the groups count behind
different permission boundaries. The search API
has no paging cursor: its `complete` flag says
plainly whether the cap trimmed a group, and a
caller who needs more than the cap cannot page to
it through the API. A saved search is a stored
query re-run live, not a stored result: its
answers change as the instance changes.

## Commit search scans a capped history

Commit search scans at most 5000 commits per
repository, newest first, over every ref. A
matching commit older than that scan in a
long-lived repository is not found, and the
results do not announce that the scan stopped:
the cap is stated here, where the limit lives,
instead.

## Speed is promised per hardware class, and one class is unproven

The latency budgets are stated per hardware class
— server, laptop, Pi-class ARM — as p95
measurements over one reference corpus, and a
measurement claims only the class it ran on. The
Pi-class budget is stated but NOT PROVEN: it has
not been measured on Pi-class hardware. A budget
is not a guarantee for your corpus, your pattern
or your machine.
