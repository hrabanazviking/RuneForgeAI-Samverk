"""Layout shell (S-382).

Roadmap S-382: Layout shell -- one navigation skeleton for
all surfaces; a findability test script (timed tasks: mint
a token, create a repo, add a mirror) that every release
must pass.

Every Samverk surface hangs on ONE skeleton: the same
primary navigation, in the same order, with the same names,
reached from the same home. This module is that skeleton
as code -- the surface registry and the links between
surfaces -- plus the findability harness that proves a
newcomer can actually find the three things a forge exists
for.

- **One skeleton.** `SURFACES` names every surface once;
  `NAV_ORDER` is the primary navigation; `LINKS` is the
  directed graph of in-shell moves. A surface not in the
  registry does not exist for navigation; a surface in the
  registry but unreachable from home fails the audit.
- **Findability is timed, not vibes.** Each task in
  `FINDABILITY_TASKS` is a path through the graph walked
  step by step; every step carries the shell's declared
  step cost (one page decision, STEP_SECONDS). A task
  passes when its destination is reached within
  MAX_TASK_STEPS steps and MAX_TASK_SECONDS seconds.
  `run_findability` walks all three tasks and reports
  each by name; tools/findability_check.py runs it as the
  release script and exits non-zero on any failure.
- **Rendering draws the decided skeleton.** `render_nav`
  emits the primary navigation for a current surface,
  labels escaped through S-376's one escaping seam, the
  current surface marked in text (aria-current), never by
  colour alone.

Pure code: no store, no audit event, no migration --
schema 140 / taxonomy 142 stand. Design numbers (corner
cuts, frame strengths) come from S-381's registry.
"""
from __future__ import annotations

from collections import deque

from samverk.escaping import escape_html_text

STEP_SECONDS = 4
MAX_TASK_STEPS = 4
MAX_TASK_SECONDS = 30

SURFACES = {
    "home": "Home",
    "repositories": "Repositories",
    "issues": "Issues",
    "pull_requests": "Pull requests",
    "explore": "Explore",
    "notifications": "Notifications",
    "settings": "Settings",
    "tokens": "Access tokens",
    "new_repository": "New repository",
    "mirrors": "Mirrors",
    "new_mirror": "New mirror",
    "admin": "Admin",
}

NAV_ORDER = ("home", "repositories", "issues", "pull_requests",
             "explore", "notifications", "settings", "admin")

LINKS = {
    "home": ("repositories", "issues", "pull_requests", "explore",
             "notifications", "settings", "admin", "new_repository"),
    "repositories": ("home", "new_repository", "mirrors"),
    "issues": ("home", "repositories"),
    "pull_requests": ("home", "repositories"),
    "explore": ("home", "repositories"),
    "notifications": ("home",),
    "settings": ("home", "tokens", "mirrors"),
    "tokens": ("settings", "home"),
    "new_repository": ("repositories", "home"),
    "mirrors": ("settings", "new_mirror", "home"),
    "new_mirror": ("mirrors", "home"),
    "admin": ("home", "settings"),
}

FINDABILITY_TASKS = {
    "mint_a_token": "tokens",
    "create_a_repo": "new_repository",
    "add_a_mirror": "new_mirror",
}


def shortest_path(start, goal, links=None):
    """Breadth-first path through the shell graph, or None."""
    graph = LINKS if links is None else links
    if start not in SURFACES or goal not in SURFACES:
        return None
    if start == goal:
        return (start,)
    seen = {start}
    queue = deque([(start, (start,))])
    while queue:
        node, path = queue.popleft()
        for nxt in graph.get(node, ()):
            if nxt in seen:
                continue
            if nxt == goal:
                return path + (nxt,)
            seen.add(nxt)
            queue.append((nxt, path + (nxt,)))
    return None


def audit_shell(links=None):
    """Judge the skeleton: registry, nav and reachability."""
    graph = LINKS if links is None else links
    problems = []
    for name in NAV_ORDER:
        if name not in SURFACES:
            problems.append(f"nav_surface_unknown:{name}")
    for src, dsts in graph.items():
        if src not in SURFACES:
            problems.append(f"link_source_unknown:{src}")
        for dst in dsts:
            if dst not in SURFACES:
                problems.append(f"link_target_unknown:{dst}")
    for name in SURFACES:
        if shortest_path("home", name, graph) is None:
            problems.append(f"surface_unreachable:{name}")
    return problems


def run_findability(links=None):
    """Walk every findability task; report each by name."""
    graph = LINKS if links is None else links
    results = {}
    for task, goal in FINDABILITY_TASKS.items():
        path = shortest_path("home", goal, graph)
        if path is None:
            results[task] = {"ok": False, "reason": "unreachable",
                             "steps": None, "seconds": None, "path": None}
            continue
        steps = len(path) - 1
        seconds = steps * STEP_SECONDS
        ok = steps <= MAX_TASK_STEPS and seconds <= MAX_TASK_SECONDS
        results[task] = {"ok": ok,
                         "reason": None if ok else "over_budget",
                         "steps": steps, "seconds": seconds,
                         "path": path}
    return results


def findability_passed(links=None):
    return all(r["ok"] for r in run_findability(links).values())


def render_nav(current):
    """The primary navigation, current surface named in text."""
    if current not in SURFACES:
        raise ValueError("surface_unknown")
    items = []
    for name in NAV_ORDER:
        label = escape_html_text(SURFACES[name])
        if name == current:
            items.append(
                f'<li aria-current="page"><span>{label}</span></li>')
        else:
            items.append(f'<li><a href="/{name}">{label}</a></li>')
    return '<nav aria-label="Primary"><ul>' + "".join(items) + "</ul></nav>"
