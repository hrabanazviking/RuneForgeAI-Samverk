# Study 19 — Issue search and queries

*Clean-room study. Sources: the publicly documented search
behaviour of GitHub-class forges (qualifier names and shapes
are public user-facing behaviour), observed use, and this
project's own issue stores (S-121…S-134). Written in our own
words; no host's code, assets, or design copied. This study
is the grammar S-135 implements in subset, S-136 saves, and
Part X's S-206 executes globally.*

## The shape of a query

A query is one line of text, at most 500 characters in the
S-135 subset. It is a sequence of **tokens** separated by
whitespace. A token is one of:

1. a **qualifier** — `name:value`, where the value may be
   double-quoted so names carrying spaces stay one token
   (`label:"good first issue"`, `milestone:"Launch 1"`);
2. a **free-text term** — any other token, matched
   case-insensitively against an issue's title and body; a
   quoted phrase is one term, matched as a phrase.

Tokens compose by **AND**: every qualifier and every term
must hold for an issue to match. There is no OR and no
parenthesisation in the grammar — a user who needs a union
runs two searches (and S-136 can save both). Contradictory
qualifiers (`is:open is:closed`) match nothing, honestly,
rather than silently preferring one.

## The qualifier table

Implemented in the S-135 subset (per-repository issue page):

| Qualifier | Values | Meaning |
|---|---|---|
| `is:` | `open`, `closed`, `issue` | state / kind filter |
| `label:` | a label name in this repository | the issue carries the label; repeated `label:` requires every named label |
| `author:` | an account name | the issue's author |
| `assignee:` | an account name | one of the issue's assignees |
| `milestone:` | a milestone title in this repository | the issue sits in that milestone |

Reserved for the full grammar (Part X, S-206, over the
global FTS + structured index; documented here so saved
filters written today can name them when that part lands —
a parser that meets one before then refuses it by name,
it never silently drops it):

| Qualifier | Meaning |
|---|---|
| `is:pr`, `is:issue` | kind filter across issues and pull requests together |
| `repo:owner/name` | scope to one repository in a global search |
| `no:label`, `no:assignee`, `no:milestone` | the field is empty |
| `created:YYYY-MM-DD`, `updated:…`, with `>`, `<`, `..` ranges | date filters over real calendar dates |
| `sort:created-asc` / `sort:created-desc` / `sort:comments-desc` | result ordering; the subset's default is number order |
| `-qualifier:value` | negation of one qualifier |

## Failure law

- An unknown qualifier is a **refusal that names it**
  (`query_invalid`) — never a silent drop, because a dropped
  qualifier silently widens a search (the S-118 law), and
  never free text, because `label:bug` typed by a user who
  meant the qualifier must not quietly become a text hunt.
- An empty qualifier value, an unterminated quote, a
  control character, and an `is:` value outside its
  vocabulary are the same named refusal.
- A qualifier naming something that does not exist here
  (a label this repository never had) is **not** an error:
  it simply matches nothing, and the page's empty state
  says what to try next.
- Matching is case-insensitive for names and text alike;
  account, label, and milestone identity is the canonical
  lowercase identity the owning stores already keep.

## Permissions

A search answers only what its viewer may read (S-054).
In a private repository a stranger's search receives the
uniform not-found answer, exactly like every other issue
surface — a search box must never become an enumeration
oracle for private issues.
