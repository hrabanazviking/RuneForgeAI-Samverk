# Install walk (S-349)

Roadmap S-349: from bare machine to first admin in one
documented pass, timed; every step's failure mode named
in the guide.

This is the one documented pass. It is implemented as
code in `samverk/install_walk.py` (`run_install_walk` +
`render_walk_report`), so every numbered step below is
a check that actually runs, in this order, and a failed
step stops the walk — later steps are reported
`skipped`, never passed. Steps that cannot be automated
are written below as **operator steps**, plainly, with
their own failure modes; nothing operator-only is
dressed as automated.

## Run it

```sh
python3 - <<'EOF'
from pathlib import Path
from samverk.install_walk import render_walk_report, run_install_walk
report = run_install_walk(Path('.'), Path('/path/to/data-root'),
                          'yourname', 'a-long-enough-password')
print(render_walk_report(report), end='')
raise SystemExit(0 if report.ok else 1)
EOF
```

Choose the admin username and password yourself; the
password is never stored anywhere except as the
account's scrypt hash, and it never appears in the
report. Re-running the walk on an installed instance is
safe: it verifies every step, reports the standing
admin, and creates nothing.

## Timed run (measured, not estimated)

Measured on purplelongship (the build machine, under
parallel campaign load) on 2026-11-22, running the
walk's automated steps from the team-07 checkout into
a scratch prefix (`hidden_files/s349-scratch/instance`,
log `hidden_files/s349-timed-walk.log`):

- **Whole pass: 7.049 s** (monotonic, inside the walk;
  7.075 s wall clock around the process call).
- Per step: python_version 0.000 s, dependency 0.001 s,
  checkout_layout 0.000 s, data_root 0.000 s,
  config 0.000 s, database_init 6.267 s,
  instance_key 0.001 s, first_admin 0.231 s,
  server_health 0.549 s.
- database_init dominates because a fresh database
  runs all 139 migrations; on an idle machine expect
  the pass to be faster. The honest figure for *this*
  machine at *this* load is the one above.

## The nine automated steps

### 1. python_version — Python 3.11 or newer is present
Check: the running interpreter's version against the
3.11 floor (pyproject's `requires-python`).
Failure mode: python_too_old / python_missing: the interpreter is older than 3.11, or no python3 is on PATH at all, so the package cannot even be imported (it uses 3.11 syntax and stdlib).
Remedy: Install Python 3.11 or newer from the OS package manager or python.org, then re-run the walk; `python3 --version` must agree before anything else is worth trying.

### 2. dependency — The one dependency (cryptography) imports
Check: `cryptography` imports and reports its version
(the pinned 46.0.5 line).
Failure mode: dependency_missing / dependency_broken: the cryptography package is not installed for this interpreter, or imports but is not the pinned 46.0.5 line, so token and secret code paths would fail later, at a worse moment.
Remedy: Install the pinned dependency into the same interpreter that will run Samverk: `python3 -m pip install cryptography==46.0.5` (or the OS package), then re-run; never run two interpreters and expect one environment.

### 3. checkout_layout — The checkout is complete
Check: pyproject.toml and the core modules
(`samverk/__init__.py`, `cli.py`, `db.py`, `server.py`)
stand in the source root.
Failure mode: checkout_incomplete: pyproject.toml or a core samverk module is missing -- a partial clone, a zip that dropped files, or the walk pointed at the wrong directory.
Remedy: Point the walk at the root of a complete checkout (the directory holding pyproject.toml), or re-clone / re-extract it whole; do not paper over a missing module by copying files piecemeal.

### 4. data_root — The data root can be created and written
Check: the data root is created if missing and a probe
file can be written and removed inside it.
Failure mode: data_root_unwritable: the data root cannot be created or a probe file cannot be written -- wrong ownership, a read-only mount, or a full disk.
Remedy: Choose a data root the operator's account owns (or fix ownership/permissions on the named path), free disk space if the disk is full, then re-run; the walk never falls back to a different root silently.

### 5. config — Configuration loads and points at the chosen data root
Check: `load_config` with the walk's data root; the
loaded configuration must resolve to that same root.
Failure mode: config_invalid: the INI file does not parse, a port is not a number, or the loaded configuration resolves to a different data root than the walk was given -- the instance would open a different database than the one the walk initialises.
Remedy: Fix the named key in samverk.ini (or drop the file to take defaults), and make SAMVERK_DATA_ROOT / the ini data_root agree with the walk's data root; then re-run.

### 6. database_init — The database initialises at the current schema
Check: `db.init_db` opens `<data_root>/samverk.db` and
`schema_version` equals the current schema, **139**.
Failure mode: database_init_failed / schema_mismatch: the database file cannot be opened (corrupt file, a directory in its place, no write permission) or migrations stop short of the current schema version.
Remedy: If the path holds a corrupt or foreign file, move it aside and let the walk create a fresh database (an existing real database is migrated in place, never recreated); fix permissions if the file cannot be written; a migration error names its version -- keep the error and the database file for diagnosis.

### 7. instance_key — The instance signing key exists with private permissions
Check: `ensure_instance_key(data_root, "signing")`
returns the current key (minted mode-600 if missing).
Failure mode: instance_key_failed: the key cannot be minted (keys directory unwritable) or an existing key file is readable by group/other users, which the custody law refuses to load.
Remedy: Fix ownership on <data_root>/keys, and `chmod 600` any key file the check names; never delete a standing key to make the error go away -- rotation is `samverk keys rotate`.

### 8. first_admin — A first administrator exists
Check: an admin stands when the step ends. On an empty
instance the walk creates the account through the full
S-025 registration law and promotes it in the same
transaction (witnessed `admin.user.role_change`, from
member to admin, via install_walk; registration keeps
its `auth.signup.success`). If an admin already
stands, the step passes and creates nothing.
Failure mode: first_admin_refused / accounts_without_admin: the username, email, or password fails the registration law (the refusal names the rule), an admin already stands (not a failure -- the walk creates nothing), or accounts exist with no admin among them, which the walk refuses to repair by minting a new admin beside them.
Remedy: For a law refusal, choose a username/password that meets the stated rule and re-run. If an admin already stands, sign in as that admin. If accounts stand with no admin, follow the recovery operator step in docs/INSTALL_WALK.md -- it is a deliberate, witnessed act, never an install re-run.

### 9. server_health — The server answers its health route
Check: the server is built for the walk's data root on
an ephemeral loopback port, `GET /healthz` must answer
200 with the samverk health payload, and the server is
shut down again — the check leaves nothing running.
Failure mode: server_health_failed: the server cannot bind (port already in use), or /healthz does not answer 200 with the samverk health payload -- the instance would be installed but not serving.
Remedy: Free the named port or choose another, confirm nothing else answers on it, and re-run; if the payload is wrong, the thing answering is not Samverk -- do not declare the install done.

## Operator steps (not automated, by design)

- **Run the instance.** After the walk:
  `samverk serve --config <data_root>/samverk.ini`
  (or `SAMVERK_DATA_ROOT=<data_root> samverk serve`).
  The walk deliberately installs **no service, timer,
  or autostart**. Failure mode: the process dies with
  the terminal / the port is taken. Remedy: run it
  under your own service manager by your own decision,
  on a free port.
- **Choose the real data root.** The scratch prefix in
  the timed run is for measurement only. Failure mode:
  pointing production at a scratch or temp directory
  and losing the instance when it is cleaned. Remedy:
  pick a durable, owned directory first, then walk
  against it.
- **Recovery: accounts exist, no admin.** The walk
  refuses this on purpose. The operator road, done
  deliberately at the database with the server
  stopped: register nothing new; promote the chosen
  existing account with
  `UPDATE users SET is_admin = 1 WHERE username_lower = '<name>';`
  through `db.connect`, then restart and sign in.
  Failure mode: promoting the wrong account. Remedy:
  read the users table first and name the account
  exactly; this act is yours, witnessed by your own
  hand, never by an install re-run.
- **TLS and exposure.** The walk binds loopback for
  its check. Serving beyond loopback is S-015's law:
  configure `tls_cert_file` + `tls_key_file`, or arm
  the audit-logged plaintext override knowingly.
  Failure mode: plaintext beyond loopback refused at
  serve time. Remedy: that refusal is the law working;
  configure TLS.
- **Backups.** Nothing in the walk backs anything up.
  Failure mode: a perfect install, one disk failure,
  no instance. Remedy: copy the data root (database +
  `keys/`) into your backup habit from day one.

## Deliberate non-changes

No migration and no new audit event: the schema
stands at 139 and the taxonomy stands at 138. The
first-admin promotion rides the standing
`admin.user.role_change` event; the database, key
custody, config, and health seams are all reused.
