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

"""PBC (push-button) screen: a manual, single-target action requiring a
human to physically press the router's WPS button — deliberately kept
separate from the Orchestrator's unattended queue (see the approved
design doc's "Decisions made with the user" section).

Runs on its own background thread via the shared radio_lock, mutually
exclusive with the Orchestrator's queue run (there's only one radio).
Never routed through the Orchestrator and never constructs a
GuiPrompter (see gui/prompter.py's module docstring): PBC needs no pin
resolution at all.
"""

import threading

import termuxgui as tg

from src.wps.connection import Initialize as ConnectionInitialize


class PbcScreen:
    def __init__(self, activity, parent, interface, settings, radio_lock, on_log=None):
        self.activity = activity
        self.interface = interface
        self.settings = settings
        self.radio_lock = radio_lock
        self.on_log = on_log or (lambda message: None)

        self.root = tg.LinearLayout(activity, parent)
        self.bssid_input = tg.EditText(activity, "", self.root)
        self.start_button = tg.Button(activity, "Start PBC", self.root)
        self.status_view = tg.TextView(activity, "Idle", self.root)

    def on_click(self, view_id) -> bool:
        if view_id == self.start_button:
            self._start()
            return True
        return False

    def _start(self) -> None:
        bssid = (self.bssid_input.gettext() or "").strip() or None
        thread = threading.Thread(target=self._run_pbc, args=(bssid,), daemon=True)
        thread.start()

    def _run_pbc(self, bssid) -> None:
        if not self.radio_lock.acquire(blocking=False):
            self.on_log("PBC: radio busy (queue is running) — stop the queue and try again")
            return
        try:
            connection = ConnectionInitialize(self.interface, self.settings)
            connection.singleConnection(bssid=bssid, pbc_mode=True)
        finally:
            self.radio_lock.release()
