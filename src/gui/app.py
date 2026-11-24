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

"""Termux:GUI application entrypoint.

Only this module's import *structure* is tested here
(tests/test_gui_app_import.py, by stubbing the termuxgui module) — there
is no Termux:GUI plugin and no Android device in the implementation
environment to run this against for real. See README.md's GUI section
for the required on-device follow-up verification (real rendering/
event delivery/dialogs/notifications; a live scan/queue/PBC run;
backgrounding during a long queue run; a kill -9 crash-safety check).

Threading rule: the main thread owns the event loop (`for ev in
c.events()`) and is the only thread that ever touches View objects.
The Orchestrator's run() and the PBC flow each run on their own
background thread, mutually exclusive via a shared threading.Lock
(there's only one radio/interface). Engine Events (from the EventBus)
are pushed onto a thread-safe queue.Queue by a subscriber callback that
may fire on a background thread; the main loop drains that queue
between GUI events and is the only place that turns those into View
updates (log_screen.append, queue_screen.refresh).
"""

import os
import queue
import stat
import sys
import tempfile
import threading
from shutil import which

import termuxgui as tg

from src import logger
from src import setup as ose_setup
from src.errors import FatalError
from src.events import EventBus
from src.gui.log_screen import LogScreen
from src.gui.pbc_screen import PbcScreen
from src.gui.queue_screen import QueueScreen
from src.gui.scan_screen import ScanScreen
from src.orchestrator import Orchestrator
from src.settings import Settings

DEFAULT_INTERFACE = "wlan0"

# Android always provides a system shell here, regardless of which (if
# any) Termux package provides `am`/`termux-am` — used only as the
# shim's shebang, never to invoke am itself.
_TERMUX_SH = "/system/bin/sh"


def main() -> None:
    """Entrypoint: run _run(), converting any FatalError raised during
    setup (missing root, missing binary, missing termux-am, ...) into a
    clean exit instead of a raw traceback — mirrors ose.py's own
    main()/_run() split."""

    try:
        _run()
    except FatalError as e:
        sys.exit(f'[!] {e} \n')


def _ensure_termux_am_available(which_fn=which) -> None:
    """termuxgui's Connection() hardcodes the literal command name
    "termux-am" with no fallback for it being entirely absent (only for
    it timing out, which it then retries via plain `am`). Confirmed
    on-device: a Termux package can be literally named `termux-am`
    (0.8.0-2) yet install its own binary as plain `am`, not `termux-am` —
    and the newer `termux-am-socket` package (which does provide a real
    `termux-am` wrapper) isn't published on every mirror yet.

    Rather than patch the third-party termuxgui package or depend on one
    specific Termux package existing, this drops a one-line shim exec'ing
    `am` into a scratch directory prepended to PATH, so termuxgui's
    hardcoded subprocess call resolves regardless of which of the two
    binaries Termux happens to provide. No-op if termux-am is already on
    PATH; raises FatalError only if neither exists at all.
    """

    if which_fn('termux-am') is not None:
        return

    if which_fn('am') is None:
        raise FatalError(
            "Neither termux-am nor am were found on PATH — install a Termux "
            "package that provides one of them, e.g. 'pkg install -y "
            "termux-am' or 'pkg install -y termux-am-socket' (the termuxgui "
            "package needs one to reach the Termux:GUI plugin app)"
        )

    shim_dir = tempfile.mkdtemp(prefix='ose-gui-termux-am-shim-')
    shim_path = os.path.join(shim_dir, 'termux-am')
    with open(shim_path, 'w', encoding='utf-8') as f:
        f.write(f'#!{_TERMUX_SH}\nexec am "$@"\n')
    mode = os.stat(shim_path).st_mode
    os.chmod(shim_path, mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    os.environ['PATH'] = shim_dir + os.pathsep + os.environ.get('PATH', '')


def _run() -> None:
    ose_setup.checkRequirements()
    ose_setup.setupDirectories()

    _ensure_termux_am_available()

    settings = Settings(interface=DEFAULT_INTERFACE)

    event_bus = EventBus()
    logger.set_event_bus(event_bus)
    event_queue: "queue.Queue" = queue.Queue()
    event_bus.subscribe(event_queue.put)

    orchestrator = Orchestrator(DEFAULT_INTERFACE, settings, event_bus=event_bus)
    radio_lock = threading.Lock()

    with tg.Connection() as connection:
        activity = tg.Activity(connection)
        root = tg.LinearLayout(activity)
        tabs = tg.TabLayout(activity, root)
        tabs.setlist(["Scan", "Queue", "Log", "PBC"])

        pages = tg.LinearLayout(activity, root)

        scan_screen = ScanScreen(activity, pages, DEFAULT_INTERFACE, settings, orchestrator)
        queue_screen = QueueScreen(activity, pages, orchestrator, radio_lock=radio_lock)
        log_screen = LogScreen(activity, pages)
        pbc_screen = PbcScreen(
            activity, pages, DEFAULT_INTERFACE, settings, radio_lock,
            on_log=logger.warning,
        )

        screens = (scan_screen, queue_screen, log_screen, pbc_screen)

        def drain_event_queue() -> None:
            while True:
                try:
                    event = event_queue.get_nowait()
                except queue.Empty:
                    break
                log_screen.append(event)
                queue_screen.refresh()

        for ev in connection.events():
            if ev.type == tg.Event.destroy:
                break

            if ev.type == tg.Event.click:
                view_id = ev.value.get("id")
                for screen in screens:
                    on_click = getattr(screen, "on_click", None)
                    if on_click is not None and on_click(view_id):
                        break

            if ev.type == tg.Event.refresh:
                on_refresh = getattr(scan_screen, "on_refresh", None)
                if on_refresh is not None:
                    on_refresh()

            drain_event_queue()
