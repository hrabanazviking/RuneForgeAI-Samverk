# Admin Panel (S-351)

The instance admin's one desk for users, organizations, and
repositories: `samverk/admin_panel.py` (`AdminPanel`), battery
`tests/test_admin_panel.py`.

## Who may reach it

Every method judges the actor first through the account store:
a missing account is refused `no_such_user`, a non-admin
`not_admin`, and nothing — not even a listing — is answered
before that judgement passes. Destructive attempts by
non-admins are witnessed in the audit log under the attempted
action's own event with outcome `denied`. Read refusals have
no event in the standing taxonomy and, like the instance
audit view (S-198), are refused plainly and not witnessed;
no taxonomy event was invented for them.

## Search

One box, three subjects. `search(actor_id, query, kind=None,
limit=50)` matches every query term, case-insensitively,
against at least one field of a subject (AND across terms):
users by username and email, organizations by name, display
name, and bio, repositories by owner, name, and description.
The pure judgement is `matches_query`; `normalize_query`
fails closed (`query_invalid`) on non-text, control
characters, and over-long queries.

Two deliberate differences from S-211's public people
search: accounts in **every** status are listed (a suspended
account the public cannot find is exactly the one an admin
must), and email is a search field (admins already see the
address on the row; S-211's law guards the public directory,
which is untouched). Empty sections render an honest empty
state ("No users match." / "No organizations match." /
"No repositories match.") — see
`render_admin_panel_page`.

## Destructive actions: sudo-gated, audit-logged, fail-closed

Create user, suspend user, delete user, delete repository,
delete organization, and role change (`set_admin`) all pass
one gate (`_gate_destructive`) before anything executes:

1. The panel must hold an audit log — without one the act is
   refused `audit_required`. An unaudited destructive action
   is impossible by construction, not by discipline.
2. The acting admin must hold a fresh S-036 sudo grant on
   the calling session — otherwise `sudo_required`,
   witnessed `denied`, and nothing executes.
3. Only then is the authorization appended to the audit log
   (`detail {"via": "admin_panel", "phase": "authorized"}`)
   **before** the executing seam runs; the seam adds its own
   witness entry, so each act carries two.

Panel pre-judges each seam's foreseeable refusals (duplicate
username, self-suspension, missing reason, confirmation
mismatch, already-pending, repos remaining) before the gate,
so an authorization entry never precedes a refusal the panel
could have foreseen.

## The seams keep their laws

- **Suspend / unsuspend** are S-044's `AccountSuspension`:
  reason required, no self-suspension, sessions revoked,
  content hidden not deleted, witnessed under
  `admin.user.suspend` / `admin.user.unsuspend`. Unsuspend
  is restorative, not destructive: admin-gated and audited,
  but not sudo-gated.
- **Delete user** is S-043's process (typed confirmation of
  the username, 7-day grace, tombstone), witnessed under
  `admin.user.delete` (panel) and `auth.deletion.request`
  (seam). The panel hands S-043 a re-auth verifier bound to
  the *acting admin's* fresh grant on the admin's session —
  the re-authentication an admin act can honestly claim.
- **Delete repository** stays S-056 owner-only and
  **delete organization** stays S-199 owner-only: an
  instance admin who does not own the repo/org is refused
  by the seam's own law (`not_repo_owner` /
  `not_org_owner`). The panel invents no bypass. Org
  deletion still requires every repository to be
  transferred or deleted explicitly first
  (`repos_remaining`).
- **Create user** rides S-004 registration (witnessed
  `admin.user.create` at the desk, `auth.signup.success`
  by the seam); `make_admin=True` additionally witnesses
  `admin.user.role_change`.
- **Role change** refuses `cannot_demote_self`, and
  `last_admin` when the target is the instance's last
  remaining admin, so the panel can never lock the
  instance out of itself.

## Stance

No migration and no new taxonomy event: schema **139** and
taxonomy **138** stand. Every event the panel writes is a
standing one — `admin.user.create`, `admin.user.suspend`,
`admin.user.unsuspend`, `admin.user.delete`,
`admin.user.role_change`, `repo.settings.change`,
`auth.organization.update` — plus the seams' own entries.
