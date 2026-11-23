# macOS service (S-411)

Roadmap S-411: Samverk installs and runs under launchd, with
the install walk documented to the same standard -- Part
XVIII's standard, as S-410's Windows slice kept it: every
step named, every step's failure mode named, in the manner
of S-349's install walk.

The definition is code: `samverk/macos_service.py`
(`build_service_spec` + the plist and command renderers +
the walk steps below, kept from drifting apart by the
battery). launchd supervises the server process directly,
so there is no service host: the daemon's
ProgramArguments are S-345's server entry itself, where
the SCM on Windows needed `windows_service_host.py` to
speak its protocol. The plist files are data in the repo
at `deploy/launchd/`, rendered by the module with
`plistlib` and shipped byte-identical to its rendering for
the standing spec. `tools/run_macos_service.py` prints the
whole rendered picture for any spec. No Docker, ever
(standing law).

## The daemon

| Fact | Value |
|---|---|
| Label / plist | `org.samverk.server` / `/Library/LaunchDaemons/org.samverk.server.plist` (root:wheel, 0644) |
| Runs | the one server of S-345's run model: web, API, Git HTTP, LFS HTTP, entered by `<python3> -m samverk serve --config <data_root>/samverk.ini` |
| Domain | `system` -- a LaunchDaemon, started at boot before any login; never a per-user LaunchAgent |
| Account | `_samverk` -- a dedicated service user (macOS's underscore convention for service accounts, e.g. `_www`): the daemon never runs as root, and the account can write only the data root (the walk's chown step) |
| Start | `RunAtLoad` once bootstrapped; registration itself loads nothing -- `install.sh` bootstraps only on the operator's `--load` |
| Restart | `KeepAlive` on unsuccessful exit (a clean stop stays stopped) with `ThrottleInterval` 60 -- the launchd analogue of S-410's SCM restart-after-60 s law |
| Default data root | `/Library/Application Support/Samverk` -- the machine-wide analogue of the platform seam's per-user macOS default (`~/Library/Application Support/Samverk`); a system daemon has no operator home for the per-user root to mean anything under |
| Logging | launchd has no journal: the daemon's stdout/stderr go to `logs/samverk-server.out.log` / `.err.log` inside the data root, named in the plist; the server's own log redaction (S-018) is installed inside the process before it serves -- no second log law is invented here |

The periodic workers are not daemons, on macOS exactly as
on Linux: S-348 ships them as oneshot units plus timers,
and here `deploy/launchd/` ships the same worker set as
launchd jobs whose schedule keys carry the cadence --
`org.samverk.webhook-delivery` (`StartInterval` 60, the
webhook timer's every-minute tick) and
`org.samverk.weekly-digest` (`StartCalendarInterval`
Monday 06:00, the digest timer's slot). `worker_commands`
renders every worker's one-shot command line from the
topology (webhook delivery, weekly digest, artifact
expiry -- real module entries with this spec's database
and data root substituted). Mirror-sync renders **no**
command and ships **no** plist: it has no standalone CLI
yet (its scheduler tick is an in-process seam, S-345),
and a fabricated command would be a false claim, not a
convenience. Artifact-expiry likewise ships no plist in
this slice -- S-348's shipped set is kept exactly -- and
its rendered command line is the operator's road to
scheduling it. Git over SSH is likewise not part of this
daemon: as on every OS it arrives through the host's SSH
door as a forced command (S-345's external door), never
through a Samverk listener.

## The install walk

One documented pass, in order. Steps 1-8 are the
`INSTALL_WALK_STEPS` of `samverk/macos_service.py`; each
names its failure mode in the guide's own token, as Part
XVIII requires.

### 1. root_shell -- A root shell (sudo)
Work from an administrator account; the generated install script refuses to run without root (`id -u` must be 0 under sudo). Copying into /Library/LaunchDaemons and bootstrapping the system domain are root acts by macOS's own law.
Failure mode: not_root: install answers 'Permission denied' in /Library/LaunchDaemons, or launchctl bootstrap answers 'Permission denied' for the system domain.
Remedy: Re-run under `sudo` from an administrator account; service registration is an administrator act on macOS as on every OS Samverk ships a service for.

### 2. python_runtime -- Python 3.11 or newer, natively installed
Run `which python3` and note the absolute path; it becomes the spec's python_exe. Confirm `python3 --version` is 3.11+. The /usr/bin/python3 that ships with the Xcode Command Line Tools is a real interpreter once the tools are installed; a Homebrew or python.org interpreter is equally native.
Failure mode: python_missing: no python3 on PATH, the Command Line Tools stub that only pops the install dialogue, or a version older than 3.11.
Remedy: Install the Xcode Command Line Tools (`xcode-select --install`) or Python 3.11+ from python.org or Homebrew -- a native macOS install, never through Docker (the spec refuses those paths) -- then re-check `which python3`.

### 3. package_installed -- The samverk package imports under that interpreter
From the checkout: `python3 -m pip install .` then `python3 -c "import samverk"`. The one admitted dependency (cryptography) installs with it.
Failure mode: package_not_importable: ModuleNotFoundError for samverk or cryptography under the very interpreter the daemon will run.
Remedy: Install into the same interpreter named in the spec (never a second one); the daemon runs that interpreter or nothing.

### 4. data_root_and_config -- Data root and the one config file
Create the data root (default /Library/Application Support/Samverk) with its logs directory, and place samverk.ini in it with data_root pointing at the same root (S-346/S-347).
Failure mode: data_root_unwritable: the directory cannot be created, or the config resolves to a different root than the walk was given.
Remedy: Fix the path in samverk.ini so config and spec name one root; never let the daemon open a different database than the walk initialised.

### 5. first_admin_walk -- First admin, by S-349's install walk
Run the S-349 install walk against the data root (docs/INSTALL_WALK.md) so the database, instance key, and first admin stand before the daemon ever loads.
Failure mode: first_admin_refused: the walk stops at a named step -- its own guide names each failure mode and remedy; the daemon is not loaded over a half-walked instance.
Remedy: Remedy the walk's named step and re-run the walk (it is idempotent); only then install the plists.

### 6. service_user_rights -- The service user can write the data root
Create the dedicated service user if it is absent (System Settings > Users & Groups, or `sysadminctl`), named _samverk, then give it ownership of the data root only: `chown -R _samverk '<data_root>'` with the walk's chosen root.
Failure mode: service_user_or_access: the daemon exits at once and its stderr log shows PermissionError, or launchctl print shows a non-zero last exit code with the database unwritable.
Remedy: Re-run the chown for exactly the data root and confirm no other directory was opened up; the account needs nothing else.

### 7. plist_install -- Install the plists (installs, loads nothing)
Run deploy/launchd/install.sh as root: it checks root, verifies each shipped plist parses as data, copies the three plists into /Library/LaunchDaemons (root:wheel, 0644), and lints the installed copies with plutil. Nothing is bootstrapped.
Failure mode: plist_install_failed: plutil -lint rejects a plist (it is not the bytes render_plist produced), or the copy into /Library/LaunchDaemons is refused.
Remedy: For a lint failure, restore the shipped plist from the checkout rather than editing the installed copy -- the module is the one seam; for a refused copy, return to the root_shell step.

### 8. load_and_health -- Load, and the health answer
`sudo sh deploy/launchd/install.sh --load` (or `launchctl bootstrap system /Library/LaunchDaemons/org.samverk.server.plist` by hand), then `launchctl print system/org.samverk.server` shows state = running and GET /healthz on the configured host/port answers 200 with the Samverk payload.
Failure mode: daemon_load_failed: bootstrap answers an error (a job of the same label already loaded), print shows the job not running or in a respawn loop, or /healthz does not answer -- the port may be taken.
Remedy: For an already-loaded job, bootout first rather than loading a second; read the daemon's stderr log inside the data root, free the named port or choose another in samverk.ini, and load again; a daemon that is not answering /healthz is not installed, whatever launchctl says.

## Uninstall

`sudo sh deploy/launchd/uninstall.sh` boots the three jobs
out of the system domain and removes their plist files.
The data root and its instance are NOT deleted -- the
whole instance, its database, keys, and repositories,
stands untouched; S-341's whole-instance export is the
data's road out, exactly as on Linux and Windows.

## Honest remainder -- NOT PROVEN on macOS

This slice was built and tested on Linux. What is proven:
the spec, the validation refusals, the rendered plists,
launchctl command lines and scripts, and the shipped
plist files' identity with the rendered ones, all as data
and pure functions, counted by
`tests/test_macos_service.py`. What is NOT PROVEN: a real
macOS host install, a launchd bootstrap, a KeepAlive
restart, or a health answer -- no Mac ran any of it. The
macOS cells of the support matrix (S-405) stay NOT PROVEN
until a counted run on a real Mac flips them; S-416's
gate owns that claim. No migration and no new taxonomy
event: the schema stands at 140 and the taxonomy at 142.
