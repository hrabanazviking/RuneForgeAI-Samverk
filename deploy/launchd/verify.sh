#!/bin/sh
# Verify the shipped plists without installing anything (S-411):
#     sh deploy/launchd/verify.sh
# Parses every plist in this directory as data (plistlib) and
# checks each one against the dict samverk/macos_service.py
# renders for the standing spec -- the same judgement the
# battery makes, runnable by hand on any OS.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/../.." && pwd)
command -v python3 >/dev/null 2>&1 || { echo "verify.sh: python3 not found" >&2; exit 1; }
PYTHONPATH="$ROOT" python3 - "$HERE" <<'PYEOF'
import plistlib, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]).resolve().parent.parent))
from samverk import macos_service as m
spec = m.build_service_spec()
want = {spec.label: m.server_plist(spec)}
for n in m.SHIPPED_WORKERS:
    want[m.worker_label(n)] = m.worker_plist(spec, n)
for label, job in sorted(want.items()):
    got = plistlib.loads((Path(sys.argv[1]) / (label + ".plist")).read_bytes())
    if got != job:
        print(f"verify: {label}.plist DRIFTS from macos_service")
        sys.exit(1)
    print(f"verify: {label}.plist parses and matches the module")
print("verify.sh: all plists verify clean")
PYEOF
