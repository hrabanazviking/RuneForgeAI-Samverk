"""Motion discipline (S-391).

Roadmap S-391: Motion discipline -- UI motion within the
Lawbook's bands (80-140ms / 160-220ms), ceremonial motion
rare; `prefers-reduced-motion` respected fully.

Motion is punctuation, not wallpaper. The Lawbook gives
everyday motion two bands and ceremony a ration:

- **micro** motion (hover, focus, toggle feedback) lives
  in 80-140ms;
- **transition** motion (surface changes, panels) lives
  in 160-220ms;
- **ceremonial** motion (the rare, deliberate flourish)
  is exempt from the bands but rationed: at most one per
  surface and never more than CEREMONIAL_MAX_SHARE of
  all registered motion.

`MOTIONS` is the standing registry. `audit_motion` names
any duration outside its band and any ceremony that
breaks the ration. `reduced_motion` applies the user's
`prefers-reduced-motion`: every duration becomes 0 and
ceremonial motion is removed outright -- respected
fully means nothing moves, not that things move less.

Pure code: no store, no audit event, no migration --
schema 140 / taxonomy 142 stand.
"""
from __future__ import annotations

BANDS = {"micro": (80, 140), "transition": (160, 220)}
CEREMONIAL_MAX_SHARE = 0.10

# (name, surface, kind, duration_ms)
MOTIONS = (
    ("hover_lift", "repositories", "micro", 100),
    ("focus_ring_in", "settings", "micro", 90),
    ("toggle_slide", "settings", "micro", 120),
    ("check_pop", "pull_requests", "micro", 110),
    ("tab_switch", "issues", "micro", 100),
    ("panel_open", "repositories", "transition", 180),
    ("surface_crossfade", "home", "transition", 200),
    ("drawer_slide", "notifications", "transition", 170),
    ("modal_rise", "new_repository", "transition", 210),
    ("gate_pass_flourish", "home", "ceremonial", 900),
)


def audit_motion(motions=None):
    """Judge durations against the bands and the ration."""
    rows = MOTIONS if motions is None else motions
    problems = []
    ceremonial = [r for r in rows if r[2] == "ceremonial"]
    for name, surface, kind, ms in rows:
        if kind in BANDS:
            lo, hi = BANDS[kind]
            if not (lo <= ms <= hi):
                problems.append(f"motion_out_of_band:{name}:{ms}")
        elif kind != "ceremonial":
            problems.append(f"motion_kind_unknown:{name}:{kind}")
    if rows and len(ceremonial) / len(rows) > CEREMONIAL_MAX_SHARE:
        problems.append(
            f"ceremonial_too_common:{len(ceremonial)}/{len(rows)}")
    per_surface = {}
    for name, surface, kind, ms in ceremonial:
        per_surface[surface] = per_surface.get(surface, 0) + 1
        if per_surface[surface] > 1:
            problems.append(f"ceremonial_per_surface:{surface}")
    return problems


def reduced_motion(motions=None):
    """prefers-reduced-motion, fully: nothing moves at all."""
    rows = MOTIONS if motions is None else motions
    return tuple((name, surface, kind, 0)
                 for name, surface, kind, ms in rows
                 if kind != "ceremonial")


def motion_passed(motions=None):
    rows = MOTIONS if motions is None else motions
    return (audit_motion(rows) == []
            and all(ms == 0 for *_, ms in reduced_motion(rows)))
