import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from worker import caller_uid

class CallerTests(unittest.TestCase):
    def test_sudo_uid_preserves_normal_capture_owner(self):
        with patch.dict(os.environ,{'SUDO_UID':'1000'},clear=True):
            self.assertEqual(caller_uid(),1000)

    def test_sudo_uid_has_priority_over_legacy_identity(self):
        with patch.dict(os.environ,{'SUDO_UID':'1001','PKEXEC_UID':'1000'},clear=True):
            self.assertEqual(caller_uid(),1001)

    def test_legacy_worker_remains_compatible(self):
        with patch.dict(os.environ,{'PKEXEC_UID':'1000'},clear=True):
            self.assertEqual(caller_uid(),1000)

    def test_missing_invalid_or_root_identity_is_rejected(self):
        for identity in ({},{'SUDO_UID':'0'},{'SUDO_UID':'-1'},{'SUDO_UID':'invalid'}):
            with patch.dict(os.environ,identity,clear=True),self.assertRaises(ValueError):
                caller_uid()

if __name__=='__main__':
    unittest.main()
