"""Dependency policy — the admitted-dependency register (S-017).

Samverk is **stdlib-first**: the Python standard library is the
default and, so far, the only supplier. A third-party dependency
is admitted only when it earns its place, and admission means an
entry in `ADMITTED_DEPENDENCIES` below *and* in
`docs/DEPENDENCY_REGISTER.md`, carrying:

- the distribution name (as it appears in `pyproject.toml`),
- an exact pinned version (``==`` — ranges are not pins),
- the import name code actually uses, and
- a **reason line**: what the standard library cannot do, or
  cannot do safely, that justifies the supply-chain weight.

The battery (`tests/test_dependencies.py`) is the CI-style check
the roadmap asks for: it parses `pyproject.toml` and requires the
declared runtime dependencies to be exactly this register, and
it AST-scans every module in the package (and the test suite)
requiring every import to be stdlib, intra-package, or admitted
here. An unregistered import fails the build — a dependency
cannot drift in through a stray `import` or a quiet pyproject
edit; both doors are watched.

Today the register holds exactly one admission, `cryptography`,
registered at S-305 (the roadmap's founding stance names it the
admitted dependency, as in Samtal; S-305's SSH-signature
verification is the first code that truly needs it). The battery
proves the register, the project file and this doc agree on
every run.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AdmittedDependency:
    distribution: str   # name in pyproject.toml, e.g. "argon2-cffi"
    pin: str            # exact pin, e.g. "==23.1.0"
    import_name: str    # top-level module code imports
    reason: str         # why the stdlib does not suffice


# Admit by appending here AND to docs/DEPENDENCY_REGISTER.md,
# with the pin mirrored in pyproject.toml — the battery checks
# all three agree.
ADMITTED_DEPENDENCIES: tuple[AdmittedDependency, ...] = (
    AdmittedDependency(
        distribution="cryptography",
        pin="==46.0.5",
        import_name="cryptography",
        reason=(
            "The standard library cannot verify Ed25519, ECDSA "
            "or RSA SSHSIG signatures (S-305 signed-commit "
            "verification); hand-rolling public-key signature "
            "checks is exactly the unsafe kind of stdlib-only. "
            "The roadmap founding stance names cryptography "
            "as the admitted dependency, as in Samtal.")),
)
