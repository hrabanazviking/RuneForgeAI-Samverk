# Systemd units (S-348)

Native systemd units for running Samverk on Linux -- Debian and
Ubuntu alike. No Docker, ever (standing law). The unit files are data
in the repo at `deploy/systemd/`; this page is the operator guide for
them. S-345's run model is what they implement: one server process
serves web, API and the transports' HTTP half, and background jobs are
separate worker processes under the same unit family.

## The units

| Unit | Type | Entry point (verified in the code) |
|---|---|---|
| `samverk-server.service` | `simple`, long-running | `python3 -m samverk serve --config /etc/samverk/samverk.ini` -- `samverk/__main__.py` -> `samverk/cli.py:main` (the `serve` subcommand) -> `samverk/server.py:serve` |
| `samverk-webhook-worker.service` | `oneshot` batch | `python3 -m samverk.webhook_delivery /var/lib/samverk/samverk.db /var/lib/samverk` -- `samverk/webhook_delivery.py:main` drains one due batch and exits |
| `samverk-webhook-worker.timer` | timer, every minute | starts the webhook worker; the recurrence lives here, not in the worker |
| `samverk-digest-worker.service` | `oneshot` batch | `python3 -m samverk.digest_job /var/lib/samverk/samverk.db /var/lib/samverk` -- `samverk/digest_job.py:main` composes the last completed week's digests and exits |
| `samverk-digest-worker.timer` | timer, Mon 06:00, persistent | starts the digest worker; catches up a run missed while off |

There is no long-running worker daemon in the code, so no unit pretends
there is one: the batch workers are honestly `Type=oneshot` and their
timers carry the cadence. The reference runner
(`samverk/reference_runner.py`) is a per-assignment program an operator
or a CI system invokes with one job; it is not a service and gets no
unit.

The database path in the worker commands is the server's own database:
`Config.db_path` is `<data_root>/samverk.db` (`samverk/config.py`), and
the shipped config sets `data_root = /var/lib/samverk`. The repos root
argument is the data root itself, the one tree of S-347.

## Identity, paths, configuration

- Dedicated system user and group `samverk` (created by the install
  script), shell `nologin`. Nothing runs as root.
- Data root `/var/lib/samverk` (`StateDirectory=samverk`, mode from
  `UMask=0027`), configuration `/etc/samverk/samverk.ini`
  (`ConfigurationDirectory=samverk` on the server).
- `deploy/systemd/samverk.ini.example` is the starting config: loopback
  bind on port 8737. Before binding beyond loopback, terminate TLS (or
  set `tls_cert_file`/`tls_key_file`) -- the server itself refuses
  non-loopback plaintext without an audited override (S-015), and the
  unit does not weaken that law.
- The code must be importable by the system python3 as the `samverk`
  package (e.g. installed with `pip install .` from the repo, or the
  repo placed on the service's path by the operator's packaging). The
  units name `/usr/bin/python3 -m samverk ...`, never a shell.

## Hardening

Every service unit sets the same baseline, tightened per unit where
its work allows: `NoNewPrivileges`, `PrivateTmp`,
`ProtectSystem=strict` with only `/var/lib/samverk` writable
(`ReadWritePaths`), `ProtectHome`, kernel/control-group/clock/hostname
protections, `RestrictSUIDSGID`, `LockPersonality`,
`RestrictRealtime`, `PrivateDevices`, `ProtectProc=invisible` with
`ProcSubset=pid`, an empty capability bounding set, and
`RestrictAddressFamilies` -- `AF_UNIX AF_INET AF_INET6` for the server
and the webhook worker (it makes outbound deliveries), `AF_UNIX` only
for the digest worker (composition only; no mail leaves that process).
`MemoryDenyWriteExecute` is deliberately NOT set: CPython extension
modules in the one admitted dependency (`cryptography`) are not
guaranteed W^X-clean on every architecture Samverk targets (x86-64 and
ARM/Pi), and a hardening flag that can kill the server on one target
is worse than its absence; the rest of the sandbox above still holds.

## Journal logging

All units log to the journal and nowhere else:
`StandardOutput=journal`, `StandardError=journal`, with
`SyslogIdentifier` naming each unit (`samverk-server`,
`samverk-webhook-worker`, `samverk-digest-worker`). Read them with
`journalctl -u samverk-server` (etc.). The server's own log redaction
(S-018) is installed inside the process before it serves, so journal
lines pass through it first.

## Install

```sh
sudo sh deploy/systemd/install.sh          # install + verify, do not enable
sudo sh deploy/systemd/install.sh --enable # install, verify, enable + start
```

The script creates the `samverk` user if missing, installs the units
into `/etc/systemd/system/`, writes `/etc/samverk/samverk.ini` from the
example only if none exists, runs `systemctl daemon-reload`, and runs
`systemd-analyze verify` over the installed service units. Without
`--enable` nothing is enabled or started. `deploy/systemd/verify.sh`
runs the same verify over the repo copies without installing anything.

## Proof and remainders (honest record, 2026-11-22)

- Ubuntu (laptop, purplelongship, Ubuntu 26.04, systemd 259):
  `systemd-analyze verify` over all three service units -- clean
  (log: `hidden_files/s348-verify.log`). The content battery
  `tests/test_systemd_units.py` proves the directives, the hardening
  set, journal logging, and that every named entry point exists in
  the code.
- Debian (Pi): NOT tested from this seat -- the Pi leg is a recorded
  remainder for the coordinator (see CAMPAIGN_STATE.md, S-348 entry).
  The units use no Ubuntu-specific directive, and the install script
  is plain POSIX sh over `useradd`/`install`/`systemctl`, but that is
  an expectation, not a proof; the slice does not claim it.
- No migration (schema 139 stands) and no new taxonomy event
  (138 stand): units are deployment data, not instance state.
