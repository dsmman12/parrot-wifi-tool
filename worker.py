#!/usr/bin/python3
"""Installed root-owned worker. Fixed operations; JSON-lines IPC; no shell execution."""
import contextlib
import fcntl
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import selectors
import shutil
import signal
import subprocess
import sys
import threading
import time

# Under python -I, explicitly load only the installed root-owned code directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import clean, interfaces, mac, networks, number, test_command, WpsObserver, merge_wps, clients, handshake_announced

ROOT = Path('/var/lib/parrot-wifi-tool')
STOP = threading.Event()
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C', 'TERM': 'dumb'}

def emit(kind, **data):
    try:
        print(json.dumps({'event': kind, **data}), flush=True)
    except BrokenPipeError:
        STOP.set()

def command(args, check=True):
    p = subprocess.run(args, capture_output=True, text=True, timeout=20, env=ENV)
    if check and p.returncode:
        raise RuntimeError(clean(p.stderr or p.stdout).strip() or f'{args[0]} failed ({p.returncode})')
    return p

def devices():
    return interfaces(command(['iw', 'dev']).stdout)

def survey_bands(info):
    phy = info.get('phy', '').replace('#', '')
    if not re.fullmatch(r'phy[0-9]+', phy):
        return 'bg'
    capabilities = command(['iw', 'phy', phy, 'info'], False)
    if capabilities.returncode == 0:
        for line in capabilities.stdout.splitlines():
            if re.search(r'\b5[0-9]{3} MHz\b', line) and 'disabled' not in line.lower():
                return 'abg'
    return 'bg'

def device(name):
    if not name or '/' in name or len(name) > 15:
        raise ValueError('Invalid wireless interface.')
    for item in devices():
        if item['name'] == name:
            return item
    raise ValueError('Adapter disappeared or was renamed. Refresh adapters.')

def state_path(name):
    return ROOT / f'{name}.json'

def recover_saved_state(name, path, state):
    if state.get('type') != 'P2P-device':
        return state
    # Older parsers let an unnamed P2P block overwrite the preceding netdev.
    # Its MAC may be wrong too: recover a verified permanent MAC, never guess.
    link = json.loads(command(['ip', '-j', 'link', 'show', 'dev', name]).stdout)[0]
    candidates = [link.get('permaddr', '')]
    if shutil.which('ethtool', path=ENV['PATH']):
        result = command(['ethtool', '-P', name], False)
        if result.returncode == 0:
            candidates.extend(re.findall(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', result.stdout))
    assign_type = Path('/sys/class/net') / name / 'addr_assign_type'
    if assign_type.exists() and assign_type.read_text().strip() == '0':
        candidates.append(link.get('address', ''))
    permanent = None
    for candidate in candidates:
        try:
            permanent = mac(candidate)
            break
        except ValueError:
            continue
    if permanent is None:
        raise RuntimeError('Old P2P snapshot is invalid, and the permanent MAC could not be verified. Install ethtool and retry, or replug the USB card before retrying. Original snapshot retained.')
    backup = path.with_suffix('.pre-p2p-fix.json')
    if not backup.exists():
        backup.write_text(json.dumps(state))
        os.chmod(backup, 0o600)
    state = {**state, 'type':'managed', 'mac':permanent}
    path.write_text(json.dumps(state))
    emit('log', text='Repaired old P2P snapshot: managed mode and verified permanent MAC. Original record backed up.')
    return state

def remember(name):
    path = state_path(name)
    if path.exists():
        state = recover_saved_state(name, path, json.loads(path.read_text()))
        emit('state_saved', interface=name)
        return state
    info = device(name)
    nm = command(['nmcli', '-g', 'GENERAL.NM-MANAGED', 'device', 'show', name], False) if shutil.which('nmcli', path=ENV['PATH']) else None
    link = json.loads(command(['ip', '-j', 'link', 'show', 'dev', name]).stdout)[0]
    state = {'mac': info['mac'], 'type': info['type'], 'up': 'UP' in link['flags'],
             'nm': nm.stdout.strip().lower() if nm and nm.returncode == 0 else ''}
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(state))
    os.replace(tmp, path)
    emit('state_saved', interface=name)
    return state

def unmanage(name):
    if shutil.which('nmcli', path=ENV['PATH']):
        command(['nmcli', 'device', 'set', name, 'managed', 'no'])

def set_mode(name, mode):
    command(['ip', 'link', 'set', 'dev', name, 'down'])
    command(['iw', 'dev', name, 'set', 'type', mode])
    command(['ip', 'link', 'set', 'dev', name, 'up'])
    if device(name)['type'] != mode:
        raise RuntimeError('Driver did not enter the requested mode.')

def restore(name):
    path = state_path(name)
    if not path.exists():
        emit('log', text='No pending adapter changes; already restored.')
        emit('restored', interface=name)
        return
    state = recover_saved_state(name, path, json.loads(path.read_text()))
    unmanage(name)
    command(['ip', 'link', 'set', 'dev', name, 'down'])
    command(['iw', 'dev', name, 'set', 'type', state['type']])
    command(['ip', 'link', 'set', 'dev', name, 'address', mac(state['mac'])])
    command(['ip', 'link', 'set', 'dev', name, 'up' if state['up'] else 'down'])
    if state['nm'] in ('yes', 'no'):
        command(['nmcli', 'device', 'set', name, 'managed', state['nm']])
    actual = device(name)
    if actual['type'] != state['type'] or actual['mac'].lower() != state['mac'].lower():
        raise RuntimeError('Restoration could not be verified; saved state retained.')
    path.unlink()
    emit('restored', interface=name)
    emit('log', text='Original mode, MAC, link state and known NetworkManager setting restored. Reconnect Wi-Fi if needed.')

def listen():
    # Parent owns this pipe. EOF, Stop, or GUI exit cancels the root-owned child.
    try:
        sys.stdin.readline()
    finally:
        STOP.set()

def run_stream(args, seconds, session, stop_on_lock=False, on_tick=None, on_line=None, terminal_width=None):
    # Airodump truncates its status header to stdin's terminal width. Give only
    # the capture child a wide pseudo-terminal; keep GUI cancellation on our pipe.
    with contextlib.ExitStack() as resources:
        input_fd = subprocess.DEVNULL
        if terminal_width is not None:
            import struct
            import termios
            master, slave = os.openpty()
            resources.callback(os.close, master)
            resources.callback(os.close, slave)
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 40, terminal_width, 0, 0))
            input_fd = slave
        return _run_stream(args, seconds, session, stop_on_lock, on_tick, on_line, input_fd)

def _run_stream(args, seconds, session, stop_on_lock, on_tick, on_line, input_fd):
    emit('log', text='Running: ' + ' '.join(args))
    p = subprocess.Popen(args, stdin=input_fd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         start_new_session=True, env=ENV, cwd=session)
    selector = selectors.DefaultSelector()
    selector.register(p.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + seconds
    next_tick = time.monotonic()
    interrupted = False
    pending = b''
    output_tail = []
    try:
        with (session / 'output.log').open('w') as log:
            while True:
                if STOP.is_set() or time.monotonic() >= deadline:
                    interrupted = True
                    break
                if on_tick and time.monotonic() >= next_tick:
                    on_tick()
                    next_tick = time.monotonic() + 2
                ready = selector.select(0.2)
                for key, _ in ready:
                    chunk = os.read(key.fileobj.fileno(), 4096)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    log.write(chunk.decode(errors='replace'))
                    log.flush()
                    pending += re.sub(rb'\x1b\[[0-9;]*[HfABCD]', b'\n', chunk).replace(b'\r', b'\n')
                    while b'\n' in pending:
                        line, pending = pending.split(b'\n', 1)
                        text = clean(line.decode(errors='replace')).strip()
                        if text:
                            output_tail.append(text[:500])
                            output_tail = output_tail[-8:]
                            emit('log', text=text[:2000])
                            if on_line:
                                on_line(text)
                        if stop_on_lock and ('rate limiting' in text.lower() or 'wps locked' in text.lower()):
                            emit('log', text='Router reported WPS lock/rate limiting; stopping.')
                            interrupted = True
                            STOP.set()
                if p.poll() is not None and not selector.get_map():
                    break
            if pending:
                text = clean(pending.decode(errors='replace'))
                emit('log', text=text[:2000])
                if on_line:
                    on_line(text)
    finally:
        selector.close()
        # Stop all descendants, including pixiewps, even if the parent exited.
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            p.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)
            p.wait()
        p.stdout.close()
    if p.returncode and not interrupted:
        detail = '\n'.join(output_tail)[-1800:] or 'No output was produced.'
        raise RuntimeError(f'{args[0]} exited with code {p.returncode}.\n{detail}')
    emit('log', text='Stopped / time limit reached.' if interrupted else 'Operation finished.')

def handoff_files(session, uid, gid):
    # Directory remains root-owned: user cannot replace entries while root traverses.
    for entry in session.iterdir():
        if entry.is_file() and not entry.is_symlink():
            os.chmod(entry, 0o600)
            os.chown(entry, uid, gid)
    os.chmod(session, 0o750)
    os.chown(session, 0, gid)

def caller_uid():
    # sudo/pkexec set the original desktop user's UID. Never accept it via JSON.
    uid = int(os.environ.get('SUDO_UID', os.environ.get('PKEXEC_UID', '-1')))
    if uid <= 0:
        raise ValueError('Launch with parrot-wifi-tool as your normal desktop user so sudo can authorize the worker.')
    return uid

def main():
    with contextlib.ExitStack() as resources:
        execute(resources)

def execute(resources):
    if os.geteuid() != 0:
        raise RuntimeError('Use the installed desktop app; the worker requires administrator authorization.')
    os.umask(0o077)
    ROOT.mkdir(mode=0o711, parents=True, exist_ok=True)
    os.chmod(ROOT, 0o711)
    uid = caller_uid()
    gid = pwd.getpwuid(uid).pw_gid
    action, data = sys.argv[1], json.loads(sys.argv[2])
    name = data.get('interface', '')
    if action == 'status':
        emit('devices', items=devices())
        return
    info = device(name)
    if action not in ('monitor', 'managed', 'random', 'custom', 'restore-mac', 'restore',
                      'survey', 'capture', 'injection', 'deauth', 'wash', 'wps', 'pixie'):
        raise ValueError('Unsupported operation.')
    # Radio-wide lock for configuration and tests; capture and directed deauth use
    # separate slots so a selected client can reconnect during the capture.
    phy = info['phy'].replace('#', '')
    lock = resources.enter_context((ROOT / f'{phy}.lock').open('a'))
    shared = action in ('capture', 'deauth')
    try:
        fcntl.flock(lock, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError('This radio is busy in another operation.')
    if shared:
        slot = resources.enter_context((ROOT / f'{phy}-{action}.lock').open('a'))
        try:
            fcntl.flock(slot, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError(f'A {action} operation is already using this radio.')
    if action == 'restore':
        restore(name)
        return
    if action in ('monitor', 'managed', 'random', 'custom', 'restore-mac'):
        remember(name)
        try:
            unmanage(name)
            if action in ('monitor', 'managed'):
                set_mode(name, 'monitor' if action == 'monitor' else 'managed')
                if action == 'managed':
                    state = json.loads(state_path(name).read_text())
                    if state['nm'] in ('yes', 'no'):
                        command(['nmcli', 'device', 'set', name, 'managed', state['nm']])
            else:
                value = ('02:' + ':'.join(f'{b:02x}' for b in secrets.token_bytes(5))) if action == 'random' else mac(data['mac']) if action == 'custom' else mac(json.loads(state_path(name).read_text())['mac'])
                command(['ip', 'link', 'set', 'dev', name, 'down'])
                command(['ip', 'link', 'set', 'dev', name, 'address', value])
                command(['ip', 'link', 'set', 'dev', name, 'up'])
                if device(name)['mac'].lower() != value:
                    raise RuntimeError('Driver rejected the MAC change.')
                emit('log', text='MAC change verified. Card remains unmanaged to prevent NetworkManager replacing the test MAC; use Managed mode or Restore adapter to reconnect.')
            emit('log', text=f'Adapter verified: {device(name)}')
        except Exception:
            try:
                restore(name)
            except Exception as recovery:
                emit('log', text=f'Recovery needs attention: {recovery}. Use Restore adapter.')
            raise
        return
    seconds = number(data.get('seconds', 30), 5, 3600 if action == 'capture' else 300)
    channel = None
    bssid = None
    if action in ('capture', 'deauth', 'wps', 'pixie', 'injection'):
        bssid = mac(data['bssid'])
        channel = str(number(data['channel'], 1, 233))
    if action in ('deauth', 'wps', 'pixie') and data.get('authorized') is not True:
        raise ValueError('Explicit authorized target confirmation required.')
    cap_scope = ROOT / f'{phy}-capture.json'
    if action == 'deauth':
        if cap_scope.exists():
            scope = json.loads(cap_scope.read_text())
            if scope != {'bssid': bssid, 'channel': channel}:
                raise ValueError('Deauth target must match the running capture and channel.')
    radio_operation(action, data, name, info, uid, gid, lock, cap_scope, seconds, channel, bssid)

def cleanup_radio(name, lock):
    # Capture and directed deauth share a radio. Only the last worker restores.
    fcntl.flock(lock, fcntl.LOCK_UN)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        emit('log', text='Restoration deferred until the other operation on this radio stops.')
        return False
    restore(name)
    return True

def prepare_radio(name, info):
    # Shared capture/deauth workers must not race snapshot creation or mode setup.
    path = ROOT / (info['phy'].replace('#', '') + '-setup.lock')
    with path.open('a') as setup_lock:
        deadline = time.monotonic() + 60
        while True:
            if STOP.is_set():
                return False
            try:
                fcntl.flock(setup_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Timed out waiting for adapter setup.')
                time.sleep(0.05)
        remember(name)
        if device(name)['type'] != 'monitor':
            unmanage(name)
            set_mode(name, 'monitor')
    return True

def radio_operation(action, data, name, info, uid, gid, lock, cap_scope, seconds, channel, bssid):
    session = None
    publish_survey = None
    handshake_found = False
    threading.Thread(target=listen, daemon=True).start()
    try:
        if action == 'capture':
            emit('capture_stage', text=f'Preparing {name}: entering monitor mode…')
        if not prepare_radio(name, info):
            return
        session_root = ROOT / 'sessions'
        session_root.mkdir(mode=0o711, exist_ok=True)
        os.chmod(session_root, 0o711)  # mkdir mode is restricted by the worker's umask.
        # Allow only traversal to private group-readable session folders, not listing.
        os.chmod(ROOT, 0o711)
        session = session_root / (time.strftime('%Y%m%d-%H%M%S-') + secrets.token_hex(6))
        session.mkdir(mode=0o700)
        emit('session', path=str(session))
        if action == 'survey':
            args = ['airodump-ng', '--band', survey_bands(info), '--wps', '--beacons', '--write', str(session / 'survey'), '--output-format', 'pcap,csv', '--write-interval', '1', name]
        elif action == 'capture':
            args = ['airodump-ng', '--background', '0', '--update', '1', '--bssid', bssid, '--channel', channel, '--write', str(session / 'capture'), '--output-format', 'pcap,csv', '--write-interval', '1', name]
        elif action == 'wash':
            args = ['wash', '-i', name]
        elif action == 'injection':
            args = ['aireplay-ng', '--test', '-a', bssid, name]
        else:
            args = test_command(action, name, data, session)
        if channel:
            if action == 'capture':
                emit('capture_stage', text=f'{name}: monitor mode verified; tuning to channel {channel}…', mode='monitor')
            command(['iw', 'dev', name, 'set', 'channel', channel])
        if action == 'capture':
            cap_scope.write_text(json.dumps({'bssid': bssid, 'channel': channel}))
        observer = WpsObserver()
        def publish_survey():
            csv_files = sorted(session.glob('*.csv'))
            cap_files = sorted(session.glob('*.cap'))
            observations = observer.update(cap_files[0]) if cap_files else observer.items
            if csv_files:
                items = merge_wps(networks(csv_files[0].read_text(errors='replace')), observations)
                emit('networks', items=items)
        def publish_capture():
            csv_files = sorted(session.glob('*.csv'))
            if csv_files:
                emit('clients', items=clients(csv_files[0].read_text(errors='replace'), bssid))
        def capture_line(text):
            nonlocal handshake_found
            if not handshake_found and handshake_announced(text, bssid):
                handshake_found = True
                (session / 'handshake.json').write_text(json.dumps({'bssid':bssid,'recognized_by':'airodump-ng'}))
                emit('handshake', bssid=bssid)
                STOP.set()
        run_stream(args, seconds, session, action in ('wps', 'pixie'),
                   on_tick=publish_survey if action == 'survey' else publish_capture if action == 'capture' else None,
                   on_line=capture_line if action == 'capture' else None,
                   terminal_width=160 if action == 'capture' else None)
        if action == 'capture' and not handshake_found:
            emit('capture_status', text='Capture ended without an Airodump-confirmed handshake. Captured files are still available.')
    finally:
        try:
            if action == 'capture':
                cap_scope.unlink(missing_ok=True)
            if session is not None:
                if action == 'survey' and publish_survey is not None:
                    publish_survey()
                handoff_files(session, uid, gid)
                emit('files', paths=[str(p) for p in session.iterdir() if p.is_file()])
        finally:
            # Every completed/stopped radio operation restores the saved state.
            cleanup_radio(name, lock)

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        emit('error', text=str(exc))
        sys.exit(1)
