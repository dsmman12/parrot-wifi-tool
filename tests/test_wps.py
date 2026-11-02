import pathlib
import struct
import sys
import tempfile
import unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from core import WpsObserver, wps_advertisement, merge_wps

AP = '02:11:22:33:44:55'

def frame(locked=0, wps=True):
    header = b'\x80\x00\x00\x00' + b'\xff'*6 + bytes.fromhex(AP.replace(':',''))*2 + b'\x00\x00'
    fixed = b'\x00'*12
    attrs = b'\x10\x4a\x00\x01\x10'
    if locked is not None:
        attrs += b'\x10\x57\x00\x01' + bytes([locked])
    value = b'\x00\x50\xf2\x04' + attrs
    return header + fixed + (b'\xdd' + bytes([len(value)]) + value if wps else b'\x00\x03Lab')

def pcap(packet, endian='<', linktype=105):
    return struct.pack(endian+'IHHIIII',0xa1b2c3d4,2,4,0,0,65535,linktype) + struct.pack(endian+'IIII',1,0,len(packet),len(packet)) + packet

class WpsTests(unittest.TestCase):
    def test_available_locked_and_unknown_lock(self):
        self.assertEqual(wps_advertisement(frame(0),105)[1]['wps'], 'Available')
        self.assertTrue(wps_advertisement(frame(1),105)[1]['wps_locked'])
        self.assertIsNone(wps_advertisement(frame(None),105)[1]['wps_locked'])

    def test_no_wps_is_unknown_never_disabled(self):
        self.assertIsNone(wps_advertisement(frame(wps=False),105))
        result = merge_wps([{'bssid':AP}], {})[0]
        self.assertEqual(result['wps'], 'Unknown')
        self.assertFalse(result['wps_detected'])

    def test_radiotap_and_fcs(self):
        rt = b'\x00\x00\x09\x00\x02\x00\x00\x00\x10'
        self.assertEqual(wps_advertisement(rt+frame()+b'\xde\xad\xbe\xef',127)[0], AP)
        bad_rt = rt[:-1] + b'\x50'
        self.assertIsNone(wps_advertisement(bad_rt+frame()+b'\x00'*4,127))

    def test_truncated_or_wrong_frame_does_not_claim_wps(self):
        self.assertIsNone(wps_advertisement(frame()[:-1],105))
        self.assertIsNone(wps_advertisement(b'\x08'+frame()[1:],105))
        self.assertIsNone(wps_advertisement(frame(),1))
        self.assertIsNone(wps_advertisement(b'\x00\x00\xff\xff'+b'\x00'*40,127))

    def test_probe_response_and_malformed_attribute(self):
        self.assertIsNotNone(wps_advertisement(b'\x50'+frame()[1:],105))
        broken = frame().replace(b'\x10\x57\x00\x01',b'\x10\x57\xff\xff')
        self.assertIsNone(wps_advertisement(broken,105))

    def test_both_pcap_byte_orders(self):
        with tempfile.TemporaryDirectory() as directory:
            for endian in ('<','>'):
                path=pathlib.Path(directory)/('little' if endian=='<' else 'big')
                path.write_bytes(pcap(frame(),endian))
                self.assertEqual(WpsObserver().update(path)[AP]['wps'], 'Available')

    def test_partial_record_resumes_and_new_lock_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            path=pathlib.Path(directory)/'capture.cap'
            data=pcap(frame())
            path.write_bytes(data[:-2])
            observer=WpsObserver()
            self.assertEqual(observer.update(path),{})
            with path.open('ab') as stream:
                stream.write(data[-2:])
            self.assertEqual(observer.update(path)[AP]['wps'], 'Available')
            self.assertEqual(observer.offset,len(data))
            with path.open('ab') as stream:
                stream.write(pcap(frame(1))[24:])
            self.assertEqual(observer.update(path)[AP]['wps'], 'Locked')

    def test_oversized_record_and_unknown_format_are_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            path=pathlib.Path(directory)/'capture.cap'
            path.write_bytes(pcap(frame())[:24]+struct.pack('<IIII',0,0,0xffffffff,0))
            self.assertEqual(WpsObserver().update(path),{})
            path.write_bytes(b'\x0a\x0d\x0d\x0a'+b'\x00'*24)
            self.assertEqual(WpsObserver().update(path),{})

if __name__ == '__main__':
    unittest.main()
