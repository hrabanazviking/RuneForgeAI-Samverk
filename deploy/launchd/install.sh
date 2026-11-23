#!/bin/sh
# Install Samverk's launchd jobs natively (S-411). No Docker, ever.
# Run as root on macOS:
#     sudo sh deploy/launchd/install.sh [--load]
# Without --load the plists are installed and linted but NOT
# bootstrapped: turning a service on is the operator's word.
# The script is idempotent; re-running refreshes the plist files
# and never overwrites an existing samverk.ini in the data root.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DATA_ROOT="/Library/Application Support/Samverk"
PLISTS="org.samverk.server.plist org.samverk.webhook-delivery.plist org.samverk.weekly-digest.plist"
if [ "$(id -u)" != "0" ]; then echo "install.sh: run as root (sudo)" >&2; exit 1; fi
command -v launchctl >/dev/null 2>&1 || { echo "install.sh: launchctl not found; this install path is for macOS" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "install.sh: python3 not found" >&2; exit 1; }
if ! id _samverk >/dev/null 2>&1; then
  echo "install.sh: the _samverk service user does not exist yet." >&2
  echo "install.sh: create it first (walk step service_user_rights, docs/MACOS_SERVICE.md)" >&2
  exit 1
fi
install -d -o _samverk -m 0750 "$DATA_ROOT" "$DATA_ROOT/logs"
if [ ! -e "$DATA_ROOT/samverk.ini" ]; then
  install -m 0644 "$HERE/samverk.ini.example" "$DATA_ROOT/samverk.ini"
  echo "install.sh: wrote $DATA_ROOT/samverk.ini from the example; edit it before first load"
fi
for plist in $PLISTS; do install -o root -g wheel -m 0644 "$HERE/$plist" "/Library/LaunchDaemons/$plist"; done
# Verify what was installed, from the installed copies.
for plist in $PLISTS; do plutil -lint "/Library/LaunchDaemons/$plist"; done
echo "install.sh: plists installed and linted clean (plutil)"
if [ "${1:-}" = "--load" ]; then
  for plist in $PLISTS; do launchctl bootstrap system "/Library/LaunchDaemons/$plist"; done
  echo "install.sh: bootstrapped org.samverk.server and the worker jobs"
else
  echo "install.sh: NOT loaded. To start: sudo sh deploy/launchd/install.sh --load"
fi
