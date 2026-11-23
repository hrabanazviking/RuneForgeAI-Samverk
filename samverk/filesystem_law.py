"""S-408 — Filesystem law.

Roadmap line: repository storage and metadata correct on
case-sensitive *and* case-insensitive filesystems; the
two-names-differing-only-by-case collision is handled
deterministically and tested on both kinds.

THE LAW
1. Case-fold identity. Two storage names that differ only by
   case (Unicode casefold) are THE SAME name for storage
   purposes. On a case-insensitive filesystem they are literally
   one file; on a case-sensitive filesystem they are two files
   that would silently merge the moment the tree is copied,
   checked out, or mirrored onto an insensitive filesystem
   (default APFS, NTFS, exFAT). Samverk therefore treats the
   collision as a defect on BOTH kinds, never as a
   platform-specific quirk.
2. Deterministic refusal, never silent overwrite. A name set
   containing a case collision is REFUSED as a whole, with a
   stable machine-readable reason and the colliding names in
   sorted (codepoint) order. No name wins by arrival order,
   directory order, or filesystem behaviour — the outcome is
   identical on every OS and every run. (Follows the S-013
   repo_paths convention: unlawful storage shapes raise a
   ValueError subclass carrying a stable `reason` code.)
3. Probe, don't guess. Whether a directory's filesystem is
   case-sensitive is PROBED by creating two probe files that
   differ only by case and counting what the filesystem kept —
   never inferred from the OS name (a case-sensitive APFS volume
   or a case-insensitive ext4 ciopfs mount both exist).
4. Simulated insensitive kind. Tests exercise the insensitive
   semantics through SimulatedInsensitiveDirectory, an honest
   in-memory model keyed by casefold. It SIMULATES; it does not
   claim a run on a real insensitive filesystem. Host probe
   results are reported as measured, in those words.
"""
from __future__ import annotations
import os, tempfile
from pathlib import Path
__all__=["FilesystemLawError","fold_key","find_case_collisions","check_names","probe_case_sensitive","audit_directory","SimulatedInsensitiveDirectory","plan_storage"]

class FilesystemLawError(ValueError):
    """A name set refused by the S-408 law; `reason` is stable."""
    def __init__(self, reason, detail=""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason

def fold_key(name):
    """The storage identity of a name: its Unicode casefold."""
    return str(name).casefold()

def find_case_collisions(names):
    """Return collisions as a tuple of tuples, fully deterministic:
    groups sorted by fold key, names inside a group sorted by
    codepoint. Only groups of 2+ DISTINCT names are collisions;
    exact duplicates are reported by check_names separately."""
    groups={}
    for n in names:
        groups.setdefault(fold_key(n), set()).add(n)
    out=[]
    for key in sorted(groups):
        members=sorted(groups[key])
        if len(members)>1:
            out.append(tuple(members))
    return tuple(out)

def check_names(names):
    """Validate a storage name set. Returns the names as a sorted
    tuple when lawful; raises FilesystemLawError otherwise.
    Exact duplicates -> 'duplicate_name'; case-only differences
    -> 'case_collision'. Deterministic on every platform."""
    names=list(names)
    seen=set()
    for n in names:
        if n in seen:
            raise FilesystemLawError("duplicate_name", repr(n))
        seen.add(n)
    collisions=find_case_collisions(names)
    if collisions:
        detail="; ".join(" vs ".join(repr(m) for m in g) for g in collisions)
        raise FilesystemLawError("case_collision", detail)
    return tuple(sorted(names))

def plan_storage(names):
    """Deterministic storage plan: {name: fold_key} for a lawful
    set, refusing a colliding set as a whole (check_names). The
    plan is identical on case-sensitive and case-insensitive
    filesystems, so a tree planned here can be materialised on
    either kind without merging or overwriting."""
    lawful=check_names(names)
    return {n: fold_key(n) for n in lawful}

_PROBE_A="SamverkProbe408A"; _PROBE_B="samverkprobe408a"
def probe_case_sensitive(directory):
    """Probe *directory*'s filesystem: create two files differing
    only by case; True iff both survive as distinct entries.
    Probe files are always removed. Never guesses from OS."""
    d=Path(directory)
    a=d/_PROBE_A; b=d/_PROBE_B
    for p in (a,b):
        if p.exists(): p.unlink()
    try:
        a.write_text("A", encoding="utf-8")
        b.write_text("B", encoding="utf-8")
        entries={e.name for e in d.iterdir()}
        return _PROBE_A in entries and _PROBE_B in entries
    finally:
        for p in (a,b):
            try: p.unlink()
            except FileNotFoundError: pass

def audit_directory(directory):
    """Audit an existing directory: probe its kind and find any
    case collisions already on disk. Returns a dict with
    case_sensitive (bool, as probed), names (sorted), collisions
    (from find_case_collisions), clean (no collisions)."""
    d=Path(directory)
    names=sorted(e.name for e in d.iterdir())
    collisions=find_case_collisions(names)
    return {"case_sensitive": probe_case_sensitive(d), "names": names,
            "collisions": [list(g) for g in collisions],
            "clean": not collisions}

class SimulatedInsensitiveDirectory:
    """Honest in-memory SIMULATION of a case-insensitive directory:
    names are keyed by fold_key, so storing 'ReadMe' then 'readme'
    targets the same slot. Used to test the insensitive kind on a
    sensitive host. NOT a real filesystem run."""
    def __init__(self): self._slots={}
    def store(self, name, data):
        key=fold_key(name)
        overwritten=key in self._slots
        self._slots[key]=(name, data)
        return overwritten
    def names(self): return sorted(n for n,_ in self._slots.values())
    def __len__(self): return len(self._slots)
