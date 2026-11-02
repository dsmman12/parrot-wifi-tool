"""Create real Tk widgets, exercise selection and shutdown; no radio operations."""
import pathlib
import sys
from unittest.mock import patch
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from app import App
with patch.object(App, 'refresh'):
    app = App()
    app.events.put(('devices', [{'name': 'wlxTEST', 'phy': 'phy#1', 'mac': '02:11:22:33:44:55', 'type': 'managed'}]))
    app.poll_events()
    assert app.adapter.get() == 'wlxTEST'
    item = app.tree.insert('', 'end', values=('Lab', '02:11:22:33:44:55', 6, 'WPA2', -40))
    app.tree.selection_set(item)
    app.select_network()
    assert app.bssid.get() == '02:11:22:33:44:55'
    assert app.channel.get() == '6'
    assert app.authorized.get() is False
    app.update_idletasks()
    app.destroy()
print('GUI smoke test passed')
