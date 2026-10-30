# Samverk — Dependency Register (S-017)

**Policy: stdlib-first.** Samverk runs on the Python standard
library. Every third-party dependency is supply-chain weight — a
thing that must be fetched, trusted, updated, and answered for —
so one is admitted only when the standard library cannot do the
job, or cannot do it safely, and the admission is written down
here and in `samverk/dependencies.py` with an exact pinned
version and a reason line.

**Runtime dependencies admitted: none.** The battery
(`tests/test_dependencies.py`) proves this on every run: it
requires `pyproject.toml`'s declared dependencies to match the
register exactly, and AST-scans the package and the test suite
so no unregistered import can drift in.

## Admitted runtime dependencies

| Distribution | Pin | Import name | Reason |
|---|---|---|---|
| *(none)* | — | — | — |

## How a dependency is admitted

1. Name what the standard library cannot do (or cannot do
   safely) — that sentence becomes the reason line.
2. Add a row here, an `AdmittedDependency` in
   `samverk/dependencies.py`, and the pinned requirement in
   `pyproject.toml`, all in the same commit.
3. The battery must stay green; it checks all three agree.

## Notes

- Build backend (`setuptools`) is a build-time tool only, never
  imported by Samverk code, and is not a runtime dependency.
- The test suite runs on the stdlib `unittest` — no test-only
  dependencies are admitted either.
