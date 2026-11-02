# Parrot Wi-Fi Tool

A lightweight Python/Tk desktop app for testing your own Wi-Fi networks on Parrot OS. Version **0.1.0** is an initial release: unit-tested and intended for hardware validation on Parrot. It has no AI/API dependency and does not need HexStrike or Ollama running.

## Install on Parrot

Run these commands as your normal desktop user, **without sudo in front of the whole block**:

```bash
sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/dsmman12/parrot-wifi-tool.git
cd parrot-wifi-tool
bash install.sh
```

Open **Parrot Wi-Fi Tool** from the application menu, use the desktop shortcut, or run:

```bash
parrot-wifi-tool
```

The installer uses the distribution packages for Python/Tk, iw, iproute2, NetworkManager, Aircrack-ng, Reaver/Wash, Pixiewps and pkexec. It installs root-owned application files under `/usr/local/lib/parrot-wifi-tool`. The UI runs as your user; a fixed-operation helper uses a standard **pkexec administrator prompt** for adapter/radio operations. No passwordless sudo rule, custom broad polkit policy, web server, or remote control service is installed.

If your desktop lacks a polkit authentication agent, pkexec prompts may fail. Launch within a normal Parrot desktop session with its authentication agent running. Do not run the whole GUI as root.

## What is included

- Adapter dropdown: discovers current interface names, mode, MAC and sysfs driver.
- Enable/verify monitor mode, switch back to managed mode, and restore the saved original state.
- Random locally administered MAC, custom unicast MAC, restore saved MAC.
- Twenty-second network survey with selectable SSID, BSSID, channel, security and signal table.
- Targeted WPA/WPA2 capture with a 5–3,600 second limit; Stop flushes files.
- A folder picker and session export, including packet captures, CSV and tool output.
- Local handshake recognition using Aircrack-ng with an empty wordlist. This checks the capture, not a password. Inconclusive tool output is explicitly labeled.
- Selected-AP injection test.
- Directed deauthentication against a specified client, 1–5 bursts. This may run beside a capture of the same AP/channel on the selected card.
- WPS discovery using Wash, a bounded PIN test (1–100 attempts, 120 seconds), and one-attempt Pixie Dust test (120 seconds). Reported WPS locks/rate limiting stop the test. No lock bypass is used.
- Stop All closes the control pipes so the privileged helper terminates its child process groups, including descendants. Operations also have time limits.

## First use

1. Plug in your USB Wi-Fi adapter and open the app. The first `wlx…` card is selected if present; always verify the dropdown.
2. Open **Adapter controls → Enable monitor mode**. Approve the administrator prompt. Confirm that mode changes to `monitor` in the adapter header/log.
3. Open **Survey & capture → Scan networks**. After 20 seconds, select your network. This fills the AP BSSID and channel.
4. Confirm you own or have permission to test that target. Choose a save folder, set the capture duration, and select **Start targeted capture**.
5. Reconnect one of your own devices to the network. Stop capture, then **Save latest session**. **Check handshake file…** opens a file picker; select the `.cap` and keep the correct AP BSSID selected.
6. Before returning the card to everyday use, stop all tasks and select **Restore adapter completely**. Wi-Fi may need to be reconnected.

For an active test, select the correct target/channel and open **Active tests & WPS**. Directed deauth requires the client MAC; it does not broadcast against all nearby clients. The app asks for confirmation before each active test. Be aware that even a single aireplay-ng burst contains multiple frames.

## Files and privacy

Running tools write to a fresh, fixed session folder under `/var/lib/parrot-wifi-tool/sessions/`. After the process finishes, file ownership is assigned to your user so you can export without root access. Session folders remain root-owned and group-readable/traversable; files are mode 600. **Save latest session** copies the most recently completed session into a timestamped subfolder of your chosen destination. An existing export is not overwritten.

Captures/logs can contain device identifiers, traffic and recovered WPS credentials. Keep them private. They are ignored by Git and are never uploaded by this app. Sessions remain on disk until you remove them yourself. No automatic cleanup deletes your captures.

## Adapter and protocol limitations

Monitor mode and injection depend on chipset, kernel and driver. This app uses `iw` on the selected interface, verifies the mode, and attempts to roll back configuration failures. It does not install or repair DKMS drivers. RTL8814AU driver warnings may still require separate driver diagnosis. Other cards sharing the same physical radio can also be affected by channel/mode changes; use a dedicated USB radio.

Only the selected interface is unmanaged in NetworkManager. The app does not run `airmon-ng check kill` or globally stop networking. Original MAC, mode, link state and known NetworkManager management state are saved before the first change. The saved MAC is the address present then, which can differ from the factory hardware MAC. Persistent state survives a normal restart; unplugging/replacing a card with the same interface name can make old saved state stale. Use Restore adapter before unplugging.

Closing the GUI stops active jobs but deliberately leaves the chosen monitor/MAC settings in place. Restore explicitly before exiting. Power loss or killing the privileged helper itself can require manual recovery or unplugging/replugging the adapter. The app cannot guarantee driver recovery.

Protected Management Frames can prevent deauthentication. WPA3 is not the WPA2 offline handshake/password-check workflow. Hidden SSIDs may remain hidden. A completed test or missing handshake is not proof of security. WPS tests may fail on patched/locked hardware or because the required package variant/options differ; inspect the displayed tool output.

## Update

Close the app and restore the adapter first. From your clone:

```bash
git pull --ff-only
bash install.sh
```

## Remove

Restore the adapter, close the app, then run `bash uninstall.sh` from the clone. It removes app/launcher files but keeps captures, exported files, dependencies and saved recovery state.

## Validation

```bash
python3 -m py_compile app.py worker.py core.py
python3 -m unittest discover -s tests -v
bash -n install.sh uninstall.sh
# With xvfb installed:
xvfb-run -a python3 tests/smoke_gui.py
```

Tests cover MAC validation, target bounds, network parsing, handshake result interpretation, scoped command construction, child-process cancellation/timeouts, WPS lock handling and failed monitor-mode rollback. The GUI smoke test exercises real Tk widgets without a radio. **Live adapter/radio behavior must be validated on your Parrot machine.**

Tool references: [Aircrack-ng documentation](https://www.aircrack-ng.org/documentation.html), [Airodump-ng](https://www.aircrack-ng.org/doku.php?id=airodump-ng), [Aireplay-ng](https://www.aircrack-ng.org/doku.php?id=aireplay-ng), [Reaver/Wash upstream](https://github.com/t6x/reaver-wps-fork-t6x).

Only test equipment you own or have explicit permission to assess.
