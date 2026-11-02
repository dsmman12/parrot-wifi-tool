"""Shared validation and parsers. No radio or privileged side effects on import."""
import csv
import io
import re

VERSION = '0.4.1'
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
            current = None
        elif line.startswith('Unnamed/non-netdev interface'):
            current = None
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
    """Recognize counted or targeted WPA acceptance; tool errors stay inconclusive."""
    output = clean(output)
    counts = [int(n) for n in re.findall(r'\b(\d+)\s+handshakes?\b', output, re.I)]
    lower = output.lower()
    if 'no valid wpa handshakes found' in lower:
        return 'No usable WPA/WPA2 handshake recognized in this file.'
    targeted_acceptance = bool(re.search(r'\b[1-9][0-9]* potential targets?\b', lower)) and 'key not found' in lower
    if any(n > 0 for n in counts):
        return 'Handshake recognized by Aircrack-ng (not a recovered password).'
    if targeted_acceptance:
        return 'Aircrack-ng accepted WPA/WPA2 authentication data (handshake or PMKID). No password was recovered.'
    if 'no valid wpa handshakes found' in output.lower() or counts:
        return 'No usable WPA/WPA2 handshake recognized in this file.'
    return 'Inconclusive. Inspect the tool output; no positive handshake result was recognized.'

def test_command(action, interface, data, session):
    """Construct argument lists, never shell strings."""
    bssid = mac(data['bssid'])
    channel = str(number(data['channel'], 1, 233))
    if action == 'deauth':
        args = ['aireplay-ng', '--deauth', str(number(data.get('count', 1), 1, 5)), '-a', bssid]
        if data.get('whole_network') is not True:
            station = mac(data['station'])
            if station == bssid:
                raise ValueError('Client MAC must differ from the access point.')
            args += ['-c', station]
        return args + [interface]
    if action in ('wps', 'pixie'):
        attempts = 1 if action == 'pixie' else number(data.get('attempts', 10), 1, 100)
        args = ['reaver', '-i', interface, '-b', bssid, '-c', channel, '-vv',
                '-g', str(attempts), '-d', '2', '-l', '60', '-s', str(session / 'reaver.session')]
        if action == 'pixie':
            args += ['-K', '1']
        return args
    raise ValueError('Unknown test.')


def wps_advertisement(packet, linktype):
    """Read WPS vendor IEs from beacon/probe-response frames, not client payloads."""
    if linktype == 127:  # LINKTYPE_IEEE802_11_RADIOTAP
        if len(packet) < 8 or packet[0] != 0:
            return None
        length = int.from_bytes(packet[2:4], 'little')
        if length < 8 or length > len(packet):
            return None
        # Radiotap Flags follows optional TSFT, after all present-bit words.
        first_present = int.from_bytes(packet[4:8], 'little')
        present, cursor = first_present, 8
        for _ in range(8):
            if not present & 0x80000000:
                break
            if cursor + 4 > length:
                return None
            present = int.from_bytes(packet[cursor:cursor + 4], 'little')
            cursor += 4
        else:
            return None
        if first_present & 1:
            cursor = (cursor + 7) // 8 * 8 + 8
        flags = 0
        if first_present & 2:
            if cursor >= length:
                return None
            flags = packet[cursor]
        if flags & 0x40:  # Bad FCS: don't infer WPS status from corrupt frames.
            return None
        packet = packet[length:]
        if flags & 0x10:
            if len(packet) < 4:
                return None
            packet = packet[:-4]
    elif linktype != 105:  # LINKTYPE_IEEE802_11
        return None
    # Beacon/probe response, protocol version 0; reject protected/fragmented frames.
    if len(packet) < 36 or packet[0] not in (0x80, 0x50) or packet[1] & 0x44 or packet[22] & 0x0f:
        return None
    try:
        bssid = mac(':'.join(f'{b:02x}' for b in packet[16:22]))
    except ValueError:
        return None
    payloads = []
    pos = 36  # 24-byte management header + 12-byte fixed parameters
    while pos + 2 <= len(packet):
        kind, length = packet[pos:pos + 2]
        pos += 2
        if pos + length > len(packet):
            return None
        value = packet[pos:pos + length]
        pos += length
        if kind == 221 and value.startswith(b'\x00\x50\xf2\x04'):
            payloads.append(value[4:])
    if not payloads:
        return None
    # WPS attributes can span consecutive vendor IEs.
    data = b''.join(payloads)
    locked, pos = None, 0
    while pos + 4 <= len(data):
        tag = int.from_bytes(data[pos:pos + 2], 'big')
        length = int.from_bytes(data[pos + 2:pos + 4], 'big')
        pos += 4
        if pos + length > len(data):
            return None
        value = data[pos:pos + length]
        pos += length
        if tag == 0x1057 and length == 1 and value[0] in (0, 1):
            locked = bool(value[0])
    if pos != len(data):
        return None
    return bssid, {'wps_detected': True, 'wps_locked': locked,
                   'wps': 'Locked' if locked is True else 'Available' if locked is False else 'Detected (lock ?)'}


class WpsObserver:
    """Incrementally consume classic pcap, retrying incomplete records next tick."""
    def __init__(self):
        self.path = None
        self.offset = 0
        self.endian = None
        self.linktype = None
        self.items = {}

    def update(self, path):
        import struct
        if path != self.path:
            self.path, self.offset, self.endian, self.linktype = path, 0, None, None
            self.items = {}
        try:
            with path.open('rb') as stream:
                if self.offset == 0:
                    header = stream.read(24)
                    if len(header) < 24:
                        return self.items
                    if header[:4] in (b'\xd4\xc3\xb2\xa1', b'\x4d\x3c\xb2\xa1'):
                        self.endian = '<'
                    elif header[:4] in (b'\xa1\xb2\xc3\xd4', b'\xa1\xb2\x3c\x4d'):
                        self.endian = '>'
                    else:
                        return self.items
                    self.linktype = struct.unpack(self.endian + 'I', header[20:24])[0] & 0xffff
                    self.offset = 24
                stream.seek(self.offset)
                for _ in range(10000):  # Bound work per UI update, even on busy radios.
                    record = stream.read(16)
                    if len(record) < 16:
                        break
                    length = struct.unpack(self.endian + 'I', record[8:12])[0]
                    if length > 16 * 1024 * 1024:
                        break
                    packet = stream.read(length)
                    if len(packet) != length:
                        break
                    self.offset += 16 + length
                    result = wps_advertisement(packet, self.linktype)
                    if result:
                        bssid, info = result
                        self.items[bssid] = info
        except FileNotFoundError:
            pass
        return self.items


def merge_wps(items, observations):
    return [{**item, **observations.get(item['bssid'],
             {'wps': 'Unknown', 'wps_detected': False, 'wps_locked': None})} for item in items]


def clients(text, bssid):
    """Read only stations associated with the selected AP from Airodump CSV."""
    bssid = mac(bssid)
    in_stations = False
    result = []
    for row in csv.reader(io.StringIO(text)):
        if row and row[0].strip() == 'Station MAC':
            in_stations = True
            continue
        if not in_stations or len(row) < 6:
            continue
        try:
            station = mac(row[0])
            ap = mac(row[5])
        except ValueError:
            continue
        if ap == bssid and station != bssid:
            result.append({'mac': station, 'signal': row[3].strip(), 'packets': row[4].strip()})
    return result


def handshake_announced(text, bssid):
    """Trust only Airodump's explicit handshake announcement for this target."""
    target = mac(bssid)
    for line in clean(text).splitlines():
        # Only the status header, never an AP row or an SSID that contains text.
        if not re.match(r'^\s*CH\s+[-0-9, ]+', line) or '[ Elapsed:' not in line:
            continue
        matches = re.findall(r'\]\[ WPA handshake:\s*((?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2})', line, re.I)
        if target in (value.lower() for value in matches):
            return True
    return False
