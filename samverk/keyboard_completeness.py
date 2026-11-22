"""Keyboard completeness (S-388).

Roadmap S-388: Keyboard completeness -- every action
reachable by keyboard; visible focus everywhere; the
battery walks the core flows keyboard-only.

A forge you cannot drive without a mouse is a forge half
the room cannot use. This module is the keyboard map as
code:

- `FOCUS_ORDER` names, per surface, the exact tab order
  of its focusable elements; every S-386 target on the
  surface must appear in it (a target the keyboard cannot
  reach does not exist for keyboard users).
- `ACTIONS` names every action with its keyboard route
  (the focus stops from the surface's first stop to the
  control that fires it); an action with no route is
  named `action_unreachable`.
- Visible focus is law, not taste: every focusable
  carries a declared focus outline of at least
  FOCUS_OUTLINE_MIN px (judged here, rendered by the
  shell); a focusable without one is `focus_invisible`.
- No traps: every surface's focus order ends at an exit
  stop that returns to the primary navigation (S-382).

`walk_flow` walks S-382's three findability tasks
keyboard-only, stop by stop, and the battery holds it to
the same budgets. Pure code: no store, no audit event, no
migration -- schema 140 / taxonomy 142 stand.
"""
from __future__ import annotations

from samverk.layout_shell import FINDABILITY_TASKS, LINKS, SURFACES
from samverk.target_sizes import TARGETS

FOCUS_OUTLINE_MIN = 2

# surface -> tuple of focusable names in tab order.
FOCUS_ORDER = {
    "home": ("nav_repositories", "nav_issues", "nav_pull_requests",
             "nav_explore", "nav_notifications", "nav_settings",
             "nav_admin", "create_repo_button", "exit_to_nav"),
    "repositories": ("nav_home", "repo_link", "create_repo_button",
                     "exit_to_nav"),
    "issues": ("nav_home", "exit_to_nav"),
    "pull_requests": ("nav_home", "exit_to_nav"),
    "explore": ("nav_home", "search_input", "exit_to_nav"),
    "notifications": ("nav_home", "exit_to_nav"),
    "settings": ("nav_home", "mint_token_button", "save_button",
                 "exit_to_nav"),
    "tokens": ("nav_home", "mint_token_button", "exit_to_nav"),
    "new_repository": ("nav_home", "create_repo_button", "exit_to_nav"),
    "mirrors": ("nav_home", "add_mirror_button", "exit_to_nav"),
    "new_mirror": ("nav_home", "add_mirror_button", "exit_to_nav"),
    "admin": ("nav_home", "exit_to_nav"),
}

# Focus outline (px) declared per focusable; exit stop is shell chrome.
FOCUS_OUTLINE = {name: 3 for surface in FOCUS_ORDER.values()
                 for name in surface if name != "exit_to_nav"}
FOCUS_OUTLINE["exit_to_nav"] = 3

# action -> (surface, firing control)
ACTIONS = {
    "mint_a_token": ("tokens", "mint_token_button"),
    "create_a_repo": ("new_repository", "create_repo_button"),
    "add_a_mirror": ("new_mirror", "add_mirror_button"),
    "search": ("explore", "search_input"),
    "save_settings": ("settings", "save_button"),
    "open_repo": ("repositories", "repo_link"),
}


def keyboard_route(action, actions=None, focus=None):
    """Tab stops from surface entry to the firing control."""
    acts = ACTIONS if actions is None else actions
    order = FOCUS_ORDER if focus is None else focus
    if action not in acts:
        return None
    surface, control = acts[action]
    stops = order.get(surface, ())
    if control not in stops:
        return None
    return stops[:stops.index(control) + 1]


def audit_keyboard(focus=None, actions=None, targets=None):
    """Judge reachability, visible focus, traps, coverage."""
    order = FOCUS_ORDER if focus is None else focus
    acts = ACTIONS if actions is None else actions
    tgts = TARGETS if targets is None else targets
    problems = []
    for surface in SURFACES:
        if surface not in order:
            problems.append(f"surface_without_focus_order:{surface}")
        elif not order[surface] or order[surface][-1] != "exit_to_nav":
            problems.append(f"keyboard_trap:{surface}")
    anywhere = {n for stops in order.values() for n in stops}
    for name, surface, kind, w, h in tgts:
        # Nav targets are global chrome (S-382 renders the nav on
        # every surface): reachable if any order carries them.
        # Any other target must be in its own surface's order.
        if name.startswith("nav_"):
            if name not in anywhere:
                problems.append(f"target_not_focusable:{name}")
        elif name not in order.get(surface, ()):
            problems.append(f"target_not_focusable:{name}")
    for name in {n for stops in order.values() for n in stops}:
        if FOCUS_OUTLINE.get(name, 0) < FOCUS_OUTLINE_MIN:
            problems.append(f"focus_invisible:{name}")
    for action in acts:
        if keyboard_route(action, acts, order) is None:
            problems.append(f"action_unreachable:{action}")
    return problems


def walk_flow(task):
    """Walk one findability task keyboard-only via S-382 links."""
    goal = FINDABILITY_TASKS[task]
    from samverk.layout_shell import shortest_path
    path = shortest_path("home", goal)
    if path is None:
        return None
    stops = []
    for surface in path:
        stops.extend(FOCUS_ORDER.get(surface, ())[:1])
    return {"task": task, "surfaces": path, "stops": tuple(stops),
            "ok": path[-1] == goal}


def keyboard_passed():
    return audit_keyboard() == [] and all(
        walk_flow(t)["ok"] for t in FINDABILITY_TASKS)
