#!/usr/bin/python3
"""Installed root-owned worker. Fixed operations; JSON-lines IPC; no shell execution."""
import contextlib
import fcntl
import json
import os
from pathlib import Path
import pwd
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
from core import clean, interfaces, mac, networks, number, test_command, WpsObserver, merge_wps

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

def device(name):
    if not name or '/' in name or len(name) > 15:
        raise ValueError('Invalid wireless interface.')
    for item in devices():
        if item['name'] == name:
            return item
    raise ValueError('Adapter disappeared or was renamed. Refresh adapters.')

def state_path(name):
    return ROOT / f'{name}.json'

def remember(name):
    path = state_path(name)
    if path.exists():
        return json.loads(path.read_text())
    info = device(name)
    nm = command(['nmcli', '-g', 'GENERAL.NM-MANAGED', 'device', 'show', name], False) if shutil.which('nmcli', path=ENV['PATH']) else None
    link = json.loads(command(['ip', '-j', 'link', 'show', 'dev', name]).stdout)[0]
    state = {'mac': info['mac'], 'type': info['type'], 'up': 'UP' in link['flags'],
             'nm': nm.stdout.strip().lower() if nm and nm.returncode == 0 else ''}
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(state))
    os.replace(tmp, path)
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
        raise ValueError('No saved adapter state. Nothing to restore.')
    state = json.loads(path.read_text())
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
    emit('log', text='Original mode, MAC, link state and known NetworkManager setting restored. Reconnect Wi-Fi if needed.')

def listen():
    # Parent owns this pipe. EOF, Stop, or GUI exit cancels the root-owned child.
    try:
        sys.stdin.readline()
    finally:
        STOP.set()

def run_stream(args, seconds, session, stop_on_lock=False, on_tick=None):
    emit('log', text='Running: ' + ' '.join(args))
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         start_new_session=True, env=ENV, cwd=session)
    selector = selectors.DefaultSelector()
    selector.register(p.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + seconds
    next_tick = time.monotonic()
    interrupted = False
    pending = b''
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
                    pending += chunk.replace(b'\r', b'\n')
                    while b'\n' in pending:
                        line, pending = pending.split(b'\n', 1)
                        text = clean(line.decode(errors='replace')).strip()
                        if text:
                            emit('log', text=text[:2000])
                        if stop_on_lock and ('rate limiting' in text.lower() or 'wps locked' in text.lower()):
                            emit('log', text='Router reported WPS lock/rate limiting; stopping.')
                            interrupted = True
                            STOP.set()
                if p.poll() is not None and not selector.get_map():
                    break
            if pending:
                emit('log', text=clean(pending.decode(errors='replace'))[:2000])
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
        raise RuntimeError(f'{args[0]} exited with code {p.returncode}; see output log.')
    emit('log', text='Stopped / time limit reached.' if interrupted else 'Operation finished.')

def handoff_files(session, uid, gid):
    # Directory remains root-owned: user cannot replace entries while root traverses.
    for entry in session.iterdir():
        if entry.is_file() and not entry.is_symlink():
            os.chmod(entry, 0o600)
            os.chown(entry, uid, gid)
    os.chmod(session, 0o750)
    os.chown(session, 0, gid)

def main():
    with contextlib.ExitStack() as resources:
        execute(resources)

def execute(resources):
    if os.geteuid() != 0:
        raise RuntimeError('Use the installed desktop app; the worker requires administrator authorization.')
    os.umask(0o077)
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    # PKEXEC_UID is supplied by pkexec, not the GUI request.
    uid = int(os.environ.get('PKEXEC_UID', '-1'))
    if uid <= 0:
        raise ValueError('Launch from your normal desktop account through pkexec.')
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
                state = json.loads(state_path(name).read_text())
                if info['type'] == 'managed' and state['nm'] in ('yes', 'no'):
                    command(['nmcli', 'device', 'set', name, 'managed', state['nm']])
            emit('log', text=f'Adapter verified: {device(name)}')
        except Exception:
            try:
                restore(name)
            except Exception as recovery:
                emit('log', text=f'Recovery needs attention: {recovery}. Use Restore adapter.')
            raise
        return
    if info['type'] != 'monitor':
        raise ValueError('Enable monitor mode first.')
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
    session_root = ROOT / 'sessions'
    session_root.mkdir(mode=0o711, exist_ok=True)
    os.chmod(session_root, 0o711)  # mkdir mode is restricted by the worker's umask.
    # Allow only traversal to private group-readable session folders, not listing.
    os.chmod(ROOT, 0o711)
    session = session_root / (time.strftime('%Y%m%d-%H%M%S-') + secrets.token_hex(6))
    session.mkdir(mode=0o700)
    emit('session', path=str(session))
    if action == 'survey':
        args = ['airodump-ng', '--wps', '--beacons', '--write', str(session / 'survey'), '--output-format', 'pcap,csv', '--write-interval', '1', name]
    elif action == 'capture':
        args = ['airodump-ng', '--bssid', bssid, '--channel', channel, '--write', str(session / 'capture'), '--output-format', 'pcap,csv', '--write-interval', '1', name]
    elif action == 'wash':
        args = ['wash', '-i', name]
    elif action == 'injection':
        args = ['aireplay-ng', '--test', '-a', bssid, name]
    else:
        args = test_command(action, name, data, session)
    if channel:
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
    threading.Thread(target=listen, daemon=True).start()
    try:
        run_stream(args, seconds, session, action in ('wps', 'pixie'),
                   on_tick=publish_survey if action == 'survey' else None)
    finally:
        if action == 'capture':
            cap_scope.unlink(missing_ok=True)
        if action == 'survey':
            publish_survey()
        handoff_files(session, uid, gid)
        emit('files', paths=[str(p) for p in session.iterdir() if p.is_file()])

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        emit('error', text=str(exc))
        sys.exit(1)
