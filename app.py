#!/usr/bin/python3
"""Parrot Wi-Fi Tool desktop GUI. Runs as the logged-in user, never root."""
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinter.scrolledtext import ScrolledText

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import VERSION, clean, handshake_status, interfaces, mac, number

BASE = Path(__file__).resolve().parent
TOOLS = ('iw', 'ip', 'nmcli', 'pkexec', 'airodump-ng', 'aireplay-ng', 'aircrack-ng', 'wash', 'reaver', 'pixiewps')

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f'Parrot Wi-Fi Tool {VERSION}')
        self.geometry('1160x830')
        self.minsize(940, 700)
        self.configure(background='#101827')
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('.', background='#172236', foreground='#e2e8f0', fieldbackground='#0d1625')
        style.configure('TButton', padding=(10, 7))
        style.map('TButton', background=[('active', '#275178')])
        style.configure('Treeview', background='#0d1625', fieldbackground='#0d1625', rowheight=26)
        style.configure('Treeview.Heading', background='#22334a', foreground='white')
        style.map('Treeview', background=[('selected', '#245c85')])
        self.events = queue.Queue()
        self.jobs = {}
        self.devices = []
        self.last_session = None
        self.last_caps = []
        self.pending_close = False
        self.adapter = tk.StringVar()
        self.status = tk.StringVar(value='Ready')
        self.bssid = tk.StringVar()
        self.channel = tk.StringVar(value='6')
        self.station = tk.StringVar()
        self.custom_mac = tk.StringVar()
        self.seconds = tk.StringVar(value='120')
        self.attempts = tk.StringVar(value='10')
        self.count = tk.StringVar(value='1')
        self.authorized = tk.BooleanVar(value=False)
        self.export_folder = tk.StringVar(value=str(Path.home() / 'WiFi-Captures'))
        self.build_ui()
        self.protocol('WM_DELETE_WINDOW', self.close_app)
        self.after(100, self.poll_events)
        self.refresh()

    def build_ui(self):
        header = ttk.Frame(self, padding=14)
        header.pack(fill='x')
        ttk.Label(header, text='PARROT / WI-FI LAB', font=('Sans', 21, 'bold')).pack(side='left')
        ttk.Label(header, text='Desktop network testing', font=('Sans', 11)).pack(side='right')
        top = ttk.LabelFrame(self, text='1  Adapter', padding=10)
        top.pack(fill='x', padx=14, pady=(0, 8))
        self.adapter_box = ttk.Combobox(top, textvariable=self.adapter, state='readonly', width=35)
        self.adapter_box.pack(side='left', padx=(0, 8))
        self.adapter_box.bind('<<ComboboxSelected>>', lambda _: self.adapter_info())
        ttk.Button(top, text='Refresh cards', command=self.refresh).pack(side='left')
        ttk.Button(top, text='Dependencies', command=self.dependencies).pack(side='left', padx=5)
        self.info_label = ttk.Label(top, text='')
        self.info_label.pack(side='right')
        tabs = ttk.Notebook(self)
        tabs.pack(fill='both', expand=True, padx=14)
        radio, capture, tests = [ttk.Frame(tabs, padding=12) for _ in range(3)]
        tabs.add(radio, text='Adapter controls')
        tabs.add(capture, text='Survey & capture')
        tabs.add(tests, text='Active tests & WPS')
        ttk.Label(radio, text='Use a dedicated USB adapter: monitor mode disconnects the selected card from normal Wi-Fi.', wraplength=900).pack(anchor='w', pady=8)
        modes = ttk.Frame(radio)
        modes.pack(fill='x', pady=10)
        for label, action in [('Enable monitor mode', 'monitor'), ('Managed mode', 'managed'), ('Restore adapter completely', 'restore')]:
            ttk.Button(modes, text=label, command=lambda a=action: self.adapter_action(a)).pack(side='left', padx=(0, 8))
        macbox = ttk.LabelFrame(radio, text='MAC address', padding=10)
        macbox.pack(fill='x', pady=10)
        ttk.Button(macbox, text='Random MAC', command=lambda: self.adapter_action('random')).pack(side='left', padx=(0, 8))
        ttk.Button(macbox, text='Restore saved MAC', command=lambda: self.adapter_action('restore-mac')).pack(side='left', padx=(0, 8))
        ttk.Entry(macbox, textvariable=self.custom_mac, width=20).pack(side='left', padx=8)
        ttk.Button(macbox, text='Apply custom MAC', command=lambda: self.adapter_action('custom')).pack(side='left')
        ttk.Label(radio, text='Original state is saved before the first change. Restore adapter returns to that state.\nMAC randomization changes the transmitted address; it does not provide anonymity.\nOnly the selected interface is unmanaged; global NetworkManager and other adapters are left alone.', wraplength=900).pack(anchor='w', pady=15)
        toolbar = ttk.Frame(capture)
        toolbar.pack(fill='x')
        ttk.Button(toolbar, text='Scan networks · 20 sec', command=lambda: self.start('survey', {'seconds': 20})).pack(side='left')
        ttk.Label(toolbar, text='Select a row to set the target below.').pack(side='left', padx=12)
        cols = ('ssid', 'bssid', 'channel', 'security', 'signal')
        self.tree = ttk.Treeview(capture, columns=cols, show='headings', height=6, selectmode='browse')
        for column, width in zip(cols, (240, 175, 70, 110, 70)):
            self.tree.heading(column, text=column.upper())
            self.tree.column(column, width=width)
        self.tree.pack(fill='both', expand=True, pady=10)
        self.tree.bind('<<TreeviewSelect>>', self.select_network)
        row = ttk.Frame(capture)
        row.pack(fill='x', pady=4)
        ttk.Label(row, text='Capture limit (seconds)').pack(side='left')
        ttk.Spinbox(row, from_=5, to=3600, textvariable=self.seconds, width=7).pack(side='left', padx=8)
        ttk.Button(row, text='Start targeted capture', command=self.capture).pack(side='left', padx=5)
        ttk.Button(row, text='Stop capture', command=lambda: self.stop('capture')).pack(side='left', padx=5)
        ttk.Button(row, text='Check handshake file…', command=self.check_file).pack(side='left', padx=5)
        row = ttk.Frame(capture)
        row.pack(fill='x', pady=6)
        ttk.Entry(row, textvariable=self.export_folder).pack(side='left', fill='x', expand=True)
        ttk.Button(row, text='Choose save folder…', command=self.choose_folder).pack(side='left', padx=5)
        ttk.Button(row, text='Save latest session', command=self.export_session).pack(side='left')
        ttk.Label(capture, text='Capture waits for a client to reconnect. Stop flushes capture files; export copies them to your chosen folder.\nHandshake checking recognizes Aircrack-ng output; it does not recover a password.', wraplength=950).pack(anchor='w', pady=4)
        ttk.Label(tests, text='Active tests can interrupt your selected network. Use only your own equipment or an explicitly authorized assessment.', wraplength=950).pack(anchor='w', pady=8)
        row = ttk.Frame(tests)
        row.pack(fill='x', pady=5)
        ttk.Label(row, text='Client MAC (directed deauth)').pack(side='left')
        ttk.Entry(row, textvariable=self.station, width=22).pack(side='left', padx=8)
        ttk.Label(row, text='Bursts').pack(side='left')
        ttk.Spinbox(row, from_=1, to=5, textvariable=self.count, width=4).pack(side='left', padx=8)
        ttk.Button(row, text='Directed deauth test', command=lambda: self.active('deauth')).pack(side='left')
        ttk.Button(tests, text='Injection test · selected AP', command=lambda: self.active('injection')).pack(anchor='w', pady=8)
        wps = ttk.LabelFrame(tests, text='WPS assessment', padding=10)
        wps.pack(fill='x', pady=10)
        ttk.Button(wps, text='WPS discovery · 20 sec', command=lambda: self.start('wash', {'seconds': 20})).pack(side='left', padx=(0, 8))
        ttk.Label(wps, text='PIN attempts').pack(side='left')
        ttk.Spinbox(wps, from_=1, to=100, textvariable=self.attempts, width=5).pack(side='left', padx=8)
        ttk.Button(wps, text='Bounded PIN test', command=lambda: self.active('wps')).pack(side='left', padx=5)
        ttk.Button(wps, text='Pixie Dust test', command=lambda: self.active('pixie')).pack(side='left', padx=5)
        ttk.Label(tests, text='WPS tests stop after 120 seconds or the attempt limit and stop on reported lock/rate limiting.\nNo result does not prove a router is secure. PMF may prevent deauthentication. WPA3 does not use the WPA2 offline handshake workflow.', wraplength=950).pack(anchor='w', pady=8)
        target = ttk.LabelFrame(self, text='2  Assessment target', padding=10)
        target.pack(fill='x', padx=14, pady=8)
        ttk.Label(target, text='AP BSSID').pack(side='left')
        ttk.Entry(target, textvariable=self.bssid, width=21).pack(side='left', padx=8)
        ttk.Label(target, text='Channel').pack(side='left')
        ttk.Spinbox(target, from_=1, to=233, textvariable=self.channel, width=5).pack(side='left', padx=8)
        ttk.Checkbutton(target, variable=self.authorized, text='I own / have permission to test this target').pack(side='left', padx=8)
        bar = ttk.Frame(self, padding=(14, 0, 14, 8))
        bar.pack(fill='x')
        ttk.Label(bar, textvariable=self.status).pack(side='left', fill='x', expand=True)
        ttk.Button(bar, text='STOP ALL', command=self.stop_all).pack(side='right')
        self.log = ScrolledText(self, height=10, bg='#080f1b', fg='#a6e3c1', insertbackground='white', font=('Monospace', 9), state='disabled')
        self.log.pack(fill='both', padx=14, pady=(0, 12))
        self.write('Ready. Refresh cards → enable monitor mode → scan → select target → capture. Administrator prompts come from pkexec.')

    def write(self, text):
        self.log.configure(state='normal')
        self.log.insert('end', text + '\n')
        if int(self.log.index('end-1c').split('.')[0]) > 1200:
            self.log.delete('1.0', '300.0')
        self.log.see('end')
        self.log.configure(state='disabled')

    def background(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    def refresh(self):
        if self.jobs:
            return
        def work():
            try:
                p = subprocess.run(['iw', 'dev'], capture_output=True, text=True, timeout=10)
                if p.returncode:
                    raise RuntimeError(p.stderr.strip() or 'iw dev failed')
                self.events.put(('devices', interfaces(p.stdout)))
            except Exception as exc:
                self.events.put(('error', str(exc)))
        self.background(work)

    def adapter_info(self):
        item = next((d for d in self.devices if d['name'] == self.adapter.get()), None)
        if item:
            name = item['name']
            driver_link = Path('/sys/class/net') / name / 'device/driver'
            driver = driver_link.resolve().name if driver_link.exists() else 'unknown driver'
            self.info_label.configure(text=f"{item['type']} · {item['mac']} · {driver}")

    def dependencies(self):
        lines = [f'{tool}: {shutil.which(tool) or "MISSING"}' for tool in TOOLS]
        messagebox.showinfo('Dependencies', '\n'.join(lines) + '\n\nInstall missing dependencies using install.sh.')

    def target_data(self):
        if not self.authorized.get():
            raise ValueError('Confirm that you own or have permission to test the selected target.')
        return {'bssid': mac(self.bssid.get()), 'channel': number(self.channel.get(), 1, 233), 'authorized': True}

    def adapter_action(self, action):
        data = {}
        if action == 'custom':
            try:
                data['mac'] = mac(self.custom_mac.get())
            except ValueError as exc:
                messagebox.showerror('MAC address', str(exc))
                return
        if action in ('monitor', 'managed', 'random', 'custom', 'restore-mac'):
            if not messagebox.askokcancel('Adapter change', f'Change {self.adapter.get()}? This may disconnect this adapter. Other interfaces will not be stopped.'):
                return
        self.start(action, data)

    def select_network(self, _=None):
        selected = self.tree.selection()
        if selected:
            values = self.tree.item(selected[0], 'values')
            self.bssid.set(values[1])
            self.channel.set(values[2])
            self.authorized.set(False)

    def capture(self):
        try:
            data = self.target_data()
            data['seconds'] = number(self.seconds.get(), 5, 3600)
            self.start('capture', data)
        except ValueError as exc:
            messagebox.showerror('Capture', str(exc))

    def active(self, action):
        try:
            data = self.target_data()
            data['seconds'] = 120 if action in ('wps', 'pixie') else 25
            if action == 'deauth':
                data.update(station=mac(self.station.get()), count=number(self.count.get(), 1, 5))
            if action == 'wps':
                data['attempts'] = number(self.attempts.get(), 1, 100)
            if messagebox.askokcancel('Confirm active test', f"Run {action} against {data['bssid']} on channel {data['channel']}?\nThis can interrupt clients or trigger a router WPS lockout."):
                self.start(action, data)
        except ValueError as exc:
            messagebox.showerror('Test target', str(exc))

    def start(self, action, data):
        if self.pending_close:
            return
        name = self.adapter.get()
        if not name:
            messagebox.showerror('Adapter', 'Select an adapter first.')
            return
        # Only directed deauth may coexist with an active capture, same scope.
        if self.jobs:
            cap = self.jobs.get('capture')
            allowed = action == 'deauth' and cap and len(self.jobs) == 1 and all(data.get(k) == cap['data'].get(k) for k in ('bssid', 'channel')) and name == cap['data']['interface']
            if not allowed:
                messagebox.showinfo('Operation running', 'Stop the current operation first. Only a directed deauth test on the captured target can run alongside capture.')
                return
        missing = [t for t in ('pkexec',) if not shutil.which(t)]
        required = {'survey': 'airodump-ng', 'capture': 'airodump-ng', 'deauth': 'aireplay-ng', 'injection': 'aireplay-ng', 'wash': 'wash', 'wps': 'reaver', 'pixie': 'reaver'}.get(action)
        if required and not shutil.which(required):
            missing.append(required)
        if action == 'pixie' and not shutil.which('pixiewps'):
            missing.append('pixiewps')
        if missing:
            messagebox.showerror('Missing dependencies', ', '.join(missing) + '\nRun install.sh.')
            return
        data = {**data, 'interface': name}
        self.jobs[action] = {'process': None, 'cancel': False, 'data': data}
        self.adapter_box.configure(state='disabled')
        self.status.set('Running: ' + ', '.join(self.jobs))
        self.write(f'[{action}] Requesting administrator authorization…')
        def work():
            try:
                args = ['pkexec', '/usr/bin/python3', '-I', str(BASE / 'worker.py'), action, json.dumps(data)]
                p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
                # Send process handle through queue; all Tk state stays on the UI thread.
                self.events.put(('process', (action, p)))
                for line in p.stdout:
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        event = {'event': 'log', 'text': clean(line).strip()}
                    self.events.put(('worker', (action, event)))
                p.stdout.close()
                code = p.wait()
                self.events.put(('finished', (action, code)))
            except Exception as exc:
                self.events.put(('error', str(exc)))
                self.events.put(('finished', (action, 1)))
        self.background(work)

    def stop(self, action):
        job = self.jobs.get(action)
        if job:
            job['cancel'] = True
            p = job['process']
            if p and p.stdin and not p.stdin.closed:
                p.stdin.close()
            self.write(f'[{action}] Stop requested; waiting for process cleanup.')

    def stop_all(self):
        for action in list(self.jobs):
            self.stop(action)

    def poll_events(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == 'devices':
                    self.devices = data
                    self.adapter_box.configure(values=[d['name'] for d in data])
                    if self.adapter.get() not in [d['name'] for d in data]:
                        preferred = next((d['name'] for d in data if d['name'].startswith('wlx')), data[0]['name'] if data else '')
                        self.adapter.set(preferred)
                    self.adapter_info()
                    if not data:
                        self.write('No wireless interfaces found. Check USB connection and driver.')
                elif kind == 'error':
                    self.write('ERROR: ' + data)
                elif kind == 'process':
                    action, p = data
                    job = self.jobs.get(action)
                    if job:
                        job['process'] = p
                        if job['cancel'] and p.stdin and not p.stdin.closed:
                            p.stdin.close()
                elif kind == 'worker':
                    action, event = data
                    event_type = event.get('event')
                    if event_type in ('log', 'error'):
                        self.write(f'[{action}] ' + event.get('text', ''))
                    elif event_type == 'session':
                        # Do not replace latest completed session until files are finalized.
                        self.write('Session: ' + event['path'])
                    elif event_type == 'files':
                        paths = [Path(p) for p in event['paths']]
                        if paths:
                            self.last_session = paths[0].parent
                            self.last_caps = [p for p in paths if p.suffix == '.cap']
                            self.write('Files ready. Use Save latest session to export.')
                    elif event_type == 'networks':
                        self.tree.delete(*self.tree.get_children())
                        for item in event['items']:
                            self.tree.insert('', 'end', values=[item[k] for k in ('ssid', 'bssid', 'channel', 'security', 'signal')])
                        self.write(f"Survey found {len(event['items'])} access points.")
                elif kind == 'finished':
                    action, code = data
                    job = self.jobs.pop(action, None)
                    if job and job['process'] and job['process'].stdin and not job['process'].stdin.closed:
                        job['process'].stdin.close()
                    self.write(f'[{action}] Finished (exit {code}).' + (' Authorization cancelled or denied.' if code in (126, 127) else ''))
                    self.status.set('Running: ' + ', '.join(self.jobs) if self.jobs else 'Ready')
                    if not self.jobs:
                        self.adapter_box.configure(state='readonly')
                        self.refresh()
                    if self.pending_close and not self.jobs:
                        self.destroy()
                        return
                elif kind == 'analysis':
                    self.write(data)
                    messagebox.showinfo('Handshake check', data)
        except queue.Empty:
            pass
        self.after(100, self.poll_events)

    def choose_folder(self):
        path = filedialog.askdirectory(title='Choose where to save captures')
        if path:
            self.export_folder.set(path)

    def export_session(self):
        if not self.last_session:
            messagebox.showinfo('Save captures', 'Complete or stop an operation first.')
            return
        try:
            destination = Path(self.export_folder.get()).expanduser() / self.last_session.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(self.last_session, destination, dirs_exist_ok=False)
            self.write(f'Saved session to {destination}')
            messagebox.showinfo('Saved', str(destination))
        except Exception as exc:
            messagebox.showerror('Save failed', str(exc))

    def check_file(self):
        filename = filedialog.askopenfilename(title='Select a capture file', filetypes=[('Packet captures', '*.cap *.pcap *.pcapng'), ('All files', '*')], initialdir=str(self.last_session or Path.home()))
        if not filename:
            return
        try:
            bssid = mac(self.bssid.get())
        except ValueError as exc:
            messagebox.showerror('Select target', str(exc))
            return
        if not shutil.which('aircrack-ng'):
            messagebox.showerror('Missing dependency', 'Install aircrack-ng.')
            return
        def work():
            try:
                p = subprocess.run(['aircrack-ng', '-a', '2', '-b', bssid, '-w', '/dev/null', filename], capture_output=True, text=True, timeout=30)
                output = clean(p.stdout + '\n' + p.stderr)
                self.events.put(('analysis', handshake_status(output) + '\n\n' + output[-3500:]))
            except Exception as exc:
                self.events.put(('error', str(exc)))
        self.background(work)

    def close_app(self):
        if self.jobs:
            if not messagebox.askokcancel('Stop before exit', 'Stop all operations and close? Adapter settings remain as shown. Use Restore adapter before exit to restore its saved state.'):
                return
            self.pending_close = True
            self.stop_all()
        else:
            self.destroy()

if __name__ == '__main__':
    if os.geteuid() == 0:
        print('Launch as your regular desktop user, without sudo.')
        sys.exit(1)
    App().mainloop()
