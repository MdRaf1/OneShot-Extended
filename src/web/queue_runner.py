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

"""QueueRunner: background run-loop controller for the Orchestrator's
unattended auto-chain sweep.

Framework-agnostic port of the (now-deleted) Termux:GUI QueueScreen's
threading logic, which never actually touched any GUI widget inside
its own run-loop code — only `threading` and the orchestrator — so this
is a mechanical move, not a rewrite.

start() drives Orchestrator.run() in a loop (not a single call) so that
a target locked during one pass is automatically revisited once its
cooldown expires, per the design doc's "repeated-run() usage model" —
without this loop the caller would have to manually re-invoke start()
after every cooldown window. The whole loop holds `radio_lock` for its
duration (there's only one radio/interface, shared with the PBC route),
and start() is re-entrancy-guarded so a second call can't launch a
second concurrent run() over the same SessionStore/interface.
"""

import threading

DEFAULT_POLL_INTERVAL = 5.0


class QueueRunner:
    def __init__(self, orchestrator, radio_lock=None, poll_interval=DEFAULT_POLL_INTERVAL):
        self.orchestrator = orchestrator
        self.radio_lock = radio_lock if radio_lock is not None else threading.Lock()
        self.poll_interval = poll_interval

        self._run_thread = None
        self._stop_requested = threading.Event()

    def start(self) -> None:
        if self._run_thread is not None and self._run_thread.is_alive():
            return  # already running; ignore the extra call
        self._stop_requested.clear()
        self._run_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._run_thread.start()

    def stop(self) -> None:
        self._stop_requested.set()
        self.orchestrator.stop()

    def is_running(self) -> bool:
        return self._run_thread is not None and self._run_thread.is_alive()

    def _run_loop(self) -> None:
        with self.radio_lock:
            while not self._stop_requested.is_set():
                self.orchestrator.run()
                if self._stop_requested.is_set():
                    return
                self._stop_requested.wait(timeout=self.poll_interval)
