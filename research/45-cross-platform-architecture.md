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

<!-- S-405 support matrix: begin -->

## Support matrix (ratified at S-405)

The promise, written down at S-405: the Samverk
server is supported on Linux, Windows and macOS,
on x86-64 and ARM64 CPUs, with the Raspberry Pi 5
as the floor. The law module is
`samverk/support_matrix.py`; the rendered matrix
document is `docs/SUPPORT_MATRIX.md`; the counted
log is `docs/support-matrix-s405.md`.

A cell is PROVEN only when its battery has run in
that cell (Part XXII's law). At ratification every
cell below is **NOT PROVEN** -- no platform is
claimed proven without a real run on that
platform, and no cell flips on wording.

| Cell | Dimension | Platform | CPU / surface | Floor | Status | Flips at |
|---|---|---|---|---|---|---|
| linux-x86-64 | os_cpu | Linux | x86-64 | ordinary laptop, desktop or server | NOT PROVEN | S-416 |
| linux-arm64-pi5 | os_cpu | Linux | ARM64 | Raspberry Pi 5 (the floor: nothing weaker is promised) | NOT PROVEN | S-415 |
| windows-x86-64 | os_cpu | Windows | x86-64 | ordinary laptop, desktop or server | NOT PROVEN | S-416 |
| macos-arm64 | os_cpu | macOS | ARM64 | Apple silicon Mac | NOT PROVEN | S-416 |
| fs-case-sensitive | filesystem | filesystem | n/a | the filesystems Linux servers ship by default | NOT PROVEN | S-408 |
| fs-case-insensitive | filesystem | filesystem | n/a | the default filesystems of Windows and macOS | NOT PROVEN | S-408 |
| deploy-real-sshd | deployment | deployment | n/a | a stock sshd on a promised OS | NOT PROVEN | Part XXII (S-415/S-416 cells) |
| deploy-real-http | deployment | deployment | n/a | the server answering real HTTP clients on a promised OS | NOT PROVEN | Part XXII (S-415/S-416 cells) |
| service-systemd | service | Linux | any promised CPU | a systemd Linux host | NOT PROVEN | S-412 |
| service-windows | service | Windows | x86-64 | a Windows host, no Docker and no WSL requirement | NOT PROVEN | S-410 |
| service-launchd | service | macOS | ARM64 | an Apple silicon Mac | NOT PROVEN | S-411 |
| browser-device-reach | reach | web UI | n/a | current Chrome, Firefox, Safari and Edge; phone and tablet browsers | NOT PROVEN | S-414 |

Windows on ARM64 and macOS on x86-64 are not
promised and have no cells. S-415 flips the
Linux ARM64 cell, S-416 is the portability gate
for the Windows and macOS cells, S-408 owns the
filesystem cells, S-410..S-412 the service forms,
and S-414 the browser and device reach cell.

<!-- S-405 support matrix: end -->
