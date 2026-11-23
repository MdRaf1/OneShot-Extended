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

"""Scan screen: runs an iw scan, lists WPS-capable networks with the
same stored/vulnerable/locked highlighting scanner.py's own CLI table
uses, and lets the operator pick which ones to add to the queue.

This screen's multi-select Checkbox list *is* the replacement for
WiFiScanner.promptNetwork()'s numbered-list input() — it calls
WiFiScanner._iwScanner() directly rather than that prompting method.
"""

import termuxgui as tg

from src.gui import presenters
from src.wifi.scanner import WiFiScanner


class ScanScreen:
    def __init__(self, activity, parent, interface, settings, orchestrator, vuln_list=None):
        self.activity = activity
        self.orchestrator = orchestrator
        self.scanner = WiFiScanner(interface, vuln_list=vuln_list, settings=settings)

        self.root = tg.SwipeRefreshLayout(activity, parent)
        inner = tg.LinearLayout(activity, self.root)
        self.scan_button = tg.Button(activity, "Scan", inner)
        self.enqueue_button = tg.Button(activity, "Add selected to queue", inner)
        self.scroll = tg.NestedScrollView(activity, inner)
        self.list_layout = tg.LinearLayout(activity, self.scroll)

        self._networks: dict[int, dict] = {}
        self._checkboxes: dict[int, "tg.Checkbox"] = {}
        self._checked: dict[int, bool] = {}

    def on_click(self, view_id) -> bool:
        if view_id == self.scan_button:
            self.scan()
            return True
        if view_id == self.enqueue_button:
            self.enqueue_selected()
            return True
        for index, checkbox in self._checkboxes.items():
            if view_id == checkbox:
                self._checked[index] = not self._checked.get(index, False)
                return True
        return False

    def on_refresh(self) -> None:
        self.scan()
        self.root.setrefreshing(False)

    def scan(self) -> None:
        networks = self.scanner._iwScanner()  # pylint: disable=protected-access
        self._render(networks or {})

    def _render(self, networks: dict) -> None:
        self.list_layout.deletechildren()
        self._networks = networks
        self._checkboxes = {}
        self._checked = {}

        for index, network in networks.items():
            network = dict(network)
            network['_stored'] = (network.get('BSSID'), network.get('ESSID')) in self.scanner.STORED
            network['_vulnerable_model'] = bool(self.scanner.VULN_LIST) and (
                f'{network.get("Model")} {network.get("Model number")}' in self.scanner.VULN_LIST
                or network.get('Device name') in self.scanner.VULN_LIST
            )
            row = presenters.format_network_row(network)

            item_row = tg.LinearLayout(self.activity, self.list_layout, vertical=False)
            checkbox = tg.Checkbox(self.activity, row['label'], item_row)
            self._checkboxes[index] = checkbox
            self._checked[index] = False

    def enqueue_selected(self) -> None:
        for index, checked in self._checked.items():
            if not checked:
                continue
            network = self._networks.get(index)
            if network is None:
                continue
            self.orchestrator.enqueue(network.get('BSSID'), network.get('ESSID'))
