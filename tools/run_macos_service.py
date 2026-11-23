#!/usr/bin/env python3
"""S-411 -- macOS launchd service runner (pure stdlib).
Usage: python3 tools/run_macos_service.py [python_exe] [data_root]
Prints the service spec, the server plist, the rendered launchctl
install / load / status / uninstall sequences, the worker command
lines, and the install walk's steps with their failure modes;
exits 0 only when the standing spec validates clean. Everything
printed is generated data proven as data -- no Mac ran anything:
a real macOS install is NOT PROVEN (see docs/MACOS_SERVICE.md).
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from samverk.macos_service import (INSTALL_WALK_STEPS,
    build_service_spec, install_commands, load_commands,
    render_command_line, render_plist, server_plist,
    status_commands, uninstall_commands, validate_spec,
    worker_commands)

def main():
    python_exe = sys.argv[1] if len(sys.argv) > 1 else "/usr/bin/python3"
    data_root = sys.argv[2] if len(sys.argv) > 2 else "/Library/Application Support/Samverk"
    spec = build_service_spec(python_exe, data_root)
    problems = validate_spec(spec)
    print(f"daemon: {spec.label} (user {spec.user_name}, domain {spec.domain})")
    print(f"program: {' '.join(spec.program_arguments)}")
    print(f"data root: {spec.data_root}  db: {spec.db_path}")
    print("server plist:")
    print(render_plist(server_plist(spec)))
    print("install sequence (loads nothing):")
    for argv in install_commands(spec, ROOT + "/deploy/launchd"):
        print("  " + render_command_line(argv))
    print("load sequence:")
    for argv in load_commands(spec):
        print("  " + render_command_line(argv))
    print("status sequence:")
    for argv in status_commands(spec):
        print("  " + render_command_line(argv))
    print("uninstall sequence (data root kept):")
    for argv in uninstall_commands(spec):
        print("  " + render_command_line(argv))
    print("workers:")
    for name, argv, words in worker_commands(spec):
        print(f"  {name}: " + (render_command_line(argv) if argv else f"NONE -- {words}"))
    print("install walk:")
    for i, s in enumerate(INSTALL_WALK_STEPS, 1):
        print(f"  {i}. {s['name']} -- {s['title']} [failure: {s['failure']}]")
    print("VERDICT:", "SPEC CLEAN -- definition, plists, commands "
          "and walk render consistently; macOS host run NOT PROVEN"
          if not problems else f"PROBLEMS: {problems}")
    return 0 if not problems else 1

if __name__ == "__main__":
    sys.exit(main())
