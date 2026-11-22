#!/bin/sh
# Install Samverk's systemd units natively (S-348). No Docker, ever.
# Run as root on Debian or Ubuntu:
#     sudo sh deploy/systemd/install.sh [--enable]
# Without --enable the units are installed and verified but NOT
# enabled or started: turning a service on is the operator's word.
# The script is idempotent; re-running refreshes the unit files and
# never overwrites an existing /etc/samverk/samverk.ini.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
UNITS="samverk-server.service samverk-webhook-worker.service samverk-webhook-worker.timer samverk-digest-worker.service samverk-digest-worker.timer"
if [ "$(id -u)" != "0" ]; then echo "install.sh: run as root (sudo)" >&2; exit 1; fi
command -v systemctl >/dev/null 2>&1 || { echo "install.sh: systemctl not found; this install path is for systemd systems" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "install.sh: python3 not found" >&2; exit 1; }
if ! id samverk >/dev/null 2>&1; then
  useradd --system --home-dir /var/lib/samverk --shell /usr/sbin/nologin samverk
  echo "install.sh: created system user 'samverk'"
fi
install -d -o samverk -g samverk -m 0750 /var/lib/samverk
install -d -m 0755 /etc/samverk
if [ ! -e /etc/samverk/samverk.ini ]; then
  install -m 0644 "$HERE/samverk.ini.example" /etc/samverk/samverk.ini
  echo "install.sh: wrote /etc/samverk/samverk.ini from the example; edit it before first start"
fi
for unit in $UNITS; do install -m 0644 "$HERE/$unit" "/etc/systemd/system/$unit"; done
systemctl daemon-reload
# Verify what was installed, from the installed copies.
for unit in samverk-server.service samverk-webhook-worker.service samverk-digest-worker.service; do
  systemd-analyze verify "/etc/systemd/system/$unit"
done
echo "install.sh: units installed and verified (systemd-analyze verify clean)"
if [ "${1:-}" = "--enable" ]; then
  systemctl enable --now samverk-server.service samverk-webhook-worker.timer samverk-digest-worker.timer
  echo "install.sh: enabled samverk-server.service and both worker timers"
else
  echo "install.sh: NOT enabled. To start: systemctl enable --now samverk-server.service samverk-webhook-worker.timer samverk-digest-worker.timer"
fi
