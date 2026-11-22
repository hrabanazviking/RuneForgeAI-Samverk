"""Run model (S-345) -- the deployment topology, in code.

Part XVIII opens here. Before this slice the pieces
stood apart and true: S-002's `server.serve` runs one
threaded HTTP server; the web faces, the REST API
services and the transports' HTTP half (git smart HTTP,
S-0xx `git_http`; the LFS API, `lfs_api`) are service
modules the HTTP process composes; and the background
jobs -- webhook delivery (S-250), the weekly digest
(S-235), artifact expiry, mirror sync (S-331) -- each
carry their own off-request-path entry and the standing
law that no request ever runs them. What no slice had
done is *name the whole*: which processes exist, what
each one serves, and under what family they are run and
supervised together. That naming is this slice, and its
laws are plain:

- **One server process serves everything HTTP.** Web,
  API, and the transports' HTTP half (git smart HTTP +
  LFS) are surfaces of the single `server` role, entered
  by `python3 -m samverk serve` (S-002's `serve`). There
  is no separate web process, API process or git-HTTP
  process, and no worker may serve an HTTP surface.
- **Background jobs are separate worker processes.**
  Each job family is its own worker role with its own
  process and its own entry point, run on its cadence
  by an operator or scheduler -- never inside the
  server process and never on a request path. A worker
  stopped or crashed leaves the server serving; a
  worker run reads and writes the same data root and
  database as the server (the shared-state law: the
  database and repo tree are the meeting point, never
  a socket between our own processes).
- **One unit family.** Every role's unit name carries
  the family prefix `samverk-` (`samverk-server`,
  `samverk-webhook-delivery`, ...). S-348 authors the
  native unit files under exactly these names; S-346's
  one config file is read by every role alike. The
  names and entries defined here are the data those
  slices consume -- this slice authors no unit files
  and no new config keys.
- **The SSH transport is not a family process.** Git
  over SSH arrives through the host's sshd as a forced
  command (`ssh_serve`, per connection); it is drawn in
  the topology as an external door, honestly outside
  the unit family, because no Samverk process listens
  for it.

The shapes are data (`ProcessRole`, `Topology`), the
judgement is pure (`validate_topology` names every way
a handed topology breaks the laws above), and
`render_topology` draws the same picture the operator
guide (docs/RUN_MODEL.md) carries -- a test keeps the
drawing and the code from drifting apart.

No migration (schema stays 139); no new taxonomy
event (138 stand).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

from .config import DEFAULT_HOST, DEFAULT_PORT

#: The one unit family every role belongs to.
UNIT_FAMILY = "samverk"

# -- surfaces ---------------------------------------------------

SURFACE_WEB = "web"
SURFACE_API = "api"
SURFACE_GIT_HTTP = "git-http"
SURFACE_LFS_HTTP = "lfs-http"

#: Every HTTP surface the instance answers. All of them
#: belong to the server role and to no worker.
HTTP_SURFACES = (
    SURFACE_WEB, SURFACE_API, SURFACE_GIT_HTTP, SURFACE_LFS_HTTP,
)

ROLE_SERVER = "server"
ROLE_WORKER = "worker"

CADENCE_ALWAYS_ON = "always-on"
CADENCE_PERIODIC = "periodic"
CADENCE_ON_TICK = "on-tick"


@dataclass(frozen=True)
class ProcessRole:
    """One process in the topology: its name, kind,
    unit, entry point, the surfaces it serves (server
    only), the jobs it runs (workers only) and its
    cadence. `has_cli` is honest: a worker whose module
    carries its own `main` says True; the mirror-sync
    worker, whose seam today is a service entry an
    external scheduler tick calls, says False and its
    `entry` names that seam -- S-348 gives it a unit
    whose ExecStart wraps the tick."""

    name: str
    kind: str
    unit: str
    entry: str
    cadence: str
    serves: tuple = ()
    jobs: tuple = ()
    has_cli: bool = True
    words: str = ""


@dataclass(frozen=True)
class Topology:
    """The whole run model: one server role, the worker
    roles, and the family they share."""

    family: str
    server: ProcessRole
    workers: tuple = ()
    external_doors: tuple = ()

    @property
    def roles(self) -> tuple:
        return (self.server,) + tuple(self.workers)

    def role_named(self, name: str) -> ProcessRole | None:
        for role in self.roles:
            if role.name == name:
                return role
        return None

    def role_for_unit(self, unit: str) -> ProcessRole | None:
        for role in self.roles:
            if role.unit == unit:
                return role
        return None


# -- the standing topology --------------------------------------

SERVER_ROLE = ProcessRole(
    name="server",
    kind=ROLE_SERVER,
    unit="samverk-server",
    entry="python3 -m samverk serve",
    cadence=CADENCE_ALWAYS_ON,
    serves=HTTP_SURFACES,
    words="the one HTTP process: web, API, git smart "
          "HTTP and the LFS API, composed by "
          "samverk.server.serve on the configured "
          "host and port",
)

WORKER_ROLES = (
    ProcessRole(
        name="webhook-delivery",
        kind=ROLE_WORKER,
        unit="samverk-webhook-delivery",
        entry="python3 -m samverk.webhook_delivery "
              "<db-path> <repos-root>",
        cadence=CADENCE_PERIODIC,
        jobs=("webhook-delivery",),
        words="drains due webhook deliveries from the "
              "outbox (S-250); one run drains one due "
              "batch, so the scheduler ticks it",
    ),
    ProcessRole(
        name="weekly-digest",
        kind=ROLE_WORKER,
        unit="samverk-weekly-digest",
        entry="python3 -m samverk.digest_job "
              "<db-path> <repos-root>",
        cadence=CADENCE_PERIODIC,
        jobs=("weekly-digest",),
        words="composes the weekly activity digest "
              "from the event store (S-235), for the "
              "accounts that chose a weekly cadence",
    ),
    ProcessRole(
        name="artifact-expiry",
        kind=ROLE_WORKER,
        unit="samverk-artifact-expiry",
        entry="python3 -m samverk.artifact_expiry "
              "<db-path> <data-root>",
        cadence=CADENCE_PERIODIC,
        jobs=("artifact-expiry",),
        words="sweeps CI artifacts whose retention has "
              "expired; the deliberate act that clears "
              "the expired standing rows",
    ),
    ProcessRole(
        name="mirror-sync",
        kind=ROLE_WORKER,
        unit="samverk-mirror-sync",
        entry="samverk.sync_scheduler:"
              "SyncSchedulerService.run_due "
              "(scheduler tick; no standalone __main__ "
              "yet -- S-348's unit wraps the tick)",
        cadence=CADENCE_ON_TICK,
        jobs=("mirror-sync",),
        has_cli=False,
        words="syncs pull mirrors that are due, on "
              "their jittered per-mirror intervals "
              "(S-331); each due mirror's next sync "
              "advances whether it synced or failed",
    ),
)

#: Doors into the instance that no family process
#: listens for, drawn honestly outside the family.
EXTERNAL_DOORS = (
    "ssh: the host sshd runs samverk.ssh_serve as a "
    "forced command per connection -- git over SSH "
    "is served there, not by any family process",
)


def build_topology() -> Topology:
    """The composition root: the standing topology,
    assembled from the role definitions above. S-346
    (config) and S-348 (units) consume this shape."""
    return Topology(
        family=UNIT_FAMILY,
        server=SERVER_ROLE,
        workers=WORKER_ROLES,
        external_doors=EXTERNAL_DOORS,
    )


# -- the pure judgement ------------------------------------------

def validate_topology(topology: Topology) -> list[str]:
    """Judge a topology against the run-model laws and
    return the problems found, in plain words; an empty
    list means the topology stands. Pure: no I/O, no
    clock, the same topology always judges the same."""
    problems: list[str] = []
    server = topology.server
    if server.kind != ROLE_SERVER:
        problems.append("the server role is not a server")
    for surface in HTTP_SURFACES:
        if surface not in server.serves:
            problems.append(
                f"the server does not serve {surface}")
    for surface in server.serves:
        if surface not in HTTP_SURFACES:
            problems.append(
                f"the server serves unknown surface {surface}")
    if server.jobs:
        problems.append(
            "the server runs background jobs: "
            + ", ".join(server.jobs))
    if server.cadence != CADENCE_ALWAYS_ON:
        problems.append("the server is not always-on")
    seen_names: set = set()
    seen_units: set = set()
    seen_jobs: set = set()
    for role in topology.roles:
        if role.name in seen_names:
            problems.append(f"duplicate role name {role.name}")
        seen_names.add(role.name)
        if role.unit in seen_units:
            problems.append(f"duplicate unit {role.unit}")
        seen_units.add(role.unit)
        if not role.unit.startswith(topology.family + "-"):
            problems.append(
                f"unit {role.unit} is outside the "
                f"{topology.family} family")
        if not role.entry:
            problems.append(f"role {role.name} has no entry point")
    for worker in topology.workers:
        if worker.kind != ROLE_WORKER:
            problems.append(f"worker {worker.name} is not a worker")
        for surface in worker.serves:
            problems.append(
                f"worker {worker.name} serves HTTP surface "
                f"{surface} -- only the server serves HTTP")
        if not worker.jobs:
            problems.append(f"worker {worker.name} runs no job")
        for job in worker.jobs:
            if job in seen_jobs:
                problems.append(
                    f"job {job} is run by more than one worker")
            seen_jobs.add(job)
        if worker.cadence == CADENCE_ALWAYS_ON:
            problems.append(
                f"worker {worker.name} is always-on -- workers "
                "run on a cadence or a tick, the server alone "
                "is always-on")
    return problems


def topology_stands(topology: Topology) -> bool:
    return not validate_topology(topology)


# -- the drawing ---------------------------------------------------

def render_topology(topology: Topology | None = None) -> str:
    """Draw the topology as text: the same drawing the
    operator guide (docs/RUN_MODEL.md) carries."""
    topo = topology if topology is not None else build_topology()
    lines = [
        f"Samverk run model -- one unit family: {topo.family}-*",
        "",
        "  clients --HTTP--> [server] " + topo.server.unit,
        "                      serves: " + ", ".join(topo.server.serves),
        "                      entry: " + topo.server.entry,
        "",
    ]
    for door in topo.external_doors:
        lines.append("  external door: " + door)
    if topo.external_doors:
        lines.append("")
    lines.append("  background workers (separate processes, "
                 "same family, same data root):")
    for worker in topo.workers:
        lines.append(f"    [{worker.name}] {worker.unit}")
        lines.append(f"        jobs: {', '.join(worker.jobs)} "
                     f"({worker.cadence})")
        lines.append(f"        entry: {worker.entry}")
    lines += [
        "",
        "  shared state: one data root -- database, "
        "repositories, keys --",
        "  read and written by the server and every "
        "worker alike;",
        "  no process talks to another over a socket.",
    ]
    return "\n".join(lines)


def operator_words(topology: Topology | None = None) -> list[str]:
    """The topology in plain operator words, one line
    per role."""
    topo = topology if topology is not None else build_topology()
    out = [f"{topo.server.unit}: {topo.server.words} "
           f"(default bind {DEFAULT_HOST}:{DEFAULT_PORT}, "
           "config-file governed from S-346)."]
    for worker in topo.workers:
        out.append(f"{worker.unit}: {worker.words}.")
    return out


def main(argv: list[str] | None = None) -> int:
    """The operator's read of the run model:
    ``python3 -m samverk.run_model [--check]`` prints
    the topology drawing and the plain-words lines;
    with --check it also judges the standing topology
    and exits 1 naming every problem if it falls."""
    args = list(sys.argv[1:] if argv is None else argv)
    topo = build_topology()
    print(render_topology(topo))
    print()
    for line in operator_words(topo):
        print(line)
    if "--check" in args:
        problems = validate_topology(topo)
        if problems:
            for problem in problems:
                print(f"PROBLEM: {problem}")
            return 1
        print("run model check: the standing topology stands")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
