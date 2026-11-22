"""Design tokens (S-381) -- Part XX opens.

Roadmap S-381: Design tokens -- the Lawbook's numbers as
code: corner cuts 6-12px, <=3 frame strengths, accent budget
5-12%, >=4 dark surface values, body text 14-18px.

The Lawbook (Book XIV) states its visual law in numbers.
Until this slice those numbers lived only in prose; a page
could break every one of them and no test would notice.
This module is the numbers as code: one frozen registry
that every surface draws from, plus the judge that refuses
a token set -- or a page's declared usage -- that breaks
the law.

- **Corner cuts** live in [6, 12] px; the registry carries
  exactly three cuts (soft 6, standard 9, deep 12).
- **Frame strengths** number at most 3 (hairline, standard,
  strong); a fourth strength is refused by name.
- **Accent budget**: the accent's share of a surface must
  sit in [5, 12] percent -- present enough to guide the
  eye, never loud enough to own the page. `accent_share`
  computes a page's share from declared element areas and
  `check_accent_budget` judges it.
- **Dark surfaces**: at least 4 distinct dark surface
  values form the darkness ladder; the registry carries 5.
- **Body text** sits in [14, 18] px; the registry's body
  size is 16, with small text never below the 14 floor for
  running text.

`render_css_variables` emits the registry as CSS custom
properties -- the one seam through which pages take the
numbers. `validate_registry` re-judges the standing
registry itself, so a future edit that breaks the law
fails the battery instead of shipping quietly. Pure code:
no store, no audit event, no migration -- schema 140 /
taxonomy 142 stand.
"""
from __future__ import annotations

from dataclasses import dataclass

CORNER_CUT_MIN_PX = 6
CORNER_CUT_MAX_PX = 12
MAX_FRAME_STRENGTHS = 3
ACCENT_BUDGET_MIN_PCT = 5.0
ACCENT_BUDGET_MAX_PCT = 12.0
MIN_DARK_SURFACES = 4
BODY_TEXT_MIN_PX = 14
BODY_TEXT_MAX_PX = 18


@dataclass(frozen=True)
class DesignTokens:
    corner_cuts_px: tuple
    frame_strengths_px: tuple
    accent_colour: str
    dark_surfaces: tuple
    body_text_px: int
    small_text_px: int
    heading_text_px: int


TOKENS = DesignTokens(
    corner_cuts_px=(6, 9, 12),
    frame_strengths_px=(1, 2, 3),
    accent_colour="#c9a227",
    dark_surfaces=("#0b0d10", "#12151a", "#1a1e25", "#232833", "#2e3542"),
    body_text_px=16,
    small_text_px=14,
    heading_text_px=18,
)


def validate_registry(tokens=TOKENS):
    """Judge a token set against the Lawbook's numbers.

    Returns a list of violation codes; empty means lawful.
    """
    problems = []
    for cut in tokens.corner_cuts_px:
        if not (CORNER_CUT_MIN_PX <= cut <= CORNER_CUT_MAX_PX):
            problems.append("corner_cut_out_of_range")
    if not tokens.corner_cuts_px:
        problems.append("corner_cut_missing")
    if len(tokens.frame_strengths_px) > MAX_FRAME_STRENGTHS:
        problems.append("too_many_frame_strengths")
    if not tokens.frame_strengths_px:
        problems.append("frame_strength_missing")
    if len(set(tokens.dark_surfaces)) < MIN_DARK_SURFACES:
        problems.append("too_few_dark_surfaces")
    if not (BODY_TEXT_MIN_PX <= tokens.body_text_px <= BODY_TEXT_MAX_PX):
        problems.append("body_text_out_of_range")
    if tokens.small_text_px < BODY_TEXT_MIN_PX:
        problems.append("small_text_below_floor")
    if tokens.heading_text_px < tokens.body_text_px:
        problems.append("heading_below_body")
    return problems


def accent_share(elements):
    """Accent share of a page, in percent.

    `elements` is an iterable of (area, is_accent) pairs.
    An empty page has share 0.0.
    """
    total = 0.0
    accent = 0.0
    for area, is_accent in elements:
        if area < 0:
            raise ValueError("element_area_negative")
        total += area
        if is_accent:
            accent += area
    if total == 0:
        return 0.0
    return 100.0 * accent / total


def check_accent_budget(elements):
    """Judge one page's accent share against the budget."""
    share = accent_share(elements)
    if share < ACCENT_BUDGET_MIN_PCT:
        return {"ok": False, "share_pct": share, "reason": "accent_below_budget"}
    if share > ACCENT_BUDGET_MAX_PCT:
        return {"ok": False, "share_pct": share, "reason": "accent_over_budget"}
    return {"ok": True, "share_pct": share, "reason": None}


def corner_cut(name):
    cuts = {"soft": TOKENS.corner_cuts_px[0],
            "standard": TOKENS.corner_cuts_px[1],
            "deep": TOKENS.corner_cuts_px[2]}
    if name not in cuts:
        raise ValueError("corner_cut_unknown")
    return cuts[name]


def render_css_variables(tokens=TOKENS):
    """The registry as CSS custom properties -- the one seam."""
    lines = [":root {"]
    for i, cut in enumerate(tokens.corner_cuts_px):
        lines.append(f"  --sv-corner-cut-{i}: {cut}px;")
    for i, strength in enumerate(tokens.frame_strengths_px):
        lines.append(f"  --sv-frame-{i}: {strength}px;")
    lines.append(f"  --sv-accent: {tokens.accent_colour};")
    for i, surface in enumerate(tokens.dark_surfaces):
        lines.append(f"  --sv-surface-{i}: {surface};")
    lines.append(f"  --sv-body-text: {tokens.body_text_px}px;")
    lines.append(f"  --sv-small-text: {tokens.small_text_px}px;")
    lines.append(f"  --sv-heading-text: {tokens.heading_text_px}px;")
    lines.append("}")
    return "\n".join(lines) + "\n"
