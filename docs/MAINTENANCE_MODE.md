# Maintenance mode (S-353)

Roadmap S-353: *Maintenance mode — read-only banner with reason and
expected return; transports refuse pushes with the message; admins
retain access.*

Module: `samverk/maintenance_mode.py`. Battery:
`tests/test_maintenance_mode.py` (21 tests).

## The shape

- **State** lives in the founding `settings` table (no migration;
  schema stays 139): `maintenance.enabled`, `maintenance.reason`,
  `maintenance.expected_return`, `maintenance.set_by`,
  `maintenance.set_at`. Absence of the rows is the off state.
- **Changes are admin-only.** `MaintenanceMode.enable(actor, reason,
  expected_return)` / `disable(actor)` refuse a non-admin (or
  anonymous) actor with `admin_required` and change nothing.
  Enabling requires a reason and an expected return, both in plain
  words (`reason_required` / `expected_return_required`).
- **Witnessed with the standing event.** Each change appends
  `admin.settings.change` with target `maintenance` — no new
  taxonomy event (138 stand).
- **Judgement is pure.** `decide_access(state, is_admin=..., write=...)`:
  mode off allows everything (standing permissions judge); mode on
  allows all reads, allows pushes by admins (admins retain access),
  and refuses every other push with `push_refusal_message(state)` —
  the one sentence carrying the operator's reason and expected
  return, identical at every door.

## The doors

1. **Smart HTTP** (`SmartHttpService._resolve`, the write leg, after
   the S-334 mirror check): a receive-pack advertisement or POST is
   refused with `TransportError("maintenance_mode", <message>)`
   before any pack byte moves. Upload legs are untouched.
2. **SSH** (`SshServeService.serve`, `git-receive-pack` only, before
   the S-089 gate): refused `fatal: <message>` with exit 128, before
   the pack runner is called. Upload legs are untouched.
3. **Pre-receive gate** (S-089): `MaintenanceMode.gate_plugin` plugs
   into the protection stage and vetoes with the same message; the
   actor is judged by the context username (a deploy key is not an
   admin and is refused).

## The banner

`render_maintenance_banner(state)` returns the fragment any page
chrome can carry: empty while the mode is off; while on, a
`role="status"` block stating in words that the instance is
read-only for maintenance, the reason, and the expected return —
never colour-only, every operator value escaped through S-010.
`render_maintenance_page(state)` is the standalone page stating the
same facts whole, including who set the mode.

## What the battery proves

Pure judgements (off / reads / non-admin push refused with the
message / admin push allowed); service law (admin-only enable and
disable, reason + expected return required, state persists,
audit rows land, schema 139 and taxonomy 138 unchanged); banner
(empty off, facts on, operator markup escaped); real HTTP door
(push refused with reason + return, reads answer, admin owner
retains the push door, off behaves as before); real SSH door (push
refused before the pack runner, reads run, admin retains access);
the S-089 gate plug-in (refuses non-admin, allows admin).
