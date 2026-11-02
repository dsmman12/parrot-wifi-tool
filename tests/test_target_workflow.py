import contextlib
import io
from pathlib import Path
import sys
import tempfile
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import clients, handshake_announced, test_command
import worker

AP='02:11:22:33:44:55'
CLIENT='02:11:22:33:44:66'
HEADER=f' CH  6 ][ Elapsed: 0 s ][ 2026-11-01 20:00 ][ WPA handshake: {AP} '

class TargetWorkflowTests(unittest.TestCase):
    def setUp(self):
        worker.STOP.clear()

    def test_client_scan_filters_other_aps_and_unassociated_stations(self):
        text='BSSID,header\n\nStation MAC, First time seen, Last time seen, Power, # packets, BSSID, Probed ESSIDs\n'+CLIENT+',x,x,-42,12,'+AP+',\n02:11:22:33:44:77,x,x,-55,20,02:aa:bb:cc:dd:ee,\n02:11:22:33:44:88,x,x,-60,5,(not associated),\n'
        self.assertEqual(clients(text,AP),[{'mac':CLIENT,'signal':'-42','packets':'12'}])

    def test_whole_ap_deauth_is_bounded_and_cannot_broadcast_without_target(self):
        args=test_command('deauth','wlan0',{'bssid':AP,'channel':6,'count':1,'whole_network':True},Path('/tmp'))
        self.assertEqual(args,['aireplay-ng','--deauth','1','-a',AP,'wlan0'])
        with self.assertRaises(ValueError):
            test_command('deauth','wlan0',{'bssid':AP,'channel':6,'count':0,'whole_network':True},Path('/tmp'))
        with self.assertRaises(ValueError):
            test_command('deauth','wlan0',{'bssid':'ff:ff:ff:ff:ff:ff','channel':6,'count':1,'whole_network':True},Path('/tmp'))

    def test_handshake_requires_targeted_status_header_not_ssid_or_wrong_ap(self):
        self.assertTrue(handshake_announced(HEADER,AP))
        self.assertFalse(handshake_announced(HEADER,'02:aa:bb:cc:dd:ee'))
        self.assertFalse(handshake_announced('WPA handshake: '+AP,AP))
        self.assertFalse(handshake_announced('02:aa:bb:cc:dd:ee -40 WPA2 [ WPA handshake: '+AP,AP))

    def test_stream_stops_on_confirmed_handshake_without_waiting_full_timer(self):
        found=[]
        def on_line(line):
            if handshake_announced(line,AP):
                found.append(AP)
                worker.STOP.set()
        with tempfile.TemporaryDirectory() as folder,contextlib.redirect_stdout(io.StringIO()):
            start=time.monotonic()
            script='import time; print('+repr(HEADER)+',flush=True); time.sleep(60)'
            worker.run_stream([sys.executable,'-u','-c',script],10,Path(folder),on_line=on_line,terminal_width=160)
            self.assertLess(time.monotonic()-start,3)
        self.assertEqual(found,[AP])

    def test_capture_child_gets_wide_terminal_without_stealing_control_pipe(self):
        with tempfile.TemporaryDirectory() as folder,contextlib.redirect_stdout(io.StringIO()) as output:
            script='import os; print(os.get_terminal_size(0).columns)'
            worker.run_stream([sys.executable,'-c',script],5,Path(folder),terminal_width=160)
            self.assertIn('160',output.getvalue())

if __name__=='__main__':
    unittest.main()
