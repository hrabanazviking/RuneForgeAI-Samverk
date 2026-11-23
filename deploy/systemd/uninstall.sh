#!/bin/sh
# Uninstall Samverk's systemd registration (S-412). No Docker, ever.
# Run as root:
#     sudo sh deploy/systemd/uninstall.sh
# Disables and stops the server and both worker timers, removes the
# unit files from /etc/systemd/system/, and reloads systemd. The
# data root (/var/lib/samverk) and the config (/etc/samverk) are NOT
# deleted -- the whole instance stands untouched; S-341's
# whole-instance export is the data's road out, exactly as on
# Windows and macOS.
set -u
if [ "$(id -u)" != "0" ]; then echo "uninstall.sh: run as root (sudo)" >&2; exit 1; fi
systemctl disable --now samverk-server.service samverk-webhook-worker.timer samverk-digest-worker.timer || true
rm -f /etc/systemd/system/samverk-server.service /etc/systemd/system/samverk-webhook-worker.service /etc/systemd/system/samverk-webhook-worker.timer /etc/systemd/system/samverk-digest-worker.service /etc/systemd/system/samverk-digest-worker.timer
systemctl daemon-reload
echo "uninstall.sh: service removed; data root kept: /var/lib/samverk (config kept: /etc/samverk)"
