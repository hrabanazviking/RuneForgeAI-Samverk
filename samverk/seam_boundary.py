"""Seam boundary (S-375) — what the seam is NOT.

The honest boundary, declared in one place in code so
the battery can hold the codebase to it, and written
for operators in docs/SEAM_BOUNDARY.md. The seam joins
two sovereignties; it merges neither, and these are
the lines it never crosses:

- No federation: villages do not federate. Samverk
  never trusts another village's word about identity,
  membership, or permission; every seam door decides
  locally, on Samverk's own stores.
- No cross-village identity: the S-362 link is one
  Samverk account holding one external identifier,
  made by that account's own signed act. There is no
  global villager, no portable identity, and an
  external id is an identifier, never a credential.
- No Samtal requirement for Samverk: Samverk runs
  whole on its own — accounts, login, repositories,
  export — with the seam unconfigured. The seam is
  disabled by default (S-361 seam_enabled) and the
  kill switch (S-366) can close it without touching
  anything standalone.

boundary_statements() is the counted declaration;
check_boundary() re-verifies the load-bearing claims
against the standing code (seam off by default, the
contract's own no-federation line) and reports any
drift by name. No migration, no new taxonomy event:
this slice declares and checks; it builds nothing.
"""
from __future__ import annotations

from pathlib import Path

from .seam_contract import seam_enabled

BOUNDARIES = (
    {
        "id": "no_federation",
        "claim": "No federation: villages do not federate; "
                 "every seam door decides locally on "
                 "Samverk's own stores.",
    },
    {
        "id": "no_cross_village_identity",
        "claim": "No cross-village identity: a link is one "
                 "account holding one external identifier, "
                 "never a credential, never portable.",
    },
    {
        "id": "no_samtal_requirement",
        "claim": "No Samtal requirement for Samverk: "
                 "Samverk runs whole standalone with the "
                 "seam unconfigured or closed.",
    },
)


def boundary_statements() -> tuple:
    """The boundary, counted: every statement, in order."""
    return BOUNDARIES


def check_boundary(settings: dict | None = None) -> dict:
    """Re-verify the load-bearing claims on the standing
    code. Returns {ok, checks: [{name, ok, detail}]}; a
    failed check names the drift, never a blur."""
    checks = []
    off = not seam_enabled(settings) and not seam_enabled(None) \
        and not seam_enabled({})
    checks.append({
        "name": "seam_disabled_by_default",
        "ok": bool(off),
        "detail": "seam_enabled is False for None, {} and "
                  "the given settings" if off else
                  "seam_enabled came back True by default",
    })
    src = Path(__file__).with_name("seam_contract.py").read_text()
    named = "federation between villages is" in src
    checks.append({
        "name": "contract_names_no_federation",
        "ok": named,
        "detail": "seam_contract.py states the no-federation "
                  "line" if named else
                  "seam_contract.py lost its no-federation line",
    })
    fed = [p.name for p in Path(__file__).parent.glob("*federat*")]
    checks.append({
        "name": "no_federation_surface",
        "ok": not fed,
        "detail": "no federation module in samverk/" if not fed
                  else f"federation surface appeared: {fed}",
    })
    return {"ok": all(c["ok"] for c in checks), "checks": checks}
