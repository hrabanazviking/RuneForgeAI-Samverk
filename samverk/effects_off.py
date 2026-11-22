"""Effects-off coherence (S-385).

Roadmap S-385: Effects-off coherence -- glow and texture
disabled: the UI remains fully legible and hierarchical.

Glow and texture are seasoning, never structure. This
module registers every styled element with the channels
that carry its place in the hierarchy, split in two kinds:

- **structural** channels survive effects-off: heading
  level, type size (the S-381 ladder), weight, and frame
  strength (S-381's three strengths);
- **effect** channels vanish: glow, texture, shadow.

`audit_effects_off` judges the standing registry twice:
(1) hierarchy -- for any two elements in a group whose
ranks differ, a structural channel must separate them in
the same direction; an element ranked only by an effect
is named `effects_only`. (2) legibility -- every text
element's foreground/background pair must keep WCAG
contrast >= 4.5 with effects off (a glow halo must never
be what makes text readable). Pure code: no store, no
audit event, no migration -- schema 140 / taxonomy 142
stand. Luminance is S-383's one implementation.
"""
from __future__ import annotations

from samverk.grayscale_coherence import luminance

MIN_CONTRAST = 4.5

# (name, group, rank, size_px, weight, frame, effects, fg, bg)
# fg/bg None = not a text element. effects: tuple of effect channels.
ELEMENTS = (
    ("page_title", "page", 3, 28, 700, 0, ("glow",), "#f0f3f6", "#0b0d10"),
    ("section_heading", "page", 2, 20, 700, 0, (), "#f0f3f6", "#12151a"),
    ("body_text", "page", 1, 16, 400, 0, (), "#d6dce3", "#12151a"),
    ("muted_text", "page", 0, 14, 400, 0, (), "#9aa7b4", "#12151a"),
    ("primary_button", "actions", 2, 16, 600, 2, ("glow",), "#0b0d10", "#c9a227"),
    ("plain_button", "actions", 1, 16, 400, 1, (), "#f0f3f6", "#232833"),
    ("card_title", "card", 2, 16, 700, 0, (), "#f0f3f6", "#1a1e25"),
    ("card_body", "card", 1, 16, 400, 0, ("texture",), "#d6dce3", "#1a1e25"),
    ("accent_link", "page", 1, 16, 600, 0, (), "#c9a227", "#12151a"),
)


def contrast_ratio(fg, bg):
    hi, lo = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _structural_gap(a, b):
    """Structural separation in rank order, or None if tied."""
    for idx in (3, 4, 5):  # size, weight, frame
        if a[idx] != b[idx]:
            return a[idx] - b[idx]
    return None


def audit_effects_off(elements=None):
    """Judge hierarchy + legibility with all effects off."""
    rows = ELEMENTS if elements is None else elements
    problems = []
    by_group = {}
    for row in rows:
        by_group.setdefault(row[1], []).append(row)
    for group, members in by_group.items():
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                if a[2] == b[2]:
                    continue
                higher, lower = (a, b) if a[2] > b[2] else (b, a)
                gap = _structural_gap(higher, lower)
                if gap is None or gap < 0:
                    problems.append(
                        f"effects_only:{group}:{higher[0]}/{lower[0]}")
    for name, group, rank, size, weight, frame, fx, fg, bg in rows:
        if fg is not None and contrast_ratio(fg, bg) < MIN_CONTRAST:
            problems.append(f"illegible_without_effects:{name}")
    return problems


def effects_off_passed(elements=None):
    return audit_effects_off(elements) == []
