import contextlib
import fcntl
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import worker

class CleanupTests(unittest.TestCase):
    def setUp(self):
        worker.STOP.clear()

    def radio(self, action='capture', mode='monitor', stream_error=None, setup_error=None, stopped=False):
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            root=Path(folder)
            info={'name':'wlan0','phy':'phy#1','mac':'02:11:22:33:44:55','type':mode}
            def stream(*args, **kwargs):
                if stopped:
                    worker.STOP.set()
                if stream_error:
                    raise stream_error
            with patch.object(worker,'ROOT',root), patch.object(worker,'remember'), patch.object(worker,'device',return_value=info), patch.object(worker.threading,'Thread'), patch.object(worker,'unmanage') as unmanage, patch.object(worker,'set_mode',side_effect=setup_error) as set_mode, patch.object(worker,'command'), patch.object(worker,'survey_bands',return_value='bg'), patch.object(worker,'run_stream',side_effect=stream), patch.object(worker,'handoff_files') as handoff, patch.object(worker,'cleanup_radio') as cleanup:
                call=lambda: worker.radio_operation(action,{},'wlan0',info,1000,1000,None,root/'scope.json',5,None,None)
                if stream_error or setup_error:
                    with self.assertRaises(RuntimeError):
                        call()
                else:
                    call()
                return cleanup.call_count, handoff.call_count, set_mode.call_args_list, unmanage.call_count

    def test_capture_completion_restores_after_files_are_finalized(self):
        clean,handoff,_,_=self.radio()
        self.assertEqual((clean,handoff),(1,1))

    def test_tool_failure_still_restores_and_keeps_files(self):
        clean,handoff,_,_=self.radio(stream_error=RuntimeError('tool failed'))
        self.assertEqual((clean,handoff),(1,1))

    def test_failed_monitor_setup_still_restores(self):
        clean,handoff,_,_=self.radio(mode='managed',setup_error=RuntimeError('driver failed'))
        self.assertEqual((clean,handoff),(1,0))

    def test_new_test_reenters_monitor_mode_after_previous_restore(self):
        clean,_,calls,unmanage=self.radio(mode='managed')
        self.assertEqual(clean,1)
        self.assertEqual(calls[0].args,('wlan0','monitor'))
        self.assertEqual(unmanage,1)

    def test_completed_and_stopped_surveys_both_restore(self):
        self.assertEqual(self.radio(action='survey')[0],1)
        self.assertEqual(self.radio(action='survey',stopped=True)[0],1)

    def test_last_shared_worker_does_the_restoration(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'radio.lock'
            with path.open('a') as capture, path.open('a') as deauth, patch.object(worker,'restore') as restore, contextlib.redirect_stdout(io.StringIO()):
                fcntl.flock(capture,fcntl.LOCK_SH)
                fcntl.flock(deauth,fcntl.LOCK_SH)
                self.assertFalse(worker.cleanup_radio('wlan0',capture))
                restore.assert_not_called()
                self.assertTrue(worker.cleanup_radio('wlan0',deauth))
                restore.assert_called_once_with('wlan0')

    def test_verified_restore_applies_saved_mac_mode_link_and_manager(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            snapshot=root/'wlan0.json'
            state={'mac':'02:11:22:33:44:55','type':'managed','up':True,'nm':'yes'}
            snapshot.write_text(json.dumps(state))
            with patch.object(worker,'ROOT',root), patch.object(worker,'unmanage'), patch.object(worker,'command') as command, patch.object(worker,'device',return_value=state), patch.object(worker,'emit') as emit:
                worker.restore('wlan0')
                commands=[call.args[0] for call in command.call_args_list]
                self.assertIn(['iw','dev','wlan0','set','type','managed'],commands)
                self.assertIn(['ip','link','set','dev','wlan0','address',state['mac']],commands)
                self.assertIn(['ip','link','set','dev','wlan0','up'],commands)
                self.assertIn(['nmcli','device','set','wlan0','managed','yes'],commands)
                emit.assert_any_call('restored',interface='wlan0')
            self.assertFalse(snapshot.exists())

    def test_failed_restore_retains_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            snapshot=root/'wlan0.json'
            snapshot.write_text(json.dumps({'mac':'02:11:22:33:44:55','type':'managed','up':True,'nm':'yes'}))
            with patch.object(worker,'ROOT',root), patch.object(worker,'unmanage'), patch.object(worker,'command'), patch.object(worker,'device',return_value={'type':'monitor','mac':'02:11:22:33:44:55'}):
                with self.assertRaises(RuntimeError):
                    worker.restore('wlan0')
            self.assertTrue(snapshot.exists())

    def test_shared_workers_serialize_snapshot_and_monitor_setup(self):
        import threading
        import time
        with tempfile.TemporaryDirectory() as folder:
            active=0
            maximum=0
            guard=threading.Lock()
            def remember(_):
                nonlocal active,maximum
                with guard:
                    active+=1
                    maximum=max(maximum,active)
                time.sleep(0.03)
                with guard:
                    active-=1
            info={'phy':'phy#1','type':'monitor'}
            errors=[]
            def prepare():
                try:
                    worker.prepare_radio('wlan0',info)
                except Exception as exc:
                    errors.append(exc)
            with patch.object(worker,'ROOT',Path(folder)), patch.object(worker,'remember',side_effect=remember), patch.object(worker,'device',return_value=info):
                threads=[threading.Thread(target=prepare) for _ in range(2)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=3)
                    self.assertFalse(thread.is_alive())
            self.assertFalse(errors)
            self.assertEqual(maximum,1)

    def test_restore_with_nothing_pending_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(worker,'ROOT',Path(folder)), patch.object(worker,'emit') as emit:
            worker.restore('wlan0')
            self.assertIn(('restored',),[c.args for c in emit.call_args_list])

if __name__=='__main__':
    unittest.main()
