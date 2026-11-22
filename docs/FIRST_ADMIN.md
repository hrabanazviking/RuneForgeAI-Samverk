# First-admin creation (S-350)

Roadmap S-350: a CLI command creates the first admin; the
admin's first sign-in lands on a home that shows the next
three things to do (the anti-Forgejo gate: token creation,
repo creation, and mirror setup each reachable and labelled
in plain words — verified by the Part XXI usability walk).

## What stands

- `samverk/first_admin.py` — `FirstAdminService` is the one
  door that creates the first admin, and the CLI door is
  `samverk admin create-first-admin --username NAME
  [--email EMAIL] [--config PATH] [--password-env VAR]`.
  The password comes from a hidden prompt (typed twice) or
  from the environment variable named by `--password-env`;
  it is never taken from argv, never printed, never stored
  in plaintext, and never appears in an audit detail — it is
  judged by S-025's standing password policy and hashed by
  S-004's scrypt seam, exactly like a registered account's.
- **First means first.** The pure `decide_first_admin`
  refuses whenever any admin already exists
  (`admin_exists`), whoever asks and whatever name they
  choose. Ordinary accounts may already stand — the door is
  also the recovery road for an instance whose admin was
  lost — but it will never mint a second first admin. The
  account is born `active` with `is_admin` set, in one
  insert, under S-025's whole username/email law (reserved
  names such as `admin` are refused here as everywhere).
  The act is audited `admin.user.create` (already in the
  frozen taxonomy; method `cli_first_admin`), and refusals
  are audited denied with their reason.
- **The first sign-in home.** `FirstAdminHome.steps_for`
  judges the admin's real state — tokens (S-032/S-033),
  repositories (S-013 store), mirrors (S-070) — and the pure
  `decide_next_steps` returns exactly three steps, in the
  order a new admin meets them. `render_first_admin_home`
  renders them as an ordered list in plain words, each a
  link to its real surface, each carrying its state in
  words (`To do` / `Done`, never colour alone), all escaped
  through S-010.

## The three doors, honestly

- **Token creation** links to `/settings/tokens`, the real
  token page (S-034) over the S-032/S-033 creation stores.
- **Repository creation** has no web page yet. Its landed
  door is `POST /api/v1/repos` (S-242, "POST creates one
  under the caller's own name with the web's own creation
  law"), and the step links to `/api/v1/repos`.
- **Mirror setup** has no standalone page. A mirror belongs
  to a repository (S-070 `MirrorService.create_mirror`;
  per-repo mirror pages render its state), so the step
  links to the admin's first repository when one exists,
  and to the repositories door before that, and its words
  say a mirror is set up on its repository.

No dead door is drawn as live: when a web page for repo
creation or mirror setup lands, the step hrefs move to it.

## Deliberate non-changes

No migration and no new audit event: the schema stands at
139 and the taxonomy stands at 138. The slice reuses the
seams its predecessors built (S-025 account law, S-004
hashing, S-027 sign-in, S-032/S-033 tokens, S-070 mirrors,
S-242 repositories API), on purpose.
