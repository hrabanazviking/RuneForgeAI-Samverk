# Samverk research 45 — Linux, Windows, macOS and ARM portability by construction

**Research dossier, 2026-11-06.** Clean-room synthesis from public protocols, standards and testable observations; guidance, **not a declaration of implementation**. Roadmap: **S-002, S-405–S-416**.

## Core facts and constraints

- A Python standard-library source tree can still be platform-dependent through POSIX permissions, process signals, hard-coded separators, `fcntl`, service managers and file locking.
- Git installations and SSH daemons have different paths and behaviors on Linux, macOS and Windows; a passing Linux test is not proof on another OS.
- Filesystems differ in case sensitivity, Unicode normalization, file-name restrictions and atomic rename semantics; Git tree paths are not identical to host paths.

## Samverk engineering direction

- Audit every OS touchpoint and route it through `samverk/platform_seam.py` or an explicit submodule contract. Build a matrix for path, lock, subprocess, signals, perms, service and arch.
- Do not use shell commands that depend on bash/POSIX utilities inside portable core; call portable APIs or detect/version the installed Git executable.
- State support separately for Linux x86-64, Linux ARM64 (Pi 5), Windows x86-64 and macOS ARM64; file systems and real SSH/HTTP deployment get their own cells.
- Use reproducible native test runners for each OS, with temporary data roots and safe file permissions. Treat service packaging as platform-specific adapters, never container-only workaround.

## Threats and tricky cases

- Two repositories `Foo`/`foo` on case-insensitive disk, alternate path separator in URL, Windows reserved device name, symlink restrictions, ACL vs mode-600 semantics.
- Python `http.server` production caveats apply on every OS; infrastructure security needs platform-by-platform proof.

## Acceptance and experiment plan

- Run complete Git core/transport/UI/security suite on each matrix host and publish exact Python, Git and OS versions.
- Cross-device export/import with UTF-8, raw bytes and case-collision test fixtures; fail safely when irreconcilable.
- Verify native startup, service restart and data-root permissions on systemd, Windows service and launchd.

## Review checklist

Record current source modules, whether features are routable from the real server, exact authorization points, schema/recovery implications, and a passing test transcript on named hardware. If a claim is not tested, label it **NOT PROVEN**. For every accepted change, update relevant roadmap gate, claims register and project memory map with new evidence; preserve historical keeper entries. Do not copy closed-source code or proprietary UI assets.

## Primary sources

1. https://docs.python.org/3/library/os.html
2. https://docs.python.org/3/library/subprocess.html
3. https://git-scm.com/docs/git
4. https://docs.python.org/3/library/http.server.html
