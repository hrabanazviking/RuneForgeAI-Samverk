# Health and status (S-359)

Two faces, both honest because both are gathered at request time and
nothing is cached:

## `GET /healthz` — the probe

The public health door. Every answer is computed from the real
database file at the configured data root, opened **read-only** (a
health read creates nothing and migrates nothing):

- a real `SELECT 1` against the file,
- the schema version, read through the database layer's own
  `schema_version`, judged against the current migration head
  (**139**).

Answers:

| State | HTTP | Body |
|---|---|---|
| Database up, schema current | 200 | `{"status": "ok", "db": "up", "schema_version": 139, ...}` |
| No database file yet (bare checkout, nothing initialised) | 200 | `{"status": "ok", "db": "missing", "schema_version": null, "reason": "database_not_initialised"}` |
| Database file stands but cannot be read | 503 | `{"status": "down", "db": "down", "schema_version": null, "reason": "database_unreachable"}` |
| Database readable, schema not current | 503 | `{"status": "down", "db": "up", "schema_version": <n>, "reason": "schema_mismatch"}` |

A broken database never answers a false ok. The bare-checkout row is
the standing skeleton contract (the server itself is up before first
initialisation) and it is *named* `missing` in the payload, never
dressed as a checked database.

The payload carries no sensitive numbers beyond up/down, the
database word, and the schema version: no disk figures, no counts,
no paths. That is the standing practice for a public health door;
the numbers live behind the admin door below.

## `GET /admin/status` — the operator's page

Site admins only. Over HTTP the caller's session cookie is resolved
through the standing session store: anonymous or unknown answers
401, a signed-in non-admin 403. The service door
(`samverk/health_status.py`, `HealthStatus.status`) speaks the
S-215 reasons `no_such_user` / `not_site_admin`, checked before
anything is read.

The page shows, all gathered fresh at the request:

- **Overall** — one judged word: `down` (the probe is down),
  `degraded` (index stale or failed, dead work in any queue, or a
  damaged data layout), or `ok`. Work merely waiting is backlog,
  shown as numbers; it is not dressed as degradation.
- **Database** — up/down, schema version against the head, bytes on
  disk (file plus WAL sidecars), account and repository counts.
- **Disk** — the data root's filesystem free/used/total and percent,
  plus the data tree's own bytes walked file by file.
- **Search index** — S-215's instance health whole: the queue lag
  in seconds (the age of the oldest waiting index job — an
  un-indexed change shows as lag *and* as a waiting count),
  waiting/running/done/dead, repositories up to date vs behind,
  documents indexed, and the folded headline status.
- **Job backlog** — counted from the real queue tables:
  `index_jobs` (S-205), `webhook_deliveries` (S-250) and
  `weekly_digests` (S-235), per-status counts for each, the total
  still owed (waiting or in flight), and the dead total. A queue
  that cannot be counted says so on the page instead of showing a
  false 0.
- **Data layout** — S-347's layout verdict for the root, with any
  problem entries named.

Change the world and the page changes: the battery proves it by
enqueueing an index job (lag and backlog move) and by landing a
file in the tree (disk numbers move).

## Seams and standing

- The pure judgements (`judge_probe`, `decide_overall_status`,
  `summarise_backlog`) take facts and write nothing; the gathers
  (`probe_database`, `gather_disk_facts`, the backlog count) read
  the real seams once per call.
- S-351's admin panel is not on this base. This page stands on the
  standing admin seams (the account store's `is_admin`, S-215's
  door shape, S-006's session cookie); when the panel lands it
  links `GET /admin/status` — nothing here depends on it.
- No migration and no new taxonomy event: health reads write
  nothing and audit nothing (S-215's law for reads). Schema stands
  at **139**, taxonomy at **138**.
