"""Real distro tool checks and upstream capture replay; never transmits radio traffic.

Run on Parrot after install: python3 tests/toolchain_check.py
Downloads only two public, hash-verified Aircrack-ng test captures into a temporary
folder. Uses an empty wordlist; never attempts to recover a real network password.
"""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import WpsObserver, handshake_status, networks

os.environ['PATH'] = '/usr/sbin:/usr/bin:/sbin:/bin'
ENV = {**os.environ, 'LC_ALL':'C', 'TERM':'xterm'}
COMMIT = '7e2256f38f3590af4c19a6ae14ed79bab02242e6'
FIXTURES = {'wps2.0.pcap':'8a464055e97670de1d71ec1bbc91d954e83f0158',
            'wpa.cap':'56c5b5da58a3a7e586176fdc0731405b656ba52b'}

def run(args, timeout=20):
    result = subprocess.run(args, capture_output=True, text=True, env=ENV, timeout=timeout)
    return result, result.stdout + '\n' + result.stderr

for tool, options in [('airodump-ng',['--wps','--beacons','--output-format','-r ']),
                      ('reaver',['--max-attempts','--pixie-dust','--session']),
                      ('wash',['--interface']), ('aireplay-ng',['--deauth','--test'])]:
    _, output = run([tool,'--help'])
    for option in options:
        assert option in output, f'{tool} lacks {option}:\n{output}'
    print(f'PASS: {tool} supports the options this app uses')

with tempfile.TemporaryDirectory() as folder:
    directory = Path(folder)
    for name, expected in FIXTURES.items():
        url = f'https://raw.githubusercontent.com/aircrack-ng/aircrack-ng/{COMMIT}/test/{name}'
        with urllib.request.urlopen(url, timeout=30) as response:
            content = response.read(1024*1024)
        actual = hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()
        assert actual == expected, f'Upstream fixture hash mismatch: {name}'
        (directory/name).write_bytes(content)
    observations = WpsObserver().update(directory/'wps2.0.pcap')
    assert observations.get('00:c0:ca:78:b1:37',{}).get('wps_detected'), observations
    print('PASS: WPS parser detects upstream real WPS beacon')
    # Replay offline through airodump's actual CSV/pcap writer, no adapter selected.
    result, output = run(['airodump-ng','-r',str(directory/'wps2.0.pcap'),
                          '--write',str(directory/'survey'),'--wps','--beacons',
                          '--output-format','pcap,csv','--write-interval','1'], timeout=20)
    csv_files=list(directory.glob('survey*.csv'))
    cap_files=list(directory.glob('survey*.cap'))
    assert csv_files and cap_files, f'Airodump did not write files (exit {result.returncode}):\n{output}'
    rows=networks(csv_files[0].read_text(errors='replace'))
    assert any(i['bssid']=='00:c0:ca:78:b1:37' for i in rows), (rows,output)
    assert WpsObserver().update(cap_files[0]).get('00:c0:ca:78:b1:37',{}).get('wps_detected'), output
    print('PASS: real Airodump output matches our network and WPS parsers')
    # Upstream public WPA test fixture, empty wordlist: only handshake recognition.
    _, output = run(['aircrack-ng','-a','2','-b','00:0d:93:eb:b0:8c','-w','/dev/null',str(directory/'wpa.cap')])
    assert 'Handshake recognized by' in handshake_status(output), output
    print('PASS: real Aircrack-ng handshake output matches our detector')
print('All offline toolchain checks passed. Live monitor/injection still require your adapter.')
