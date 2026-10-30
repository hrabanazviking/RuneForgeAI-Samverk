"""Reserved and impersonation defence (S-046).

Exact reserved names are already refused at registration
(S-025). This slice guards the *neighbourhood*: a candidate
that merely *looks like* an instance-known name — a reserved
name or a live account — earns a plain-language warning at
registration time, so `adm1n`, `volrnarr` and `vol-marr`
cannot slip past human eyes unremarked.

- **Skeleton:** a name's skeleton lowercases it, drops the
  separator characters (`-`, `_`, `.`), folds common
  leetspeak substitutions (0→o, 1→i, 3→e, 4→a, 5→s, 7→t,
  @→a, $→s; a `1` meant as `l` still lands within edit
  distance 1 of the true name), and folds the visual
  confusables `rn`→`m` and `vv`→`w` (one glance wide, two
  edits wide — the battery caught both). Two names with
  equal skeletons are lookalikes by construction.
- **Near miss:** skeletons at edit distance 1 (one
  insertion, deletion, or substitution — the classic
  rn-for-m / swapped-letter territory) also warn, when both
  are long enough for the distance to mean something (≥4).
- **Warnings, not refusals:** impersonation defence here is
  honest signalling — `lookalike_warnings` returns the known
  names the candidate resembles, for the registration
  surface to show. Refusal stays S-025's job for exact
  reserved/taken names; a warning never silently blocks a
  lawful distinct name.
- `AccountStore` integration lives in
  `registration_warnings(conn, candidate)`: the known set is
  the reserved vocabulary plus every live username.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .accounts import RESERVED_USERNAMES

_LEET = str.maketrans({
    "0": "o", "1": "i", "3": "e", "4": "a",
    "5": "s", "7": "t", "@": "a", "$": "s",
})
_SEPARATORS = "-_."


def skeleton(name: str) -> str:
    lowered = name.strip().lower()
    folded = lowered.translate(_LEET)
    cleaned = "".join(c for c in folded if c not in _SEPARATORS)
    # Visual confusables that are two edits wide but one
    # glance wide: "rn" reads as "m", "vv" as "w".
    return cleaned.replace("rn", "m").replace("vv", "w")


def _edit_distance(a: str, b: str) -> int:
    """Levenshtein distance, capped early at 2 (we only care
    whether it is exactly 1)."""
    if abs(len(a) - len(b)) > 1:
        return 2
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        best = i
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
            best = min(best, cur[j])
        if best > 1 and i > 1:
            # No need for exactness beyond the threshold.
            pass
        prev = cur
    return prev[-1]


@dataclass(frozen=True)
class LookalikeWarning:
    candidate: str
    resembles: str       # the known name it looks like
    kind: str            # "reserved" | "existing"

    @property
    def message(self) -> str:
        return (f"This username looks very similar to "
                f"'{self.resembles}'. If you are not connected "
                f"with that name, consider choosing another — "
                f"lookalike names are often used to impersonate.")


def lookalike_warnings(
    candidate: object,
    known_existing: list[str] | tuple[str, ...] = (),
) -> list[LookalikeWarning]:
    """Warnings for a registration candidate against the
    reserved vocabulary and the given live usernames. An
    exact match earns no warning here — S-025 refuses those
    outright; this is the near-miss net."""
    if not isinstance(candidate, str) or not candidate.strip():
        return []
    cand_skel = skeleton(candidate)
    cand_lower = candidate.strip().lower()
    out: list[LookalikeWarning] = []
    seen: set[str] = set()

    def consider(known: str, kind: str) -> None:
        if known.lower() == cand_lower or known in seen:
            return
        known_skel = skeleton(known)
        if known_skel == cand_skel or (
                len(cand_skel) >= 4 and len(known_skel) >= 4
                and _edit_distance(cand_skel, known_skel) == 1):
            seen.add(known)
            out.append(LookalikeWarning(candidate.strip(), known, kind))

    for name in sorted(RESERVED_USERNAMES):
        consider(name, "reserved")
    for name in known_existing:
        consider(name, "existing")
    return out


def registration_warnings(
    conn: sqlite3.Connection, candidate: object,
) -> list[LookalikeWarning]:
    """The registration-surface entry point: warnings against
    reserved names plus every live username on the instance."""
    rows = conn.execute("SELECT username FROM users").fetchall()
    existing = [r["username"] for r in rows]
    return lookalike_warnings(candidate, existing)
