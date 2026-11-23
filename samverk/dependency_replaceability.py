"""S-407 — Dependency replaceability register.

Roadmap line: every dependency (the git binaries, SQLite, the
admitted cryptography dependency, any future admission) names
its equivalent or replacement path per OS; an irreplaceable
dependency is a defect under the Never-Leave-A-Bug law.

The REGISTER below is inventoried from disk, never invented:
- runtime admission: pyproject.toml + samverk/dependencies.py
  (exactly one non-stdlib import exists in the tree: cryptography)
- external programs: samverk/proc.py ALLOWED_PROGRAMS = {git, gpg},
  plus the reference runner's SHELL_CANDIDATES = (sh, bash)
- SQLite: the stdlib sqlite3 module (249 import sites), backed by
  the system/bundled libsqlite3 under CPython
- platform: CPython >= 3.11 (pyproject requires-python) and the
  build-only setuptools backend (never imported at runtime)

Every entry names a per-OS equivalent or replacement path for
linux / windows / macos. An entry with an empty path on any OS,
or replaceable=False, is a DEFECT and fails the audit. Paths are
NAMED, not exercised: no replacement has been swapped in and
proven — see docs/DEPENDENCY_REPLACEABILITY.md (NOT PROVEN).
"""
from __future__ import annotations

import ast, sys
from dataclasses import dataclass
from pathlib import Path

OSES = ("linux", "windows", "macos")

@dataclass(frozen=True)
class Dependency:
    name: str
    kind: str            # runtime | external-program | native-library | platform | build
    evidence: str        # where on disk this dependency is inventoried from
    used_for: str
    per_os: tuple        # tuple of (os, path) covering OSES exactly
    replaceable: bool = True
    risk: str = ""
    def path_for(self, os_name):
        return dict(self.per_os).get(os_name, "")

REGISTER = (
 Dependency("cryptography", "runtime",
  "pyproject.toml dependencies == ['cryptography==46.0.5']; samverk/dependencies.py ADMITTED_DEPENDENCIES (S-017/S-305); only non-stdlib import in tree (commit_signatures.py, adversarial_battery.py)",
  "Ed25519/ECDSA/RSA SSHSIG signature verification (S-305)",
  (("linux", "Equivalent: OS package python3-cryptography or another audited provider of the same hazmat APIs; Replacement path: verify via the system OpenSSL (libcrypto) through a small audited binding, keeping the S-305 battery as the acceptance gate"),
   ("windows", "Equivalent: the pinned wheel from PyPI (same distribution); Replacement path: Windows CNG/BCrypt via an audited binding for signature verification"),
   ("macos", "Equivalent: the pinned wheel from PyPI or Homebrew python-cryptography; Replacement path: system libcrypto/Security framework via an audited binding")),
  risk="Single admitted supply-chain dependency; replacement bindings are named, NOT PROVEN — no swap has been run."),
 Dependency("git", "external-program",
  "samverk/proc.py ALLOWED_PROGRAMS (S-014); spawned under the subprocess law for all repository object/ref/transport work",
  "All git object, ref, history and pack transport operations",
  (("linux", "Equivalent: any Git-for-Linux >= the probed `git version` floor from the OS package manager; Replacement path: a pure-Python git object/transport layer inside samverk/ (major reimplementation, roadmap-sized)"),
   ("windows", "Equivalent: Git for Windows (git.exe) on PATH, resolved by the same shutil.which law; Replacement path: the same pure-Python layer"),
   ("macos", "Equivalent: Xcode Command Line Tools git or Homebrew git on PATH; Replacement path: the same pure-Python layer")),
  risk="Most load-bearing dependency: no drop-in equivalent exists today; the replacement path is a major reimplementation, NAMED but NOT PROVEN. Not irreplaceable — a path exists — but highest replacement cost in the register."),
 Dependency("gpg", "external-program",
  "samverk/proc.py ALLOWED_PROGRAMS (S-305 OpenPGP verification)",
  "OpenPGP commit-signature verification",
  (("linux", "Equivalent: GnuPG from the OS package manager; Replacement path: verify OpenPGP signatures through the admitted cryptography dependency (parse + verify in-process)"),
   ("windows", "Equivalent: Gpg4win (gpg.exe) on PATH; Replacement path: the same in-process cryptography route"),
   ("macos", "Equivalent: GnuPG via Homebrew / GPG Suite; Replacement path: the same in-process cryptography route")),
  risk="Replacement route reuses an already-admitted dependency; NOT PROVEN — gpg is the only exercised path."),
 Dependency("sqlite3 / libsqlite3", "native-library",
  "stdlib sqlite3 imported across the package (249 import sites at inventory); CPython links the system libsqlite3 on Linux, the bundled library in python.org builds",
  "All persistent forge state (accounts, repos metadata, tokens, audit)",
  (("linux", "Equivalent: OS libsqlite3 (any CPython build linking it); Replacement path: another embedded store behind the existing data layer, or a pure-Python store for small installs — data migration required"),
   ("windows", "Equivalent: the sqlite3 DLL bundled with python.org CPython; Replacement path: the same store-swap route"),
   ("macos", "Equivalent: the libsqlite3 shipped with the system / python.org CPython; Replacement path: the same store-swap route")),
  risk="Data-format dependency: replacement means migration of live databases, not a binary swap; NAMED, NOT PROVEN."),
 Dependency("cpython", "platform",
  "pyproject.toml requires-python >=3.11; the whole package is CPython stdlib code",
  "Runtime interpreter for all of Samverk",
  (("linux", "Equivalent: any CPython >=3.11 from the OS / python.org / deadsnakes; Replacement path: another Python implementation only after a full battery pass (none claimed today)"),
   ("windows", "Equivalent: python.org CPython >=3.11 (python.exe); Replacement path: as linux"),
   ("macos", "Equivalent: python.org or Homebrew CPython >=3.11; Replacement path: as linux")),
  risk="No non-CPython runtime is proven; equivalence is CPython-to-CPython only."),
 Dependency("setuptools", "build",
  "pyproject.toml [build-system] requires setuptools>=68; docs/DEPENDENCY_REGISTER.md notes it is build-time only, never imported",
  "Building/installing the package only",
  (("linux", "Equivalent: OS python3-setuptools >=68; Replacement path: switch [build-system] to another PEP 517 backend (e.g. flit-core/hatchling) — a pyproject-only change"),
   ("windows", "Equivalent: setuptools from PyPI in the build env; Replacement path: the same backend switch"),
   ("macos", "Equivalent: setuptools from PyPI in the build env; Replacement path: the same backend switch")),
  risk="Build-time only; a backend switch is small but NOT PROVEN until an install walk passes on it."),
 Dependency("posix-shell (reference runner only)", "external-program",
  "samverk/reference_runner.py SHELL_CANDIDATES = ('sh', 'bash') (S-316 tooling, not forge-core runtime)",
  "Reference-runner shell steps in parity/test tooling only",
  (("linux", "Equivalent: /bin/sh or bash from the OS (native)"),
   ("windows", "Equivalent: Git Bash or WSL sh/bash on PATH; Replacement path: run the reference runner under WSL, or drop shell steps from parity jobs"),
   ("macos", "Equivalent: /bin/sh or bash shipped with macOS (native)")),
  risk="Tooling only — forge-core never spawns a shell (S-014 law). Windows equivalence via Git Bash/WSL is NAMED, NOT PROVEN."),
)

def non_stdlib_imports(root: Path) -> set:
    """AST-scan samverk/*.py for top-level non-stdlib imports."""
    std = set(sys.stdlib_module_names)
    found = set()
    for p in sorted((Path(root) / "samverk").glob("*.py")):
        tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module.split(".")[0]]
            for m in names:
                if m not in std and m != "samverk":
                    found.add(m)
    return found

def audit_tree(root: Path) -> dict:
    """Cross-check the register against the tree on disk.

    Defects: a register entry missing a per-OS path or marked
    irreplaceable; a non-stdlib import with no register entry;
    an ALLOWED_PROGRAMS member with no register entry; a
    pyproject runtime dependency with no register entry.
    """
    root = Path(root)
    defects = []
    for d in REGISTER:
        for os_name in OSES:
            if not d.path_for(os_name).strip():
                defects.append(f"{d.name}: no replacement path for {os_name}")
        if not d.replaceable:
            defects.append(f"{d.name}: IRREPLACEABLE — defect under the Never-Leave-A-Bug law")
    names = {d.name for d in REGISTER}
    imports = non_stdlib_imports(root)
    for m in sorted(imports):
        if m not in names:
            defects.append(f"unregistered non-stdlib import: {m}")
    sys.path.insert(0, str(root))
    from samverk.proc import ALLOWED_PROGRAMS
    for prog in sorted(ALLOWED_PROGRAMS):
        if prog not in names:
            defects.append(f"unregistered external program: {prog}")
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    import tomllib
    declared = set()
    for req in tomllib.loads(pyproject)["project"]["dependencies"]:
        declared.add(req.split("=")[0].split("<")[0].split(">")[0].strip())
    for dep in sorted(declared):
        if dep not in names:
            defects.append(f"unregistered pyproject dependency: {dep}")
    uses_sqlite = any("import sqlite3" in p.read_text(errors="replace")
                      for p in (root / "samverk").glob("*.py"))
    return {"dependencies": len(REGISTER), "non_stdlib_imports": sorted(imports),
            "allowed_programs": sorted(ALLOWED_PROGRAMS),
            "pyproject_dependencies": sorted(declared),
            "sqlite_in_use": uses_sqlite, "defects": defects,
            "clean": not defects}
