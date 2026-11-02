#!/bin/bash
set -euo pipefail
if [ "$(id -u)" -eq 0 ]; then
    echo 'Run parrot-wifi-tool as your normal desktop user, without sudo.'
    exit 1
fi
printf 'Authorizing Wi-Fi operations with sudo. Use your normal Parrot login password if asked.\n'
sudo -v
# Keep the normal, terminal-scoped sudo timestamp fresh only while this launcher
# is alive. No password is stored and no sudoers/polkit rule is changed.
launcher_pid=$$
(
    while kill -0 "$launcher_pid" 2>/dev/null; do
        sleep 60
        kill -0 "$launcher_pid" 2>/dev/null || exit 0
        sudo -n -v || exit 0
    done
) &
auth_refresh_pid=$!
trap 'kill "$auth_refresh_pid" 2>/dev/null || true' EXIT
/usr/bin/python3 -I /usr/local/lib/parrot-wifi-tool/app.py "$@"
