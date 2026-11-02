"""Exercise actual Tk widgets and WPS offers without any radio operations."""
import pathlib
import sys
from unittest.mock import patch
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from app import App
with patch.object(App, 'refresh'):
    app = App()
    app.events.put(('devices', [{'name':'wlxTEST','phy':'phy#1','mac':'02:11:22:33:44:55','type':'monitor'}]))
    app.poll_events()
    assert app.adapter.get() == 'wlxTEST'
    item = {'ssid':'Lab','bssid':'02:11:22:33:44:55','channel':6,'security':'WPA2','signal':-40,'wps':'Available','wps_detected':True,'wps_locked':False}
    app.update_networks([item])
    app.tree.selection_set(item['bssid'])
    app.select_network()
    assert app.tabs.select() == str(app.target_capture_tab)
    assert 'Selected Lab' in app.capture_notice.get()
    assert app.bssid.get() == item['bssid']
    assert app.channel.get() == '6'
    assert app.authorized.get() is False
    assert str(app.wps_pin_offer['state']) == 'normal'
    app.authorized.set(True)
    app.update_networks([{**item,'signal':-35}])
    app.select_network()
    assert app.authorized.get() is True  # Live refresh keeps an unchanged target.
    app.jobs['survey'] = {'process':None,'data':{},'cancel':False}
    app.update_wps_offer()
    assert str(app.wps_pin_offer['state']) == 'disabled'
    assert 'finish the scan' in app.wps_notice.get()
    with patch.object(app, 'stop') as stop:
        app.select_network()
        stop.assert_called_once_with('survey')
        assert app.tabs.select() == str(app.target_capture_tab)
    app.jobs.clear()
    app.update_networks([{**item,'wps':'Locked','wps_locked':True}])
    assert str(app.wps_pin_offer['state']) == 'disabled'
    with patch('app.messagebox.showerror') as error, patch.object(app,'start') as start:
        app.active('wps')
        start.assert_not_called()
        error.assert_called_once()
    app.update_networks([{**item,'wps':'Unknown','wps_detected':False,'wps_locked':None}])
    assert str(app.wps_pixie_offer['state']) == 'disabled'
    # A start click during survey/restore is retained and runs only after recovery.
    app.authorized.set(True)
    app.jobs={'survey':{'process':None,'cancel':False,'data':{'interface':'wlxTEST'}}}
    with patch.object(app,'start') as start, patch.object(app,'stop') as stop:
        app.capture()
        start.assert_not_called()
        stop.assert_called_once_with('survey')
        assert app.pending_capture['interface']=='wlxTEST'
        assert 'queued' in app.capture_notice.get()
    app.jobs.clear()
    app.cleanup_requested=True
    app.cleanup_failed=False
    app.dirty_adapters.clear()
    with patch.object(app,'start',return_value=True) as start:
        app.advance_cleanup()
        assert start.call_args.args[0]=='capture'
        assert start.call_args.args[1]['bssid']==item['bssid']
        assert app.pending_capture is None
    # Stop All cancels queued work, even while recovery is still running.
    app.pending_capture={'interface':'wlxTEST'}
    with patch.object(app,'request_cleanup'):
        app.stop_all()
        assert app.pending_capture is None
    # Start confirms permission in place, instead of requiring a separate checkbox.
    app.authorized.set(False)
    with patch('app.messagebox.askokcancel',return_value=True) as confirm, patch.object(app,'start',return_value=True) as start:
        app.capture()
        confirm.assert_called_once()
        assert app.authorized.get()
        assert start.call_args.args[0]=='capture'
    app.authorized.set(False)
    with patch('app.messagebox.askokcancel',return_value=False), patch.object(app,'start') as start:
        app.capture()
        start.assert_not_called()
    app.authorized.set(True)
    # A manually requested restore must also release a queued capture.
    app.jobs={'restore':{'process':None,'cancel':False,'data':{'interface':'wlxTEST'}}}
    app.cleanup_requested=False
    with patch.object(app,'start',return_value=True) as start:
        app.capture()
        start.assert_not_called()
        app.finish_job('restore',0)
        assert start.call_args.args[0]=='capture'
        assert app.pending_capture is None
    # Targeted scan shows clients; selected-client and whole-AP actions stay
    # beside the live capture, and deauth completion does not end capture.
    app.pending_close=False
    app.cleanup_requested=False
    app.bssid.set(item['bssid'])
    app.channel.set('6')
    app.authorized.set(True)
    app.handshake_found=False
    app.jobs={'capture':{'process':None,'cancel':False,'data':{'interface':'wlxTEST','bssid':item['bssid'],'channel':6}}}
    app.update_clients([{'mac':'02:11:22:33:44:66','signal':'-40','packets':'15'}])
    assert str(app.broadcast_button['state'])=='normal'
    assert str(app.reconnect_button['state'])=='disabled'
    app.client_tree.selection_set('02:11:22:33:44:66')
    app.select_client()
    assert str(app.reconnect_button['state'])=='normal'
    with patch('app.messagebox.askokcancel',return_value=True),patch.object(app,'start') as start:
        app.active('deauth',whole_network=True)
        assert start.call_args.args[1]['whole_network'] is True
        assert 'station' not in start.call_args.args[1]
        app.active('deauth')
        assert start.call_args.args[1]['station']=='02:11:22:33:44:66'
    app.jobs['deauth']={'process':None,'cancel':False,'data':{'interface':'wlxTEST'},'related_capture':True}
    with patch.object(app,'start') as start:
        app.finish_job('deauth',0)
        start.assert_not_called()
        assert 'capture' in app.jobs
        assert 'Still capturing' in app.capture_notice.get()
    app.last_session=pathlib.Path('/capture/session')
    app.jobs['deauth']={'process':None,'cancel':False,'data':{'interface':'wlxTEST'},'related_capture':True}
    app.events.put(('worker',('deauth',{'event':'files','paths':['/deauth/session/output.log']})))
    app.events.put(('worker',('capture',{'event':'handshake','bssid':item['bssid']})))
    app.poll_events()
    assert app.last_session==pathlib.Path('/capture/session')
    assert app.handshake_found
    assert str(app.broadcast_button['state'])=='disabled'
    app.jobs.clear()
    # Closing waits for BOTH overlapping workers, then for verified restoration.
    def fake_start(action,data,cleanup=False):
        app.jobs[action]={'process':None,'cancel':False,'data':data,'cleanup':cleanup}
        return True
    app.dirty_adapters={'wlxTEST'}
    app.jobs={a:{'process':None,'cancel':False,'data':{'interface':'wlxTEST'}} for a in ('capture','deauth')}
    with patch.object(app,'start',side_effect=fake_start) as start, patch.object(app,'destroy') as destroy, patch('app.messagebox.askokcancel',return_value=True):
        app.close_app()
        app.finish_job('deauth',0)
        start.assert_not_called()
        destroy.assert_not_called()
        app.finish_job('capture',0)
        start.assert_called_once_with('restore',{'interface':'wlxTEST'},cleanup=True)
        destroy.assert_not_called()
        app.events.put(('worker',('restore',{'event':'restored','interface':'wlxTEST'})))
        app.events.put(('finished',('restore',0)))
        app.poll_events()
        assert not app.dirty_adapters
        destroy.assert_called_once()
    # Denied restoration keeps the app open and the dirty adapter available for retry.
    app.pending_close=False
    app.dirty_adapters={'wlanOther'}
    with patch.object(app,'start',side_effect=fake_start), patch.object(app,'destroy') as destroy, patch('app.messagebox.showerror') as error:
        app.close_app()
        app.finish_job('restore',127)
        destroy.assert_not_called()
        error.assert_called_once()
        assert app.pending_close is False
        assert app.dirty_adapters=={'wlanOther'}
        assert app.cleanup_requested is False
    app.dirty_adapters.clear()
    app.update_idletasks()
    app.destroy()
print('GUI, WPS offer and automatic-restoration smoke tests passed')
