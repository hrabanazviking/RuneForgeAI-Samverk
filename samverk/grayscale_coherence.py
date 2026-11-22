"""Grayscale coherence (S-383).

Roadmap S-383: Grayscale coherence -- the whole UI audited
in grayscale; no meaning lost; screenshots filed as proof.

Colour may decorate, but it may never be the only carrier
of meaning. This module is the audit: every UI signal that
uses colour is registered in `MEANING_CARRIERS` with the
non-colour channels that carry the same meaning (a text
label, an icon glyph, a position or pattern). The audit
renders each carrier's colour down to its grayscale value
(the proof view) and judges two failures:

- **colour-only**: a carrier with a colour signal but no
  text and no icon loses its meaning entirely in grayscale.
- **grayscale collapse**: two carriers in one group whose
  grayscale values land within COLLAPSE_STEPS of each other
  become indistinguishable in grayscale unless a non-colour
  channel already separates them.

`render_proof_report` emits the filed proof: every carrier,
its colour, its grayscale value, and the channels that keep
its meaning alive without colour. Pure code: no store, no
audit event, no migration -- schema 140 / taxonomy 142
stand. Status text conventions follow S-157 (states said in
text+icon, never colour-only); the nav current marker is
S-382's aria-current text seam.
"""
from __future__ import annotations

COLLAPSE_STEPS = 8

# (name, group, colour, text, icon) -- text/icon None = absent.
MEANING_CARRIERS = (
    ("check_passed", "checks", "#2da44e", "Passed", "check"),
    ("check_failed", "checks", "#cf222e", "Failed", "cross"),
    ("check_pending", "checks", "#bf8700", "Pending", "clock"),
    ("repo_public", "visibility", "#57606a", "Public", "globe"),
    ("repo_private", "visibility", "#9e6a03", "Private", "lock"),
    ("branch_protected", "protection", "#8250df", "Protected", "shield"),
    ("branch_unprotected", "protection", "#6e7781", "Unprotected", None),
    ("alert_critical", "alerts", "#d1242f", "Critical", "alarm"),
    ("alert_warning", "alerts", "#9a6700", "Warning", "triangle"),
    ("alert_info", "alerts", "#0969da", "Info", "info"),
    ("nav_current", "navigation", "#c9a227", "Current page", None),
    ("nav_other", "navigation", "#57606a", "Surface name (the link text itself)", None),
)


def luminance(colour):
    """Relative luminance (0..1) of a #rrggbb colour."""
    h = colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    def lin(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def grayscale_value(colour):
    """The 0..255 gray a colour collapses to in grayscale."""
    return round(luminance(colour) * 255)


def _separated(a, b):
    """True when a non-colour channel separates two carriers."""
    return (a[3] is not None and b[3] is not None and a[3] != b[3]) or (
        a[4] is not None and b[4] is not None and a[4] != b[4])


def audit_grayscale(carriers=None):
    """Judge the standing carriers: no meaning lost in gray."""
    rows = MEANING_CARRIERS if carriers is None else carriers
    problems = []
    for name, group, colour, text, icon in rows:
        if text is None and icon is None:
            problems.append(f"colour_only:{name}")
    by_group = {}
    for row in rows:
        by_group.setdefault(row[1], []).append(row)
    for group, members in by_group.items():
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                gap = abs(grayscale_value(a[2]) - grayscale_value(b[2]))
                if gap <= COLLAPSE_STEPS and not _separated(a, b):
                    problems.append(
                        f"grayscale_collapse:{group}:{a[0]}/{b[0]}")
    return problems


def grayscale_passed(carriers=None):
    return audit_grayscale(carriers) == []


def render_proof_report(carriers=None):
    """The filed proof: every carrier in its grayscale form."""
    rows = MEANING_CARRIERS if carriers is None else carriers
    lines = ["carrier | colour | gray | text | icon"]
    for name, group, colour, text, icon in rows:
        lines.append(
            f"{name} | {colour} | {grayscale_value(colour)} | "
            f"{text or '-'} | {icon or '-'}")
    return "\n".join(lines)
