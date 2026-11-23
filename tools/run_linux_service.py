#!/usr/bin/env python3
"""S-412 -- Linux systemd service runner (pure stdlib).
Usage: python3 tools/run_linux_service.py [python_exe] [data_root]
Prints the service spec, the rendered units, the systemctl
install / enable / status / uninstall sequences, the worker
command lines, the parity matrix, and the install walk's steps
with their failure modes; exits 0 only when the standing spec
validates clean and every citizen's capability set is equal.
Everything printed is generated data proven as data, plus
S-348's systemd-analyze verify proof; a real install/enable/
health run on a dedicated host is NOT PROVEN (see
docs/LINUX_SERVICE.md).
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from samverk.linux_service import (ALL_UNITS, CAPABILITIES,
    CITIZENS, INSTALL_WALK_STEPS, PARITY_MATRIX, SERVER_UNIT,
    WORKER_UNITS, build_service_spec, enable_commands,
    install_commands, parity_capabilities, render_command_line,
    render_unit, server_unit, status_commands, timer_unit,
    uninstall_commands, validate_spec, worker_commands,
    worker_unit)

def main():
    python_exe = sys.argv[1] if len(sys.argv) > 1 else "/usr/bin/python3"
    data_root = sys.argv[2] if len(sys.argv) > 2 else "/var/lib/samverk"
    spec = build_service_spec(python_exe, data_root)
    problems = validate_spec(spec)
    print(f"unit: {spec.unit_name} (user {spec.user_name}, dir {spec.system_dir})")
    print(f"program: {' '.join(spec.server_command_list)}")
    print(f"data root: {spec.data_root}  db: {spec.db_path}  config: {spec.config_path}")
    print("server unit:")
    print(render_unit(server_unit(spec)))
    for role, unit in (("webhook-delivery", WORKER_UNITS[0]),
                       ("weekly-digest", WORKER_UNITS[1])):
        print(f"worker unit {unit}:")
        print(render_unit(worker_unit(spec, role)))
        print(f"timer unit {unit.replace('.service', '.timer')}:")
        print(render_unit(timer_unit(spec, role)))
    print("install sequence (enables nothing):")
    for argv in install_commands(spec, ROOT + "/deploy/systemd"):
        print("  " + render_command_line(argv))
    print("enable sequence (the operator's word):")
    for argv in enable_commands(spec):
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
    print("parity matrix (capability: linux | windows | macos):")
    for cap in CAPABILITIES:
        cells = PARITY_MATRIX[cap]
        print(f"  {cap}: {cells['linux']} | {cells['windows']} | {cells['macos']}")
    sets = {c: parity_capabilities(c) for c in CITIZENS}
    equal = len({frozenset(v) for v in sets.values()}) == 1
    print("install walk:")
    for i, s in enumerate(INSTALL_WALK_STEPS, 1):
        print(f"  {i}. {s['name']} -- {s['title']} [failure: {s['failure']}]")
    print(f"units: {' '.join(ALL_UNITS)}  server: {SERVER_UNIT}")
    print("VERDICT:", "SPEC CLEAN, PARITY EQUAL -- definition, "
          "units, commands and walk render consistently; real "
          "install/enable/health run NOT PROVEN"
          if not problems and equal else f"PROBLEMS: {problems} parity_equal={equal}")
    return 0 if not problems and equal else 1

if __name__ == "__main__":
    sys.exit(main())
