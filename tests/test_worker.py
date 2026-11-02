import contextlib
import io
import json
import pathlib
import os
import stat
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import worker

class ProcessTests(unittest.TestCase):
    def setUp(self):
        worker.STOP.clear()

    def test_stream_drains_and_reports_output(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()) as output:
            worker.run_stream([sys.executable, '-c', 'print("test output")'], 5, pathlib.Path(folder))
            self.assertIn('test output', output.getvalue())
            self.assertIn('test output', (pathlib.Path(folder) / 'output.log').read_text())

    def test_timeout_terminates_child(self):
        start = time.monotonic()
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            worker.run_stream([sys.executable, '-c', 'import time; time.sleep(60)'], 0.2, pathlib.Path(folder))
        self.assertLess(time.monotonic() - start, 4)

    def test_stop_event_terminates_child(self):
        worker.STOP.set()
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            worker.run_stream([sys.executable, '-c', 'import time; time.sleep(60)'], 60, pathlib.Path(folder))

    def test_nonzero_exit_is_not_success(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
            worker.run_stream([sys.executable, '-c', 'raise SystemExit(4)'], 5, pathlib.Path(folder))

    def test_reported_wps_lock_stops_process(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()) as output:
            worker.run_stream([sys.executable, '-u', '-c', 'import time; print("WARNING: Detected AP rate limiting"); time.sleep(60)'], 10, pathlib.Path(folder), True)
            self.assertTrue(worker.STOP.is_set())
            self.assertIn('stopping', output.getvalue())

    def test_sessions_remain_traversable_under_private_umask(self):
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            fake_device = dict(name='wlan0', phy='phy#1', type='monitor', mac='02:11:22:33:44:55')
            old_mask = os.umask(0o077)
            try:
                with patch.object(worker, 'ROOT', root), patch.object(worker.os, 'geteuid', return_value=0), patch.dict(worker.os.environ, {'PKEXEC_UID':'1000'}), patch.object(worker.pwd, 'getpwuid') as user, patch.object(worker, 'device', return_value=fake_device), patch.object(worker.threading, 'Thread'), patch.object(worker, 'run_stream'), patch.object(worker, 'remember'), patch.object(worker, 'command'), patch.object(worker, 'handoff_files'), patch.object(worker, 'emit'), patch.object(sys, 'argv', ['worker.py', 'survey', '{"interface":"wlan0","seconds":5}']):
                    user.return_value.pw_gid = 1000
                    worker.main()
                self.assertEqual(stat.S_IMODE((root / 'sessions').stat().st_mode), 0o711)
            finally:
                os.umask(old_mask)

    def test_scan_uses_5ghz_only_when_the_phy_reports_it(self):
        from types import SimpleNamespace
        with patch.object(worker,'command',return_value=SimpleNamespace(returncode=0,stdout='* 2412 MHz [1]\n* 5180 MHz [36] (20 dBm)')):
            self.assertEqual(worker.survey_bands({'phy':'phy#1'}),'abg')
        with patch.object(worker,'command',return_value=SimpleNamespace(returncode=0,stdout='* 2412 MHz [1]\n* 5180 MHz [36] (disabled)')):
            self.assertEqual(worker.survey_bands({'phy':'phy#1'}),'bg')
        with patch.object(worker,'command') as command:
            self.assertEqual(worker.survey_bands({'phy':'invalid'}),'bg')
            command.assert_not_called()

    def test_custom_mac_is_not_immediately_given_back_to_networkmanager(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            before = dict(name='wlan0', phy='phy#1', type='managed', mac='02:11:22:33:44:55')
            after = {**before, 'mac':'02:11:22:33:44:66'}
            with patch.object(worker, 'ROOT', pathlib.Path(folder)), patch.object(worker.os, 'geteuid', return_value=0), patch.dict(worker.os.environ, {'PKEXEC_UID':'1000'}), patch.object(worker.pwd, 'getpwuid') as user, patch.object(worker, 'device', side_effect=[before,after,after]), patch.object(worker,'remember'), patch.object(worker,'unmanage') as unmanage, patch.object(worker,'command') as command, patch.object(sys, 'argv', ['worker.py','custom','{"interface":"wlan0","mac":"02:11:22:33:44:66"}']):
                user.return_value.pw_gid=1000
                worker.main()
                unmanage.assert_called_once_with('wlan0')
                self.assertFalse(any(c.args[0][0]=='nmcli' for c in command.call_args_list))
                self.assertIn(['ip','link','set','dev','wlan0','address',after['mac']], [c.args[0] for c in command.call_args_list])

    def test_rejected_mode_rolls_back(self):
        # Exercise main's config rollback without issuing commands to a radio.
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            root.joinpath('wlan0.json').write_text(json.dumps(dict(mac='02:11:22:33:44:55', type='managed', up=True, nm='yes')))
            fake_device = dict(name='wlan0', phy='phy#1', type='managed', mac='02:11:22:33:44:55')
            with patch.object(worker, 'ROOT', root), patch.object(worker.os, 'geteuid', return_value=0), patch.dict(worker.os.environ, {'PKEXEC_UID':'1000'}), patch.object(worker.pwd, 'getpwuid') as user, patch.object(worker, 'device', return_value=fake_device), patch.object(worker, 'unmanage'), patch.object(worker, 'set_mode', side_effect=RuntimeError('driver failed')), patch.object(worker, 'restore') as restore, patch.object(sys, 'argv', ['worker.py', 'monitor', '{"interface":"wlan0"}']):
                user.return_value.pw_gid = 1000
                with self.assertRaises(RuntimeError):
                    worker.main()
                restore.assert_called_once_with('wlan0')

if __name__ == '__main__':
    unittest.main()
