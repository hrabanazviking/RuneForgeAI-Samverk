# S-412 -- Linux services parity (slice record)

- Slice: S-412, parent 080cf8e (401/416 banked). HELD ahead-work:
  banking is blocked in roadmap order on founder-only S-402;
  this commit is built + committed in team-01 only, unpushed.
- Delivered: `samverk/linux_service.py` (the systemd citizen
  as data -- unit `samverk-server.service`, system user
  `samverk`, Restart=on-failure/5s -- with validated
  `build_service_spec`, the unit renderers proven
  directive-identical to the shipped S-348 files, the
  systemctl install / enable / disable / status / restart /
  verify / uninstall renderers, worker one-shot commands
  from S-345's topology, the generated sh install/uninstall
  scripts, the 19-capability `PARITY_MATRIX` over the three
  citizens, and the 8-step `INSTALL_WALK_STEPS`),
  `deploy/systemd/uninstall.sh` (new), `tests/test_linux_service.py`,
  `tools/run_linux_service.py`, `docs/LINUX_SERVICE.md`.
- Parity verdict: the three citizens' capability sets are
  equal (19/19 each, battery-proven against the matrix);
  every Linux mechanism was verified against the shipped
  units themselves. Declared mechanism differences, not
  features: restart delay 5 s vs 60 s, journal vs routed
  output vs data-root log files, config in /etc/samverk vs
  in the data root, systemd hardening vs account-scope
  grants. No Linux-only ExecStart exists beyond the
  topology's entries (battery-proven).
- Defect found and fixed: Linux had no uninstall road
  while Windows and macOS both shipped one --
  `deploy/systemd/uninstall.sh` now ships: disable, remove
  units, reload, keep data root and config.
- Native road only: systemd units + POSIX sh + stdlib --
  no Docker, no third-party wrapper, no new dependency.
  Specs routing through Docker paths are refused
  (`container_path`), as are relative/Windows paths.
- Honest remainder: a real install/enable/boot/restart/
  health run on a dedicated host is NOT PROVEN -- not
  executed in this slice (shared keeper host; no permanent
  service without Volmarr's word for that specific
  service); `systemd-analyze verify` over the shipped
  units IS proven (S-348 neighbour battery). The Debian/Pi
  leg remains NOT PROVEN, as S-348 recorded. Mirror-sync
  renders no worker command and ships no unit (no
  standalone CLI exists); artifact-expiry renders a
  command but ships no unit (S-348's shipped set kept).
- No migration and no new taxonomy event: schema 140 /
  taxonomy 142 pinned in the battery.
