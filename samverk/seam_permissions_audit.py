"""Seam permissions audit (S-373).

The full permissions matrix re-run with linked
identities: Samtal role x Samverk role x seam surface,
counted. S-361 froze the contract, S-362 linked the
identities, S-365 mapped hall roles to repo roles
through S-190, and S-368/S-369/S-370 each judged their
own surface. This slice re-runs the whole grid in one
place so an operator can read, in counted form, exactly
who may cross the seam where — and prove that nobody
crosses anywhere their Samverk role does not already
reach.

The axes are the standing ones, never re-derived:
Samtal roles are S-365's hall roles (owner, member)
plus the linked villager who belongs to no hall
(none); Samverk roles are S-189's ladder (read, triage,
write, maintain, admin) plus no role at all (none);
surfaces are the five seam doors that judge a viewer:
the panel (S-368), the unfurl (S-370), the mentions
bridge (S-369), hall events (S-367) and village
repositories (S-365). 3 x 6 x 5 = 90 cells.

Each cell is judged by composing the standing laws:
the Samverk side is S-189's own rank (role_covers), so
a surface that needs read admits exactly the roles at
or above read; the Samtal side is each surface's own
standing rule — the panel, the unfurl and the mentions
bridge serve any linked identity, while hall events
and village repositories serve hall members only (a
hall surface has no meaning for a villager outside the
hall). The mentions bridge is the one door that needs
no repo role at all: S-369 delivers to the linked
principal, and the notification itself is S-223's.

Two collapses are part of the audit, not footnotes:
with the seam disabled, or for an identity with no
S-362 link, every one of the 90 cells denies — the
matrix has no back door around the switch or the link.
No migration, no new taxonomy event: the audit judges
and counts, it stores nothing.
"""
from __future__ import annotations

from dataclasses import dataclass

from .seam_contract import seam_enabled
from .team_permissions import ROLES, role_covers

SAMTAL_ROLES = ("owner", "member", "none")
SAMVERK_ROLES = ROLES + ("none",)
SURFACES = ("panel", "unfurl", "mentions", "hall_events", "village_repo")
_HALL_ONLY = ("hall_events", "village_repo")
_MIN_ROLE = {"panel": "read", "unfurl": "read", "mentions": None,
             "hall_events": "read", "village_repo": "read"}


@dataclass(frozen=True)
class Cell:
    samtal_role: str
    samverk_role: str
    surface: str
    allowed: bool
    reason: str


@dataclass(frozen=True)
class AuditReport:
    cells: tuple
    seam_on: bool
    linked: bool

    @property
    def total(self) -> int:
        return len(self.cells)

    @property
    def allowed(self) -> int:
        return sum(1 for c in self.cells if c.allowed)

    @property
    def denied(self) -> int:
        return self.total - self.allowed

    def for_surface(self, surface: str) -> tuple:
        cells = tuple(c for c in self.cells if c.surface == surface)
        return (len(cells), sum(1 for c in cells if c.allowed))

    def cell(self, samtal_role: str, samverk_role: str, surface: str) -> Cell:
        for c in self.cells:
            if (c.samtal_role, c.samverk_role, c.surface) == (samtal_role, samverk_role, surface):
                return c
        raise KeyError((samtal_role, samverk_role, surface))

    def summary(self) -> str:
        return (f"seam permissions audit: {self.total} cells, "
                f"{self.allowed} allowed, {self.denied} denied "
                f"(seam {'on' if self.seam_on else 'off'}, "
                f"{'linked' if self.linked else 'unlinked'} identities)")


def _judge(samtal_role: str, samverk_role: str, surface: str,
           *, seam_on: bool, linked: bool) -> Cell:
    if not seam_on:
        return Cell(samtal_role, samverk_role, surface, False, "seam_disabled")
    if not linked:
        return Cell(samtal_role, samverk_role, surface, False, "not_linked")
    if surface in _HALL_ONLY and samtal_role == "none":
        return Cell(samtal_role, samverk_role, surface, False, "not_hall_member")
    minimum = _MIN_ROLE[surface]
    if minimum is not None:
        if samverk_role == "none" or not role_covers(samverk_role, minimum):
            return Cell(samtal_role, samverk_role, surface, False, "role_insufficient")
    return Cell(samtal_role, samverk_role, surface, True, "allowed")


def run_audit(settings: dict | None = None, *, linked: bool = True) -> AuditReport:
    """Re-run the full matrix and count it. Defaults to the
    seam as configured in settings (disabled unless an
    explicit True stands, S-361's own judgement)."""
    seam_on = seam_enabled(settings)
    cells = tuple(
        _judge(st, sv, surface, seam_on=seam_on, linked=linked)
        for surface in SURFACES for st in SAMTAL_ROLES for sv in SAMVERK_ROLES)
    return AuditReport(cells=cells, seam_on=seam_on, linked=linked)
