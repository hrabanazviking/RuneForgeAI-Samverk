# Native setup, upgrades and per-platform proof

**Samverk implementation research, 2026-11-06.** This document provides proposed technical policy and acceptance work, not evidence that a feature has shipped. Existing roadmap references: S-345–S-360; S-405–S-416. Maintain the clean-room rule and no-Docker decision.

## Established context

- Native installation is a complete operation: runtime, service identity, data root, permissions, TLS, config, database, keys, backups, service restart and recovery.
- Linux x86-64 success does not establish Windows, macOS or Raspberry Pi ARM64 compatibility.
- Python HTTP server documentation warns its http.server module is not recommended for production use. Any public deployment needs a recorded ingress-security decision.

## Concrete engineering plan

- Document a blank-host check for Python 3.11+, Git, optional git-lfs, optional real OpenSSH server and filesystem characteristics; fail clearly when unsupported.
- Create a least-privileged service user and data root containing Git repositories, SQLite DB, assets, LFS, keys and logs; use native systemd/Windows service/launchd adapters.
- Initialize schema and keys, create first admin through a safe CLI, bind loopback by default, configure TLS/reverse proxy policy and start server with health checks.
- Walk the user through sign-in, token, repo creation, clone, push, issue and PR, then create first verified backup before claiming installation complete.
- Upgrade with verified export, quiesced writes, migration, restart, smoke test and documented rollback. One-way schema changes may require full restore.

## Cases likely to break naive implementations

- Windows case-insensitive names and reserved device names; macOS launchd lifecycle and normalization; Linux ACLs and process ownership; Raspberry Pi RAM constraints.
- Misconfigured reverse-proxy headers, public plaintext bind, interrupted migration and stale lock files are deployment failures, not feature tasks.
- Do not bypass a failed installation by recommending Docker or assuming WSL.

## Counted acceptance evidence required

- Have a new tester install on a clean Linux x86-64 host and Pi-class ARM64 host with a timed written guide.
- Test power interruption, failed migration and scratch restore with clone and login afterward.
- Mark OS/CPU matrix cells PROVEN only after actual suite and native service run.

## Handoff rule

For every accepted implementation, identify the module and actual server entry point, submit an unauthorized-action test, document schema or migration effects, and verify both success and refusal behavior through the live process where relevant. Record the full test count, the host, and every skip. Update PROJECT_MEMORY_MAP and CLAIMS_REGISTER only with real evidence; do not silently upgrade an untested capability to PROVEN.

## Primary references

1. https://docs.python.org/3/library/http.server.html
2. https://sqlite.org/backup.html
3. https://docs.python.org/3/library/subprocess.html
