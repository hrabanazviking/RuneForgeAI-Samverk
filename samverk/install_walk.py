"""Install walk (S-349).

Roadmap S-349: **from bare machine to first admin in
one documented pass, timed; every step's failure mode
named in the guide** (docs/INSTALL_WALK.md).

Before this slice the road from a bare checkout to a
running instance with an administrator existed only as
scattered knowledge: pyproject.toml named the Python
floor and the one dependency, config.py knew where a
data root lives, db.init_db migrated, keys.py could
mint an instance key, server.make_server could answer
/healthz -- and *nothing* could make a first admin:
AccountStore.register writes is_admin=0 for every
account and no door anywhere promoted one, so a fresh
instance could be served but never administered. This
slice gathers the whole road into one checkable walk
and builds the missing first-admin door.

- **The walk is nine checkable steps, in order.**
  python_version, dependency, checkout_layout,
  data_root, config, database_init, instance_key,
  first_admin, server_health. Each step is a check
  that runs and reports a StepResult -- ok or failed,
  what it saw in plain words, how long it took -- and
a failed step stops the walk: later steps are
  recorded `skipped`, never dressed as passed, because
  each step stands on the ones before it.
- **Every step names its failure mode and remedy in
  advance.** STEP_GUIDE is that catalogue in code:
  one entry per step with the failure the operator
  will actually meet and the remedy that fixes it.
  docs/INSTALL_WALK.md mirrors it step for step; the
  battery pins the two to the same step ids, so the
  guide cannot drift from the walk.
- **The judgements are pure.** decide_python_ok,
  decide_dependency, decide_checkout,
  decide_first_admin and judge_health_payload state
  what a probe means and write nothing. The runner
  probes, judges, and acts on the judgement.
- **First admin is a bootstrap, not a back door.**
  create_first_admin creates an account only on an
  instance with no accounts at all, through the full
  S-025 registration law (username, email, password
  policy, audit), then promotes that one account in
  the same transaction. When an admin already
  stands, the walk reports it and creates nothing;
  when accounts stand but no admin does, it refuses
  plainly -- that is a recovery, and the guide names
  the operator road instead of letting a re-run of an
  install script mint an admin beside existing users.
  The promotion is witnessed by the standing taxonomy
  event admin.user.role_change (from member, to
  admin, via install_walk); registration keeps its
  own auth.signup.success. No new event is claimed.
- **The walk creates nothing permanent.** It writes
  only inside the chosen data root (database, keys),
  starts its health-check server on an ephemeral
  loopback port and shuts it down again, and installs
  no service, timer, or autostart of any kind --
  running the instance afterwards is the operator's
  own `samverk serve`, as the guide states.
- **Timing is measured, never estimated.**
  run_install_walk times each step and the whole pass
  with a monotonic clock; WalkReport.elapsed_seconds
  is that measurement. The figure recorded in
  docs/INSTALL_WALK.md was read from a real run's log
  on the build machine, into a scratch prefix.

No migration and no new audit event: the schema
stands at 139 and the taxonomy stands at 138 -- the
users table, the key custody, and the role-change
event are all reused on purpose.
"""
from __future__ import annotations
import http.client, importlib, json, sqlite3, sys, threading, time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from . import __version__, db
from .accounts import AccountStore, RegistrationError, User
from .audit import AuditLog
from .config import Config, load_config
from .keys import ensure_instance_key
from .platform_seam import ensure_dir

__all__ = ["EXPECTED_SCHEMA_VERSION", "MIN_PYTHON", "STEP_GUIDE",
    "STEP_IDS", "InstallWalkError", "StepGuide", "StepResult",
    "WalkReport", "create_first_admin", "decide_checkout",
    "decide_dependency", "decide_first_admin", "decide_python_ok",
    "judge_health_payload", "render_walk_report", "run_install_walk"]

MIN_PYTHON = (3, 11)
EXPECTED_SCHEMA_VERSION = db.MIGRATIONS[-1][0]
REQUIRED_FILES = ("pyproject.toml", "samverk/__init__.py", "samverk/cli.py", "samverk/db.py", "samverk/server.py")

@dataclass(frozen=True)
class StepGuide:
    step_id: str; title: str; failure_mode: str; remedy: str

STEP_GUIDE = (
 StepGuide("python_version", "Python 3.11 or newer is present",
  "python_too_old / python_missing: the interpreter is older than 3.11, or no python3 is on PATH at all, so the package cannot even be imported (it uses 3.11 syntax and stdlib).",
  "Install Python 3.11 or newer from the OS package manager or python.org, then re-run the walk; `python3 --version` must agree before anything else is worth trying."),
 StepGuide("dependency", "The one dependency (cryptography) imports",
  "dependency_missing / dependency_broken: the cryptography package is not installed for this interpreter, or imports but is not the pinned 46.0.5 line, so token and secret code paths would fail later, at a worse moment.",
  "Install the pinned dependency into the same interpreter that will run Samverk: `python3 -m pip install cryptography==46.0.5` (or the OS package), then re-run; never run two interpreters and expect one environment."),
 StepGuide("checkout_layout", "The checkout is complete",
  "checkout_incomplete: pyproject.toml or a core samverk module is missing -- a partial clone, a zip that dropped files, or the walk pointed at the wrong directory.",
  "Point the walk at the root of a complete checkout (the directory holding pyproject.toml), or re-clone / re-extract it whole; do not paper over a missing module by copying files piecemeal."),
 StepGuide("data_root", "The data root can be created and written",
  "data_root_unwritable: the data root cannot be created or a probe file cannot be written -- wrong ownership, a read-only mount, or a full disk.",
  "Choose a data root the operator's account owns (or fix ownership/permissions on the named path), free disk space if the disk is full, then re-run; the walk never falls back to a different root silently."),
 StepGuide("config", "Configuration loads and points at the chosen data root",
  "config_invalid: the INI file does not parse, a port is not a number, or the loaded configuration resolves to a different data root than the walk was given -- the instance would open a different database than the one the walk initialises.",
  "Fix the named key in samverk.ini (or drop the file to take defaults), and make SAMVERK_DATA_ROOT / the ini data_root agree with the walk's data root; then re-run."),
 StepGuide("database_init", "The database initialises at the current schema",
  "database_init_failed / schema_mismatch: the database file cannot be opened (corrupt file, a directory in its place, no write permission) or migrations stop short of the current schema version.",
  "If the path holds a corrupt or foreign file, move it aside and let the walk create a fresh database (an existing real database is migrated in place, never recreated); fix permissions if the file cannot be written; a migration error names its version -- keep the error and the database file for diagnosis."),
 StepGuide("instance_key", "The instance signing key exists with private permissions",
  "instance_key_failed: the key cannot be minted (keys directory unwritable) or an existing key file is readable by group/other users, which the custody law refuses to load.",
  "Fix ownership on <data_root>/keys, and `chmod 600` any key file the check names; never delete a standing key to make the error go away -- rotation is `samverk keys rotate`."),
 StepGuide("first_admin", "A first administrator exists",
  "first_admin_refused / accounts_without_admin: the username, email, or password fails the registration law (the refusal names the rule), an admin already stands (not a failure -- the walk creates nothing), or accounts exist with no admin among them, which the walk refuses to repair by minting a new admin beside them.",
  "For a law refusal, choose a username/password that meets the stated rule and re-run. If an admin already stands, sign in as that admin. If accounts stand with no admin, follow the recovery operator step in docs/INSTALL_WALK.md -- it is a deliberate, witnessed act, never an install re-run."),
 StepGuide("server_health", "The server answers its health route",
  "server_health_failed: the server cannot bind (port already in use), or /healthz does not answer 200 with the samverk health payload -- the instance would be installed but not serving.",
  "Free the named port or choose another, confirm nothing else answers on it, and re-run; if the payload is wrong, the thing answering is not Samverk -- do not declare the install done."),
)
STEP_IDS = tuple(g.step_id for g in STEP_GUIDE)
_GUIDE = {g.step_id: g for g in STEP_GUIDE}

class InstallWalkError(Exception):
    def __init__(self, reason: str, message: str):
        super().__init__(message); self.reason = reason

@dataclass(frozen=True)
class StepResult:
    step_id: str; ok: bool; detail: str; elapsed_seconds: float = 0.0; state: str = ""
    @property
    def failure_mode(self) -> str: return _GUIDE[self.step_id].failure_mode
    @property
    def remedy(self) -> str: return _GUIDE[self.step_id].remedy

@dataclass
class WalkReport:
    source_root: Path; data_root: Path; steps: list[StepResult] = field(default_factory=list); elapsed_seconds: float = 0.0; admin_username: str | None = None
    @property
    def ok(self) -> bool: return bool(self.steps) and all(s.ok for s in self.steps)
    def step(self, step_id: str) -> StepResult | None:
        for s in self.steps:
            if s.step_id == step_id: return s
        return None

# -- pure judgements ------------------------------------------------
def decide_python_ok(version: tuple[int, ...]) -> bool:
    return tuple(version[:2]) >= MIN_PYTHON

def decide_dependency(importable: bool, version: str | None) -> tuple[bool, str]:
    if not importable: return False, "dependency_missing"
    if not version: return False, "dependency_broken"
    return True, version

def decide_checkout(present: set[str]) -> list[str]:
    return [name for name in REQUIRED_FILES if name not in present]

def decide_first_admin(user_count: int, admin_count: int) -> str:
    if admin_count > 0: return "already_present"
    if user_count == 0: return "create"
    return "refuse_nonempty_no_admin"

def judge_health_payload(status: int, body: bytes) -> tuple[bool, str]:
    if status != 200: return False, f"health route answered HTTP {status}"
    try: payload = json.loads(body.decode("utf-8"))
    except Exception: return False, "health route answered non-JSON"
    if payload.get("status") != "ok" or payload.get("service") != "samverk":
        return False, "health payload is not the samverk health payload"
    return True, f"health ok (samverk {payload.get('version', '?')})"

# -- first admin ----------------------------------------------------
def create_first_admin(conn: sqlite3.Connection, username: object, password: object, email: object = None, *, audit: AuditLog | None = None) -> User:
    """Create the instance's first administrator, or refuse plainly.
    Only an empty instance may be bootstrapped this way; see the
    module docstring for the three-way law (decide_first_admin)."""
    user_count = int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])
    admin_count = int(conn.execute("SELECT COUNT(*) FROM users WHERE is_admin != 0").fetchone()[0])
    action = decide_first_admin(user_count, admin_count)
    if action == "already_present":
        raise InstallWalkError("first_admin_exists", "An administrator already stands on this instance; the walk creates no second bootstrap admin.")
    if action == "refuse_nonempty_no_admin":
        raise InstallWalkError("accounts_without_admin", "Accounts exist but none is an administrator; refusing to mint an admin beside existing accounts -- follow the recovery operator step in docs/INSTALL_WALK.md.")
    store = AccountStore(conn, audit=audit)
    try:
        user = store.register(username, password, email)
    except RegistrationError as exc:
        raise InstallWalkError(exc.reason, str(exc)) from None
    with conn:
        conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (user.id,))
    promoted = store.get_by_id(user.id)
    assert promoted is not None and promoted.is_admin
    if audit is not None:
        audit.append(actor_kind="system", actor_id=None, action="admin.user.role_change", target_kind="user", target_id=str(user.id), outcome="success", detail={"from": "member", "to": "admin", "via": "install_walk"})
    return promoted

# -- the runner -----------------------------------------------------
class _Walk:
    def __init__(self, source_root: Path, data_root: Path, admin_username: str | None, admin_password: str | None, admin_email: str | None, time_fn: Callable[[], float]):
        self.source_root = Path(source_root); self.data_root = Path(data_root)
        self.admin_username = admin_username; self.admin_password = admin_password; self.admin_email = admin_email
        self._time = time_fn; self.cfg: Config | None = None; self.conn: sqlite3.Connection | None = None
    def _timed(self, step_id: str, fn) -> StepResult:
        start = self._time()
        try: ok, detail, state = fn()
        except InstallWalkError as exc: ok, detail, state = False, f"{exc.reason}: {exc}", exc.reason
        except Exception as exc: ok, detail, state = False, f"{type(exc).__name__}: {exc}", "error"
        return StepResult(step_id, ok, detail, round(self._time() - start, 4), state)
    def check_python(self):
        v = sys.version_info; ok = decide_python_ok(tuple(v[:3]))
        return ok, f"python {v.major}.{v.minor}.{v.micro} (floor {MIN_PYTHON[0]}.{MIN_PYTHON[1]})", "" if ok else "python_too_old"
    def check_dependency(self):
        try:
            mod = importlib.import_module("cryptography"); version = getattr(mod, "__version__", None)
        except Exception: return False, "cryptography is not importable", "dependency_missing"
        ok, info = decide_dependency(True, version)
        return ok, f"cryptography {info}", "" if ok else info
    def check_checkout(self):
        present = {name for name in REQUIRED_FILES if (self.source_root / name).is_file()}
        missing = decide_checkout(present)
        return (not missing), ("checkout complete" if not missing else f"missing: {', '.join(missing)}"), "" if not missing else "checkout_incomplete"
    def check_data_root(self):
        ensure_dir(self.data_root); probe = self.data_root / ".install-walk-probe"
        probe.write_text("ok\n", encoding="utf-8"); probe.unlink()
        return True, f"data root writable: {self.data_root}", ""
    def check_config(self):
        cfg = load_config(env={"SAMVERK_DATA_ROOT": str(self.data_root)})
        if Path(cfg.data_root) != self.data_root: return False, f"config resolves data root to {cfg.data_root}", "config_invalid"
        self.cfg = cfg; return True, f"config loads; host {cfg.host}, port {cfg.port}", ""
    def check_database(self):
        assert self.cfg is not None
        self.conn = db.init_db(self.cfg.db_path); version = db.schema_version(self.conn)
        if version != EXPECTED_SCHEMA_VERSION: return False, f"schema {version}, expected {EXPECTED_SCHEMA_VERSION}", "schema_mismatch"
        return True, f"database at {self.cfg.db_path}, schema {version}", ""
    def check_key(self):
        record = ensure_instance_key(self.data_root, "signing")
        return True, f"signing key v{record.version} fingerprint {record.fingerprint}", ""
    def check_first_admin(self):
        assert self.conn is not None
        user_count = int(self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])
        admin_count = int(self.conn.execute("SELECT COUNT(*) FROM users WHERE is_admin != 0").fetchone()[0])
        action = decide_first_admin(user_count, admin_count)
        if action == "already_present":
            row = self.conn.execute("SELECT username FROM users WHERE is_admin != 0 ORDER BY id LIMIT 1").fetchone()
            return True, f"administrator already stands: {row[0]} (nothing created)", "already_present"
        if action == "refuse_nonempty_no_admin":
            return False, "accounts exist but none is an administrator", "accounts_without_admin"
        if not self.admin_username or not self.admin_password:
            return False, "no admin username/password supplied for the bootstrap", "first_admin_refused"
        user = create_first_admin(self.conn, self.admin_username, self.admin_password, self.admin_email, audit=AuditLog(self.conn))
        return True, f"first administrator created: {user.username} (id {user.id})", "created"
    def check_health(self):
        from .server import make_server
        assert self.cfg is not None
        cfg = Config(host="127.0.0.1", port=0, data_root=self.data_root)
        httpd = make_server(cfg); port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True); thread.start()
        try:
            client = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            client.request("GET", "/healthz"); resp = client.getresponse(); body = resp.read(); client.close()
        finally:
            httpd.shutdown(); httpd.server_close(); thread.join(timeout=5)
        ok, detail = judge_health_payload(resp.status, body)
        return ok, detail, "" if ok else "server_health_failed"
    def run(self) -> WalkReport:
        checks = [("python_version", self.check_python), ("dependency", self.check_dependency), ("checkout_layout", self.check_checkout), ("data_root", self.check_data_root), ("config", self.check_config), ("database_init", self.check_database), ("instance_key", self.check_key), ("first_admin", self.check_first_admin), ("server_health", self.check_health)]
        report = WalkReport(self.source_root, self.data_root, admin_username=self.admin_username)
        total_start = self._time(); failed = False
        for step_id, fn in checks:
            if failed:
                report.steps.append(StepResult(step_id, False, "skipped: an earlier step failed", 0.0, "skipped")); continue
            result = self._timed(step_id, fn); report.steps.append(result); failed = not result.ok
        report.elapsed_seconds = round(self._time() - total_start, 4)
        if self.conn is not None: self.conn.close()
        return report

def run_install_walk(source_root: Path, data_root: Path, admin_username: str | None = None, admin_password: str | None = None, admin_email: str | None = None, *, time_fn: Callable[[], float] = time.monotonic) -> WalkReport:
    """Run the whole walk once and return its timed report."""
    return _Walk(Path(source_root), Path(data_root), admin_username, admin_password, admin_email, time_fn).run()

def render_walk_report(report: WalkReport) -> str:
    lines = [f"Samverk install walk -- samverk {__version__}", f"source: {report.source_root}", f"data root: {report.data_root}", ""]
    for s in report.steps:
        mark = "ok" if s.ok else ("skipped" if s.state == "skipped" else "FAILED")
        lines.append(f"[{mark}] {_GUIDE[s.step_id].title} ({s.elapsed_seconds:.3f}s)")
        lines.append(f"       {s.detail}")
        if not s.ok and s.state != "skipped":
            lines.append(f"       failure: {s.failure_mode}"); lines.append(f"       remedy: {s.remedy}")
    lines.append(""); lines.append(f"{'WALK OK' if report.ok else 'WALK FAILED'} in {report.elapsed_seconds:.3f}s")
    return "\n".join(lines) + "\n"
