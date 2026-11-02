import pathlib
import sys
import unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from core import mac, interfaces, networks, handshake_status, test_command, number

class ValidationTests(unittest.TestCase):
    def test_mac_rejects_broadcast_multicast_and_injection(self):
        for bad in ['ff:ff:ff:ff:ff:ff', '01:00:00:00:00:01', '00:00:00:00:00:00', 'aa:bb:cc:dd:ee:ff; reboot', '../../tmp']:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                mac(bad)
        self.assertEqual(mac('AA:BB:CC:DD:EE:FF'), 'aa:bb:cc:dd:ee:ff')

    def test_bounds(self):
        for n in (0, 6):
            with self.assertRaises(ValueError):
                number(n, 1, 5)

    def test_multiple_cards_keep_phy_and_mode(self):
        result = interfaces('phy#1\n Interface wlx123\n  addr 02:11:22:33:44:55\n  type monitor\nphy#0\n Interface wlan0\n  addr 02:aa:bb:cc:dd:ee\n  type managed\n')
        self.assertEqual([(d['name'], d['phy'], d['type']) for d in result], [('wlx123', 'phy#1', 'monitor'), ('wlan0', 'phy#0', 'managed')])

    def test_unnamed_p2p_device_cannot_overwrite_real_card(self):
        text='phy#1\n Interface wlx00c0cab2b465\n  wdev 0x100000001\n  addr 00:c0:ca:b2:b4:65\n  type managed\n Unnamed/non-netdev interface\n  wdev 0x100000002\n  addr 02:11:22:33:44:55\n  type P2P-device\nphy#0\n Unnamed/non-netdev interface\n  addr 02:aa:bb:cc:dd:ee\n  type P2P-device\n Interface wlan0\n  addr 02:22:33:44:55:66\n  type managed\n'
        result=interfaces(text)
        self.assertEqual(len(result),2)
        self.assertEqual(result[0]['type'],'managed')
        self.assertEqual(result[0]['mac'],'00:c0:ca:b2:b4:65')
        self.assertEqual(result[0]['phy'],'phy#1')
        self.assertEqual(result[1]['name'],'wlan0')

    def test_csv_hidden_ssids_and_station_section(self):
        csv = '\nBSSID, First time seen, Last time seen, channel, Speed, Privacy, Cipher, Authentication, Power, # beacons, # IV, LAN IP, ID-length, ESSID, Key\n02:11:22:33:44:55,x,x,6,54,WPA2,CCMP,PSK,-45,1,0,0,9,"Home, Lab",\n02:11:22:33:44:66,x,x,11,54,WPA2,CCMP,PSK,-50,1,0,0,0,,\n\nStation MAC, First time seen\n02:11:22:33:44:77,x,x,1,54,WPA2,CCMP,PSK,-40,1,0,0,4,Not an AP,\n'
        result = networks(csv)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['ssid'], 'Home, Lab')
        self.assertEqual(result[1]['ssid'], '<hidden>')

    def test_handshake_requires_explicit_positive_result(self):
        self.assertIn('recognized by', handshake_status('WPA (1 handshake)'))
        self.assertIn('No usable', handshake_status('WPA (0 handshakes)'))
        self.assertIn('No usable', handshake_status('No valid WPA handshakes found.'))
        self.assertIn('Inconclusive', handshake_status('EAPOL frames found\nFailed to open capture'))
        self.assertIn('accepted WPA/WPA2', handshake_status('1 potential targets\nKEY NOT FOUND'))
        self.assertIn('Inconclusive', handshake_status('KEY NOT FOUND'))
        self.assertIn('Inconclusive', handshake_status('0 potential targets\nKEY NOT FOUND'))
        self.assertIn('No usable', handshake_status('1 potential targets\nNo valid WPA handshakes found.'))

    def test_directed_deauth_is_bounded_and_has_client(self):
        data = dict(bssid='02:11:22:33:44:55', channel=6, station='02:11:22:33:44:66', count=2)
        args = test_command('deauth', 'wlan0', data, pathlib.Path('/tmp/test'))
        self.assertEqual(args, ['aireplay-ng', '--deauth', '2', '-a', data['bssid'], '-c', data['station'], 'wlan0'])
        data['count'] = 0
        with self.assertRaises(ValueError):
            test_command('deauth', 'wlan0', data, pathlib.Path('/tmp/test'))

    def test_wps_no_lock_bypass_and_capped_attempts(self):
        data = dict(bssid='02:11:22:33:44:55', channel=6, attempts=10)
        args = test_command('wps', 'wlan0', data, pathlib.Path('/fixed/session'))
        self.assertIn('-g', args)
        self.assertNotIn('-L', args)
        self.assertNotIn('--ignore-locks', args)
        self.assertEqual(args[args.index('-s') + 1], '/fixed/session/reaver.session')
        data['attempts'] = 101
        with self.assertRaises(ValueError):
            test_command('wps', 'wlan0', data, pathlib.Path('/tmp/test'))
        pixie = test_command('pixie', 'wlan0', data, pathlib.Path('/tmp/test'))
        self.assertEqual(pixie[pixie.index('-g') + 1], '1')
        self.assertIn('-K', pixie)

if __name__ == '__main__':
    unittest.main()
