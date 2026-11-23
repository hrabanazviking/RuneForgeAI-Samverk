# Platform seam — the one platform module (S-406)

Every OS touchpoint in Samverk is inventoried here and routed
through `samverk/platform_seam.py` — or carried below as a named
remainder with its reason. The audit tool
(`tools/run_platform_seam_audit.py`, logic in
`samverk/platform_seam_audit.py`) greps the tree's *code* (comments
and string literals stripped) and fails on any touchpoint that is
neither in the seam nor on the named inventory.

## The seam (samverk/platform_seam.py)

| Touchpoint | Seam entry |
|---|---|
| OS identity | `os_name()` — the only `sys.platform` read in the tree |
| CPU identity | `machine()` — the only `platform.machine()` |
| Platform description | `platform_string()` — the only `platform.platform()` |
| Paths | `data_root_default()` — per-OS data-root conventions |
| Directory creation | `ensure_dir()` |
| Permission bits (read) | `secret_file_is_private()` |
| Permission bits (write) | `restrict_to_owner()` (0o600), `make_owner_executable()` (S_IRWXU) — S-406 |

## Routed at S-406

- `platform.machine()` / `platform.platform()` call sites in
  repo_budgets, search_budgets, perf_verification,
  docs_completeness, research_corpus_audit, upgrade_drill
  → seam `machine()` / `platform_string()`.
- `.chmod(0o600)` in lfs_store, ci_artifacts, organizations,
  profiles, release_assets, uploads → seam `restrict_to_owner()`.
- `script.chmod(stat.S_IRWXU)` in proc → seam `make_owner_executable()`.

## Named remainders (inventoried, NOT routed)

Process spawning does not live in the seam: the seam's own founding
docstring names `samverk/proc.py` (S-014) as the LANDED home for
process creation, because the allowlist policy lives there.

| File | Category | Reason |
|---|---|---|
| samverk/proc.py | process | S-014 process policy home (allowlists) |
| samverk/reference_runner.py | process | External reference runner under S-014 law; parity tooling |
| samverk/seam_battery.py | process | Battery harness git calls; test tooling |
| samverk/upgrade_drill.py | process | Upgrade-drill git calls; operator tooling |
| samverk/windows_service.py | process | subprocess.list2cmdline only: pure quoting for sc.exe registration strings; creates no process |
| samverk/windows_service_host.py | process | SCM service host spawns its own Samverk child (subprocess.Popen); platform-host code |

## Categories with zero touchpoints outside the seam

- Signals: no `signal.` / `os.kill` code anywhere in samverk/.
- File locking: no `fcntl` / `msvcrt` / flock code anywhere; the
  seam's FUTURE `lock_file()` remains unlanded — NOT PROVEN that
  no locking is needed, only that none exists.
- Service management: no systemctl/launchd/sc.exe code in
  samverk/; service integration is install/docs surface
  (S-348 systemd; S-410/S-411/S-412 own the service cells).

## Audit verdict at S-406

367 files scanned outside the seam; process 49 (all inventoried
above), permissions 0, platform_id 0, signals 0, locking 0;
uninventoried strays: 0. The acceptance line reads honestly:
no stray platform calls outside the seam *and its named
inventory* — the four process remainders are named, not hidden.
