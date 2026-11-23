"""S-410 -- Windows service: Samverk as a native Windows service.

Roadmap line: Samverk installs and runs as a native Windows
service (no Docker, no WSL requirement), with the install walk
documented to Part XVIII's standard.

THE SHAPE
- One service, for the one server. S-345's run model has exactly
  one long-running process -- the server (web, API, git smart
  HTTP, LFS HTTP) -- so exactly one Windows service exists:
  ``Samverk``. The periodic workers are NOT services on any OS
  (S-348 ships them as systemd oneshot units plus timers); here
  their one-shot command lines are rendered for the operator's
  own Task Scheduler entries, and the mirror-sync worker, which
  has no standalone CLI yet, is named honestly as unrenderable
  instead of being dressed in a command that does not exist.
- Native road only. The service is registered with the Service
  Control Manager through ``sc.exe`` (a Windows inbox tool) and
  run by ``samverk/windows_service_host.py``, a stdlib-only
  service host that speaks to the SCM through ``ctypes``. No
  Docker, no WSL, no third-party service wrapper, and no new
  dependency: the admitted-dependency register (S-407) is
  untouched, because the host needs nothing beyond the standard
  library Samverk already runs on.
- Least privilege. The service runs as the virtual service
  account ``NT SERVICE\\Samverk`` -- an account Windows itself
  provisions at service creation, with no password to store,
  rotate, or leak, and no rights beyond what the operator grants
  it on the data root (the install walk's icacls step).
- Recovery is declared, not hoped for: the SCM failure actions
  restart the service after 60 seconds, three times, with the
  failure counter resetting after a day.

THE LAW
1. One seam. Every Windows-service fact -- name, account, start
   mode, recovery, the binPath, the install / uninstall / status
   command lines, the generated scripts, the install walk -- is
   defined here and rendered from `ServiceSpec`; nothing else in
   the tree spells an sc.exe line.
2. Refuse, never guess. A spec whose paths are not absolute
   Windows paths, or that routes the install through a Docker or
   WSL path, is refused with a stable machine-readable `reason`
   (the S-013 / S-408 / S-409 ValueError convention). Samverk
   under Docker or WSL is a different deployment than this
   slice's promise, and it is refused rather than relabelled.
3. Install starts nothing by itself. The generated install
   script registers the service and stops there; starting it is
   the operator's word (``-Start``), exactly as S-348's
   install.sh enables nothing without ``--enable``.

HONEST REMAINDER -- NOT PROVEN ON WINDOWS
This slice was built and tested on Linux. What is proven here:
the spec, the validation refusals, the rendered sc.exe command
lines and scripts, and the service host's structure, all as
data and pure functions. What is NOT PROVEN: a real Windows
host install, service start, SCM recovery, or health answer --
no Windows machine ran any of it. The Windows x86-64 service
cell of the support matrix stays NOT PROVEN until a counted
run on a real Windows host flips it (S-416's gate owns that
claim). docs/WINDOWS_SERVICE.md carries the same words.

No migration and no new taxonomy event: the schema stands at
140 and the taxonomy at 142. A service registration is host
state, not instance state -- nothing here touches the database.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import PureWindowsPath

from .run_model import build_topology

__all__ = [
    "SERVICE_NAME", "DISPLAY_NAME", "DESCRIPTION", "SERVICE_ACCOUNT",
    "START_MODE_AUTO", "RECOVERY_ACTIONS", "RECOVERY_RESET_SECONDS",
    "HOST_MODULE", "DEFAULT_DATA_ROOT",
    "WindowsServiceError", "ServiceSpec", "build_service_spec",
    "validate_spec", "check_spec", "server_command", "worker_commands",
    "install_commands", "uninstall_commands", "start_commands",
    "stop_commands", "status_commands", "render_command_line",
    "render_install_script", "render_uninstall_script",
    "INSTALL_WALK_STEPS",
]

#: The one service. Its name is also the virtual account's tail:
#: Windows provisions ``NT SERVICE\<name>`` at creation.
SERVICE_NAME = "Samverk"
DISPLAY_NAME = "Samverk"
DESCRIPTION = (
    "Samverk sovereign version-control forge: web, API, "
    "Git HTTP and LFS HTTP (run model S-345).")
SERVICE_ACCOUNT = r"NT SERVICE\Samverk"
START_MODE_AUTO = "auto"
#: SCM failure actions: restart after 60 s, three times.
RECOVERY_ACTIONS = "restart/60000/restart/60000/restart/60000"
RECOVERY_RESET_SECONDS = 86400
#: The stdlib service host the SCM actually launches (binPath).
HOST_MODULE = "samverk.windows_service_host"
#: The service-account analogue of S-348's /var/lib/samverk: a
#: machine-wide root, because a service account has no operator
#: profile for %LOCALAPPDATA% to mean anything under.
DEFAULT_DATA_ROOT = r"C:\ProgramData\Samverk"

_START_MODES = ("auto", "demand", "disabled")
_REFUSED_COMPONENTS = ("docker", "wsl", "wsl$", "wsl.localhost")


class WindowsServiceError(ValueError):
    """A spec refused by the S-410 law; `reason` is stable."""

    def __init__(self, reason, detail=""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


def _check_windows_path(value, what):
    """Validate one absolute, native Windows path string."""
    if not isinstance(value, str) or not value.strip():
        raise WindowsServiceError("path_missing", f"{what} is empty")
    if "\x00" in value or any(ord(c) < 0x20 for c in value):
        raise WindowsServiceError(
            "control_character", f"{what} carries a control character")
    p = PureWindowsPath(value)
    if not p.is_absolute() or not p.drive:
        raise WindowsServiceError(
            "path_not_absolute",
            f"{what} must be an absolute Windows path "
            f"(drive or UNC), got {value!r}")
    lowered = [part.lower() for part in p.parts]
    for part in lowered:
        if (part in _REFUSED_COMPONENTS or "docker" in part
                or part.startswith("\\\\wsl")):
            raise WindowsServiceError(
                "container_or_wsl_path",
                f"{what} routes through {part!r}: Samverk as a "
                "native Windows service is never installed "
                "through Docker or WSL paths")
    return str(p)


@dataclass(frozen=True)
class ServiceSpec:
    """The whole service definition as data: identity, account,
    start mode, recovery, and the three paths everything else is
    rendered from (the interpreter, the data root, the config)."""

    python_exe: str
    data_root: str
    config_path: str
    service_name: str = SERVICE_NAME
    display_name: str = DISPLAY_NAME
    description: str = DESCRIPTION
    account: str = SERVICE_ACCOUNT
    start_mode: str = START_MODE_AUTO
    recovery_actions: str = RECOVERY_ACTIONS
    recovery_reset_seconds: int = RECOVERY_RESET_SECONDS
    host_module: str = HOST_MODULE

    @property
    def db_path(self) -> str:
        """The instance database inside the data root (S-347's
        one tree: <data_root>/samverk.db)."""
        return str(PureWindowsPath(self.data_root) / "samverk.db")

    @property
    def bin_path_argv(self) -> list:
        """What the SCM launches: the interpreter running the
        service host, which runs the server as its child."""
        return [self.python_exe, "-m", self.host_module,
                "--config", self.config_path,
                "--data-root", self.data_root]

    @property
    def bin_path(self) -> str:
        return render_command_line(self.bin_path_argv)


def build_service_spec(python_exe, data_root=DEFAULT_DATA_ROOT,
                       config_path=None) -> ServiceSpec:
    """Compose and validate a spec. `python_exe` is the absolute
    path of the interpreter that will run Samverk (the walk's
    `where python` step finds it); the config defaults to
    samverk.ini inside the data root, S-346's one config file."""
    python_exe = _check_windows_path(python_exe, "python_exe")
    if not python_exe.lower().endswith(".exe"):
        raise WindowsServiceError(
            "python_not_executable",
            f"python_exe must name an .exe, got {python_exe!r}")
    data_root = _check_windows_path(data_root, "data_root")
    if config_path is None:
        config_path = str(PureWindowsPath(data_root) / "samverk.ini")
    config_path = _check_windows_path(config_path, "config_path")
    spec = ServiceSpec(python_exe=python_exe, data_root=data_root,
                       config_path=config_path)
    check_spec(spec)
    return spec


def server_command(spec: ServiceSpec) -> list:
    """The child command the service host runs: S-345's server
    role entry (``-m samverk serve``) with this spec's config."""
    return [spec.python_exe, "-m", "samverk", "serve",
            "--config", spec.config_path]


def validate_spec(spec: ServiceSpec) -> list:
    """Judge a spec against the S-410 laws; plain-words problems,
    empty when the spec stands. Pure: no I/O."""
    problems: list = []
    for value, what in ((spec.python_exe, "python_exe"),
                        (spec.data_root, "data_root"),
                        (spec.config_path, "config_path")):
        try:
            _check_windows_path(value, what)
        except WindowsServiceError as exc:
            problems.append(f"{what}: {exc}")
    if spec.service_name != SERVICE_NAME:
        problems.append(
            f"the service name is {spec.service_name!r}, "
            f"not {SERVICE_NAME!r}: the virtual account "
            "NT SERVICE\\<name> is provisioned from the name, "
            "so a renamed service silently changes its account")
    if spec.account != SERVICE_ACCOUNT:
        problems.append(
            f"the account is {spec.account!r}, not the virtual "
            f"service account {SERVICE_ACCOUNT!r}: no stored "
            "password may enter this deployment")
    if spec.start_mode not in _START_MODES:
        problems.append(
            f"start mode {spec.start_mode!r} is not one of "
            + ", ".join(_START_MODES))
    if spec.host_module != HOST_MODULE:
        problems.append(
            f"the host module is {spec.host_module!r}, not "
            f"{HOST_MODULE!r}: the SCM must launch the stdlib "
            "service host, never a wrapper from outside the tree")
    server = build_topology().server
    if not server.entry.endswith("samverk serve"):
        problems.append(
            "the run model's server entry no longer ends in "
            "'samverk serve': server_command would drift from "
            "the topology it claims to serve")
    if spec.recovery_actions != RECOVERY_ACTIONS:
        problems.append("the recovery actions differ from the "
                        "declared restart/60s x3 law")
    return problems


def check_spec(spec: ServiceSpec) -> ServiceSpec:
    """Raise WindowsServiceError on the first problem found."""
    problems = validate_spec(spec)
    if problems:
        raise WindowsServiceError("invalid_spec", problems[0])
    return spec


# -- command rendering -------------------------------------------

def render_command_line(argv) -> str:
    """Render an argv list as one Windows command line, with
    the platform quoting rules (an argument containing spaces
    or quotes is quoted and its quotes escaped). Pure string
    law; identical output on every OS."""
    return subprocess.list2cmdline([str(a) for a in argv])


def install_commands(spec: ServiceSpec) -> list:
    """The sc.exe sequence that registers the service: create
    (binPath, display name, auto start), description, the
    virtual account, and the declared recovery actions.
    Registration only -- nothing here starts the service."""
    check_spec(spec)
    name = spec.service_name
    return [
        ["sc.exe", "create", name, "binPath=", spec.bin_path,
         "DisplayName=", spec.display_name, "start=", spec.start_mode],
        ["sc.exe", "description", name, spec.description],
        ["sc.exe", "config", name, "obj=", spec.account],
        ["sc.exe", "failure", name, "reset=",
         str(spec.recovery_reset_seconds), "actions=",
         spec.recovery_actions],
        ["sc.exe", "failureflag", name, "1"],
    ]


def start_commands(spec: ServiceSpec) -> list:
    return [["sc.exe", "start", spec.service_name]]


def stop_commands(spec: ServiceSpec) -> list:
    return [["sc.exe", "stop", spec.service_name]]


def status_commands(spec: ServiceSpec) -> list:
    return [["sc.exe", "query", spec.service_name],
            ["sc.exe", "queryex", spec.service_name]]


def uninstall_commands(spec: ServiceSpec) -> list:
    """Stop, then delete the registration. The data root is
    never named here: uninstalling the service must not delete
    the instance (S-341's export is the data's road out)."""
    return stop_commands(spec) + [["sc.exe", "delete", spec.service_name]]


def worker_commands(spec: ServiceSpec) -> tuple:
    """The periodic workers as one-shot command lines for the
    operator's Task Scheduler entries -- the Windows analogue
    of S-348's oneshot units. Each entry is (role name, argv or
    None, words): a worker with no standalone CLI (mirror-sync)
    renders None and says why, never a fabricated command."""
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


# -- the install walk (Part XVIII's standard) ---------------------
#
# Every step names its failure mode and its remedy, exactly as
# S-349's install walk does; docs/WINDOWS_SERVICE.md carries
# these same steps, and the battery pins the two together.

INSTALL_WALK_STEPS = (
    {"name": "admin_shell",
     "title": "An elevated shell",
     "action": "Open PowerShell or Windows Terminal as "
               "Administrator; the generated script also refuses "
               "to run unelevated (#Requires -RunAsAdministrator).",
     "failure": "not_administrator",
     "failure_words": "sc.exe answers 'Access is denied' (error 5) "
                      "or the script stops before its first command.",
     "remedy": "Re-open the shell with 'Run as administrator' "
               "and re-run; service registration is an "
               "administrator act by Windows' own law."},
    {"name": "python_runtime",
     "title": "Python 3.11 or newer, natively installed",
     "action": "Run `where python` (or `py -0p`) and note the "
               "absolute python.exe path; it becomes the spec's "
               "python_exe. Confirm `python --version` is 3.11+.",
     "failure": "python_missing",
     "failure_words": "no python.exe on PATH, a Microsoft Store "
                      "stub that opens the Store instead of "
                      "running, or a version older than 3.11.",
     "remedy": "Install Python 3.11+ from python.org as a native "
               "Windows install (never through WSL or Docker -- "
               "the spec refuses those paths), then re-check "
               "`where python`."},
    {"name": "package_installed",
     "title": "The samverk package imports under that interpreter",
     "action": "From the checkout: `python -m pip install .` "
               "then `python -c \"import samverk\"`. The one "
               "admitted dependency (cryptography) installs "
               "with it.",
     "failure": "package_not_importable",
     "failure_words": "ModuleNotFoundError for samverk or "
                      "cryptography under the very interpreter "
                      "the service will run.",
     "remedy": "Install into the same interpreter named in the "
               "spec (never a second one); the service runs "
               "that interpreter or nothing."},
    {"name": "data_root_and_config",
     "title": "Data root and the one config file",
     "action": "Create the data root (default "
               "C:\\ProgramData\\Samverk) and place samverk.ini "
               "in it with data_root pointing at the same root "
               "(S-346/S-347).",
     "failure": "data_root_unwritable",
     "failure_words": "the directory cannot be created, or the "
                      "config resolves to a different root than "
                      "the walk was given.",
     "remedy": "Fix the path in samverk.ini so config and spec "
               "name one root; never let the service open a "
               "different database than the walk initialised."},
    {"name": "first_admin_walk",
     "title": "First admin, by S-349's install walk",
     "action": "Run the S-349 install walk against the data "
               "root (docs/INSTALL_WALK.md) so the database, "
               "instance key, and first admin stand before the "
               "service ever starts.",
     "failure": "first_admin_refused",
     "failure_words": "the walk stops at a named step -- its "
                      "own guide names each failure mode and "
                      "remedy; the service is not registered "
                      "over a half-walked instance.",
     "remedy": "Remedy the walk's named step and re-run the "
               "walk (it is idempotent); only then register "
               "the service."},
    {"name": "service_account_rights",
     "title": "The virtual account can write the data root",
     "action": "Grant the service account modify rights on the "
               "data root only: `icacls <data_root> /grant "
               "\"NT SERVICE\\Samverk:(OI)(CI)M\"`.",
     "failure": "service_logon_or_access",
     "failure_words": "start fails with error 1069 (logon) or "
                      "the running service cannot write its "
                      "database, keys, or repositories.",
     "remedy": "Re-run the icacls grant for exactly the data "
               "root and confirm no other directory was opened "
               "up; the account needs nothing else."},
    {"name": "service_create",
     "title": "Register the service (installs, starts nothing)",
     "action": "Run deploy's generated install script "
               "(render_install_script): it checks elevation, "
               "refuses a WSL environment, verifies the "
               "interpreter exists, then runs the sc.exe create / "
               "description / config / failure sequence.",
     "failure": "service_create_failed",
     "failure_words": "sc.exe exits non-zero -- a service of "
                      "the same name already exists (error "
                      "1073), or binPath names a missing file.",
     "remedy": "For 1073, uninstall the standing registration "
               "first (the uninstall script) rather than "
               "creating a second; for a missing file, correct "
               "python_exe in the spec and re-render."},
    {"name": "start_and_health",
     "title": "Start, and the health answer",
     "action": "`sc.exe start Samverk` (or re-run the install "
               "script with -Start), then `sc.exe query Samverk` "
               "shows RUNNING and GET /healthz on the configured "
               "host/port answers 200 with the Samverk payload.",
     "failure": "service_start_failed",
     "failure_words": "the service stops at once (error 1067), "
                      "query shows STOPPED, or /healthz does "
                      "not answer -- the port may be taken.",
     "remedy": "Read the host's stderr in the Windows Event "
               "Log / application output, free the named port "
               "or choose another in samverk.ini, and start "
               "again; a service that is not answering "
               "/healthz is not installed, whatever sc says."},
)


# -- generated scripts ---------------------------------------------

def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def render_install_script(spec: ServiceSpec) -> str:
    """The PowerShell install script for this spec: elevated,
    WSL-refusing, registration only -- it starts the service
    only when the operator passes -Start. NOT PROVEN on a real
    Windows host (see the module docstring)."""
    check_spec(spec)
    lines = [
        "# Samverk Windows service install (S-410). Native only:",
        "# no Docker, no WSL. Registration only -- the service",
        "# is started only when you pass -Start, your word.",
        "#Requires -RunAsAdministrator",
        "param([switch]$Start)",
        "$ErrorActionPreference = 'Stop'",
        "if ($env:WSL_DISTRO_NAME) { throw 'refusing to install "
        "from inside WSL: run this in native Windows PowerShell' }",
        f"$pythonExe = {_ps_quote(spec.python_exe)}",
        "if (-not (Test-Path $pythonExe)) { throw "
        "\"python_exe not found: $pythonExe\" }",
        f"New-Item -ItemType Directory -Force {_ps_quote(spec.data_root)} | Out-Null",
        "& icacls " + _ps_quote(spec.data_root) + " /grant "
        + _ps_quote(spec.account + ":(OI)(CI)M"),
    ]
    for argv in install_commands(spec):
        lines.append("& " + render_command_line(argv))
        lines.append("if ($LASTEXITCODE -ne 0) { throw "
                     f"'sc.exe {argv[1]} failed: ' + $LASTEXITCODE }}")
    lines += [
        "if ($Start) { & sc.exe start " + spec.service_name + " }",
        "else { Write-Host 'installed, NOT started. Start with: "
        f"sc.exe start {spec.service_name}' }}",
        "",
    ]
    return "\n".join(lines)


def render_uninstall_script(spec: ServiceSpec) -> str:
    """Stop + delete the registration. The data root is left
    standing, deliberately, and the script says so."""
    lines = [
        "# Samverk Windows service uninstall (S-410): removes the",
        "# registration only. The data root and its instance are",
        "# NOT deleted -- export (S-341) is the data's road out.",
        "#Requires -RunAsAdministrator",
        "$ErrorActionPreference = 'Continue'",
    ]
    for argv in uninstall_commands(spec):
        lines.append("& " + render_command_line(argv))
    lines.append(f"Write-Host 'service removed; data root kept: "
                 f"{spec.data_root}'")
    lines.append("")
    return "\n".join(lines)
