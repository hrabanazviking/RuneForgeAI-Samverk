"""Text scaling (S-384).

Roadmap S-384: Text scaling -- 125% and 200% scaling
passes on every core flow; no clipped controls, no
overlapping text.

Text scaling is where fixed layouts quietly break: the
words get bigger, the boxes do not, and controls clip or
overlap. This module models every core flow's controls
with their S-381 token sizes and container widths, then
re-runs the layout arithmetic at 125% and 200%:

- a control's needed width is its text at the scaled font
  (average glyph advance = half the font size, the standing
  model); a control **clips** when the need exceeds its
  container and the control cannot wrap;
- two fixed controls **overlap** when their scaled widths
  together exceed their shared row;
- wrapping (fluid) text never clips: it grows downward;
  the primary nav is a wrapping flex row and long buttons
  wrap their label and grow taller -- both are designed
  behaviour, marked wraps=True in the registry;
  which is the designed behaviour, named in the registry.

`audit_scaling` judges the standing registry at both
scales; `scaled_sizes` reports the effective token sizes
at a scale (body 16px -> 20px / 32px, small 14px -> 17.5px
/ 28px). Pure code: no store, no audit event, no migration
-- schema 140 / taxonomy 142 stand.
"""
from __future__ import annotations

import math

SCALES = (1.25, 2.0)
GLYPH_ADVANCE = 0.5  # average glyph width as a font-size share

# (flow, control, text, font_px, container_px, wraps)
CONTROLS = (
    ("navigation", "nav_home", "Home", 16, 120, True),
    ("navigation", "nav_repositories", "Repositories", 16, 160, True),
    ("navigation", "nav_pull_requests", "Pull requests", 16, 170, True),
    ("navigation", "nav_settings", "Settings", 16, 120, True),
    ("repo_header", "repo_name", "samverk", 16, 480, True),
    ("repo_header", "visibility_label", "Private", 14, 110, False),
    ("repo_header", "mirror_button", "Add mirror", 16, 150, True),
    ("issue_list", "issue_title", "Fix the thing", 16, 560, True),
    ("issue_list", "state_label", "Open", 14, 80, False),
    ("settings_form", "token_button", "Mint a token", 16, 170, True),
    ("settings_form", "save_button", "Save", 16, 90, False),
    ("settings_form", "field_hint", "Names are permanent", 14, 420, True),
)

# Fixed controls sharing one row: (flow, row, container_px, names)
ROWS = (
    ("repo_header", "header_row", 760,
     ("visibility_label", "mirror_button")),
    ("settings_form", "button_row", 300,
     ("token_button", "save_button")),
)


def needed_width(text, font_px, scale):
    return math.ceil(len(text) * GLYPH_ADVANCE * font_px * scale)


def scaled_sizes(scale):
    return {"body_px": 16 * scale, "small_px": 14 * scale}


def audit_scaling(controls=None, rows=None, scales=SCALES):
    """Judge every core flow at every scale: no clips/overlaps."""
    ctrls = CONTROLS if controls is None else controls
    rws = ROWS if rows is None else rows
    problems = []
    by_name = {c[1]: c for c in ctrls}
    for scale in scales:
        tag = f"{int(scale * 100)}pct"
        for flow, name, text, font, box, wraps in ctrls:
            if wraps:
                continue
            if needed_width(text, font, scale) > box:
                problems.append(f"clipped:{flow}:{name}@{tag}")
        for flow, row, box, names in rws:
            total = sum(needed_width(by_name[n][2], by_name[n][3], scale)
                        for n in names)
            if total > box:
                problems.append(f"overlap:{flow}:{row}@{tag}")
    return problems


def scaling_passed(controls=None, rows=None):
    return audit_scaling(controls, rows) == []
