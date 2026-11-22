"""Standalone regression (S-377) — the seam changed
nothing underneath.

With the Part XIX seam built (S-361..S-376), the
standalone batteries re-run untouched: Part IV (Git
transports) and Part XII (API & webhooks). This module
is the counted declaration of that regression, in code:

- PART_IV_MODULES / PART_XII_MODULES name the battery
  modules, exactly as they stand on disk; a missing
  module is drift, reported by name.
- check_isolation() proves the seam did not grow into
  the standalone core: no standalone module imports a
  seam module (the seam reads the core; never reverse).
- exercise_standalone() proves the doors themselves
  with the seam unconfigured: register, password login
  (the S-363 battery's own assertion that Samverk's
  login remains), repository creation, and a seam door
  refusing seam_disabled while all of that works.

The batteries themselves run as this slice's neighbour
suites, untouched — this module declares and checks;
it re-implements nothing. No migration, no new
taxonomy event.
"""
from __future__ import annotations

from pathlib import Path

PART_IV_MODULES = (
    "test_git_http_advertise", "test_git_http_upload",
    "test_git_http_receive", "test_ssh_keys",
    "test_ssh_key_resolution", "test_ssh_upload_routing",
    "test_ssh_receive_routing", "test_transport_battery",
)
PART_XII_MODULES = (
    "test_api_contract", "test_api_authentication",
    "test_api_repositories", "test_api_issues_pulls",
    "test_webhook_signing", "test_webhook_events",
    "test_webhook_subscriptions", "test_webhook_delivery",
)
STANDALONE_CORE = (
    "accounts", "login", "sessions", "repositories",
    "issues", "pull_requests", "gists", "notification_reasons",
    "mirrors", "whole_instance_export",
)
SEAM_MODULES = (
    "seam_contract", "seam_identity", "seam_sso",
    "seam_kill_switch", "seam_permissions_audit",
    "seam_battery", "seam_boundary", "agent_parity",
    "village_repos", "village_backup", "file_succession",
    "hall_events", "samtal_panel", "mentions_bridge",
    "link_unfurl", "embedded_polish",
)


def declared_batteries() -> dict:
    """The regression, counted: both parts, in order."""
    return {"part_iv": PART_IV_MODULES,
            "part_xii": PART_XII_MODULES,
            "total": len(PART_IV_MODULES) + len(PART_XII_MODULES)}


def check_battery_files(root: Path) -> dict:
    """Every declared module stands on disk, untouched
    in name; a missing one is named, never blurred."""
    tests = Path(root) / "tests"
    missing = [m for m in PART_IV_MODULES + PART_XII_MODULES
               if not (tests / f"{m}.py").is_file()]
    return {"ok": not missing, "missing": missing,
            "declared": len(PART_IV_MODULES) + len(PART_XII_MODULES)}


def check_isolation(root: Path) -> dict:
    """No standalone core module imports a seam module."""
    pkg = Path(root) / "samverk"
    offenders = []
    for name in STANDALONE_CORE:
        path = pkg / f"{name}.py"
        if not path.is_file():
            offenders.append(f"{name}: core module missing")
            continue
        src = path.read_text()
        for seam in SEAM_MODULES:
            if f"import {seam}" in src or f"from .{seam}" in src \
                    or f"from samverk.{seam}" in src:
                offenders.append(f"{name} imports {seam}")
    return {"ok": not offenders, "offenders": offenders,
            "core_checked": len(STANDALONE_CORE)}


def exercise_standalone(conn, data_root, accounts, *, audit=None,
                        time_fn=None) -> dict:
    """The standalone doors, worked with NO seam
    settings at all: register + password login through
    the standing LoginService, repository creation
    through RepositoryStore, and the Samtal panel
    refusing seam_disabled beside them. Returns the
    counted outcome; raises nothing it can name."""
    from .login import LoginService
    from .repositories import RepositoryStore
    from .samtal_panel import SamtalPanelError, SamtalPanelService
    from .sessions import SessionStore
    now = time_fn or __import__("time").time
    checks = []
    user = accounts.register("standalone_villager",
                             "a long enough passphrase")
    checks.append({"name": "register", "ok": user is not None})
    sessions = SessionStore(conn, time_fn=now)
    login = LoginService(conn, accounts, sessions, audit=audit,
                         time_fn=now)
    token = login.login("standalone_villager",
                        "a long enough passphrase")
    checks.append({"name": "password_login",
                   "ok": bool(token) and
                   sessions.authenticate(token) == user.id})
    repos = RepositoryStore(conn, data_root, accounts,
                            audit=audit, time_fn=now)
    repo = repos.create_repository(user.id, user.username,
                                   "standalone-repo")
    checks.append({"name": "create_repository",
                   "ok": repo.full_name ==
                   "standalone_villager/standalone-repo"})
    panel = SamtalPanelService(conn, data_root, accounts,
                               settings=None, audit=audit,
                               time_fn=now)
    try:
        panel.payload_for(user)
        refused = None
    except SamtalPanelError as exc:
        refused = exc.reason
    checks.append({"name": "seam_door_refuses_cleanly",
                   "ok": refused == "seam_disabled"})
    return {"ok": all(c["ok"] for c in checks),
            "checks": checks}


def regression_report(root: Path) -> dict:
    """One counted place: batteries declared and on
    disk, isolation held. The live doors are proven by
    exercise_standalone (the battery drives it)."""
    files = check_battery_files(root)
    isolation = check_isolation(root)
    return {"batteries": declared_batteries(),
            "files": files, "isolation": isolation,
            "ok": files["ok"] and isolation["ok"]}
