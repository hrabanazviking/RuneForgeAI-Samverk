"""Upgrade drill (S-396).

Roadmap S-396: **an RC instance with real-shaped data
upgraded per S-357 and verified; the drill log is a
release artifact.**

S-357 shipped the upgrade procedure as judged code
(export -> verify -> stop -> migrate -> start -> verify
counts, rollback to the export on any later failure)
and rehearsed it on a minimal scratch instance (two
users, two repositories, one LFS object). This slice
is the release-candidate drill of that procedure: the
same procedure, unmodified, run end to end against an
instance shaped like a real one — several users, several
repositories owned by different users with mixed
visibility, real git history (chained commits, a second
branch, a tag), and LFS objects in more than one
repository — in two legs:

- **Leg A (upgrade):** a stand-in next migration
  (pretend schema 141, drill instance only — no such
  migration ships) is applied through S-357. The leg
  passes only if the procedure reports success AND the
  drill's own independent verification holds: head
  commits, branch and tag refs, and LFS bytes are
  byte-identical to the pre-upgrade instance, the user
  and repository counts match the RC shape, and the
  rehearsal row the migration wrote is present.
- **Leg B (rollback):** a fresh RC instance is upgraded
  with a migration that commits a destructive change
  and throws mid-way. The leg passes only if S-357
  rolls the instance back to the export: schema back
  at the pre-upgrade version, the deleted user
  restored, the half-migrated table gone, and heads
  and LFS bytes again identical.

The drill log (``drill_log_dict`` /
``render_drill_log``) is the release artifact: it
records the RC shape, both legs' step-by-step results
from the S-357 reports, the independent verification,
and the verdict, with the machine the drill ran on.
A drill that cannot be judged is never reported as
passed: any failed leg or failed verification names
its problems and the verdict is NOT PASSED.

No migration of this slice's own and no new taxonomy
event: the schema stands at 140 and the taxonomy
stands at 142. The stand-in migration touches drill
instances only.
"""
from __future__ import annotations

import os, platform, subprocess, time
from dataclasses import dataclass, field
from pathlib import Path

from . import db
from .accounts import AccountStore
from .config import Config
from .db import schema_version
from .lfs_store import LFSStore, oid_for
from .refs import RefStore
from .repositories import RepositoryStore
from .secrets import Secrets
from .upgrades import UpgradeProcedure

__all__ = ["RC_REPOS", "RC_USERS", "DrillError",
    "build_rc_instance", "destructive_drill_migration",
    "drill_log_dict", "expected_rc_counts", "judge_drill",
    "render_drill_log", "run_drill", "standin_drill_migration"]

ADMIN_PASSWORD = "correct horse battery"

# The RC shape: (username, is_admin) and
# (owner, name, visibility, commit_count).
RC_USERS = (("volmarr", True), ("yrsa", False),
            ("astrid", False))
RC_REPOS = (
    ("volmarr", "forge-core", "public", 5),
    ("volmarr", "forge-web", "public", 4),
    ("yrsa", "field-notes", "private", 3),
    ("astrid", "star-charts", "public", 3),
)
# LFS payloads per repository: (repo name, payload).
RC_LFS = (("forge-core", b"rc forge-core asset v1\n" * 16),
          ("forge-core", b"rc forge-core asset v2\n" * 16),
          ("field-notes", b"rc field-notes asset\n" * 16))


class DrillError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def expected_rc_counts() -> dict:
    """The RC shape's counts, from the shape alone. Pure."""
    return {"users": len(RC_USERS), "repos": len(RC_REPOS),
            "commits": sum(r[3] for r in RC_REPOS),
            "lfs_objects": len(RC_LFS)}


def judge_drill(upgrade_ok: bool, rollback_ok: bool,
                problems: list) -> bool:
    """Pure verdict: the drill passes only when both
    legs pass and no problem is named."""
    return bool(upgrade_ok and rollback_ok and not problems)

_GIT_ENV = {"GIT_AUTHOR_NAME": "RC Drill",
            "GIT_AUTHOR_EMAIL": "drill@example.invalid",
            "GIT_COMMITTER_NAME": "RC Drill",
            "GIT_COMMITTER_EMAIL": "drill@example.invalid"}


def _git(repo: Path, *args, input_bytes=None) -> str:
    env = dict(os.environ); env.update(_GIT_ENV)
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         input=input_bytes, capture_output=True, env=env)
    if out.returncode != 0:
        raise DrillError("git_failed", out.stderr.decode("utf-8", "replace"))
    return out.stdout.decode().strip()


def standin_drill_migration(conn):
    """The rehearsed stand-in next migration: a new
    table plus the schema bump to a pretend 141, on
    the drill database only. No such migration ships."""
    with conn:
        conn.execute("CREATE TABLE upgrade_rehearsal "
                     "(id INTEGER PRIMARY KEY, note TEXT NOT NULL)")
        conn.execute("INSERT INTO upgrade_rehearsal (note) "
                     "VALUES ('s396-drill')")
        conn.execute("INSERT OR REPLACE INTO schema_meta "
                     "(key, value) VALUES ('version', '141')")
    return 141


def destructive_drill_migration(conn):
    """A migration that commits damage and throws:
    leg B's rollback trigger. Drill instances only."""
    with conn:
        conn.execute("DELETE FROM users WHERE username = 'yrsa'")
        conn.execute("CREATE TABLE half_migrated_junk (id INTEGER)")
    raise RuntimeError("drill migration exploded mid-way")


@dataclass
class RCInstance:
    data_root: Path
    conn: object
    accounts: AccountStore
    repos: RepositoryStore
    admin: object
    heads: dict = field(default_factory=dict)
    refs: dict = field(default_factory=dict)
    lfs: dict = field(default_factory=dict)


def build_rc_instance(data_root: Path) -> RCInstance:
    """Build one real-shaped RC instance on disk:
    the RC users, repositories with chained real git
    history (plus a side branch and a tag each), and
    the RC LFS objects. Returns the opened instance
    with its pre-upgrade facts recorded."""
    data_root = Path(data_root); data_root.mkdir(parents=True)
    conn = db.init_db(data_root / "samverk.db")
    accounts = AccountStore(conn)
    users = {}
    for name, is_admin in RC_USERS:
        user = accounts.register(name, ADMIN_PASSWORD)
        if is_admin:
            with conn:
                conn.execute("UPDATE users SET is_admin = 1 "
                             "WHERE id = ?", (user.id,))
        users[name] = accounts.get_by_username(name)
    repos = RepositoryStore(conn, data_root, accounts)
    heads, refs, lfs = {}, {}, {}
    for owner, name, visibility, n_commits in RC_REPOS:
        repos.create_repository(users[owner].id, owner, name,
                                visibility=visibility,
                                description=f"RC drill repository {name}")
        path = repos.path_for(owner, name)
        parent = None; head = None
        for i in range(n_commits):
            blob = _git(path, "hash-object", "-w", "--stdin",
                        input_bytes=f"{name} revision {i}\n".encode())
            tree = _git(path, "mktree",
                        input_bytes=f"100644 blob {blob}\tREADME.txt\n".encode())
            args = ["commit-tree", tree]
            if parent: args += ["-p", parent]
            head = _git(path, *args, input_bytes=f"{name} commit {i}\n".encode())
            parent = head
        _git(path, "update-ref", "refs/heads/main", head)
        _git(path, "update-ref", "refs/heads/side", head)
        _git(path, "update-ref", "refs/tags/rc-1", head)
        key = f"{owner}/{name}"
        heads[key] = head
        refs[key] = {"refs/heads/main": head, "refs/heads/side": head,
                     "refs/tags/rc-1": head}
    for repo_name, payload in RC_LFS:
        owner = next(o for o, n, _v, _c in RC_REPOS if n == repo_name)
        store = LFSStore(repos.path_for(owner, repo_name))
        oid = oid_for(payload); store.put(oid, payload)
        lfs.setdefault(f"{owner}/{repo_name}", []).append((oid, payload))
    return RCInstance(data_root, conn, accounts, repos,
                      users["volmarr"], heads, refs, lfs)


def _verify_content(repos: RepositoryStore, inst: RCInstance) -> list:
    """Independent verification: every recorded ref
    still resolves to the same commit and every LFS
    payload is byte-identical. Returns problems."""
    problems = []
    for key, want_refs in inst.refs.items():
        owner, name = key.split("/", 1)
        store = RefStore(repos.path_for(owner, name))
        for ref, want in want_refs.items():
            got = store.resolve(ref)
            if got != want:
                problems.append(f"{key} {ref}: want {want}, got {got}")
    for key, objects in inst.lfs.items():
        owner, name = key.split("/", 1)
        store = LFSStore(repos.path_for(owner, name))
        for oid, payload in objects:
            path = store.path_for(oid)
            if not path.is_file() or path.read_bytes() != payload:
                problems.append(f"{key} LFS {oid}: payload differs")
    return problems


def _counts(conn) -> dict:
    return {"users": int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]),
            "repos": int(conn.execute("SELECT COUNT(*) FROM repositories").fetchone()[0]),
            "schema": schema_version(conn)}


def _run_leg(base: Path, label: str, migration_fn, expect_ok: bool) -> dict:
    inst = build_rc_instance(base / label / "instance")
    config = Config(data_root=inst.data_root,
                    secret_file=inst.data_root / "secrets.env")
    secrets = Secrets({"INSTANCE_KEY": "never-log-this-value"})
    proc = UpgradeProcedure(inst.conn, inst.data_root, inst.accounts,
                            inst.repos, config=config, secrets=secrets)
    started = time.time()
    report = proc.run(inst.admin.id, base / label / "exports",
                      stopped=True, started=True,
                      migration_fn=migration_fn,
                      signin_username="volmarr",
                      signin_password=ADMIN_PASSWORD)
    elapsed = round(time.time() - started, 3)
    # Leg B's migration failure is the rehearsed trigger,
    # not a drill problem: only its rollback outcome judges.
    problems = list(report.rollback_problems)
    if expect_ok:
        problems = list(report.problems) + problems
    content = _verify_content(proc.repositories, inst)
    counts = _counts(proc.conn)
    want = expected_rc_counts()
    if counts["users"] != want["users"]:
        problems.append(f"users: want {want['users']}, got {counts['users']}")
    if counts["repos"] != want["repos"]:
        problems.append(f"repos: want {want['repos']}, got {counts['repos']}")
    problems += content
    if expect_ok:
        rehearsal_ok = False
        if report.ok and counts["schema"] == 141:
            row = proc.conn.execute(
                "SELECT note FROM upgrade_rehearsal").fetchone()
            rehearsal_ok = bool(row and row[0] == "s396-drill")
        leg_ok = bool(report.ok and not content and rehearsal_ok)
        if counts["schema"] != 141:
            problems.append(f"schema: want 141 after upgrade, got {counts['schema']}")
    else:
        tables = {r[0] for r in proc.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        leg_ok = bool(not report.ok and report.rolled_back
                      and counts["schema"] == 140
                      and "half_migrated_junk" not in tables
                      and proc.accounts.get_by_username("yrsa") is not None
                      and not content)
        if counts["schema"] != 140:
            problems.append(f"schema: want 140 after rollback, got {counts['schema']}")
        if "half_migrated_junk" in tables:
            problems.append("half_migrated_junk survived the rollback")
    return {"leg": label, "ok": leg_ok,
            "procedure_ok": bool(report.ok),
            "rolled_back": bool(report.rolled_back),
            "failed_step": report.failed_step,
            "headline": report.headline,
            "steps": [{"step": s.step_id, "ok": bool(s.ok),
                       "detail": s.detail} for s in report.steps],
            "counts_after": counts, "elapsed_seconds": elapsed,
            "problems": problems}


def run_drill(base: Path) -> dict:
    """Run both legs under *base* and return the drill
    log as data. Each leg builds its own fresh RC
    instance; nothing outside *base* is touched."""
    base = Path(base)
    leg_a = _run_leg(base, "leg-a-upgrade", standin_drill_migration, True)
    leg_b = _run_leg(base, "leg-b-rollback", destructive_drill_migration, False)
    problems = ([f"leg-a-upgrade: {p}" for p in leg_a["problems"]]
                + [f"leg-b-rollback: {p}" for p in leg_b["problems"]])
    passed = judge_drill(leg_a["ok"], leg_b["ok"], problems)
    return {"slice": "S-396", "procedure": "S-357",
            "machine": platform.machine(),
            "platform": platform.platform(),
            "rc_shape": expected_rc_counts(),
            "rc_users": [u for u, _a in RC_USERS],
            "rc_repos": [f"{o}/{n}" for o, n, _v, _c in RC_REPOS],
            "schema_before": 140, "taxonomy_events": 142,
            "legs": [leg_a, leg_b], "problems": problems,
            "verdict": "PASSED" if passed else "NOT PASSED",
            "passed": passed}


def drill_log_dict(log: dict) -> dict:
    """The log as JSON-safe data (it already is)."""
    return dict(log)


def render_drill_log(log: dict) -> str:
    """Render the drill log as the markdown release
    artifact. Plain words, real numbers, honest verdict."""
    lines = ["# Upgrade drill log — S-396", "",
             "Release artifact: an RC instance with real-shaped data "
             "upgraded per S-357 and verified. Generated by "
             "`tools/run_upgrade_drill.py` from a real run; "
             "no result in this log is asserted without running.", "",
             f"- Machine: `{log['machine']}` ({log['platform']})",
             f"- RC shape: {log['rc_shape']['users']} users, "
             f"{log['rc_shape']['repos']} repositories, "
             f"{log['rc_shape']['commits']} commits, "
             f"{log['rc_shape']['lfs_objects']} LFS objects",
             f"- Repositories: {', '.join(log['rc_repos'])}",
             f"- Schema before: {log['schema_before']}; "
             f"taxonomy events: {log['taxonomy_events']}", ""]
    for leg in log["legs"]:
        lines += [f"## {leg['leg']}", "",
                  f"- Procedure headline: {leg['headline']}",
                  f"- Counts after: users {leg['counts_after']['users']}, "
                  f"repositories {leg['counts_after']['repos']}, "
                  f"schema {leg['counts_after']['schema']}",
                  f"- Elapsed: {leg['elapsed_seconds']} s", ""]
        for step in leg["steps"]:
            mark = "ok" if step["ok"] else "FAILED"
            lines.append(f"- [{mark}] {step['step']}: {step['detail']}")
        lines.append("")
    if log["problems"]:
        lines += ["## Problems", ""]
        lines += [f"- {p}" for p in log["problems"]]
        lines.append("")
    lines += ["## Verdict", "", f"UPGRADE DRILL {log['verdict']}", ""]
    return "\n".join(lines)
