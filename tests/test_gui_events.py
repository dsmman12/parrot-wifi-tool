"""Verify event floods yield to desktop input without dropping errors."""
import queue
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import App

class GuiEventTests(unittest.TestCase):
    def test_flood_yields_and_preserves_remaining_events(self):
        events = queue.Queue()
        for i in range(1000):
            events.put(('error', str(i)))
        seen, scheduled = [], []
        fake = SimpleNamespace(events=events, write=seen.append,
            after=lambda delay, callback: scheduled.append(delay), poll_events=lambda: None)
        with patch('app.time.monotonic', return_value=0):
            App.poll_events(fake)
        self.assertEqual(len(seen), 100)
        self.assertEqual(events.qsize(), 900)
        self.assertEqual(scheduled, [10])
        for _ in range(9):
            App.poll_events(fake)
        self.assertEqual(len(seen), 1000)
        self.assertEqual(scheduled[-1], 100)

    def test_time_budget_yields_before_count_limit(self):
        events = queue.Queue()
        events.put(('error', 'retained'))
        seen, scheduled = [], []
        fake = SimpleNamespace(events=events, write=seen.append,
            after=lambda delay, callback: scheduled.append(delay), poll_events=lambda: None)
        with patch('app.time.monotonic', side_effect=[0, .020]):
            App.poll_events(fake)
        self.assertEqual(seen, [])
        self.assertEqual(events.qsize(), 1)
        self.assertEqual(scheduled, [10])
