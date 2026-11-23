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
"""

import threading

import termuxgui as tg

from src.gui import presenters


class QueueScreen:
    def __init__(self, activity, parent, orchestrator):
        self.activity = activity
        self.orchestrator = orchestrator

        self.root = tg.LinearLayout(activity, parent)
        controls = tg.LinearLayout(activity, self.root, vertical=False)
        self.start_button = tg.Button(activity, "Start", controls)
        self.stop_button = tg.Button(activity, "Stop", controls)

        self.scroll = tg.NestedScrollView(activity, self.root)
        self.list_layout = tg.LinearLayout(activity, self.scroll)
        self._row_views = {}  # bssid -> TextView

    def on_click(self, view_id) -> bool:
        if view_id == self.start_button:
            self._start()
            return True
        if view_id == self.stop_button:
            self.orchestrator.stop()
            return True
        return False

    def _start(self) -> None:
        thread = threading.Thread(target=self.orchestrator.run, daemon=True)
        thread.start()

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
