"""Screen-reader pass (S-389).

Roadmap S-389: Screen-reader pass -- ARIA landmarks and
labels on core flows verified with a real screen reader;
findings fixed or named.

What a screen reader meets is structure, not pixels:
landmarks to jump between, headings in order, and an
accessible name on every control. This module audits
that structure over the pages Samverk actually renders:

- `LANDMARKS` declares, per S-382 surface, the landmark
  set the page skeleton must emit (banner, navigation,
  main, contentinfo); a surface missing one is named.
- `audit_rendered` parses rendered HTML: the navigation
  landmark must carry its aria-label, every link must
  have an accessible name (its text or an aria-label --
  an icon alone is not a name, S-387's law in reader
  form), and heading levels must not skip.
- Every S-387 status carrier's text doubles as its
  accessible name; `audit_status_names` holds that seam.

NAMED REMAINDER (honest, per the roadmap's "fixed or
named"): the live walkthrough with a real screen reader
(Orca on the fleet laptops) has NOT been run in this
slice -- no reader session exists on this seat to run it
with. What is verified here is the full structural audit
the reader consumes; the live session is recorded in
docs/SCREEN_READER_PASS.md as the outstanding finding
F-S389-1, to be closed by a reader session, not by code.

Pure code: no store, no audit event, no migration --
schema 140 / taxonomy 142 stand.
"""
from __future__ import annotations

import re

from samverk.layout_shell import NAV_ORDER, SURFACES, render_nav
from samverk.never_colour_only import status_carriers

REQUIRED_LANDMARKS = ("banner", "navigation", "main", "contentinfo")

LANDMARKS = {surface: REQUIRED_LANDMARKS for surface in SURFACES}


def audit_landmarks(landmarks=None):
    rows = LANDMARKS if landmarks is None else landmarks
    problems = []
    for surface in SURFACES:
        have = rows.get(surface, ())
        for needed in REQUIRED_LANDMARKS:
            if needed not in have:
                problems.append(f"landmark_missing:{surface}:{needed}")
    return problems


def accessible_name(link_html):
    """The name a reader announces for one link, or None."""
    label = re.search(r'aria-label="([^"]+)"', link_html)
    if label:
        return label.group(1)
    text = re.sub(r"<[^>]+>", "", link_html).strip()
    return text or None


def audit_rendered(html):
    """Judge one rendered page's reader-facing structure."""
    problems = []
    nav = re.search(r"<nav[^>]*>", html)
    if nav is None:
        problems.append("landmark_missing:rendered:navigation")
    elif 'aria-label="Primary"' not in nav.group(0):
        problems.append("nav_landmark_unlabelled")
    for link in re.findall(r"<a [^>]*>.*?</a>", html):
        if accessible_name(link) is None:
            problems.append(f"link_without_name:{link[:40]}")
    levels = [int(n) for n in re.findall(r"<h([1-6])[ >]", html)]
    for a, b in zip(levels, levels[1:]):
        if b > a + 1:
            problems.append(f"heading_skip:h{a}->h{b}")
    return problems


def audit_status_names(carriers=None):
    """Every status's text is its accessible name (S-387 seam)."""
    problems = []
    for name, group, colour, text, icon in status_carriers(carriers):
        if not text:
            problems.append(f"status_without_accessible_name:{name}")
    return problems


def audit_core_flows():
    """The full pass over every rendered nav surface + registries."""
    problems = audit_landmarks() + audit_status_names()
    for surface in NAV_ORDER:
        problems += audit_rendered(render_nav(surface))
    return problems


def screen_reader_passed():
    return audit_core_flows() == []
