import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import worker

class P2pRecoveryTests(unittest.TestCase):
    def test_kernel_permanent_mac_repairs_mode_and_backs_up_corrupt_record(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'testcard0.json'
            state={'type':'P2P-device','mac':'02:11:22:33:44:55','nm':'yes','up':True}
            path.write_text(json.dumps(state))
            result=SimpleNamespace(returncode=0,stdout=json.dumps([{'permaddr':'00:c0:ca:b2:b4:65'}]))
            with patch.object(worker,'command',return_value=result),patch.object(worker.shutil,'which',return_value=None),patch.object(worker,'emit'):
                fixed=worker.recover_saved_state('testcard0',path,state)
            self.assertEqual(fixed['type'],'managed')
            self.assertEqual(fixed['mac'],'00:c0:ca:b2:b4:65')
            self.assertEqual(json.loads(path.with_suffix('.pre-p2p-fix.json').read_text()),state)
            self.assertEqual(json.loads(path.read_text()),fixed)

    def test_ethtool_permanent_mac_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'testcard0.json'
            state={'type':'P2P-device','mac':'02:11:22:33:44:55','nm':'yes','up':True}
            path.write_text(json.dumps(state))
            results=[SimpleNamespace(returncode=0,stdout='[{}]'),SimpleNamespace(returncode=0,stdout='Permanent address: 00:c0:ca:b2:b4:65')]
            with patch.object(worker,'command',side_effect=results),patch.object(worker.shutil,'which',return_value='/usr/sbin/ethtool'),patch.object(worker,'emit'):
                self.assertEqual(worker.recover_saved_state('testcard0',path,state)['mac'],'00:c0:ca:b2:b4:65')

    def test_unknown_permanent_mac_never_reuses_untrusted_p2p_address(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'testcard0.json'
            state={'type':'P2P-device','mac':'02:11:22:33:44:55','nm':'yes','up':True}
            original=json.dumps(state)
            path.write_text(original)
            result=SimpleNamespace(returncode=0,stdout='[{}]')
            with patch.object(worker,'command',return_value=result),patch.object(worker.shutil,'which',return_value=None):
                with self.assertRaises(RuntimeError):
                    worker.recover_saved_state('testcard0',path,state)
            self.assertEqual(path.read_text(),original)
            self.assertFalse(path.with_suffix('.pre-p2p-fix.json').exists())

if __name__=='__main__':
    unittest.main()
