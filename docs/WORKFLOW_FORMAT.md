# Workflow format — Samverk's own, adopted (S-313)

Samverk workflows live in `.samverk/workflows/` as
YAML files, one workflow per file, in a shape that
is GitHub-familiar in structure and documented as
ours. This page is the study record the roadmap
asks for: the mapping from the GitHub shape, field
by field, and the deliberate differences, stated as
differences. It concludes the CI study in research
file 25 (`research/25-ci-actions-concepts.md`),
which separates the two products a forge's CI
holds — workflows defined by repository code, and
independent runners executing jobs. Samverk defines
workflows and talks to runners; it does not
pretend a runner is a forge feature. The machine-
readable twin of this page is
`samverk/workflow_format.py`, whose validator
judges a workflow document against this shape.

## The shape

```yaml
name: CI
on: [push, pull_request]
permissions: read-all
jobs:
  test:
    runner: [linux, self-hosted]
    steps:
      - name: Run the tests
        run: python3 -m unittest discover -s tests
```

Top level: `name` (optional), `on` (required),
`env`, `permissions`, `concurrency`, `jobs`
(required). A job carries `name`, `runner`
(required), `needs`, `if`, `env`,
`timeout-minutes`, `steps` (required, non-empty).
A step carries `name`, `run` (required), `env`,
`working-directory`, `shell`, `if` — and nothing
else. The trigger vocabulary this slice names is
`push`, `pull_request`, `tag`, `schedule` and
`workflow_dispatch`; S-314 owns what each trigger
does. Files are parsed with Samverk's standing
YAML subset (S-162's parser, reused whole) — the
forge is stdlib-first and admits no second YAML
parser.

## The mapping, GitHub to Samverk

- **Location** — `.github/workflows/` →
  `.samverk/workflows/` (renamed). Samverk never
  reads the GitHub directory; the two forges never
  fight over one file.
- **`name` → `name`** (same). Optional in both;
  the file stem names the workflow when absent.
- **`on` → `on`** (same word, same place). Samverk
  keeps the key as text — never the YAML 1.1
  boolean — and S-314 owns the triggers.
- **`jobs` → `jobs`** (same). S-315 owns the
  jobs-and-steps model the key holds.
- **`runs-on` → `runner`** (renamed — the one
  rename). GitHub names a hosted image; Samverk
  names runner labels (S-317), because a village
  instance's runners are its own machines. One
  label or a list of labels.
- **`needs` → `needs`** (same). Must name standing
  jobs and never cycle.
- **`steps[].run` → `steps[].run`** (same). A shell
  step is a shell step — the one step kind the
  format carries.
- **`steps[].uses` → not carried.** Marketplace
  actions do not exist here; a step using one is
  refused by name. Write the shell instead.
- **`env` → `env`** (same). Literal pairs at
  workflow, job and step level; no expression
  language evaluates them yet.
- **`permissions` → `permissions`** (same
  vocabulary, stricter default — see below).
- **`concurrency` → `concurrency`** (same). A
  group name or a mapping with a `group`.
- **`${{ ... }}` expressions → not carried.**
  Refused, never half-evaluated.
- **`strategy.matrix` → not carried yet.**
  Matrix expansion is S-315's to scope honestly;
  `strategy` is an unknown key until then.

## The deliberate differences

- **The directory is ours.** A repository may
  carry both directories while it migrates;
  neither forge executes the other's files.
- **No `uses:` — steps are shell, only.** Research
  25 names arbitrary workflow code as
  intentionally untrusted; a marketplace action
  is third-party code fetched by name at run
  time. Here, what runs is what the repository
  says, reviewable in the same diff.
- **`runner:` labels, not `runs-on:` images.**
  There is no hosted-image catalogue on a village
  instance to name, so the format does not
  pretend one.
- **`on` is a word, never a boolean.** YAML 1.1
  reads the bare word `on` as `true`; workflows
  have vanished that way. The parser keeps keys
  as text, and the validator refuses a boolean
  trigger key with the reason stated.
- **No `${{ }}` expression language yet.** Values
  are literal. If expressions are designed later
  they arrive with their own governance, not by
  drift.
- **Permissions default to read-only.** An
  undeclared `permissions:` means read-only, so
  S-314's scheduler and S-320's fork rule inherit
  the strict reading.
- **Unknown keys are refused, never ignored.** A
  misspelled or not-yet-carried key fails
  validation in plain words; a format that
  ignores what it does not know teaches authors
  their file says something it does not.

## What Part XVI must not break

Recorded in the module as `MUST_NOT_BREAK`, as
the law S-314..S-328 build under: a runner is
not the forge; no Docker anywhere in Part XVI;
fork safety lives in the scheduler, not in docs;
secrets are scoped, injected and masked (S-319,
S-018's filter); checks bind to the commit that
ran; skipped is never passed (S-325's named
trap); schedules read the default branch only;
and every run-changing action is audit-logged
when its slice lands — this slice mints no event
(135 stand: 33 auth / 89 repo / 13 admin) and no
migration (schema stays 128).
