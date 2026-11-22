"""Target sizes (S-386).

Roadmap S-386: Target sizes -- interactive targets
>=44x44px, controls 40-48px; the audit is automated over
rendered pages.

Small targets are a tax on every hand, paid hardest by
the hands that can least afford it. The law is two numbers:

- every interactive **target** (links, buttons, toggles)
  is at least 44x44px;
- every **control** (buttons, inputs, selects) stands in
  the 40-48px height band -- and since a control is also
  a target, standing controls sit at 44-48px where the two
  laws overlap, so rows stay even (S-381's
  frame discipline applied to reach).

`TARGETS` is the standing registry: name, surface, kind,
width, height. `audit_targets` judges the registry;
`audit_rendered_nav` runs the audit over a rendered page
-- it reads S-382's rendered primary navigation, and every
link it finds must resolve to a registered target that
passes the 44px law, so a new nav surface cannot ship
with an unmeasured target. Pure code: no store, no audit
event, no migration -- schema 140 / taxonomy 142 stand.
"""
from __future__ import annotations

import re

from samverk.layout_shell import SURFACES, render_nav

MIN_TARGET = 44
CONTROL_MIN = 40
CONTROL_MAX = 48

# (name, surface, kind, width_px, height_px) kind: target|control
TARGETS = (
    ("nav_home", "home", "target", 96, 44),
    ("nav_repositories", "repositories", "target", 150, 44),
    ("nav_issues", "issues", "target", 96, 44),
    ("nav_pull_requests", "pull_requests", "target", 160, 44),
    ("nav_explore", "explore", "target", 104, 44),
    ("nav_notifications", "notifications", "target", 150, 44),
    ("nav_settings", "settings", "target", 110, 44),
    ("nav_admin", "admin", "target", 96, 44),
    ("mint_token_button", "tokens", "control", 170, 44),
    ("create_repo_button", "new_repository", "control", 180, 44),
    ("add_mirror_button", "new_mirror", "control", 160, 44),
    ("save_button", "settings", "control", 96, 44),
    ("search_input", "explore", "control", 320, 44),
    ("repo_link", "repositories", "target", 220, 44),
)


def audit_targets(targets=None):
    """Judge the registry against the two size laws."""
    rows = TARGETS if targets is None else targets
    problems = []
    for name, surface, kind, w, h in rows:
        if w < MIN_TARGET or h < MIN_TARGET:
            problems.append(f"target_too_small:{name}:{w}x{h}")
        if kind == "control" and not (CONTROL_MIN <= h <= CONTROL_MAX):
            problems.append(f"control_out_of_band:{name}:{h}")
        if surface not in SURFACES:
            problems.append(f"target_surface_unknown:{name}:{surface}")
    return problems


def audit_rendered_nav(html=None, targets=None):
    """Every link in the rendered nav has a passing target."""
    page = render_nav("home") if html is None else html
    rows = TARGETS if targets is None else targets
    by_surface = {r[1]: r for r in rows if r[0].startswith("nav_")}
    problems = []
    for href in re.findall(r'href="/([a-z_]+)"', page):
        row = by_surface.get(href)
        if row is None:
            problems.append(f"rendered_target_unregistered:{href}")
        elif row[3] < MIN_TARGET or row[4] < MIN_TARGET:
            problems.append(f"rendered_target_too_small:{href}")
    return problems


def targets_passed(targets=None):
    return audit_targets(targets) == [] and audit_rendered_nav() == []
