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
    app.jobs.clear()
    app.update_networks([{**item,'wps':'Locked','wps_locked':True}])
    assert str(app.wps_pin_offer['state']) == 'disabled'
    with patch('app.messagebox.showerror') as error, patch.object(app,'start') as start:
        app.active('wps')
        start.assert_not_called()
        error.assert_called_once()
    app.update_networks([{**item,'wps':'Unknown','wps_detected':False,'wps_locked':None}])
    assert str(app.wps_pixie_offer['state']) == 'disabled'
    app.update_idletasks()
    app.destroy()
print('GUI and WPS offer smoke tests passed')
