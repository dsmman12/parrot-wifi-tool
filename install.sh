#!/bin/bash
set -euo pipefail
if [ "$(id -u)" -eq 0 ]; then
    echo 'Run: bash install.sh (as your normal desktop user, without sudo).'
    exit 1
fi
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
for file in app.py worker.py core.py; do
    test -f "$project_dir/$file" || { echo "Missing $file. Download the complete repository."; exit 1; }
done
sudo apt-get update
sudo apt-get install -y python3 python3-tk iw iproute2 network-manager aircrack-ng reaver pixiewps pkexec
sudo install -d -o root -g root -m 755 /usr/local/lib/parrot-wifi-tool
sudo install -o root -g root -m 644 "$project_dir/app.py" "$project_dir/worker.py" "$project_dir/core.py" /usr/local/lib/parrot-wifi-tool/
sudo install -d -o root -g root -m 755 /usr/local/bin
sudo tee /usr/local/bin/parrot-wifi-tool >/dev/null <<'LAUNCHER'
#!/bin/sh
exec /usr/bin/python3 -I /usr/local/lib/parrot-wifi-tool/app.py "$@"
LAUNCHER
sudo chmod 755 /usr/local/bin/parrot-wifi-tool
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/parrot-wifi-tool.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Parrot Wi-Fi Tool
Comment=Desktop Wi-Fi testing for authorized networks
Exec=/usr/local/bin/parrot-wifi-tool
Icon=network-wireless
Terminal=false
Categories=Network;System;
DESKTOP
if command -v xdg-user-dir >/dev/null 2>&1; then
    desktop_dir="$(xdg-user-dir DESKTOP)"
    if [ -d "$desktop_dir" ] && [ "$desktop_dir" != "$HOME" ]; then
        cp "$HOME/.local/share/applications/parrot-wifi-tool.desktop" "$desktop_dir/"
        chmod u+x "$desktop_dir/parrot-wifi-tool.desktop"
    fi
fi
printf '\nInstalled. Open Parrot Wi-Fi Tool from your app menu, or run: parrot-wifi-tool\n'
printf 'The desktop may ask you to mark the shortcut as trusted. No passwordless sudo rule was installed.\n'
