# Samverk — Dependency Replaceability Register (S-407)

Every dependency Samverk actually has — inventoried from disk
(pyproject.toml, `samverk/dependencies.py`, `samverk/proc.py`
ALLOWED_PROGRAMS, an AST scan of all imports, sqlite3 use) —
names its equivalent or replacement path per OS. An entry with
no path, or one marked irreplaceable, is a defect under the
Never-Leave-A-Bug law and fails the battery
(`tests/test_dependency_replaceability.py`).

**Verdict: 7 dependencies, 0 irreplaceable, 0 defects.**
Replacement paths are NAMED, not exercised — see NOT PROVEN.

## cryptography (runtime)

- Evidence: pyproject.toml dependencies == ['cryptography==46.0.5']; samverk/dependencies.py ADMITTED_DEPENDENCIES (S-017/S-305); only non-stdlib import in tree (commit_signatures.py, adversarial_battery.py)
- Used for: Ed25519/ECDSA/RSA SSHSIG signature verification (S-305)
- **linux:** Equivalent: OS package python3-cryptography or another audited provider of the same hazmat APIs; Replacement path: verify via the system OpenSSL (libcrypto) through a small audited binding, keeping the S-305 battery as the acceptance gate
- **windows:** Equivalent: the pinned wheel from PyPI (same distribution); Replacement path: Windows CNG/BCrypt via an audited binding for signature verification
- **macos:** Equivalent: the pinned wheel from PyPI or Homebrew python-cryptography; Replacement path: system libcrypto/Security framework via an audited binding
- Risk: Single admitted supply-chain dependency; replacement bindings are named, NOT PROVEN — no swap has been run.

## git (external-program)

- Evidence: samverk/proc.py ALLOWED_PROGRAMS (S-014); spawned under the subprocess law for all repository object/ref/transport work
- Used for: All git object, ref, history and pack transport operations
- **linux:** Equivalent: any Git-for-Linux >= the probed `git version` floor from the OS package manager; Replacement path: a pure-Python git object/transport layer inside samverk/ (major reimplementation, roadmap-sized)
- **windows:** Equivalent: Git for Windows (git.exe) on PATH, resolved by the same shutil.which law; Replacement path: the same pure-Python layer
- **macos:** Equivalent: Xcode Command Line Tools git or Homebrew git on PATH; Replacement path: the same pure-Python layer
- Risk: Most load-bearing dependency: no drop-in equivalent exists today; the replacement path is a major reimplementation, NAMED but NOT PROVEN. Not irreplaceable — a path exists — but highest replacement cost in the register.

## gpg (external-program)

- Evidence: samverk/proc.py ALLOWED_PROGRAMS (S-305 OpenPGP verification)
- Used for: OpenPGP commit-signature verification
- **linux:** Equivalent: GnuPG from the OS package manager; Replacement path: verify OpenPGP signatures through the admitted cryptography dependency (parse + verify in-process)
- **windows:** Equivalent: Gpg4win (gpg.exe) on PATH; Replacement path: the same in-process cryptography route
- **macos:** Equivalent: GnuPG via Homebrew / GPG Suite; Replacement path: the same in-process cryptography route
- Risk: Replacement route reuses an already-admitted dependency; NOT PROVEN — gpg is the only exercised path.

## sqlite3 / libsqlite3 (native-library)

- Evidence: stdlib sqlite3 imported across the package (249 import sites at inventory); CPython links the system libsqlite3 on Linux, the bundled library in python.org builds
- Used for: All persistent forge state (accounts, repos metadata, tokens, audit)
- **linux:** Equivalent: OS libsqlite3 (any CPython build linking it); Replacement path: another embedded store behind the existing data layer, or a pure-Python store for small installs — data migration required
- **windows:** Equivalent: the sqlite3 DLL bundled with python.org CPython; Replacement path: the same store-swap route
- **macos:** Equivalent: the libsqlite3 shipped with the system / python.org CPython; Replacement path: the same store-swap route
- Risk: Data-format dependency: replacement means migration of live databases, not a binary swap; NAMED, NOT PROVEN.

## cpython (platform)

- Evidence: pyproject.toml requires-python >=3.11; the whole package is CPython stdlib code
- Used for: Runtime interpreter for all of Samverk
- **linux:** Equivalent: any CPython >=3.11 from the OS / python.org / deadsnakes; Replacement path: another Python implementation only after a full battery pass (none claimed today)
- **windows:** Equivalent: python.org CPython >=3.11 (python.exe); Replacement path: as linux
- **macos:** Equivalent: python.org or Homebrew CPython >=3.11; Replacement path: as linux
- Risk: No non-CPython runtime is proven; equivalence is CPython-to-CPython only.

## setuptools (build)

- Evidence: pyproject.toml [build-system] requires setuptools>=68; docs/DEPENDENCY_REGISTER.md notes it is build-time only, never imported
- Used for: Building/installing the package only
- **linux:** Equivalent: OS python3-setuptools >=68; Replacement path: switch [build-system] to another PEP 517 backend (e.g. flit-core/hatchling) — a pyproject-only change
- **windows:** Equivalent: setuptools from PyPI in the build env; Replacement path: the same backend switch
- **macos:** Equivalent: setuptools from PyPI in the build env; Replacement path: the same backend switch
- Risk: Build-time only; a backend switch is small but NOT PROVEN until an install walk passes on it.

## posix-shell (reference runner only) (external-program)

- Evidence: samverk/reference_runner.py SHELL_CANDIDATES = ('sh', 'bash') (S-316 tooling, not forge-core runtime)
- Used for: Reference-runner shell steps in parity/test tooling only
- **linux:** Equivalent: /bin/sh or bash from the OS (native)
- **windows:** Equivalent: Git Bash or WSL sh/bash on PATH; Replacement path: run the reference runner under WSL, or drop shell steps from parity jobs
- **macos:** Equivalent: /bin/sh or bash shipped with macOS (native)
- Risk: Tooling only — forge-core never spawns a shell (S-014 law). Windows equivalence via Git Bash/WSL is NAMED, NOT PROVEN.

## NOT PROVEN

- No replacement path has been swapped in and run: no crypto
  provider swap, no SQLite store migration, no non-CPython
  runtime pass, no Git-for-Windows / Xcode-git run of the full
  battery, no Git Bash/WSL reference-runner run, and no
  setuptools backend switch.
- The git replacement path (pure-Python object/transport layer)
  is roadmap-sized future work, not an existing equivalent.
