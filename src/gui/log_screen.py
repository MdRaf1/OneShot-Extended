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

"""Log screen: a scrollable, append-only pane of engine Events.

append() renders one Event via presenters.format_log_line and must only
ever be called from the main thread that owns `c.events()` (see
app.py's docstring on the threading rule) — never directly from an
EventBus subscriber callback, which can fire on a background
(orchestrator/PBC) thread.
"""

import termuxgui as tg

from src import presenters

MAX_LINES = 200


class LogScreen:
    def __init__(self, activity, parent):
        self.activity = activity
        self.scroll = tg.NestedScrollView(activity, parent)
        self.text_view = tg.TextView(activity, "", self.scroll)
        self._lines = []

    def append(self, event) -> None:
        self._lines.append(presenters.format_log_line(event))
        if len(self._lines) > MAX_LINES:
            self._lines = self._lines[-MAX_LINES:]
        self.text_view.settext("\n".join(self._lines))
