# Linux service (S-412) -- services parity

Roadmap S-412: Linux services parity -- the systemd
units (S-348) re-verified as one of three equal citizens;
no feature exists on Linux that the service model
forbids elsewhere.

The definition is code: `samverk/linux_service.py`
(`build_service_spec` + the unit and command renderers +
the parity table + the walk steps below, kept from
drifting apart by the battery). The unit files are data
in the repo at `deploy/systemd/`, shipped by S-348; this
slice's battery proves the shipped files carry exactly
the directives the module renders for the standing spec,
so the seam describes the units that already ship.
`tools/run_linux_service.py` prints the whole rendered
picture for any spec. No Docker, ever (standing law).
`docs/SYSTEMD_UNITS.md` remains S-348's operator guide
to the units themselves; this page is the parity record
and the install walk to Part XVIII's standard -- every
step named, every step's failure mode named, in the
manner of S-349's install walk, as S-410 and S-411 kept
it for their citizens.

## The service

| Fact | Value |
|---|---|
| Unit / file | `samverk-server.service` / `/etc/systemd/system/samverk-server.service` (root-owned, 0644) |
| Runs | the one server of S-345's run model: web, API, Git HTTP, LFS HTTP, entered by `/usr/bin/python3 -m samverk serve --config /etc/samverk/samverk.ini` |
| Type / start | `Type=simple`; `WantedBy=multi-user.target` -- starts at boot, before any login, once enabled; installation itself enables nothing -- `install.sh` enables only on the operator's `--enable` |
| Account | `samverk` -- a dedicated system user and group (shell `nologin`), created by the install script: the server never runs as root, and the account can write only the data root |
| Restart | `Restart=on-failure` with `RestartSec=5s` -- a clean stop stays stopped. The other citizens declare 60 s (SCM restart/60000; launchd ThrottleInterval 60): the delay is a declared mechanism difference, recorded in the parity table, not a capability difference |
| Default data root | `/var/lib/samverk` -- the machine-wide root, owned by the service user (mode 0750, `UMask=0027`) |
| Config | `/etc/samverk/samverk.ini` -- S-346's one config file, in the FHS config place; the other citizens keep the same one file inside their data root (mechanism, not feature) |
| Logging | the journal, and nowhere else: `StandardOutput=journal`, `StandardError=journal`, `SyslogIdentifier` per unit; read with `journalctl -u samverk-server`. The server's own log redaction (S-018) is installed inside the process before it serves |
| Hardening | the S-348 baseline on every unit: `ProtectSystem=strict` with only the data root writable, empty capability bounding set, kernel/control-group/clock/hostname protections, `PrivateDevices`, `ProtectProc=invisible`, per-unit `RestrictAddressFamilies` (the digest worker, which sends nothing, is `AF_UNIX` only). `MemoryDenyWriteExecute` is deliberately NOT set, for S-348's recorded reason |

The periodic workers are not daemons, on Linux exactly
as on the other citizens: S-348 ships them as
`Type=oneshot` units plus timers, and the timers carry
the cadence -- `samverk-webhook-worker.timer` every
minute (`OnUnitActiveSec=1min`) and
`samverk-digest-worker.timer` Monday 06:00
(`OnCalendar=Mon 06:00`, `Persistent=true`).
`worker_commands` renders every worker's one-shot
command line from the topology (webhook delivery,
weekly digest, artifact expiry -- real module entries
with this spec's database and data root substituted).
Mirror-sync renders **no** command and ships **no**
unit: it has no standalone CLI yet (its scheduler tick
is an in-process seam, S-345), and a fabricated command
would be a false claim, not a convenience. Git over SSH
is likewise not part of this service: as on every OS it
arrives through the host's sshd as a forced command
(S-345's external door), never through a Samverk
listener.

## The parity table

Every capability the service model promises, and the
native mechanism each citizen uses (the same table as
`PARITY_MATRIX` in `samverk/linux_service.py`, pinned
together by the battery). Mechanisms differ; the
capability set must not -- a capability only one
citizen had would be a parity defect.

| Capability | Linux (systemd) | Windows (SCM, S-410) | macOS (launchd, S-411) |
|---|---|---|---|
| one_server_process | samverk-server.service, Type=simple, runs the one S-345 server entry | the Samverk SCM service runs the one S-345 server entry via the service host | org.samverk.server runs the one S-345 server entry directly under launchd |
| dedicated_service_account | system user/group samverk (nologin), created by the install script | virtual service account NT SERVICE\Samverk | dedicated service user _samverk |
| starts_at_boot | WantedBy=multi-user.target once enabled | SCM start mode auto once registered and started by the operator | system LaunchDaemon, RunAtLoad once bootstrapped by the operator |
| restart_on_failure | Restart=on-failure, RestartSec=5s (S-348) | SCM failure actions restart/60000 x3, counter resets after 86400 s | KeepAlive on unsuccessful exit, ThrottleInterval 60 |
| periodic_workers_not_daemons | workers are Type=oneshot units; timers carry the cadence | workers are one-shot command lines for the operator's Task Scheduler entries | workers are one-shot launchd jobs; schedule keys carry the cadence |
| webhook_every_minute | samverk-webhook-worker.timer OnUnitActiveSec=1min | worker command rendered for a 1-minute Task Scheduler entry | org.samverk.webhook-delivery StartInterval 60 |
| digest_monday_0600 | samverk-digest-worker.timer OnCalendar=Mon 06:00, Persistent=true | worker command rendered for a Monday 06:00 Task Scheduler entry | org.samverk.weekly-digest StartCalendarInterval Mon 06:00 |
| install_registers_without_starting | install.sh installs + verifies, enables nothing without --enable | the install script registers, starts nothing without -Start | install.sh copies + lints, bootstraps nothing without --load |
| start_only_on_operator_word | systemctl enable --now, via install.sh --enable or by hand | sc.exe start, via the install script -Start or by hand | launchctl bootstrap, via install.sh --load or by hand |
| uninstall_keeps_instance_data | uninstall.sh (S-412) disables + removes units, keeps data root and config | the uninstall script deletes the service registration, keeps the data root | uninstall.sh boots out + removes plists, keeps the data root |
| health_answer_defines_installed | walk step 8: systemctl shows active and GET /healthz answers 200, or it is not installed | walk step 8: sc query shows RUNNING and GET /healthz answers 200, or it is not installed | walk step 8: launchctl print shows running and GET /healthz answers 200, or it is not installed |
| native_system_logging | the journal: StandardOutput=journal with SyslogIdentifier per unit | the service host's child inherits the service's stdout/stderr, routed by the operator (Event Log / file) | log files inside the data root, named in the plist (launchd has no journal) |
| one_config_file_for_all_roles | /etc/samverk/samverk.ini (S-346's one file, in the FHS config place) | samverk.ini inside the data root (S-346's one file) | samverk.ini inside the data root (S-346's one file) |
| machine_wide_data_root | /var/lib/samverk | C:\ProgramData\Samverk | /Library/Application Support/Samverk |
| first_admin_before_first_start | walk step 5: S-349's install walk stands before the units are enabled | walk step 5: S-349's install walk stands before the service is registered | walk step 5: S-349's install walk stands before the daemon is loaded |
| ssh_via_host_door_not_service | the host sshd runs samverk.ssh_serve as a forced command; no unit listens for SSH | the host's SSH door runs the forced command; the service never listens for SSH | the host's SSH door runs the forced command; the daemon never listens for SSH |
| no_fabricated_worker_command | mirror-sync renders no command and ships no unit (no standalone CLI exists) | mirror-sync renders no worker command (no standalone CLI exists) | mirror-sync renders no command and ships no plist (no standalone CLI exists) |
| native_install_no_container_no_emulation | systemd units + POSIX sh install; specs routing through Docker paths are refused | sc.exe + stdlib service host; Docker/WSL paths are refused | launchctl + plistlib (stdlib); Docker paths are refused |
| least_privilege_sandbox | systemd hardening baseline on every unit (ProtectSystem=strict, only the data root writable, empty capability set) | the virtual account can write only the data root (the walk's icacls grant) | the service user owns only the data root (the walk's chown step) |

Parity defect found and fixed by this slice: the Linux
citizen had no uninstall road -- both other citizens
ship an uninstall that removes the registration and
keeps the instance data, and `deploy/systemd/` had
none. `deploy/systemd/uninstall.sh` now ships (see
Uninstall, below), and the matrix's
uninstall_keeps_instance_data row is true for Linux
because of it.

## The install walk

One documented pass, in order. Steps 1-8 are the
`INSTALL_WALK_STEPS` of `samverk/linux_service.py`; each
names its failure mode in the guide's own token, as Part
XVIII requires.

### 1. root_shell -- A root shell (sudo)
Work from an administrator account; the install script refuses to run without root (`id -u` must be 0 under sudo). Creating the system user, writing /etc/systemd/system and enabling units are root acts by Linux's own law.
Failure mode: not_root: install answers 'Permission denied' in /etc/systemd/system, or systemctl answers 'Access denied'.
Remedy: Re-run under `sudo`; service registration is an administrator act on Linux as on every OS Samverk ships a service for.

### 2. python_runtime -- Python 3.11 or newer, natively installed
Run `which python3` and note the absolute path; the shipped units name /usr/bin/python3. Confirm `python3 --version` is 3.11+.
Failure mode: python_missing: no python3 on PATH, or a version older than 3.11.
Remedy: Install Python 3.11+ with the distribution's own package manager -- a native install, never through Docker (the spec refuses those paths) -- then re-check `which python3`.

### 3. package_installed -- The samverk package imports under that interpreter
From the checkout: `python3 -m pip install .` then `python3 -c "import samverk"`. The one admitted dependency (cryptography) installs with it.
Failure mode: package_not_importable: ModuleNotFoundError for samverk or cryptography under the very interpreter the units will run.
Remedy: Install into the same interpreter the units name (never a second one); the service runs that interpreter or nothing.

### 4. data_root_and_config -- Data root and the one config file
Create the data root (default /var/lib/samverk, owned by the service user) and place samverk.ini in /etc/samverk with data_root pointing at the same root (S-346/S-347); the install script does both and never overwrites a standing config.
Failure mode: data_root_unwritable: the directory cannot be created, or the config resolves to a different root than the walk was given.
Remedy: Fix the path in samverk.ini so config and spec name one root; never let the service open a different database than the walk initialised.

### 5. first_admin_walk -- First admin, by S-349's install walk
Run the S-349 install walk against the data root (docs/INSTALL_WALK.md) so the database, instance key, and first admin stand before the units are ever enabled.
Failure mode: first_admin_refused: the walk stops at a named step -- its own guide names each failure mode and remedy; the service is not enabled over a half-walked instance.
Remedy: Remedy the walk's named step and re-run the walk (it is idempotent); only then install the units.

### 6. service_user_rights -- The service user can write the data root
The install script creates the dedicated system user samverk (nologin) if it is absent and gives it ownership of the data root only: `install -d -o samverk -g samverk -m 0750 /var/lib/samverk`.
Failure mode: service_user_or_access: the server exits at once and the journal shows PermissionError, or systemctl shows a non-zero exit with the database unwritable.
Remedy: Re-run the ownership step for exactly the data root and confirm no other directory was opened up; the account needs nothing else.

### 7. unit_install -- Install the units (installs, enables nothing)
Run deploy/systemd/install.sh as root: it checks root, creates the service user, installs the five units into /etc/systemd/system, writes the example config only if none exists, runs systemctl daemon-reload, and verifies the installed service units with systemd-analyze verify. Nothing is enabled or started.
Failure mode: unit_install_failed: systemd-analyze verify rejects a unit (it is not the directives this module renders), or the copy into /etc/systemd/system is refused.
Remedy: For a verify failure, restore the shipped unit from the checkout rather than editing the installed copy -- this module is the one seam; for a refused copy, return to the root_shell step.

### 8. enable_and_health -- Enable, and the health answer
`sudo sh deploy/systemd/install.sh --enable` (or `systemctl enable --now samverk-server.service samverk-webhook-worker.timer samverk-digest-worker.timer` by hand), then `systemctl status samverk-server` shows active and GET /healthz on the configured host/port answers 200 with the Samverk payload.
Failure mode: service_enable_failed: enable answers an error, status shows the unit failed or in a restart loop, or /healthz does not answer -- the port may be taken.
Remedy: Read the unit's journal (`journalctl -u samverk-server`), free the named port or choose another in samverk.ini, and enable again; a service that is not answering /healthz is not installed, whatever systemctl says.
## Uninstall

`sudo sh deploy/systemd/uninstall.sh` disables and
stops the server and both worker timers, removes the
five unit files from /etc/systemd/system, and reloads
systemd. The data root and its instance are NOT
deleted, and neither is the config in /etc/samverk --
the whole instance, its database, keys, and
repositories, stands untouched; S-341's whole-instance
export is the data's road out, exactly as on Windows
and macOS. This script is the parity defect this slice
found and fixed: before S-412 the Linux citizen had no
uninstall road at all.

## Honest remainder -- what is NOT PROVEN

What is proven: the spec, the validation refusals, the
rendered units' directive identity with the shipped
S-348 files, the systemctl command lines and scripts,
the parity table's equal capability sets, and
`systemd-analyze verify` clean over the shipped units
on this host (S-348's battery, re-run as a neighbour
of this slice's battery). What is NOT PROVEN: a real
install, enable, boot, restart, or health answer on a
dedicated host -- no such run was executed in this
slice; the keeper host is shared, and no permanent
service may be stood up on it without Volmarr's word
for that specific service. The Debian/Pi leg S-348
already recorded also stands: the units use no
Ubuntu-specific directive and the scripts are plain
POSIX sh, but that is an expectation, not a proof.
The Linux cells of the support matrix (S-405) flip to
PROVEN only on counted real-host runs; S-416's gate
owns that claim. No migration and no new taxonomy
event: the schema stands at 140 and the taxonomy
at 142.
