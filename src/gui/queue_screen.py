#  OneShot-Extended (WPS penetration testing utility) is a fork of the tool with extra features
#  Copyright (C) 2026 chkndrp
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.

"""Queue screen: enqueued targets, their state/progress, and the
Start/Stop controls for the Orchestrator's unattended auto-chain sweep.

refresh() must only ever be called from the main thread (see app.py's
threading-rule docstring) — it is the only place that turns the
Orchestrator's queue snapshot into View updates.

Start drives Orchestrator.run() in a loop (not a single call) so that a
target locked during one pass is automatically revisited once its
cooldown expires, per the design doc's "repeated-run() usage model" —
without this loop the user would have to manually re-press Start after
every cooldown window. The whole loop holds `radio_lock` for its
duration (there's only one radio/interface, shared with the PBC
screen), and Start is re-entrancy-guarded so a double-click can't launch
a second concurrent run() over the same SessionStore/interface.
"""

import threading

import termuxgui as tg

from src import presenters

DEFAULT_POLL_INTERVAL = 5.0


class QueueScreen:
    def __init__(self, activity, parent, orchestrator, radio_lock=None, poll_interval=DEFAULT_POLL_INTERVAL):
        self.activity = activity
        self.orchestrator = orchestrator
        self.radio_lock = radio_lock if radio_lock is not None else threading.Lock()
        self.poll_interval = poll_interval

        self.root = tg.LinearLayout(activity, parent)
        controls = tg.LinearLayout(activity, self.root, vertical=False)
        self.start_button = tg.Button(activity, "Start", controls)
        self.stop_button = tg.Button(activity, "Stop", controls)

        self.scroll = tg.NestedScrollView(activity, self.root)
        self.list_layout = tg.LinearLayout(activity, self.scroll)
        self._row_views = {}  # bssid -> TextView
        self._run_thread = None
        self._stop_requested = threading.Event()

    def on_click(self, view_id) -> bool:
        if view_id == self.start_button:
            self._start()
            return True
        if view_id == self.stop_button:
            self._stop_requested.set()
            self.orchestrator.stop()
            return True
        return False

    def _start(self) -> None:
        if self._run_thread is not None and self._run_thread.is_alive():
            return  # already running; ignore the double-click
        self._stop_requested.clear()
        self._run_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._run_thread.start()

    def _run_loop(self) -> None:
        with self.radio_lock:
            while not self._stop_requested.is_set():
                self.orchestrator.run()
                if self._stop_requested.is_set():
                    return
                self._stop_requested.wait(timeout=self.poll_interval)

    def refresh(self) -> None:
        for record in self.orchestrator.get_queue_snapshot():
            row = presenters.format_queue_row(record)
            text = f"{row['label']}: {row['status_text']}"
            if row['progress_percent'] is not None:
                text += f" ({row['progress_percent']}%)"

            existing = self._row_views.get(record.bssid)
            if existing is None:
                self._row_views[record.bssid] = tg.TextView(self.activity, text, self.list_layout)
            else:
                existing.settext(text)
