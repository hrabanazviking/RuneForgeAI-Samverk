# Windows service (S-410)

Roadmap S-410: Samverk installs and runs as a native Windows
service (No Docker, no WSL requirement), with the install walk
documented to Part XVIII's standard -- every step named, every
step's failure mode named, in the manner of S-349's install walk.

The definition is code: `samverk/windows_service.py`
(`build_service_spec` + the command renderers + the walk steps
below, kept from drifting apart by the battery). The program the
Service Control Manager launches is
`samverk/windows_service_host.py`, a stdlib-only service host
(`ctypes` against advapi32/kernel32 -- no pywin32, no new
dependency, so S-407's register is untouched) that runs the real
server as its supervised child. `tools/run_windows_service.py`
prints the whole rendered picture for any spec.

## The service

| Fact | Value |
|---|---|
| Name / display name | `Samverk` |
| Runs | the one server of S-345's run model: web, API, Git HTTP, LFS HTTP, entered by `-m samverk serve --config <data_root>\samverk.ini` |
| binPath | `"<python.exe>" -m samverk.windows_service_host --config <config> --data-root <data_root>` |
| Account | `NT SERVICE\Samverk` -- the virtual service account Windows provisions at creation: no password exists to store, rotate, or leak |
| Start mode | `auto` (starts at boot, once registered; registration itself starts nothing) |
| Recovery | SCM failure actions `restart/60000/restart/60000/restart/60000`, counter resets after 86400 s; failure flag set so non-crash failures count too |
| Default data root | `C:\ProgramData\Samverk` -- the machine-wide analogue of S-348's `/var/lib/samverk`; a service account has no operator profile, so `%LOCALAPPDATA%` would name the wrong tree |
| Logging | the server's own log redaction (S-018) is installed inside the process before it serves; the host's child inherits the service's stdout/stderr, which the operator routes at install time (Event Log / file) -- no second log law is invented here |

The periodic workers are not services, on Windows exactly as on
Linux: S-348 ships them as oneshot units plus timers, and here
`worker_commands` renders their one-shot command lines
(webhook delivery, weekly digest, artifact expiry -- real module
entries from the run model, with this spec's database and data
root substituted) for the operator's own Task Scheduler entries.
Mirror-sync renders **no** command: it has no standalone CLI yet
(its scheduler tick is an in-process seam, S-345), and a
fabricated command would be a false claim, not a convenience.
Git over SSH is likewise not part of this service: as on every
OS it arrives through the host's SSH door as a forced command
(S-345's external door), never through a Samverk listener.

## The install walk

One documented pass, in order. Steps 1-8 are the
`INSTALL_WALK_STEPS` of `samverk/windows_service.py`; each names
its failure mode in the guide's own token, as Part XVIII
requires.

### 1. admin_shell -- An elevated shell
Open PowerShell or Windows Terminal as Administrator; the
generated script also refuses to run unelevated
(`#Requires -RunAsAdministrator`).
Failure mode: not_administrator: sc.exe answers 'Access is
denied' (error 5) or the script stops before its first command.
Remedy: Re-open the shell with 'Run as administrator' and
re-run; service registration is an administrator act by
Windows' own law.

### 2. python_runtime -- Python 3.11 or newer, natively installed
Run `where python` (or `py -0p`) and note the absolute
python.exe path; it becomes the spec's python_exe. Confirm
`python --version` is 3.11+.
Failure mode: python_missing: no python.exe on PATH, a
Microsoft Store stub that opens the Store instead of running,
or a version older than 3.11.
Remedy: Install Python 3.11+ from python.org as a native
Windows install (never through WSL or Docker -- the spec
refuses those paths), then re-check `where python`.

### 3. package_installed -- The samverk package imports under that interpreter
From the checkout: `python -m pip install .`, then
`python -c "import samverk"`. The one admitted dependency
(cryptography) installs with it.
Failure mode: package_not_importable: ModuleNotFoundError for
samverk or cryptography under the very interpreter the service
will run.
Remedy: Install into the same interpreter named in the spec
(never a second one); the service runs that interpreter or
nothing.

### 4. data_root_and_config -- Data root and the one config file
Create the data root (default `C:\ProgramData\Samverk`) and
place samverk.ini in it with data_root pointing at the same
root (S-346/S-347).
Failure mode: data_root_unwritable: the directory cannot be
created, or the config resolves to a different root than the
walk was given.
Remedy: Fix the path in samverk.ini so config and spec name
one root; never let the service open a different database than
the walk initialised.

### 5. first_admin_walk -- First admin, by S-349's install walk
Run the S-349 install walk against the data root
(docs/INSTALL_WALK.md) so the database, instance key, and
first admin stand before the service ever starts.
Failure mode: first_admin_refused: the walk stops at a named
step -- its own guide names each failure mode and remedy; the
service is not registered over a half-walked instance.
Remedy: Remedy the walk's named step and re-run the walk (it
is idempotent); only then register the service.

### 6. service_account_rights -- The virtual account can write the data root
Grant the service account modify rights on the data root only:
`icacls <data_root> /grant "NT SERVICE\Samverk:(OI)(CI)M"`
(the generated install script runs exactly this grant).
Failure mode: service_logon_or_access: start fails with error
1069 (logon) or the running service cannot write its database,
keys, or repositories.
Remedy: Re-run the icacls grant for exactly the data root and
confirm no other directory was opened up; the account needs
nothing else.

### 7. service_create -- Register the service (installs, starts nothing)
Render the spec (`tools/run_windows_service.py` shows it), then
run the generated install script (`render_install_script`): it
checks elevation, refuses a WSL environment
(`WSL_DISTRO_NAME` set means you are not in native Windows),
verifies the interpreter exists, creates the data root, applies
the step-6 grant, and runs the registration sequence:

```
sc.exe create Samverk binPath= "\"<python.exe>\" -m samverk.windows_service_host --config <config> --data-root <data_root>" DisplayName= Samverk start= auto
sc.exe description Samverk "Samverk sovereign version-control forge: web, API, Git HTTP and LFS HTTP (run model S-345)."
sc.exe config Samverk obj= "NT SERVICE\Samverk"
sc.exe failure Samverk reset= 86400 actions= restart/60000/restart/60000/restart/60000
sc.exe failureflag Samverk 1
```

Failure mode: service_create_failed: sc.exe exits non-zero --
a service of the same name already exists (error 1073), or
binPath names a missing file.
Remedy: For 1073, uninstall the standing registration first
(below) rather than creating a second; for a missing file,
correct python_exe in the spec and re-render.

### 8. start_and_health -- Start, and the health answer
`sc.exe start Samverk` (or re-run the install script with
`-Start`), then `sc.exe query Samverk` shows RUNNING and
`GET /healthz` on the configured host/port answers 200 with
the Samverk health payload (S-359).
Failure mode: service_start_failed: the service stops at once
(error 1067), query shows STOPPED, or /healthz does not
answer -- the port may be taken.
Remedy: Read the host's output, free the named port or choose
another in samverk.ini, and start again; a service that is not
answering /healthz is not installed, whatever sc says.

## Uninstall

The generated uninstall script runs `sc.exe stop Samverk` then
`sc.exe delete Samverk`. The data root is **not** deleted --
the instance's road out is S-341's whole-instance export, and
an uninstall that destroyed data would be a defect, not a
feature.

## Operator steps (not automated, by design)

- **Task Scheduler entries for the workers.** Create one task
  per rendered worker command, running as the same virtual
  account where the scheduler allows, on the cadences S-348's
  timers declare (webhook delivery every minute; digest weekly
  Mon 06:00; artifact expiry on the operator's cadence).
  Failure mode: a task running as the operator's account
  writes files the service account cannot read. Remedy: keep
  one account -- the service's -- for everything that touches
  the data root.
- **TLS and exposure.** The config's default bind is loopback.
  Serving beyond loopback is S-015's law, unchanged on
  Windows: configure `tls_cert_file` + `tls_key_file`, or arm
  the audit-logged plaintext override knowingly.
- **Backups.** Nothing in this walk backs anything up.
  Remedy: copy the data root (database + `keys/`) into your
  backup habit from day one, as on every OS.

## Proof and remainders (honest record, 2026-11-22)

- **Proven on Linux (this build machine):** the spec and its
  refusals (relative paths, POSIX paths, WSL UNC paths, Docker
  paths, non-.exe interpreters, renamed service / non-virtual
  account), the rendered sc.exe sequences (create never starts;
  uninstall stops before delete and never names the data
  root), the generated PowerShell scripts' content, the
  service host's child command, argument parsing, and
  off-Windows refusal, and this guide's pin against the walk
  steps in code -- battery `tests/test_windows_service.py`,
  counted in the slice record (docs/windows-service-s410.md).
- **NOT PROVEN on Windows:** everything that needs a real
  Windows host -- the sc.exe registration itself, the host's
  SCM conversation (StartServiceCtrlDispatcher and friends),
  service start, the virtual account's real rights, SCM
  recovery after a crash, and the /healthz answer from a
  running service. No Windows machine ran any of it, and this
  page does not claim otherwise. The support matrix's Windows
  service cell therefore stays NOT PROVEN; a counted run on a
  real Windows host is the only thing that flips it, at
  S-416's portability gate.
- **Deliberate non-changes:** no migration (schema stands at
  140) and no new taxonomy event (142 stand): a service
  registration is host state, not instance state. No new
  dependency: the host is stdlib `ctypes` only. README.md
  untouched.
