"""S-411 -- macOS service: Samverk under launchd.

Roadmap line: Samverk installs and runs under launchd, with
the install walk documented to the same standard (Part
XVIII's standard, as S-410's Windows slice kept it).

THE SHAPE
- One daemon, for the one server. S-345's run model has
  exactly one long-running process -- the server (web, API,
  git smart HTTP, LFS HTTP) -- so exactly one always-on
  launchd job exists: the system daemon labelled
  ``org.samverk.server``. The periodic workers are NOT
  daemons on any OS (S-348 ships them as systemd oneshot
  units plus timers); here the two workers S-348 ships
  units for (webhook delivery, weekly digest) ship as
  launchd jobs whose calendars carry the cadence, and
  every worker's one-shot command line is rendered from
  the topology -- the mirror-sync worker, which has no
  standalone CLI yet, is named honestly as unrenderable
  instead of being dressed in a command that does not
  exist.
- No service host. The Windows slice needed a stdlib host
  because the SCM will only run a program that speaks its
  protocol; launchd supervises an ordinary process
  directly, so the daemon's ProgramArguments ARE S-345's
  server entry -- there is no wrapper to write and none
  is invented.
- Native road only. Jobs are registered with ``launchctl``
  (a macOS inbox tool) from plist files rendered by this
  module and shipped under ``deploy/launchd/``. No Docker,
  no third-party service wrapper, and no new dependency:
  the plists are built with ``plistlib`` from the standard
  library, so the admitted-dependency register (S-407) is
  untouched.
- Least privilege. The daemon runs as the dedicated
  service user ``_samverk`` (the underscore prefix is
  macOS's own convention for service accounts, e.g.
  ``_www``) -- never as root beyond what launchd itself
  does to start it, and with write access only to the
  data root (the install walk's chown step).
- Restart is declared, not hoped for: ``KeepAlive`` on
  unsuccessful exit plus ``ThrottleInterval`` 60 -- the
  launchd analogue of S-410's SCM restart-after-60 s law
  and S-348's ``Restart=on-failure`` / ``RestartSec=5s``
  family posture, at the 60-second interval S-410 set.

THE LAW
1. One seam. Every launchd fact -- label, user, restart
   posture, the program arguments, the install / load /
   unload / status command lines, the generated scripts,
   the install walk -- is defined here and rendered from
   `LaunchdSpec`; nothing else in the tree spells a
   launchctl line or a plist key.
2. Refuse, never guess. A spec whose paths are not
   absolute POSIX paths, or that routes the install
   through a Docker path, is refused with a stable
   machine-readable `reason` (the S-013 / S-408 / S-409 /
   S-410 ValueError convention). Samverk under Docker is
   a different deployment than this slice's promise, and
   it is refused rather than relabelled.
3. Install loads nothing by itself. The generated install
   script copies and lints the plists and stops there;
   loading (bootstrapping) the daemon is the operator's
   word (``--load``), exactly as S-348's install.sh
   enables nothing without ``--enable`` and S-410's
   script starts nothing without ``-Start``.

HONEST REMAINDER -- NOT PROVEN ON MACOS
This slice was built and tested on Linux. What is proven
here: the spec, the validation refusals, the rendered
plists and launchctl command lines and scripts, and the
shipped plist files' identity with the rendered ones, all
as data and pure functions. What is NOT PROVEN: a real
macOS host install, launchd bootstrap, KeepAlive restart,
or health answer -- no Mac ran any of it. The macOS cells
of the support matrix stay NOT PROVEN until a counted run
on a real Mac flips them (S-416's gate owns that claim).
docs/MACOS_SERVICE.md carries the same words.

No migration and no new taxonomy event: the schema stands
at 140 and the taxonomy at 142. A launchd registration is
host state, not instance state -- nothing here touches
the database.
"""
from __future__ import annotations

import plistlib
import shlex
from dataclasses import dataclass
from pathlib import PurePosixPath

from .run_model import build_topology

__all__ = [
    "SERVER_LABEL", "DISPLAY_NAME", "DESCRIPTION", "SERVICE_USER",
    "DAEMON_DOMAIN", "DAEMONS_DIR", "THROTTLE_INTERVAL_SECONDS",
    "DEFAULT_DATA_ROOT", "DEFAULT_PYTHON",
    "MacosServiceError", "LaunchdSpec", "build_service_spec",
    "validate_spec", "check_spec", "server_command", "worker_commands",
    "server_plist", "worker_plist", "render_plist",
    "install_commands", "load_commands", "unload_commands",
    "status_commands", "uninstall_commands", "render_command_line",
    "render_install_script", "render_uninstall_script",
    "restart_commands", "worker_label", "SHIPPED_WORKERS",
    "INSTALL_WALK_STEPS",
]

#: The one always-on daemon. launchd labels are reverse-DNS
#: by macOS convention; the label is also the plist's file
#: name (``<label>.plist``) and its bootstrap target tail.
SERVER_LABEL = "org.samverk.server"
DISPLAY_NAME = "Samverk"
DESCRIPTION = (
    "Samverk sovereign version-control forge: web, API, "
    "Git HTTP and LFS HTTP (run model S-345).")
#: The dedicated service user (macOS's underscore convention
#: for service accounts). The daemon never runs as root.
SERVICE_USER = "_samverk"
#: System daemons live in launchd's `system` domain and are
#: bootstrapped from this directory -- never a user agent:
#: the server must run at boot, before any login, exactly as
#: S-348's units hang off multi-user.target.
DAEMON_DOMAIN = "system"
DAEMONS_DIR = "/Library/LaunchDaemons"
#: KeepAlive restarts are throttled to one per 60 s -- the
#: launchd analogue of S-410's restart/60000 recovery law.
THROTTLE_INTERVAL_SECONDS = 60
#: The machine-wide analogue of the platform seam's per-user
#: macOS default (~/Library/Application Support/Samverk): a
#: system daemon has no operator home for the per-user root
#: to mean anything under, so the root is the machine tree.
DEFAULT_DATA_ROOT = "/Library/Application Support/Samverk"
#: Where a Homebrew-free system python3 commonly stands; the
#: walk finds the operator's real interpreter and the spec is
#: built from it -- this default is a starting point, named
#: as such, never a claim about any particular Mac.
DEFAULT_PYTHON = "/usr/bin/python3"

_REFUSED_COMPONENTS = ("docker",)


class MacosServiceError(ValueError):
    """A spec refused by the S-411 law; `reason` is stable."""

    def __init__(self, reason, detail=""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


def _check_posix_path(value, what):
    """Validate one absolute, native POSIX path string."""
    if not isinstance(value, str) or not value.strip():
        raise MacosServiceError("path_missing", f"{what} is empty")
    if "\x00" in value or any(ord(c) < 0x20 for c in value):
        raise MacosServiceError(
            "control_character", f"{what} carries a control character")
    p = PurePosixPath(value)
    if not p.is_absolute():
        raise MacosServiceError(
            "path_not_absolute",
            f"{what} must be an absolute POSIX path, got {value!r}")
    for part in (part.lower() for part in p.parts):
        if part in _REFUSED_COMPONENTS or "docker" in part:
            raise MacosServiceError(
                "container_path",
                f"{what} routes through {part!r}: Samverk under "
                "launchd is never installed through a Docker path")
    return str(p)


@dataclass(frozen=True)
class LaunchdSpec:
    """The whole service definition as data: label, user,
    restart posture, and the three paths everything else is
    rendered from (the interpreter, the data root, the
    config)."""

    python_exe: str
    data_root: str
    config_path: str
    label: str = SERVER_LABEL
    user_name: str = SERVICE_USER
    domain: str = DAEMON_DOMAIN
    daemons_dir: str = DAEMONS_DIR
    throttle_interval: int = THROTTLE_INTERVAL_SECONDS

    @property
    def db_path(self) -> str:
        """The instance database inside the data root (S-347's
        one tree: <data_root>/samverk.db)."""
        return str(PurePosixPath(self.data_root) / "samverk.db")

    @property
    def plist_path(self) -> str:
        """Where the server plist installs: launchd's own law
        names the file for the label it carries."""
        return str(PurePosixPath(self.daemons_dir)
                   / (self.label + ".plist"))

    @property
    def target(self) -> str:
        """The launchctl service target: <domain>/<label>."""
        return f"{self.domain}/{self.label}"

    @property
    def program_arguments(self) -> list:
        """What launchd runs: the interpreter running S-345's
        server entry with this spec's config. No host, no
        wrapper -- launchd supervises the process itself."""
        return server_command(self)

    @property
    def stdout_path(self) -> str:
        return str(PurePosixPath(self.data_root) / "logs"
                   / "samverk-server.out.log")

    @property
    def stderr_path(self) -> str:
        return str(PurePosixPath(self.data_root) / "logs"
                   / "samverk-server.err.log")


def build_service_spec(python_exe=DEFAULT_PYTHON,
                       data_root=DEFAULT_DATA_ROOT,
                       config_path=None) -> LaunchdSpec:
    """Compose and validate a spec. `python_exe` is the
    absolute path of the interpreter that will run Samverk
    (the walk's `which python3` step finds it); the config
    defaults to samverk.ini inside the data root, S-346's
    one config file."""
    python_exe = _check_posix_path(python_exe, "python_exe")
    data_root = _check_posix_path(data_root, "data_root")
    if config_path is None:
        config_path = str(PurePosixPath(data_root) / "samverk.ini")
    config_path = _check_posix_path(config_path, "config_path")
    spec = LaunchdSpec(python_exe=python_exe, data_root=data_root,
                       config_path=config_path)
    check_spec(spec)
    return spec


def server_command(spec: LaunchdSpec) -> list:
    """The daemon's program: S-345's server role entry
    (``-m samverk serve``) with this spec's config."""
    return [spec.python_exe, "-m", "samverk", "serve",
            "--config", spec.config_path]


def validate_spec(spec: LaunchdSpec) -> list:
    """Judge a spec against the S-411 laws; plain-words
    problems, empty when the spec stands. Pure: no I/O."""
    problems: list = []
    for value, what in ((spec.python_exe, "python_exe"),
                        (spec.data_root, "data_root"),
                        (spec.config_path, "config_path")):
        try:
            _check_posix_path(value, what)
        except MacosServiceError as exc:
            problems.append(f"{what}: {exc}")
    if spec.label != SERVER_LABEL:
        problems.append(
            f"the label is {spec.label!r}, not {SERVER_LABEL!r}: "
            "the plist file name and the bootstrap target are "
            "derived from the label, so a renamed daemon "
            "silently becomes a different service")
    if spec.user_name != SERVICE_USER:
        problems.append(
            f"the user is {spec.user_name!r}, not the dedicated "
            f"service user {SERVICE_USER!r}: the daemon must "
            "not run as root or as an operator's login user")
    if spec.domain != DAEMON_DOMAIN:
        problems.append(
            f"the domain is {spec.domain!r}, not {DAEMON_DOMAIN!r}: "
            "a user agent starts at login; the server must "
            "start at boot, before any login")
    if spec.daemons_dir != DAEMONS_DIR:
        problems.append(
            f"the daemons directory is {spec.daemons_dir!r}, "
            f"not {DAEMONS_DIR!r}: system daemons install "
            "there and nowhere else")
    if spec.throttle_interval != THROTTLE_INTERVAL_SECONDS:
        problems.append("the throttle interval differs from the "
                        "declared 60-second restart law")
    server = build_topology().server
    if not server.entry.endswith("samverk serve"):
        problems.append(
            "the run model's server entry no longer ends in "
            "'samverk serve': server_command would drift from "
            "the topology it claims to serve")
    return problems


def check_spec(spec: LaunchdSpec) -> LaunchdSpec:
    """Raise MacosServiceError on the first problem found."""
    problems = validate_spec(spec)
    if problems:
        raise MacosServiceError("invalid_spec", problems[0])
    return spec


# -- plist rendering -----------------------------------------
#
# A plist is data. Every job is a dict built here and dumped
# with plistlib; the files under deploy/launchd/ are those
# dumps for the standing spec, and the battery keeps the
# files and the dicts from drifting apart.

def server_plist(spec: LaunchdSpec) -> dict:
    """The server daemon's plist as data: run at load,
    kept alive on unsuccessful exit only (a clean stop is
    the operator's word and stays stopped), throttled
    restarts, the data root as working directory, and the
    server's output to log files inside the data root --
    launchd has no journal, so the files are named here
    rather than a second log law being invented."""
    check_spec(spec)
    return {
        "Label": spec.label,
        "ProgramArguments": spec.program_arguments,
        "UserName": spec.user_name,
        "WorkingDirectory": spec.data_root,
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": spec.throttle_interval,
        "StandardOutPath": spec.stdout_path,
        "StandardErrorPath": spec.stderr_path,
        "ProcessType": "Standard",
    }


#: Worker cadences, mirroring S-348's timers exactly: the
#: webhook timer ticks every minute; the digest timer fires
#: Monday 06:00 (launchd Weekday 1 is Monday).
_WORKER_SCHEDULES = {
    "webhook-delivery": ("StartInterval", 60),
    "weekly-digest": ("StartCalendarInterval",
                      {"Weekday": 1, "Hour": 6, "Minute": 0}),
}

#: The workers that ship plists: exactly S-348's shipped set.
SHIPPED_WORKERS = tuple(_WORKER_SCHEDULES)


def worker_label(role_name: str) -> str:
    return f"org.samverk.{role_name}"


def worker_plist(spec: LaunchdSpec, role_name: str) -> dict:
    """One shipped worker's plist as data: a one-shot job
    (no RunAtLoad, no KeepAlive -- the schedule key carries
    the cadence, exactly as a systemd timer does) running
    the worker's real entry with this spec's database and
    data root substituted. Raises MacosServiceError for a
    worker that ships no plist."""
    check_spec(spec)
    argv = dict((n, a) for n, a, _ in worker_commands(spec))
    if role_name not in _WORKER_SCHEDULES or argv.get(role_name) is None:
        raise MacosServiceError(
            "worker_not_shipped",
            f"{role_name!r} ships no launchd plist: either it "
            "has no standalone CLI or it is outside S-348's "
            "shipped worker set")
    key, schedule = _WORKER_SCHEDULES[role_name]
    return {
        "Label": worker_label(role_name),
        "ProgramArguments": argv[role_name],
        "UserName": spec.user_name,
        "WorkingDirectory": spec.data_root,
        key: schedule,
        "StandardOutPath": str(PurePosixPath(spec.data_root)
                               / "logs" / f"{role_name}.out.log"),
        "StandardErrorPath": str(PurePosixPath(spec.data_root)
                                 / "logs" / f"{role_name}.err.log"),
    }


def render_plist(job: dict) -> str:
    """Render one job dict as plist XML text (plistlib,
    sorted keys): the exact bytes the deploy files carry."""
    return plistlib.dumps(job, sort_keys=True).decode("utf-8")


def worker_commands(spec: LaunchdSpec) -> tuple:
    """Every worker in S-345's topology as a one-shot
    command line for this spec. Each entry is (role name,
    argv or None, words): a worker with no standalone CLI
    (mirror-sync) renders None and says why, never a
    fabricated command."""
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


# -- launchctl command rendering ------------------------------

def render_command_line(argv) -> str:
    """Render an argv list as one POSIX shell line (shlex
    quoting). Pure string law; identical on every OS."""
    return shlex.join([str(a) for a in argv])


def install_commands(spec: LaunchdSpec, source_dir: str) -> list:
    """Copy the shipped plists into /Library/LaunchDaemons
    with root ownership and 0644, and lint each installed
    copy. Registration only -- nothing here loads a job:
    bootstrap is the operator's word (load_commands)."""
    check_spec(spec)
    src = _check_posix_path(source_dir, "source_dir")
    names = [spec.label] + [worker_label(n) for n in SHIPPED_WORKERS]
    out = []
    for name in names:
        dst = str(PurePosixPath(spec.daemons_dir) / (name + ".plist"))
        out.append(["install", "-o", "root", "-g", "wheel",
                    "-m", "0644",
                    str(PurePosixPath(src) / (name + ".plist")), dst])
        out.append(["plutil", "-lint", dst])
    return out


def load_commands(spec: LaunchdSpec) -> list:
    """Bootstrap the server daemon (RunAtLoad starts it) and
    the two worker jobs into the system domain. This is the
    start act, kept separate from install by the S-411 law."""
    check_spec(spec)
    names = [spec.label] + [worker_label(n) for n in SHIPPED_WORKERS]
    return [["launchctl", "bootstrap", spec.domain,
             str(PurePosixPath(spec.daemons_dir) / (n + ".plist"))]
            for n in names]


def unload_commands(spec: LaunchdSpec) -> list:
    """Boot the jobs out of the system domain (they stop;
    the registrations on disk remain)."""
    check_spec(spec)
    names = [spec.label] + [worker_label(n) for n in SHIPPED_WORKERS]
    return [["launchctl", "bootout", f"{spec.domain}/{n}"]
            for n in names]


def status_commands(spec: LaunchdSpec) -> list:
    return [["launchctl", "print", spec.target]]


def restart_commands(spec: LaunchdSpec) -> list:
    return [["launchctl", "kickstart", "-k", spec.target]]


def uninstall_commands(spec: LaunchdSpec) -> list:
    """Boot out, then remove the plist files. The data root
    is never named here: uninstalling the service must not
    delete the instance (S-341's export is the data's road
    out)."""
    names = [spec.label] + [worker_label(n) for n in SHIPPED_WORKERS]
    out = unload_commands(spec)
    for n in names:
        out.append(["rm", "-f", str(PurePosixPath(spec.daemons_dir)
                                    / (n + ".plist"))])
    return out


# -- the install walk (Part XVIII's standard) -----------------
#
# Every step names its failure mode and its remedy, exactly
# as S-349's install walk and S-410's walk do;
# docs/MACOS_SERVICE.md carries these same steps, and the
# battery pins the two together.

INSTALL_WALK_STEPS = (
    {"name": "root_shell",
     "title": "A root shell (sudo)",
     "action": "Work from an administrator account; the "
               "generated install script refuses to run "
               "without root (`id -u` must be 0 under sudo). "
               "Copying into /Library/LaunchDaemons and "
               "bootstrapping the system domain are root acts "
               "by macOS's own law.",
     "failure": "not_root",
     "failure_words": "install answers 'Permission denied' "
                      "in /Library/LaunchDaemons, or launchctl "
                      "bootstrap answers 'Permission denied' "
                      "for the system domain.",
     "remedy": "Re-run under `sudo` from an administrator "
               "account; service registration is an "
               "administrator act on macOS as on every OS "
               "Samverk ships a service for."},
    {"name": "python_runtime",
     "title": "Python 3.11 or newer, natively installed",
     "action": "Run `which python3` and note the absolute "
               "path; it becomes the spec's python_exe. "
               "Confirm `python3 --version` is 3.11+. The "
               "/usr/bin/python3 that ships with the Xcode "
               "Command Line Tools is a real interpreter once "
               "the tools are installed; a Homebrew or "
               "python.org interpreter is equally native.",
     "failure": "python_missing",
     "failure_words": "no python3 on PATH, the Command Line "
                      "Tools stub that only pops the install "
                      "dialogue, or a version older than 3.11.",
     "remedy": "Install the Xcode Command Line Tools "
               "(`xcode-select --install`) or Python 3.11+ "
               "from python.org or Homebrew -- a native macOS "
               "install, never through Docker (the spec "
               "refuses those paths) -- then re-check "
               "`which python3`."},
    {"name": "package_installed",
     "title": "The samverk package imports under that interpreter",
     "action": "From the checkout: `python3 -m pip install .` "
               "then `python3 -c \"import samverk\"`. The one "
               "admitted dependency (cryptography) installs "
               "with it.",
     "failure": "package_not_importable",
     "failure_words": "ModuleNotFoundError for samverk or "
                      "cryptography under the very interpreter "
                      "the daemon will run.",
     "remedy": "Install into the same interpreter named in "
               "the spec (never a second one); the daemon "
               "runs that interpreter or nothing."},
    {"name": "data_root_and_config",
     "title": "Data root and the one config file",
     "action": "Create the data root (default /Library/"
               "Application Support/Samverk) with its logs "
               "directory, and place samverk.ini in it with "
               "data_root pointing at the same root "
               "(S-346/S-347).",
     "failure": "data_root_unwritable",
     "failure_words": "the directory cannot be created, or "
                      "the config resolves to a different root "
                      "than the walk was given.",
     "remedy": "Fix the path in samverk.ini so config and "
               "spec name one root; never let the daemon open "
               "a different database than the walk "
               "initialised."},
    {"name": "first_admin_walk",
     "title": "First admin, by S-349's install walk",
     "action": "Run the S-349 install walk against the data "
               "root (docs/INSTALL_WALK.md) so the database, "
               "instance key, and first admin stand before the "
               "daemon ever loads.",
     "failure": "first_admin_refused",
     "failure_words": "the walk stops at a named step -- its "
                      "own guide names each failure mode and "
                      "remedy; the daemon is not loaded over a "
                      "half-walked instance.",
     "remedy": "Remedy the walk's named step and re-run the "
               "walk (it is idempotent); only then install "
               "the plists."},
    {"name": "service_user_rights",
     "title": "The service user can write the data root",
     "action": "Create the dedicated service user if it is "
               "absent (System Settings > Users & Groups, or "
               "`sysadminctl`), named _samverk, then give it "
               "ownership of the data root only: "
               "`chown -R _samverk '<data_root>'` with the "
               "walk's chosen root.",
     "failure": "service_user_or_access",
     "failure_words": "the daemon exits at once and its "
                      "stderr log shows PermissionError, or "
                      "launchctl print shows a non-zero last "
                      "exit code with the database unwritable.",
     "remedy": "Re-run the chown for exactly the data root "
               "and confirm no other directory was opened up; "
               "the account needs nothing else."},
    {"name": "plist_install",
     "title": "Install the plists (installs, loads nothing)",
     "action": "Run deploy/launchd/install.sh as root: it "
               "checks root, verifies each shipped plist "
               "parses as data, copies the three plists into "
               "/Library/LaunchDaemons (root:wheel, 0644), "
               "and lints the installed copies with plutil. "
               "Nothing is bootstrapped.",
     "failure": "plist_install_failed",
     "failure_words": "plutil -lint rejects a plist (it is "
                      "not the bytes render_plist produced), "
                      "or the copy into /Library/LaunchDaemons "
                      "is refused.",
     "remedy": "For a lint failure, restore the shipped "
               "plist from the checkout rather than editing "
               "the installed copy -- the module is the one "
               "seam; for a refused copy, return to the "
               "root_shell step."},
    {"name": "load_and_health",
     "title": "Load, and the health answer",
     "action": "`sudo sh deploy/launchd/install.sh --load` "
               "(or `launchctl bootstrap system "
               "/Library/LaunchDaemons/org.samverk.server.plist` "
               "by hand), then `launchctl print "
               "system/org.samverk.server` shows state = "
               "running and GET /healthz on the configured "
               "host/port answers 200 with the Samverk payload.",
     "failure": "daemon_load_failed",
     "failure_words": "bootstrap answers an error (a job of "
                      "the same label already loaded), print "
                      "shows the job not running or in a "
                      "respawn loop, or /healthz does not "
                      "answer -- the port may be taken.",
     "remedy": "For an already-loaded job, bootout first "
               "rather than loading a second; read the "
               "daemon's stderr log inside the data root, "
               "free the named port or choose another in "
               "samverk.ini, and load again; a daemon that "
               "is not answering /healthz is not installed, "
               "whatever launchctl says."},
)


# -- generated scripts -----------------------------------------

def render_install_script(spec: LaunchdSpec, source_dir: str) -> str:
    """The sh install script for this spec: root-checked,
    registration only -- it bootstraps the jobs only when
    the operator passes --load. Its plist verification is
    a python3 plistlib parse, so it judges the plists the
    same way on macOS and anywhere else. NOT PROVEN on a
    real Mac (see the module docstring)."""
    check_spec(spec)
    src = _check_posix_path(source_dir, "source_dir")
    lines = [
        "#!/bin/sh",
        "# Samverk launchd install (S-411). Native only: no Docker.",
        "# Registration only -- the jobs are bootstrapped only",
        "# when you pass --load, your word.",
        "set -eu",
        "if [ \"$(id -u)\" != \"0\" ]; then echo "
        "\"install.sh: run as root (sudo)\" >&2; exit 1; fi",
        f"SRC={shlex.quote(src)}",
    ]
    for argv in install_commands(spec, src):
        lines.append(render_command_line(argv))
    lines.append("if [ \"${1:-}\" = \"--load\" ]; then")
    for argv in load_commands(spec):
        lines.append("  " + render_command_line(argv))
    lines += [
        "  echo 'install.sh: loaded org.samverk.server and "
        "the worker jobs'",
        "else",
        "  echo 'install.sh: installed, NOT loaded. Load with: "
        "sudo sh deploy/launchd/install.sh --load'",
        "fi",
        "",
    ]
    return "\n".join(lines)


def render_uninstall_script(spec: LaunchdSpec) -> str:
    """Boot out + remove the plist files. The data root is
    left standing, deliberately, and the script says so."""
    lines = [
        "#!/bin/sh",
        "# Samverk launchd uninstall (S-411): removes the",
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
