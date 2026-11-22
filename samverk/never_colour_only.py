"""Never colour-only (S-387).

Roadmap S-387: Never colour-only -- every status (checks,
alerts, protection, visibility) carries icon + text; the
audit greps the UI for violations.

S-383 proved no meaning is lost in grayscale because every
carrier kept at least one non-colour channel. This slice
is the stricter standing law for statuses specifically:
a status must carry BOTH its icon and its text, always --
one channel is a single point of failure (an icon font
that fails to load, a label truncated by S-384's scaling).

- `audit_statuses` judges S-383's MEANING_CARRIERS in the
  four status groups: any carrier missing its icon or its
  text is named.
- `grep_ui` greps the shipped UI code: any source file
  that uses a status carrier's colour must also contain
  that carrier's text and icon in the same file, so a new
  renderer cannot borrow a status colour and drop the
  channels that make it mean something.

Pure code: no store, no audit event, no migration --
schema 140 / taxonomy 142 stand.
"""
from __future__ import annotations

from pathlib import Path

from samverk.grayscale_coherence import MEANING_CARRIERS

STATUS_GROUPS = ("checks", "alerts", "protection", "visibility")


def status_carriers(carriers=None):
    rows = MEANING_CARRIERS if carriers is None else carriers
    return [r for r in rows if r[1] in STATUS_GROUPS]


def audit_statuses(carriers=None):
    """Every status carries icon + text, or it is named."""
    problems = []
    for name, group, colour, text, icon in status_carriers(carriers):
        if text is None:
            problems.append(f"status_missing_text:{name}")
        if icon is None:
            problems.append(f"status_missing_icon:{name}")
    return problems


def grep_ui(root=None, carriers=None):
    """Grep shipped UI sources for colour-only status use."""
    base = Path(__file__).resolve().parent if root is None else Path(root)
    problems = []
    for name, group, colour, text, icon in status_carriers(carriers):
        for path in sorted(base.glob("*.py")):
            src = path.read_text(encoding="utf-8")
            if colour not in src:
                continue
            if text is not None and text not in src:
                problems.append(
                    f"grep_colour_without_text:{path.name}:{name}")
            if icon is not None and icon not in src:
                problems.append(
                    f"grep_colour_without_icon:{path.name}:{name}")
    return sorted(set(problems))


def colour_only_passed(root=None, carriers=None):
    return audit_statuses(carriers) == [] and grep_ui(root, carriers) == []
