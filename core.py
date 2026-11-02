"""Shared validation and parsers. No radio or privileged side effects on import."""
import csv
import io
import re

VERSION = '0.1.0'
ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')

def clean(text):
    return ANSI.sub('', text).replace('\r', '\n')

def mac(value):
    value = str(value).strip().lower()
    if not re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}', value):
        raise ValueError('Enter a MAC address in AA:BB:CC:DD:EE:FF format.')
    if int(value[:2], 16) & 1 or value == '00:00:00:00:00:00':
        raise ValueError('A nonzero unicast MAC address is required.')
    return value

def number(value, minimum, maximum):
    value = int(value)
    if not minimum <= value <= maximum:
        raise ValueError(f'Value must be between {minimum} and {maximum}.')
    return value

def interfaces(text):
    result, current = [], None
    phy = ''
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('phy#'):
            phy = line
        elif line.startswith('Interface '):
            current = {'name': line.split()[1], 'phy': phy, 'type': '', 'mac': ''}
            result.append(current)
        elif current and line.startswith('type '):
            current['type'] = line.split()[1]
        elif current and line.startswith('addr '):
            current['mac'] = line.split()[1]
    return result

def networks(text):
    result = []
    for row in csv.reader(io.StringIO(text)):
        if not row or row[0].strip() == 'Station MAC':
            if row and row[0].strip() == 'Station MAC':
                break
            continue
        if len(row) < 14:
            continue
        try:
            bssid = mac(row[0])
            channel = number(row[3].strip(), 1, 233)
        except (ValueError, TypeError):
            continue
        result.append({'bssid': bssid, 'channel': channel, 'security': row[5].strip(),
                       'signal': row[8].strip(), 'ssid': row[13].strip() or '<hidden>'})
    return result

def handshake_status(output):
    """Only explicit positive aircrack counts count; tool errors are inconclusive."""
    output = clean(output)
    counts = [int(n) for n in re.findall(r'\b(\d+)\s+handshakes?\b', output, re.I)]
    if any(n > 0 for n in counts):
        return 'Handshake recognized by Aircrack-ng (not a recovered password).'
    if 'no valid wpa handshakes found' in output.lower() or counts:
        return 'No usable WPA/WPA2 handshake recognized in this file.'
    return 'Inconclusive. Inspect the tool output; no positive handshake result was recognized.'

def test_command(action, interface, data, session):
    """Construct argument lists, never shell strings."""
    bssid = mac(data['bssid'])
    channel = str(number(data['channel'], 1, 233))
    if action == 'deauth':
        station = mac(data['station'])
        if station == bssid:
            raise ValueError('Client MAC must differ from the access point.')
        return ['aireplay-ng', '--deauth', str(number(data.get('count', 1), 1, 5)),
                '-a', bssid, '-c', station, interface]
    if action in ('wps', 'pixie'):
        attempts = 1 if action == 'pixie' else number(data.get('attempts', 10), 1, 100)
        args = ['reaver', '-i', interface, '-b', bssid, '-c', channel, '-vv',
                '-g', str(attempts), '-d', '2', '-l', '60', '-s', str(session / 'reaver.session')]
        if action == 'pixie':
            args += ['-K', '1']
        return args
    raise ValueError('Unknown test.')
