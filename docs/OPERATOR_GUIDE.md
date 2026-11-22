# Operator guide (S-397)

The one starting point for the person who runs a Samverk
instance. The component documents hold the depth; this
guide holds the order a fresh operator meets things in,
and every procedure named here was walked against a live
instance by S-397 (docs/documentation-completeness-s397.md).

## 1. Install and first boot

Follow docs/INSTALL_WALK.md (S-349): nine automated steps
from bare checkout to first admin, each with its failure
mode and remedy named. The walk installs no service, timer
or autostart — running the instance is your decision.

## 2. Run it

Start the one server process with `samverk serve`
(optionally `--config <data_root>/samverk.ini`). One
process serves web, API, git smart HTTP and the LFS API;
background work (webhook delivery, weekly digest,
artifact expiry, mirror sync) runs as separate worker
processes in the same unit family — the full topology is
docs/RUN_MODEL.md (S-345), and the native unit files are
docs/SYSTEMD_UNITS.md (S-348).

## 3. Configure it

One file: `samverk.ini` in the data root, section
`[samverk]`. Every key, its environment override and its
default stand in docs/CONFIGURATION.md (S-346); judge a
configuration before boot with `samverk config check`
and see what would actually run with `samverk config show`.

## 4. Watch its health

`GET /healthz` is the public probe: it answers from the
real database at request time and never dresses a missing
or stale database as ok. The operator's page is
`GET /admin/status`, admins only. Both faces are specified
in docs/HEALTH_AND_STATUS.md (S-359). The data root layout
every process shares is docs/DATA_DIRECTORY_LAYOUT.md
(S-347).

## 5. Upgrade it

The one procedure is docs/UPGRADES.md (S-357): export,
verify, stop, migrate, start, verify counts — a failed
migration rolls back to the export. S-396 rehearsed it
end to end on a real-shaped instance; the drill log is
docs/upgrade-drill-s396.md.

## Honest limits

The bare server in `samverk/server.py` answers `/`,
`/healthz` and `/admin/status`; the wider web and API
surfaces are service modules wired route by route by
their own slices. This guide claims no route the walked
instance did not answer.
