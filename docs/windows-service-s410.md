# S-410 -- Windows service (slice record)

- Slice: S-410, parent 080cf8e (401/416 banked). HELD ahead-work:
  banking is blocked in roadmap order on founder-only S-402;
  this commit is built + committed in team-09 only, unpushed.
- Delivered: `samverk/windows_service.py` (the one service as
  data -- name `Samverk`, virtual account `NT SERVICE\Samverk`,
  auto start, restart/60s x3 recovery -- with validated
  `build_service_spec`, the sc.exe install / start / stop /
  status / uninstall renderers, worker one-shot commands from
  S-345's topology, the generated PowerShell install/uninstall
  scripts, and the 8-step `INSTALL_WALK_STEPS`),
  `samverk/windows_service_host.py` (stdlib `ctypes` SCM host:
  dispatcher + handler + status, supervises the real server as
  its child; refuses off Windows with `windows_only`),
  `tests/test_windows_service.py`,
  `tools/run_windows_service.py`, `docs/WINDOWS_SERVICE.md`.
- Native road only: sc.exe (Windows inbox) + stdlib host -- no
  Docker, no WSL, no third-party wrapper, no new dependency.
  Specs routing through Docker/WSL paths are refused
  (`container_or_wsl_path`), as are relative/POSIX paths.
- Honest remainder: a real Windows host install/run is
  NOT PROVEN -- this slice was built and tested on Linux;
  the generated artifacts are proven as data, the SCM
  conversation and service run are not claimed. Mirror-sync
  renders no worker command (no standalone CLI exists).
- No migration and no new taxonomy event: schema 140 /
  taxonomy 142 pinned in the battery.
