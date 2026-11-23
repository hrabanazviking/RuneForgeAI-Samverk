"""S-412 -- Linux services parity: the systemd units as
one of three equal citizens.

Roadmap line: the systemd units (S-348) re-verified as
one of three equal citizens; no feature exists on Linux
that the service model forbids elsewhere.

THE SHAPE
- S-348 shipped the units as data under deploy/systemd/
  with no code seam naming the service as a whole. S-410
  (Windows/SCM) and S-411 (macOS/launchd) each built that
  seam for their citizen. This slice builds the Linux
  seam, `samverk/linux_service.py`, in the same shape:
  one validated spec, the unit files rendered from it as
  data, the systemctl command lines rendered from it,
  and the 8-step install walk to Part XVIII's standard.
  The shipped S-348 units are NOT replaced: the battery
  proves the shipped files carry exactly the directives
  this module renders for the standing spec, so the seam
  describes the units that already ship, it does not
  invent new ones.
- One server, on every citizen. S-345's run model has
  exactly one long-running process -- the server (web,
  API, git smart HTTP, LFS HTTP) -- so exactly one
  always-on unit exists: samverk-server.service,
  Type=simple, Restart=on-failure. The periodic workers
  are NOT daemons on any OS: S-348 ships webhook delivery
  and weekly digest as Type=oneshot units plus timers
  (every minute; Monday 06:00), the same cadences S-411's
  launchd jobs carry and S-410's worker command lines
  render for Task Scheduler.
- Parity is a table, not a vibe. PARITY_CAPABILITIES
  names the capabilities every service citizen must
  provide; PARITY_MATRIX records, per capability, the
  native mechanism each of the three citizens uses. The
  battery proves the three columns name exactly the
  same capability set, and proves the Linux column
  against the shipped units themselves. A capability
  only one citizen had would be a parity defect under
  the Never-Leave-A-Bug law.
- Native differences are mechanisms, not features.
  Linux logs to the journal (macOS: log files in the
  data root; Windows: the host's routed output), keeps
  its one config file in /etc/samverk (the FHS place;
  the other citizens keep theirs in the data root), and
  sandboxes with systemd hardening directives (the
  other citizens use their own native means). What
  Samverk DOES is identical; how the OS holds it is
  each citizen's native way, recorded in the matrix.
- Restart delay is a declared mechanism, not a feature:
  Linux RestartSec=5s (S-348), the other citizens 60 s
  (S-410/S-411). The capability -- restart on failure,
  never on a clean stop's behalf beyond systemd's own
  on-failure law -- is equal; the delay is named in the
  matrix so the difference is written, not hidden.
- Install enables nothing by itself. S-348's install.sh
  installs and verifies and stops there; enabling is
  the operator's word (--enable), exactly as S-410's
  script starts nothing without -Start and S-411's
  loads nothing without --load.
- DEFECT FOUND AND FIXED in this slice: the Linux
  citizen had no uninstall road -- Windows and macOS
  both ship an uninstall that removes the registration
  and keeps the instance data; deploy/systemd/ had
  none. deploy/systemd/uninstall.sh now ships: it
  disables the server and timers, removes the unit
  files, reloads, and keeps /var/lib/samverk and
  /etc/samverk standing.

HONEST REMAINDER -- WHAT IS AND IS NOT PROVEN
Proven on this Linux host (purplelongship): the spec,
the validation refusals, the rendered units' directive
identity with the shipped S-348 files, the rendered
systemctl lines and scripts, the parity table, and
`systemd-analyze verify` clean over the shipped units
(S-348's battery, re-run as a neighbour of this one).
NOT PROVEN: a real install/enable/boot/health run of
these units on a dedicated host -- no such run was
executed in this slice (the keeper host is shared and
no permanent service may be stood up on it without
Volmarr's word for that specific service), and the
Debian/Pi leg S-348 already recorded stands: the units
use no Ubuntu-specific directive, but that is an
expectation, not a proof. S-416's gate owns the counted
real-host claims. docs/LINUX_SERVICE.md says the same.

No migration and no new taxonomy event: the schema
stands at 140 and the taxonomy at 142. A systemd
registration is host state, not instance state.
"""
from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import PurePosixPath

from .run_model import build_topology

__all__ = [
    "SERVER_UNIT", "WORKER_UNITS", "TIMER_UNITS", "ALL_UNITS",
    "DISPLAY_NAME", "DESCRIPTION", "SERVICE_USER", "SYSTEM_DIR",
    "CONFIG_DIR", "RESTART_MODE", "RESTART_DELAY_SECONDS",
    "DEFAULT_DATA_ROOT", "DEFAULT_CONFIG", "DEFAULT_PYTHON",
    "HARDENING_DIRECTIVES", "SHIPPED_WORKERS",
    "CAPABILITIES", "PARITY_MATRIX", "parity_capabilities",
    "LinuxServiceError", "SystemdSpec", "build_service_spec",
    "validate_spec", "check_spec", "server_command",
    "worker_commands", "server_unit", "worker_unit",
    "timer_unit", "render_unit", "parse_unit",
    "install_commands", "enable_commands", "disable_commands",
    "status_commands", "restart_commands", "verify_commands",
    "uninstall_commands", "render_command_line",
    "render_install_script", "render_uninstall_script",
    "INSTALL_WALK_STEPS",
]

SERVER_UNIT = "samverk-server.service"
#: The shipped worker set is S-348's, exactly as S-411 kept
#: it: webhook delivery and weekly digest get units; the
#: other topology workers get rendered command lines only
#: (artifact-expiry) or none (mirror-sync, no CLI).
SHIPPED_WORKERS = ("webhook-delivery", "weekly-digest")
_WORKER_UNIT_NAMES = {
    "webhook-delivery": "samverk-webhook-worker.service",
    "weekly-digest": "samverk-digest-worker.service",
}
WORKER_UNITS = tuple(_WORKER_UNIT_NAMES[n] for n in SHIPPED_WORKERS)
TIMER_UNITS = tuple(u.replace(".service", ".timer")
                    for u in WORKER_UNITS)
ALL_UNITS = (SERVER_UNIT,) + WORKER_UNITS + TIMER_UNITS
DISPLAY_NAME = "Samverk"
DESCRIPTION = ("Samverk server (web, API, Git HTTP)")
SERVICE_USER = "samverk"
SERVICE_GROUP = "samverk"
SYSTEM_DIR = "/etc/systemd/system"
CONFIG_DIR = "/etc/samverk"
RESTART_MODE = "on-failure"
#: Declared per citizen in the parity matrix: Linux 5 s
#: (S-348), Windows and macOS 60 s (S-410/S-411).
RESTART_DELAY_SECONDS = 5
DEFAULT_DATA_ROOT = "/var/lib/samverk"
DEFAULT_CONFIG = "/etc/samverk/samverk.ini"
DEFAULT_PYTHON = "/usr/bin/python3"
UNIT_DOC = "file:///usr/share/doc/samverk/SYSTEMD_UNITS.md"

#: The S-348 hardening baseline, in shipped order, set on
#: every service unit. RestrictAddressFamilies is per-unit
#: (the digest worker sends nothing: AF_UNIX only) and is
#: rendered separately. MemoryDenyWriteExecute is
#: deliberately absent (S-348's reasoned omission).
HARDENING_DIRECTIVES = (
    ("NoNewPrivileges", "true"), ("PrivateTmp", "true"),
    ("ProtectSystem", "strict"),
    ("ProtectHome", "true"),
    ("ProtectKernelTunables", "true"),
    ("ProtectKernelModules", "true"),
    ("ProtectKernelLogs", "true"),
    ("ProtectControlGroups", "true"),
    ("ProtectClock", "true"), ("ProtectHostname", "true"),
    ("RestrictSUIDSGID", "true"), ("LockPersonality", "true"),
    ("RestrictRealtime", "true"), ("PrivateDevices", "true"),
    ("ProtectProc", "invisible"), ("ProcSubset", "pid"),
    ("CapabilityBoundingSet", ""), ("AmbientCapabilities", ""),
    ("SystemCallArchitectures", "native"),
)
_SERVER_FAMILIES = "AF_UNIX AF_INET AF_INET6"
_REFUSED_COMPONENTS = ("docker",)


class LinuxServiceError(ValueError):
    """A spec refused by the S-412 law; `reason` is stable."""

    def __init__(self, reason, detail=""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


def _check_posix_path(value, what):
    if not isinstance(value, str) or not value.strip():
        raise LinuxServiceError("path_missing", f"{what} is empty")
    if "\x00" in value or any(ord(c) < 0x20 for c in value):
        raise LinuxServiceError(
            "control_character", f"{what} carries a control character")
    p = PurePosixPath(value)
    if not p.is_absolute():
        raise LinuxServiceError(
            "path_not_absolute",
            f"{what} must be an absolute POSIX path, got {value!r}")
    for part in (part.lower() for part in p.parts):
        if part in _REFUSED_COMPONENTS or "docker" in part:
            raise LinuxServiceError(
                "container_path",
                f"{what} routes through {part!r}: Samverk under "
                "systemd is never installed through a Docker path")
    return str(p)


@dataclass(frozen=True)
class SystemdSpec:
    """The whole Linux service definition as data: user,
    restart posture, and the three paths everything else
    is rendered from (interpreter, data root, config)."""

    python_exe: str
    data_root: str
    config_path: str
    unit_name: str = SERVER_UNIT
    user_name: str = SERVICE_USER
    group_name: str = SERVICE_GROUP
    system_dir: str = SYSTEM_DIR
    restart_mode: str = RESTART_MODE
    restart_delay: int = RESTART_DELAY_SECONDS

    @property
    def db_path(self) -> str:
        return str(PurePosixPath(self.data_root) / "samverk.db")

    @property
    def unit_path(self) -> str:
        return str(PurePosixPath(self.system_dir) / self.unit_name)

    @property
    def server_command_list(self) -> list:
        return server_command(self)


def build_service_spec(python_exe=DEFAULT_PYTHON,
                       data_root=DEFAULT_DATA_ROOT,
                       config_path=None) -> SystemdSpec:
    """Compose and validate a spec. The config defaults
    to /etc/samverk/samverk.ini -- the FHS place, and the
    path S-348's shipped server unit names; Linux keeps
    its one config file there rather than in the data
    root (a mechanism difference, recorded in the parity
    matrix, not a feature difference)."""
    python_exe = _check_posix_path(python_exe, "python_exe")
    data_root = _check_posix_path(data_root, "data_root")
    if config_path is None:
        config_path = DEFAULT_CONFIG
    config_path = _check_posix_path(config_path, "config_path")
    spec = SystemdSpec(python_exe=python_exe, data_root=data_root,
                       config_path=config_path)
    check_spec(spec)
    return spec


def server_command(spec: SystemdSpec) -> list:
    """The server unit's ExecStart argv: S-345's server
    role entry with this spec's config."""
    return [spec.python_exe, "-m", "samverk", "serve",
            "--config", spec.config_path]


def validate_spec(spec: SystemdSpec) -> list:
    problems: list = []
    for value, what in ((spec.python_exe, "python_exe"),
                        (spec.data_root, "data_root"),
                        (spec.config_path, "config_path")):
        try:
            _check_posix_path(value, what)
        except LinuxServiceError as exc:
            problems.append(f"{what}: {exc}")
    if spec.unit_name != SERVER_UNIT:
        problems.append(
            f"the unit is {spec.unit_name!r}, not {SERVER_UNIT!r}: "
            "the run model's family names the server unit, so a "
            "renamed unit silently becomes a different service")
    if spec.user_name != SERVICE_USER or spec.group_name != SERVICE_GROUP:
        problems.append(
            f"the user/group is {spec.user_name!r}/{spec.group_name!r}, "
            f"not the dedicated service user {SERVICE_USER!r}: the "
            "server must not run as root or as an operator's login user")
    if spec.system_dir != SYSTEM_DIR:
        problems.append(
            f"the system directory is {spec.system_dir!r}, not "
            f"{SYSTEM_DIR!r}: local systemd units install there "
            "and nowhere else")
    if spec.restart_mode != RESTART_MODE:
        problems.append(
            f"the restart mode is {spec.restart_mode!r}, not "
            f"{RESTART_MODE!r}: a clean stop is the operator's "
            "word and stays stopped, on every citizen")
    if spec.restart_delay != RESTART_DELAY_SECONDS:
        problems.append("the restart delay differs from the "
                        "declared 5-second S-348 law")
    server = build_topology().server
    if not server.entry.endswith("samverk serve"):
        problems.append(
            "the run model's server entry no longer ends in "
            "'samverk serve': server_command would drift from "
            "the topology it claims to serve")
    return problems


def check_spec(spec: SystemdSpec) -> SystemdSpec:
    problems = validate_spec(spec)
    if problems:
        raise LinuxServiceError("invalid_spec", problems[0])
    return spec


def worker_commands(spec: SystemdSpec) -> tuple:
    """Every worker in S-345's topology as a one-shot
    command line for this spec: (role name, argv or None,
    words). Mirror-sync renders None and says why, never
    a fabricated command -- on every citizen alike."""
    check_spec(spec)
    out = []
    for role in build_topology().workers:
        if not role.has_cli:
            out.append((role.name, None,
                        "no standalone CLI yet: the scheduler tick "
                        "is an in-process seam (S-345), so no "
                        "command is rendered rather than a false one"))
            continue
        argv = []
        for token in role.entry.split():
            if token == "python3":
                argv.append(spec.python_exe)
            elif token == "<db-path>":
                argv.append(spec.db_path)
            elif token in ("<repos-root>", "<data-root>"):
                argv.append(spec.data_root)
            else:
                argv.append(token)
        out.append((role.name, argv, role.words))
    return tuple(out)


# -- unit rendering -------------------------------------------
#
# A unit is data. Every unit is an ordered tuple of
# (section, ((key, value), ...)) built here; the files
# under deploy/systemd/ are S-348's shipped copies, and
# the battery keeps the shipped files' directives and
# this rendering from drifting apart (directive identity:
# the shipped files carry operator comments the rendering
# does not reproduce).

def _hardening(spec, families):
    out = []
    for key, value in HARDENING_DIRECTIVES:
        out.append((key, value))
        if key == "ProtectSystem":
            out.append(("ReadWritePaths", spec.data_root))
        if key == "RestrictRealtime":
            out.append(("RestrictAddressFamilies", families))
    return tuple(out)


def _service_section(spec, type_, exec_argv, identifier, families,
                     extra=()):
    pairs = [("Type", type_), ("User", spec.user_name),
             ("Group", spec.group_name),
             ("ExecStart", " ".join(exec_argv)),
             ("WorkingDirectory", spec.data_root),
             ("StateDirectory", "samverk")]
    pairs += list(extra)
    pairs += [("UMask", "0027"), ("StandardOutput", "journal"),
              ("StandardError", "journal"),
              ("SyslogIdentifier", identifier)]
    pairs += list(_hardening(spec, families))
    return tuple(pairs)


def server_unit(spec: SystemdSpec) -> tuple:
    """The one always-on unit as data: Type=simple,
    Restart=on-failure with the declared 5 s delay,
    WantedBy=multi-user.target (starts at boot, before
    any login, on the Linux citizen)."""
    check_spec(spec)
    extra = [("ConfigurationDirectory", "samverk"),
             ("Restart", spec.restart_mode),
             ("RestartSec", f"{spec.restart_delay}s")]
    return (
        ("Unit", (("Description", DESCRIPTION),
                  ("Documentation", UNIT_DOC),
                  ("After", "network.target"),
                  ("Wants", "network.target"))),
        ("Service", _service_section(
            spec, "simple", server_command(spec),
            "samverk-server", _SERVER_FAMILIES, extra)),
        ("Install", (("WantedBy", "multi-user.target"),)),
    )


_WORKER_WORDS = {
    "webhook-delivery": (
        "Samverk webhook delivery worker (one due batch)",
        "samverk-webhook-worker", _SERVER_FAMILIES, True),
    "weekly-digest": (
        "Samverk weekly digest worker (one weekly run)",
        "samverk-digest-worker", "AF_UNIX", False),
}


def worker_unit(spec: SystemdSpec, role_name: str) -> tuple:
    """One shipped worker's unit as data: Type=oneshot
    (a batch worker, not a daemon -- the timer carries
    the cadence). Raises LinuxServiceError for a worker
    that ships no unit."""
    check_spec(spec)
    argv = dict((n, a) for n, a, _ in worker_commands(spec))
    if role_name not in _WORKER_UNIT_NAMES or argv.get(role_name) is None:
        raise LinuxServiceError(
            "worker_not_shipped",
            f"{role_name!r} ships no systemd unit: either it "
            "has no standalone CLI or it is outside S-348's "
            "shipped worker set")
    desc, identifier, families, wants = _WORKER_WORDS[role_name]
    unit_pairs = [("Description", desc), ("Documentation", UNIT_DOC),
                  ("After", "network.target")]
    if wants:
        unit_pairs.append(("Wants", "network.target"))
    return (
        ("Unit", tuple(unit_pairs)),
        ("Service", _service_section(
            spec, "oneshot", argv[role_name], identifier, families)),
    )


_TIMER_WORDS = {
    "webhook-delivery": (
        "Run the Samverk webhook delivery worker every minute",
        (("OnBootSec", "2min"), ("OnUnitActiveSec", "1min"))),
    "weekly-digest": (
        "Run the Samverk weekly digest worker weekly",
        (("OnCalendar", "Mon 06:00"),)),
}


def timer_unit(spec: SystemdSpec, role_name: str) -> tuple:
    """One shipped worker's timer as data: the cadence
    lives here, not in the worker (S-348's law, kept on
    every citizen: S-411's schedule keys, S-410's Task
    Scheduler entries). Persistent=true catches up a
    run missed while the machine was off."""
    check_spec(spec)
    if role_name not in _TIMER_WORDS:
        raise LinuxServiceError(
            "worker_not_shipped",
            f"{role_name!r} ships no systemd timer")
    desc, schedule = _TIMER_WORDS[role_name]
    timer_pairs = list(schedule) + [
        ("Persistent", "true"),
        ("Unit", _WORKER_UNIT_NAMES[role_name])]
    return (
        ("Unit", (("Description", desc),)),
        ("Timer", tuple(timer_pairs)),
        ("Install", (("WantedBy", "timers.target"),)),
    )


def render_unit(sections) -> str:
    """Render unit sections as unit-file text."""
    lines = []
    for name, pairs in sections:
        lines.append(f"[{name}]")
        for key, value in pairs:
            lines.append(f"{key}={value}")
        lines.append("")
    return "\n".join(lines)


def parse_unit(text: str) -> dict:
    """Parse unit-file text into {section: {key: [values]}};
    comments and blank lines carry no directives."""
    out: dict = {}
    section = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            out.setdefault(section, {})
            continue
        if "=" in line and section is not None:
            key, value = line.split("=", 1)
            out[section].setdefault(key.strip(), []).append(value.strip())
    return out


# -- systemctl command rendering ------------------------------

def render_command_line(argv) -> str:
    return shlex.join([str(a) for a in argv])


def install_commands(spec: SystemdSpec, source_dir: str) -> list:
    """Copy the shipped units into /etc/systemd/system
    (0644, root-owned by install's default), reload, and
    verify the installed service units. Registration
    only -- nothing here enables or starts a unit:
    enablement is the operator's word (enable_commands)."""
    check_spec(spec)
    src = _check_posix_path(source_dir, "source_dir")
    out = []
    for name in ALL_UNITS:
        out.append(["install", "-m", "0644",
                    str(PurePosixPath(src) / name),
                    str(PurePosixPath(spec.system_dir) / name)])
    out.append(["systemctl", "daemon-reload"])
    for name in (SERVER_UNIT,) + WORKER_UNITS:
        out.append(["systemd-analyze", "verify",
                    str(PurePosixPath(spec.system_dir) / name)])
    return out


def enable_commands(spec: SystemdSpec) -> list:
    """Enable and start the server and both worker timers.
    This is the start act, kept separate from install by
    the S-412 law (S-348's --enable, S-410's -Start,
    S-411's --load are the same law in native dress)."""
    check_spec(spec)
    return [["systemctl", "enable", "--now",
             SERVER_UNIT, *TIMER_UNITS]]


def disable_commands(spec: SystemdSpec) -> list:
    check_spec(spec)
    return [["systemctl", "disable", "--now",
             SERVER_UNIT, *TIMER_UNITS]]


def status_commands(spec: SystemdSpec) -> list:
    return [["systemctl", "status", SERVER_UNIT],
            ["systemctl", "list-timers", *TIMER_UNITS]]


def restart_commands(spec: SystemdSpec) -> list:
    return [["systemctl", "restart", SERVER_UNIT]]


def verify_commands(spec: SystemdSpec, source_dir: str) -> list:
    """systemd-analyze verify over the repo copies,
    installing nothing (S-348's verify.sh as commands)."""
    check_spec(spec)
    src = _check_posix_path(source_dir, "source_dir")
    return [["systemd-analyze", "verify",
             str(PurePosixPath(src) / name)]
            for name in (SERVER_UNIT,) + WORKER_UNITS]


def uninstall_commands(spec: SystemdSpec) -> list:
    """Disable, remove the unit files, reload. The data
    root and the config directory are never named here:
    uninstalling the service must not delete the instance
    (S-341's export is the data's road out) -- the road
    S-410 and S-411 shipped and Linux lacked until this
    slice (see the module docstring)."""
    check_spec(spec)
    out = disable_commands(spec)
    for name in ALL_UNITS:
        out.append(["rm", "-f",
                    str(PurePosixPath(spec.system_dir) / name)])
    out.append(["systemctl", "daemon-reload"])
    return out


# -- generated scripts -----------------------------------------

def render_install_script(spec: SystemdSpec, source_dir: str) -> str:
    """The sh install script for this spec: root-checked,
    creates the service user and data root, registration
    only -- it enables the units only when the operator
    passes --enable. Mirrors S-348's shipped install.sh
    law for the standing spec."""
    check_spec(spec)
    src = _check_posix_path(source_dir, "source_dir")
    lines = [
        "#!/bin/sh",
        "# Samverk systemd install (S-412). Native only: no Docker.",
        "# Registration only -- units are enabled only when",
        "# you pass --enable, your word.",
        "set -eu",
        "if [ \"$(id -u)\" != \"0\" ]; then echo "
        "\"install.sh: run as root (sudo)\" >&2; exit 1; fi",
        f"if ! id {spec.user_name} >/dev/null 2>&1; then "
        f"useradd --system --home-dir {spec.data_root} "
        f"--shell /usr/sbin/nologin {spec.user_name}; fi",
        f"install -d -o {spec.user_name} -g {spec.group_name} "
        f"-m 0750 {spec.data_root}",
        f"install -d -m 0755 {PurePosixPath(spec.config_path).parent}",
    ]
    for argv in install_commands(spec, src):
        lines.append(render_command_line(argv))
    lines.append("if [ \"${1:-}\" = \"--enable\" ]; then")
    for argv in enable_commands(spec):
        lines.append("  " + render_command_line(argv))
    lines += [
        "  echo 'install.sh: enabled samverk-server.service "
        "and both worker timers'",
        "else",
        "  echo 'install.sh: installed, NOT enabled. Enable "
        "with: sudo sh deploy/systemd/install.sh --enable'",
        "fi",
        "",
    ]
    return "\n".join(lines)


def render_uninstall_script(spec: SystemdSpec) -> str:
    """Disable + remove the unit files. The data root and
    its instance are left standing, and the script says so."""
    lines = [
        "#!/bin/sh",
        "# Samverk systemd uninstall (S-412): removes the",
        "# registration only. The data root and its instance are",
        "# NOT deleted -- export (S-341) is the data's road out.",
        "set -u",
    ]
    for argv in uninstall_commands(spec):
        lines.append(render_command_line(argv))
    lines.append(f"echo 'service removed; data root kept: "
                 f"{spec.data_root}'")
    lines.append("")
    return "\n".join(lines)


# -- the parity table (the S-412 verdict, as data) -------------
#
# Every capability below is one the service model
# promises an operator, on any OS. PARITY_MATRIX records
# the native mechanism per citizen, from the citizens'
# own slices: Linux S-348 + this slice, Windows S-410,
# macOS S-411. The battery proves all three columns cover
# exactly CAPABILITIES, and proves the Linux mechanisms
# against the shipped units and this module. Mechanisms
# differ; the capability set must not.

CAPABILITIES = (
    "one_server_process",
    "dedicated_service_account",
    "starts_at_boot",
    "restart_on_failure",
    "periodic_workers_not_daemons",
    "webhook_every_minute",
    "digest_monday_0600",
    "install_registers_without_starting",
    "start_only_on_operator_word",
    "uninstall_keeps_instance_data",
    "health_answer_defines_installed",
    "native_system_logging",
    "one_config_file_for_all_roles",
    "machine_wide_data_root",
    "first_admin_before_first_start",
    "ssh_via_host_door_not_service",
    "no_fabricated_worker_command",
    "native_install_no_container_no_emulation",
    "least_privilege_sandbox",
)

PARITY_MATRIX = {
    "one_server_process": {
        "linux": "samverk-server.service, Type=simple, runs "
                 "the one S-345 server entry",
        "windows": "the Samverk SCM service runs the one "
                   "S-345 server entry via the service host",
        "macos": "org.samverk.server runs the one S-345 "
                 "server entry directly under launchd"},
    "dedicated_service_account": {
        "linux": "system user/group samverk (nologin), "
                 "created by the install script",
        "windows": "virtual service account NT SERVICE\\Samverk",
        "macos": "dedicated service user _samverk"},
    "starts_at_boot": {
        "linux": "WantedBy=multi-user.target once enabled",
        "windows": "SCM start mode auto once registered "
                   "and started by the operator",
        "macos": "system LaunchDaemon, RunAtLoad once "
                 "bootstrapped by the operator"},
    "restart_on_failure": {
        "linux": "Restart=on-failure, RestartSec=5s (S-348)",
        "windows": "SCM failure actions restart/60000 x3, "
                   "counter resets after 86400 s",
        "macos": "KeepAlive on unsuccessful exit, "
                 "ThrottleInterval 60"},
    "periodic_workers_not_daemons": {
        "linux": "workers are Type=oneshot units; timers "
                 "carry the cadence",
        "windows": "workers are one-shot command lines for "
                   "the operator's Task Scheduler entries",
        "macos": "workers are one-shot launchd jobs; "
                 "schedule keys carry the cadence"},
    "webhook_every_minute": {
        "linux": "samverk-webhook-worker.timer "
                 "OnUnitActiveSec=1min",
        "windows": "worker command rendered for a 1-minute "
                   "Task Scheduler entry",
        "macos": "org.samverk.webhook-delivery "
                 "StartInterval 60"},
    "digest_monday_0600": {
        "linux": "samverk-digest-worker.timer "
                 "OnCalendar=Mon 06:00, Persistent=true",
        "windows": "worker command rendered for a Monday "
                   "06:00 Task Scheduler entry",
        "macos": "org.samverk.weekly-digest "
                 "StartCalendarInterval Mon 06:00"},
    "install_registers_without_starting": {
        "linux": "install.sh installs + verifies, enables "
                 "nothing without --enable",
        "windows": "the install script registers, starts "
                   "nothing without -Start",
        "macos": "install.sh copies + lints, bootstraps "
                 "nothing without --load"},
    "start_only_on_operator_word": {
        "linux": "systemctl enable --now, via install.sh "
                 "--enable or by hand",
        "windows": "sc.exe start, via the install script "
                   "-Start or by hand",
        "macos": "launchctl bootstrap, via install.sh "
                 "--load or by hand"},
    "uninstall_keeps_instance_data": {
        "linux": "uninstall.sh (S-412) disables + removes "
                 "units, keeps data root and config",
        "windows": "the uninstall script deletes the "
                   "service registration, keeps the data root",
        "macos": "uninstall.sh boots out + removes plists, "
                 "keeps the data root"},
    "health_answer_defines_installed": {
        "linux": "walk step 8: systemctl shows active and "
                 "GET /healthz answers 200, or it is not "
                 "installed",
        "windows": "walk step 8: sc query shows RUNNING and "
                   "GET /healthz answers 200, or it is not "
                   "installed",
        "macos": "walk step 8: launchctl print shows running "
                 "and GET /healthz answers 200, or it is not "
                 "installed"},
    "native_system_logging": {
        "linux": "the journal: StandardOutput=journal with "
                 "SyslogIdentifier per unit",
        "windows": "the service host's child inherits the "
                   "service's stdout/stderr, routed by the "
                   "operator (Event Log / file)",
        "macos": "log files inside the data root, named in "
                 "the plist (launchd has no journal)"},
    "one_config_file_for_all_roles": {
        "linux": "/etc/samverk/samverk.ini (S-346's one "
                 "file, in the FHS config place)",
        "windows": "samverk.ini inside the data root "
                   "(S-346's one file)",
        "macos": "samverk.ini inside the data root "
                 "(S-346's one file)"},
    "machine_wide_data_root": {
        "linux": "/var/lib/samverk",
        "windows": "C:\\ProgramData\\Samverk",
        "macos": "/Library/Application Support/Samverk"},
    "first_admin_before_first_start": {
        "linux": "walk step 5: S-349's install walk stands "
                 "before the units are enabled",
        "windows": "walk step 5: S-349's install walk stands "
                   "before the service is registered",
        "macos": "walk step 5: S-349's install walk stands "
                 "before the daemon is loaded"},
    "ssh_via_host_door_not_service": {
        "linux": "the host sshd runs samverk.ssh_serve as a "
                 "forced command; no unit listens for SSH",
        "windows": "the host's SSH door runs the forced "
                   "command; the service never listens for SSH",
        "macos": "the host's SSH door runs the forced "
                 "command; the daemon never listens for SSH"},
    "no_fabricated_worker_command": {
        "linux": "mirror-sync renders no command and ships "
                 "no unit (no standalone CLI exists)",
        "windows": "mirror-sync renders no worker command "
                   "(no standalone CLI exists)",
        "macos": "mirror-sync renders no command and ships "
                 "no plist (no standalone CLI exists)"},
    "native_install_no_container_no_emulation": {
        "linux": "systemd units + POSIX sh install; specs "
                 "routing through Docker paths are refused",
        "windows": "sc.exe + stdlib service host; Docker/WSL "
                   "paths are refused",
        "macos": "launchctl + plistlib (stdlib); Docker "
                 "paths are refused"},
    "least_privilege_sandbox": {
        "linux": "systemd hardening baseline on every unit "
                 "(ProtectSystem=strict, only the data root "
                 "writable, empty capability set)",
        "windows": "the virtual account can write only the "
                   "data root (the walk's icacls grant)",
        "macos": "the service user owns only the data root "
                 "(the walk's chown step)"},
}

CITIZENS = ("linux", "windows", "macos")


def parity_capabilities(citizen: str) -> frozenset:
    """The capability set one citizen provides, read from
    the matrix: a citizen provides a capability when its
    matrix cell names a mechanism for it."""
    if citizen not in CITIZENS:
        raise LinuxServiceError("unknown_citizen", repr(citizen))
    return frozenset(cap for cap, cells in PARITY_MATRIX.items()
                     if cells.get(citizen))


# -- the install walk (Part XVIII's standard) ------------------
#
# Every step names its failure mode and its remedy, exactly
# as S-349's install walk and the S-410/S-411 walks do;
# docs/LINUX_SERVICE.md carries these same steps, and the
# battery pins the two together. Steps 1-6 and 8 keep the
# other citizens' step names where the act is the same act;
# step 7 is the citizen's own registration act.

INSTALL_WALK_STEPS = (
    {"name": "root_shell",
     "title": "A root shell (sudo)",
     "action": "Work from an administrator account; the "
               "install script refuses to run without root "
               "(`id -u` must be 0 under sudo). Creating the "
               "system user, writing /etc/systemd/system and "
               "enabling units are root acts by Linux's own law.",
     "failure": "not_root",
     "failure_words": "install answers 'Permission denied' "
                      "in /etc/systemd/system, or systemctl "
                      "answers 'Access denied'.",
     "remedy": "Re-run under `sudo`; service registration is "
               "an administrator act on Linux as on every OS "
               "Samverk ships a service for."},
    {"name": "python_runtime",
     "title": "Python 3.11 or newer, natively installed",
     "action": "Run `which python3` and note the absolute "
               "path; the shipped units name /usr/bin/python3. "
               "Confirm `python3 --version` is 3.11+.",
     "failure": "python_missing",
     "failure_words": "no python3 on PATH, or a version "
                      "older than 3.11.",
     "remedy": "Install Python 3.11+ with the distribution's "
               "own package manager -- a native install, "
               "never through Docker (the spec refuses those "
               "paths) -- then re-check `which python3`."},
    {"name": "package_installed",
     "title": "The samverk package imports under that interpreter",
     "action": "From the checkout: `python3 -m pip install .` "
               "then `python3 -c \"import samverk\"`. The one "
               "admitted dependency (cryptography) installs "
               "with it.",
     "failure": "package_not_importable",
     "failure_words": "ModuleNotFoundError for samverk or "
                      "cryptography under the very interpreter "
                      "the units will run.",
     "remedy": "Install into the same interpreter the units "
               "name (never a second one); the service runs "
               "that interpreter or nothing."},
    {"name": "data_root_and_config",
     "title": "Data root and the one config file",
     "action": "Create the data root (default /var/lib/"
               "samverk, owned by the service user) and place "
               "samverk.ini in /etc/samverk with data_root "
               "pointing at the same root (S-346/S-347); the "
               "install script does both and never overwrites "
               "a standing config.",
     "failure": "data_root_unwritable",
     "failure_words": "the directory cannot be created, or "
                      "the config resolves to a different root "
                      "than the walk was given.",
     "remedy": "Fix the path in samverk.ini so config and "
               "spec name one root; never let the service open "
               "a different database than the walk initialised."},
    {"name": "first_admin_walk",
     "title": "First admin, by S-349's install walk",
     "action": "Run the S-349 install walk against the data "
               "root (docs/INSTALL_WALK.md) so the database, "
               "instance key, and first admin stand before the "
               "units are ever enabled.",
     "failure": "first_admin_refused",
     "failure_words": "the walk stops at a named step -- its "
                      "own guide names each failure mode and "
                      "remedy; the service is not enabled over a "
                      "half-walked instance.",
     "remedy": "Remedy the walk's named step and re-run the "
               "walk (it is idempotent); only then install "
               "the units."},
    {"name": "service_user_rights",
     "title": "The service user can write the data root",
     "action": "The install script creates the dedicated "
               "system user samverk (nologin) if it is absent "
               "and gives it ownership of the data root only: "
               "`install -d -o samverk -g samverk -m 0750 "
               "/var/lib/samverk`.",
     "failure": "service_user_or_access",
     "failure_words": "the server exits at once and the "
                      "journal shows PermissionError, or "
                      "systemctl shows a non-zero exit with the "
                      "database unwritable.",
     "remedy": "Re-run the ownership step for exactly the "
               "data root and confirm no other directory was "
               "opened up; the account needs nothing else."},
    {"name": "unit_install",
     "title": "Install the units (installs, enables nothing)",
     "action": "Run deploy/systemd/install.sh as root: it "
               "checks root, creates the service user, "
               "installs the five units into "
               "/etc/systemd/system, writes the example "
               "config only if none exists, runs "
               "systemctl daemon-reload, and verifies the "
               "installed service units with systemd-analyze "
               "verify. Nothing is enabled or started.",
     "failure": "unit_install_failed",
     "failure_words": "systemd-analyze verify rejects a unit "
                      "(it is not the directives this module "
                      "renders), or the copy into "
                      "/etc/systemd/system is refused.",
     "remedy": "For a verify failure, restore the shipped "
               "unit from the checkout rather than editing "
               "the installed copy -- this module is the one "
               "seam; for a refused copy, return to the "
               "root_shell step."},
    {"name": "enable_and_health",
     "title": "Enable, and the health answer",
     "action": "`sudo sh deploy/systemd/install.sh "
               "--enable` (or `systemctl enable --now "
               "samverk-server.service "
               "samverk-webhook-worker.timer "
               "samverk-digest-worker.timer` by hand), then "
               "`systemctl status samverk-server` shows "
               "active and GET /healthz on the configured "
               "host/port answers 200 with the Samverk payload.",
     "failure": "service_enable_failed",
     "failure_words": "enable answers an error, status shows "
                      "the unit failed or in a restart loop, "
                      "or /healthz does not answer -- the port "
                      "may be taken.",
     "remedy": "Read the unit's journal (`journalctl -u "
               "samverk-server`), free the named port or "
               "choose another in samverk.ini, and enable "
               "again; a service that is not answering "
               "/healthz is not installed, whatever "
               "systemctl says."},
)
