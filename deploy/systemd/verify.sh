#!/bin/sh
# Verify the shipped units without installing anything (S-348):
#     sh deploy/systemd/verify.sh
# Runs systemd-analyze verify over the units in this directory. The
# 'samverk' system user need not exist for verify to pass.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
command -v systemd-analyze >/dev/null 2>&1 || { echo "verify.sh: systemd-analyze not found" >&2; exit 1; }
for unit in samverk-server.service samverk-webhook-worker.service samverk-digest-worker.service; do
  echo "verify: $unit"; systemd-analyze verify "$HERE/$unit"
done
echo "verify.sh: all units verify clean"
