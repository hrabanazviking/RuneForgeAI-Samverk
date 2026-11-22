# Samverk run model — the operator guide (S-345)

This is the topology of a running Samverk instance: which processes
exist, what each one does, and how they are supervised together.
The definitions live in code (`samverk/run_model.py`); this guide
draws the same picture for the operator. Run
`python3 -m samverk.run_model --check` on any checkout to print the
drawing from the code itself and verify the standing topology
against the laws below.

## The topology, drawn

```
Samverk run model -- one unit family: samverk-*

  clients --HTTP--> [server] samverk-server
                      serves: web, api, git-http, lfs-http
                      entry: python3 -m samverk serve

  external door: ssh: the host sshd runs samverk.ssh_serve as a forced command per connection -- git over SSH is served there, not by any family process

  background workers (separate processes, same family, same data root):
    [webhook-delivery] samverk-webhook-delivery
        jobs: webhook-delivery (periodic)
        entry: python3 -m samverk.webhook_delivery <db-path> <repos-root>
    [weekly-digest] samverk-weekly-digest
        jobs: weekly-digest (periodic)
        entry: python3 -m samverk.digest_job <db-path> <repos-root>
    [artifact-expiry] samverk-artifact-expiry
        jobs: artifact-expiry (periodic)
        entry: python3 -m samverk.artifact_expiry <db-path> <data-root>
    [mirror-sync] samverk-mirror-sync
        jobs: mirror-sync (on-tick)
        entry: samverk.sync_scheduler:SyncSchedulerService.run_due (scheduler tick; no standalone __main__ yet -- S-348's unit wraps the tick)

  shared state: one data root -- database, repositories, keys --
  read and written by the server and every worker alike;
  no process talks to another over a socket.
```

## The laws

- **One server process serves everything HTTP.** The web faces, the
  REST API and the transports' HTTP half (git smart HTTP and the LFS
  API) are surfaces of the single `samverk-server` process, entered
  by `python3 -m samverk serve`. There is no separate web, API or
  git-HTTP process.
- **Background jobs are separate worker processes.** Webhook
  delivery, the weekly digest, artifact expiry and mirror sync each
  run as their own process, on their own cadence, under the same
  unit family. No background job runs inside the server process or
  on a request path. A worker that stops leaves the server serving;
  a server restart does not lose queued work, because the queues
  live in the shared database.
- **One unit family.** Every unit name carries the `samverk-`
  prefix. S-348 authors the native unit files under exactly the
  names defined here; S-346's one config file is read by every role
  alike.
- **Shared state, no inter-process sockets.** Server and workers
  meet only in the one data root: the database, the repository tree
  and the keys (layout: S-347). No Samverk process calls another
  over a socket.
- **SSH is an external door.** Git over SSH arrives through the
  host's sshd, which runs `samverk.ssh_serve` as a forced command
  per connection. No family process listens for SSH.

## The roles

| Unit | Entry | Cadence | What it does |
| --- | --- | --- | --- |
| `samverk-server` | `python3 -m samverk serve` | always-on | The one HTTP process: web, API, git smart HTTP, LFS API. Default bind `127.0.0.1:8737`, from the config file. |
| `samverk-webhook-delivery` | `python3 -m samverk.webhook_delivery <db-path> <repos-root>` | periodic | Drains one due batch of webhook deliveries per run (S-250). |
| `samverk-weekly-digest` | `python3 -m samverk.digest_job <db-path> <repos-root>` | periodic | Composes the weekly digest from the event store (S-235). |
| `samverk-artifact-expiry` | `python3 -m samverk.artifact_expiry <db-path> <data-root>` | periodic | Sweeps expired CI artifacts. |
| `samverk-mirror-sync` | `SyncSchedulerService.run_due` via a scheduler tick | on-tick | Syncs due pull mirrors on their jittered intervals (S-331). It has no standalone `__main__` yet; S-348's unit wraps the tick. |

## Honest remainders

- The server process today composes the health and root routes in
  `samverk/server.py`; the web/API/transport services are the
  service modules this topology assigns to it, wired route by route
  by their own slices. The run model names the process they belong
  to; it does not invent routes.
- Other off-path library jobs (repository GC, search indexing)
  follow the same law — separate worker processes under this
  family — and are assigned their own worker roles when their
  units are authored in S-348.
- No unit files exist yet: S-348 writes them under the names above.
  No new config keys exist yet: S-346 defines the one config file
  every role reads.
