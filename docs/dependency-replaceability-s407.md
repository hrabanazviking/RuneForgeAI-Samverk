# S-407 — Dependency replaceability register (slice note)

Built ahead behind S-402 (founder-only), on parent 080cf8e, held
unmerged like S-403..S-406. The register itself is
`samverk/dependency_replaceability.py`; the published table is
`docs/DEPENDENCY_REPLACEABILITY.md`; the runner is
`tools/run_dependency_replaceability.py`.

Verdict at build: 7 dependencies inventoried from disk, every one
names an equivalent or replacement path for linux, windows and
macos, and the audit cross-checks the register against the tree
(non-stdlib imports, proc.py ALLOWED_PROGRAMS, pyproject
dependencies, sqlite3 use) with zero defects — no dependency is
irreplaceable, so no Never-Leave-A-Bug defect is filed.

Highest replacement cost: the git binary. No drop-in equivalent
exists today; its replacement path is a pure-Python git
object/transport layer — roadmap-sized work, named not built.

NOT PROVEN: no replacement path has been exercised — no crypto
swap, no store migration, no non-CPython run, no Git-Bash/WSL
reference-runner run, no setuptools backend switch. Windows and
macOS paths are named from the distributions' documented forms,
not run on those OSes in this slice.
