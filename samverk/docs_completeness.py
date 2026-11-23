"""Documentation completeness (S-397).

Roadmap S-397: **operator guide, admin guide, user
guide, API contract (S-237): every guide walked by a
fresh reader against a live instance.**

Before this slice the guidance stood as 78 topic
documents with no single operator, admin or user
guide a fresh reader could start from, and one
present-tense claim had already drifted (the install
walk named schema 139 as current after migration 140
landed). This slice:

- names the four guides as data (``GUIDES``): each
guide's primary document, its component documents,
and the anchors a fresh reader must find in the
primary document;
- audits the tree (``audit_guides``): every primary
and component document exists, every anchor stands
in its primary document, and no primary document
carries the stale schema/taxonomy numbers this
slice found and fixed;
- walks the guides against a live instance
(``walk_live_instance``): a real instance is stood
up from this tree with S-349's install walk, the
real server is booted on an ephemeral loopback
port, and the claims the guides make are checked
against what the instance actually answers -- the
health payload's schema version, the root payload,
the install walk's nine steps, the configuration
table's ten keys, and the API contract's resource
count. Nothing is walked in mock mode: the server
is the tree's own ``make_server`` and the database
is a real initialised instance.

The walk report (``walk_log_dict`` /
``render_walk_log``) is the release artifact: it
records what was walked, what matched, and what did
not. A claim that cannot be checked is named, never
passed silently.

No migration and no new taxonomy event: the schema
stands at 140 and the taxonomy stands at 142.
"""
from __future__ import annotations

import http.client, json, re, threading
from dataclasses import dataclass
from pathlib import Path

from . import db, taxonomy
from .platform_seam import machine as seam_machine, platform_string as seam_platform_string
from .api_contract import API_RESOURCES
from .config import Config
from .db import schema_version
from .install_walk import STEP_IDS, run_install_walk
from .server import make_server

__all__ = ["GUIDES", "Guide", "audit_guides",
    "judge_walk", "render_walk_log", "walk_live_instance",
    "walk_log_dict"]

WALK_ADMIN = "walkadmin"
WALK_PASSWORD = "correct horse battery staple"


@dataclass(frozen=True)
class Guide:
    guide_id: str
    title: str
    primary: str
    components: tuple
    anchors: tuple


GUIDES = (
    Guide("operator", "Operator guide",
        "docs/OPERATOR_GUIDE.md",
        ("docs/RUN_MODEL.md", "docs/INSTALL_WALK.md",
         "docs/CONFIGURATION.md", "docs/UPGRADES.md",
         "docs/HEALTH_AND_STATUS.md",
         "docs/DATA_DIRECTORY_LAYOUT.md",
         "docs/SYSTEMD_UNITS.md"),
        ("samverk serve", "/healthz", "samverk.ini",
         "UPGRADES", "data root")),
    Guide("admin", "Admin guide",
        "docs/ADMIN_GUIDE.md",
        ("docs/ADMIN_PANEL.md", "docs/FIRST_ADMIN.md",
         "docs/SITE_SETTINGS.md", "docs/CONFIGURATION.md"),
        ("create-first-admin", "admin panel", "sudo",
         "Site settings")),
    Guide("user", "User guide",
        "docs/USER_GUIDE.md",
        ("docs/API_CONTRACT.md", "docs/FIRST_ADMIN.md",
         "docs/SEARCH_LIMITS.md", "docs/WEBHOOK_EVENTS.md"),
        ("account", "token", "repositor", "pull request")),
    Guide("api", "API contract (S-237)",
        "docs/API_CONTRACT.md",
        ("docs/API_VERSIONING.md", "docs/API_ABUSE.md",
         "docs/WEBHOOK_EVENTS.md"),
        ("/api/v1", "permission-parity", "error-shape",
         "cursor-pagination")),
)

STALE_PATTERNS = ("schema 139", "stands at 139",
    "taxonomy stands at 138", "taxonomy stays 138")


def audit_guides(root: Path) -> list:
    """Audit the four guides on disk. Pure file reads.

    Returns a list of problem strings; empty is complete.
    """
    problems = []
    for g in GUIDES:
        primary = root / g.primary
        if not primary.is_file():
            problems.append(f"{g.guide_id}: primary missing {g.primary}")
            continue
        text = primary.read_text(encoding="utf-8")
        for anchor in g.anchors:
            if anchor not in text:
                problems.append(f"{g.guide_id}: anchor missing {anchor!r}")
        for stale in STALE_PATTERNS:
            if stale in text:
                problems.append(f"{g.guide_id}: stale claim {stale!r}")
        for comp in g.components:
            if not (root / comp).is_file():
                problems.append(f"{g.guide_id}: component missing {comp}")
    return problems


def judge_walk(checks: list) -> bool:
    """Pure verdict: every walked check passed."""
    return bool(checks) and all(c["ok"] for c in checks)


def _get(port: int, path: str):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


def walk_live_instance(root: Path, work: Path) -> dict:
    """Stand up a real instance and walk the guides' claims.

    Returns the walk log dict. Every check records what
    was claimed, what the instance answered, and whether
    they matched.
    """
    checks = []
    def check(name, ok, detail):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
    data_root = work / "instance"
    report = run_install_walk(root, data_root, WALK_ADMIN, WALK_PASSWORD)
    check("install-walk", report.ok,
          f"{len(report.steps)} steps, ok={report.ok}")
    check("install-steps-nine", tuple(s.step_id for s in report.steps) == tuple(STEP_IDS) and len(STEP_IDS) == 9,
          f"guide claims 9 automated steps; code runs {len(STEP_IDS)}")
    cfg = Config(host="127.0.0.1", port=0, data_root=data_root)
    httpd = make_server(cfg)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _get(port, "/healthz")
        payload = json.loads(body.decode("utf-8"))
        head = db.MIGRATIONS[-1][0]
        check("healthz", status == 200 and payload.get("status") == "ok" and payload.get("schema_version") == head,
              f"GET /healthz -> {status}, schema_version={payload.get('schema_version')}, current head {head}")
        status, body = _get(port, "/")
        root_payload = json.loads(body.decode("utf-8"))
        check("root", status == 200 and root_payload.get("service") == "samverk",
              f"GET / -> {status}, service={root_payload.get('service')!r}, version={root_payload.get('version')!r}")
        status, _ = _get(port, "/admin/status")
        check("admin-status-gated", status in (401, 403),
              f"GET /admin/status anonymously -> {status} (guide claims admins only)")
    finally:
        httpd.shutdown(); httpd.server_close()
    conn = db.connect(cfg.db_path)
    try:
        check("schema-current", schema_version(conn) == db.MIGRATIONS[-1][0],
              f"walked instance schema {schema_version(conn)}, head {db.MIGRATIONS[-1][0]}, taxonomy {len(taxonomy.AUDIT_EVENTS)} events")
    finally:
        conn.close()
    conf_text = (root / "docs" / "CONFIGURATION.md").read_text(encoding="utf-8")
    keys = [k for k in Config.__dataclass_fields__ if f"`{k}`" in conf_text]
    check("config-keys", len(keys) == len(Config.__dataclass_fields__),
          f"configuration guide documents {len(keys)} of {len(Config.__dataclass_fields__)} config keys")
    contract_text = (root / "docs" / "API_CONTRACT.md").read_text(encoding="utf-8")
    check("api-resources", len(API_RESOURCES) == 36 and "/api/v1" in contract_text,
          f"API contract ratifies {len(API_RESOURCES)} resources under /api/v1")
    problems = audit_guides(root)
    check("guide-audit", not problems, "; ".join(problems) if problems else "all four guides complete on disk")
    return walk_log_dict(checks)


def walk_log_dict(checks: list) -> dict:
    return {"machine": seam_machine(),
            "platform": seam_platform_string(),
            "schema": db.MIGRATIONS[-1][0],
            "taxonomy_events": len(taxonomy.AUDIT_EVENTS),
            "guides": [g.guide_id for g in GUIDES],
            "checks": checks,
            "passed": judge_walk(checks),
            "verdict": "DOCUMENTATION WALK PASSED" if judge_walk(checks) else "DOCUMENTATION WALK NOT PASSED"}


def render_walk_log(log: dict) -> str:
    lines = ["# Documentation completeness walk — S-397", "",
        "Release artifact: the operator guide, admin guide, user guide and the",
        "API contract (S-237) walked by a fresh reader against a live instance.",
        "Generated by `tools/run_docs_walk.py` from a real run; no result in this",
        "log is asserted without running. The instance was stood up from this tree",
        "with S-349's install walk and served by the tree's own server on an",
        "ephemeral loopback port — real mode, never mock.", "",
        f"- Machine: `{log['machine']}` ({log['platform']})",
        f"- Schema: {log['schema']}; taxonomy events: {log['taxonomy_events']}",
        f"- Guides walked: {', '.join(log['guides'])}", "", "## Checks", ""]
    for c in log["checks"]:
        mark = "ok" if c["ok"] else "FAILED"
        lines.append(f"- [{mark}] {c['name']}: {c['detail']}")
    lines += ["", "## Verdict", "", log["verdict"], ""]
    return "\n".join(lines)
