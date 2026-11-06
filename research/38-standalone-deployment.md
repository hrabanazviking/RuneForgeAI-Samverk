# Samverk research 38 — Native no-Docker installation, operations and upgrades

**Research dossier • 2026-11-06 • Design recommendations / NOT PROVEN until tested.** This is a clean-room synthesis of public specifications and practices. Roadmap **S-345–S-360, S-405–S-416**.

## Technology and observed constraints

- Python `http.server` documentation warns that it is not recommended for production use because only basic security checks are included. Samverk's stdlib server is a useful foundation, not proof of internet-safe exposure.
- Production installation is an operational system: process identity, writable paths, TLS, restart policy, socket binding, backups, logs and upgrades matter as much as business code.
- Native service management differs by OS: systemd on Linux, Windows services, launchd on macOS. A portable core should isolate these seams rather than assume POSIX.

## Recommended implementation approach

- Document threat-driven deployment topology: reverse proxy/TLS termination options, loopback bind defaults, host firewall, user account isolation, request size/concurrency/timeouts and update procedure.
- Review `samverk/server.py` for request smuggling/header limits, slow clients, streaming, path routing, binary Git handling, body parsing, shutdown, worker exceptions and fault containment before public ingress.
- Create explicit data-root permissions, secret material paths, least-privilege service unit and startup health check. Never require Docker.
- Provide a reproducible upgrade: export, verify manifest, stop jobs, migrate transactional DB, restart, check smoke tests, and record rollback limitations.

## Threats, edge cases and operational limits

- Exposed plaintext non-loopback server, reverse proxy missing forwarded-host restrictions, daemon restart during push, disk full, unsafe tmp dir, interrupted migration.

## Acceptance checks

- Fresh install on Pi-class host and Linux laptop; then networked smoke tests across auth, Git HTTP/SSH, UI and admin controls.
- Pen-test server exposure separately from module security tests and log all failures safely.
- Run crash/restart, disk-quota, power-interruption and restore drills.

## How to use this study

Before implementation, map each recommendation to current `samverk/` code and tests; identify new versus pre-existing functionality. Every public claim needs a testable scope, a real entry point, and a recorded host. A green unit test does not prove the browser application or real Git transport. Record accepted, deferred and rejected designs and keep `docs/CLAIMS_REGISTER.md` and `PROJECT_MEMORY_MAP.md` consistent. Any unverified security assertion remains NOT PROVEN.

## Primary public references

1. https://docs.python.org/3/library/http.server.html
2. https://cheatsheetseries.owasp.org/cheatsheets/HTTP_Headers_Cheat_Sheet.html
3. https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html
