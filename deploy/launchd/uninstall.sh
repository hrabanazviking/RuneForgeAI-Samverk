#!/bin/sh
# Remove Samverk's launchd registration (S-411). The data root
# and its instance are NOT deleted -- export (S-341) is the
# data's road out.
set -u
if [ "$(id -u)" != "0" ]; then echo "uninstall.sh: run as root (sudo)" >&2; exit 1; fi
for label in org.samverk.server org.samverk.webhook-delivery org.samverk.weekly-digest; do
  launchctl bootout "system/$label"
  rm -f "/Library/LaunchDaemons/$label.plist"
done
echo "service removed; data root kept: /Library/Application Support/Samverk"
