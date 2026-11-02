import pathlib
import sys
import tempfile
import unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from core import capture_name, save_capture_session

class CaptureSaveTests(unittest.TestCase):
    def test_named_capture_and_metadata_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            source = root / 'session'
            source.mkdir()
            (source / 'capture-01.cap').write_bytes(b'capture bytes')
            (source / 'handshake.json').write_text('{}')
            destination, captures = save_capture_session(source, root / 'exports', 'MyRouter.cap')
            self.assertEqual(captures, [destination / 'MyRouter.cap'])
            self.assertEqual(captures[0].read_bytes(), b'capture bytes')
            self.assertTrue((destination / 'handshake.json').exists())
            with self.assertRaises(FileExistsError):
                save_capture_session(source, root / 'exports', 'MyRouter')
            self.assertEqual(captures[0].read_bytes(), b'capture bytes')
            self.assertTrue((source / 'capture-01.cap').exists())

    def test_names_cannot_escape_folder(self):
        for name in ('../secret', '/tmp/test', '', '..', 'test/a', 'x' * 81):
            with self.subTest(name=name), self.assertRaises(ValueError):
                capture_name(name)

    def test_multiple_capture_files_keep_unique_names(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            source = root / 'session'
            source.mkdir()
            for i in (1, 2):
                (source / f'capture-0{i}.cap').write_text(str(i))
            destination, captures = save_capture_session(source, root / 'exports', 'Router')
            self.assertEqual([p.name for p in captures], ['Router.cap', 'Router-2.cap'])
