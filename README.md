# Parrot Wi-Fi Tool

A lightweight Python/Tk desktop app for testing your own Wi-Fi networks on Parrot OS. Version **0.3.2** is an initial release: unit-tested and intended for hardware validation on Parrot. It has no AI/API dependency and does not need HexStrike or Ollama running.

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

The installer uses the distribution packages for Python/Tk, iw, iproute2, NetworkManager, Aircrack-ng, Reaver/Wash, Pixiewps and sudo. It installs root-owned application files under `/usr/local/lib/parrot-wifi-tool`. The UI runs as your user; a fixed-operation helper uses **sudo authorization** for adapter/radio operations. The launcher asks for your normal sudo password in a terminal and refreshes that cached authorization while the window is open; buttons use noninteractive sudo instead of polkit popups. No passwordless sudo rule, custom broad polkit policy, web server, or remote control service is installed.

Start using `parrot-wifi-tool` (or its application-menu shortcut, which opens a terminal). Enter your normal Parrot sudo password there when requested. Keep that terminal open while using the app. Do not put sudo in front of the launcher or run the GUI itself as root. If your sudo policy forbids cached credentials, noninteractive helper calls will fail and the log will show the sudo error; no passwordless sudo rule is added.

## What is included

- Adapter dropdown: discovers current interface names, mode, MAC and sysfs driver.
- Enable/verify monitor mode, switch back to managed mode, and restore the saved original state.
- Random locally administered MAC, custom unicast MAC, restore saved MAC.
- Automatic 2.4/5 GHz survey on dual-band radios (falls back to 2.4 GHz when enabled 5 GHz channels are not reported by iw).
- Twenty-second network survey with live SSID, BSSID, channel, security, signal and **WPS** columns (updates about every two seconds).
- WPS advertisements are read passively from Airodump capture packets: **Available**, **Locked**, **Detected (lock ?)**, or **Unknown**. No observed advertisement means unknown, not confirmed disabled.
- Selecting a WPS-advertising router offers **Test WPS PIN** and **Test Pixie Dust** directly below the network list. Finish/stop the scan before testing. Offers are disabled for a reported lock and still require target authorization and active-test confirmation.
- Targeted WPA/WPA2 capture with a 5–3,600 second limit; Stop flushes files.
- A folder picker and session export, including packet captures, CSV and tool output.
- Local handshake recognition using Aircrack-ng with one deliberately invalid one-character WPA entry (not a valid password guess). This checks the capture, not a password. Explicit handshake counts and acceptance of WPA/WPA2 authentication data (which may be a PMKID) are labeled separately. Inconclusive tool output is explicitly labeled.
- Selected-AP injection test.
- Directed deauthentication against a specified client, 1–5 bursts. This may run beside a capture of the same AP/channel on the selected card.
- WPS discovery using Wash, a bounded PIN test (1–100 attempts, 120 seconds), and one-attempt Pixie Dust test (120 seconds). Reported WPS locks/rate limiting stop the test. No lock bypass is used.
- Automatic restoration after scans, captures/tests, failures, Stop All, and normal app close. The saved MAC, mode, link state and known NetworkManager control setting are restored; capture files are retained.
- Stop All closes control pipes so the privileged helper terminates its child process groups, including descendants, before restoring. Overlapping capture/deauth jobs wait until the last radio operation stops.
- The app waits for verified cleanup before closing. Failed/denied restoration keeps the app open and retains recovery state for retry. Tests automatically re-enter monitor mode if a preceding test restored managed mode.

## First use

1. Plug in your USB Wi-Fi adapter and open the app. The first `wlx…` card is selected if present; always verify the dropdown.
2. Open **Adapter controls → Enable monitor mode**. Authorize sudo in the launcher terminal if requested. Confirm that mode changes to `monitor` in the adapter header/log.
3. Open **Survey & capture → Scan networks**. Select your network as rows arrive. This fills the AP BSSID and channel; WPS status updates during the scan. A router advertising WPS shows test options below the list. Finish/stop the scan before testing; a reported WPS lock disables the offered tests.
4. Confirm you own or have permission to test that target. Choose a save folder, set the capture duration, and select **Start targeted capture**.
5. Reconnect one of your own devices to the network. Stop capture, then **Save latest session**. **Check handshake file…** opens a file picker; select the `.cap` and keep the correct AP BSSID selected.
6. A completed capture/test automatically restores its saved adapter state. **Stop All** also ends the scanning session and restores modified cards. **Restore adapter completely** remains available for an explicit reset. Wi-Fi may need to reconnect.

For an active test, select the correct target/channel and open **Active tests & WPS**. Directed deauth requires the client MAC; it does not broadcast against all nearby clients. The app asks for confirmation before each active test. Be aware that even a single aireplay-ng burst contains multiple frames.

## Files and privacy

Running tools write to a fresh, fixed session folder under `/var/lib/parrot-wifi-tool/sessions/`. After the process finishes, file ownership is assigned to your user so you can export without root access. Session folders remain root-owned and group-readable/traversable; files are mode 600. **Save latest session** copies the most recently completed session into a timestamped subfolder of your chosen destination. An existing export is not overwritten.

Captures/logs can contain device identifiers, traffic and recovered WPS credentials. Keep them private. They are ignored by Git and are never uploaded by this app. Sessions remain on disk until you remove them yourself. No automatic cleanup deletes your captures.

The survey saves packet captures as well as CSV so WPS vendor information elements can be decoded without another radio scanner. The parser supports classic pcap with raw 802.11 or radiotap headers, skips incomplete live records until the next update, and ignores corrupt/truncated advertisements. Unsupported capture formats leave WPS status unknown. WPS availability does not establish PIN support, vulnerability, or password recoverability. Advertisements may change after the scan; the displayed lock status is an observation from that scan.

## Adapter and protocol limitations

Monitor mode and injection depend on chipset, kernel and driver. This app uses `iw` on the selected interface, verifies the mode, and attempts to roll back configuration failures. It does not install or repair DKMS drivers. RTL8814AU driver warnings may still require separate driver diagnosis. Other cards sharing the same physical radio can also be affected by channel/mode changes; use a dedicated USB radio.

MAC changes leave the selected card unmanaged so NetworkManager cannot immediately replace its test MAC. Use **Managed mode** or **Restore adapter completely** to return it to NetworkManager. Only the selected interface is unmanaged in NetworkManager. The app does not run `airmon-ng check kill` or globally stop networking. Original MAC, mode, link state and known NetworkManager management state are saved before the first change. The saved MAC is the address present then, which can differ from the factory hardware MAC. Persistent state survives a normal restart; unplugging/replacing a card with the same interface name can make old saved state stale. Use Restore adapter before unplugging.

Scans, captures, injection/deauth/WPS tests, failed operations, Stop All, and normal window close trigger restoration. Scan results stay visible after reset, and the next scan/test automatically re-enters monitor mode. The last worker restores when capture and deauth overlap; the other worker defers. Closing waits for all workers and any remaining modified cards to be restored. If restoration is denied, a card disappears, or verification fails, the app stays open and preserves its snapshot; reconnect the card/approve the prompt and press Stop All to retry. Adapter changes discovered from a previous session are also restored on normal close. A lost GUI control pipe triggers worker cleanup during radio operations. Power loss, SIGKILL of the privileged worker, or a driver/kernel failure can still prevent cleanup; recovery state is retained for the next run. The app does not reset your router or delete saved Wi-Fi profiles.

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
# Real distro binaries + hash-verified public upstream captures (requires Internet):
python3 tests/toolchain_check.py
# With xvfb installed:
xvfb-run -a python3 tests/smoke_gui.py
```

Tests cover restoration after completion/errors/cancellation, overlapping radio-job cleanup, retained state on recovery failure, GUI close waiting and authorization-denial handling, WPS advertisement parsing, live partial-packet reads, WPS lock updates, WPS offer behavior, MAC validation, target bounds, network parsing, handshake result interpretation, scoped command construction, child-process cancellation/timeouts, WPS lock handling and failed monitor-mode rollback. The GUI smoke test exercises real Tk widgets without a radio. **Live adapter/radio behavior must be validated on your Parrot machine.** CI also runs real binary option checks, replays the upstream WPS beacon through Airodump, and verifies the handshake detector against the upstream WPA capture, using pinned/hash-checked public fixtures. These offline checks run on Ubuntu and Debian Bookworm; they cannot verify your USB radio, kernel module, injection, or WPS vulnerability.

Tool references: [Aircrack-ng documentation](https://www.aircrack-ng.org/documentation.html), [Airodump-ng](https://www.aircrack-ng.org/doku.php?id=airodump-ng), [Aireplay-ng](https://www.aircrack-ng.org/doku.php?id=aireplay-ng), [Reaver/Wash upstream](https://github.com/t6x/reaver-wps-fork-t6x).

Only test equipment you own or have explicit permission to assess.

Version 0.3.2 fixes unnamed P2P-device entries overwriting a real adapter in `iw dev` parsing. Known corrupted P2P snapshots are backed up, then migrated to managed mode with a verified permanent MAC from the kernel/ethtool (or the kernel-marked permanent current address). If a permanent MAC cannot be verified, recovery stops and keeps the old snapshot instead of guessing.
