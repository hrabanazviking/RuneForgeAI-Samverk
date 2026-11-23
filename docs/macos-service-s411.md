# S-411 -- macOS service (slice record)

- Slice: S-411, parent 080cf8e (401/416 banked). HELD ahead-work:
  banking is blocked in roadmap order on founder-only S-402;
  this commit is built + committed in team-10 only, unpushed.
- Delivered: `samverk/macos_service.py` (the one daemon as
  data -- label `org.samverk.server`, service user `_samverk`,
  system domain, KeepAlive-on-failure + 60 s throttle -- with
  validated `build_service_spec`, the plist renderers, the
  launchctl install / load / unload / status / restart /
  uninstall renderers, worker one-shot commands from S-345's
  topology, the generated sh install/uninstall scripts, and
  the 8-step `INSTALL_WALK_STEPS`),
  `deploy/launchd/` (the three shipped plists -- server +
  webhook-delivery + weekly-digest, byte-identical to the
  module's rendering for the standing spec -- plus
  install.sh / uninstall.sh / verify.sh and
  samverk.ini.example), `tests/test_macos_service.py`,
  `tools/run_macos_service.py`, `docs/MACOS_SERVICE.md`.
- No service host, deliberately: launchd supervises an
  ordinary process directly, so the daemon's
  ProgramArguments are S-345's server entry itself; the
  SCM-protocol host S-410 needed has no launchd analogue.
- Native road only: launchctl + plistlib (stdlib) -- no
  Docker, no third-party wrapper, no new dependency.
  Specs routing through Docker paths are refused
  (`container_path`), as are relative/Windows paths.
- Honest remainder: a real macOS host install/run is
  NOT PROVEN -- this slice was built and tested on Linux;
  the generated artifacts are proven as data, the launchd
  conversation and daemon run are not claimed. Mirror-sync
  renders no worker command and ships no plist (no
  standalone CLI exists); artifact-expiry renders a
  command but ships no plist (S-348's shipped set kept).
- No migration and no new taxonomy event: schema 140 /
  taxonomy 142 pinned in the battery.
