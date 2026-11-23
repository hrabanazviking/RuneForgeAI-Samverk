#!/usr/bin/env python3
"""S-410 -- Windows service runner (pure stdlib).
Usage: python3 tools/run_windows_service.py [python_exe] [data_root]
Prints the service spec, the rendered sc.exe install / uninstall /
status sequences, the worker command lines, and the install walk's
steps with their failure modes; exits 0 only when the standing spec
validates clean. Everything printed is generated data proven as
data -- no Windows host ran anything: a real Windows install is
NOT PROVEN (see docs/WINDOWS_SERVICE.md).
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from samverk.windows_service import (INSTALL_WALK_STEPS,
    build_service_spec, install_commands, render_command_line,
    status_commands, uninstall_commands, validate_spec,
    worker_commands)

def main():
    python_exe = sys.argv[1] if len(sys.argv) > 1 else r"C:\Program Files\Python311\python.exe"
    data_root = sys.argv[2] if len(sys.argv) > 2 else r"C:\ProgramData\Samverk"
    spec = build_service_spec(python_exe, data_root)
    problems = validate_spec(spec)
    print(f"service: {spec.service_name} (account {spec.account}, start {spec.start_mode})")
    print(f"binPath: {spec.bin_path}")
    print(f"data root: {spec.data_root}  db: {spec.db_path}")
    print("install sequence:")
    for argv in install_commands(spec):
        print("  " + render_command_line(argv))
    print("status sequence:")
    for argv in status_commands(spec):
        print("  " + render_command_line(argv))
    print("uninstall sequence (data root kept):")
    for argv in uninstall_commands(spec):
        print("  " + render_command_line(argv))
    print("workers (Task Scheduler one-shots):")
    for name, argv, words in worker_commands(spec):
        print(f"  {name}: " + (render_command_line(argv) if argv else f"NONE -- {words}"))
    print("install walk:")
    for i, s in enumerate(INSTALL_WALK_STEPS, 1):
        print(f"  {i}. {s['name']} -- {s['title']} [failure: {s['failure']}]")
    print("VERDICT:", "SPEC CLEAN -- definition, commands and walk "
          "render consistently; Windows host run NOT PROVEN"
          if not problems else f"PROBLEMS: {problems}")
    return 0 if not problems else 1

if __name__ == "__main__":
    sys.exit(main())
