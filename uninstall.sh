#!/bin/bash
set -euo pipefail
if [ "$(id -u)" -eq 0 ]; then
    echo 'Run bash uninstall.sh as your normal user, without sudo.'
    exit 1
fi
printf 'Close the app and use Restore adapter before uninstalling.\n'
read -r -p 'Remove the application? Captures and adapter recovery state will be kept. [y/N] ' reply
case "$reply" in y|Y) ;; *) exit 0 ;; esac
sudo rm -f -- /usr/local/bin/parrot-wifi-tool /usr/local/lib/parrot-wifi-tool/app.py /usr/local/lib/parrot-wifi-tool/worker.py /usr/local/lib/parrot-wifi-tool/core.py
sudo rmdir -- /usr/local/lib/parrot-wifi-tool 2>/dev/null || true
rm -f -- "$HOME/.local/share/applications/parrot-wifi-tool.desktop"
if command -v xdg-user-dir >/dev/null 2>&1; then
    desktop_dir="$(xdg-user-dir DESKTOP)"
    if [ -d "$desktop_dir" ] && [ "$desktop_dir" != "$HOME" ]; then
        rm -f -- "$desktop_dir/parrot-wifi-tool.desktop"
    fi
fi
printf 'Application removed. Captures remain in /var/lib/parrot-wifi-tool/sessions and your export folder.\n'
