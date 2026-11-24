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

"""FastAPI app factory for OneShot-Extended's web GUI.

create_app() takes already-constructed engine objects as parameters
rather than constructing them itself, mirroring Orchestrator's own
dependency-injection pattern — so tests build an app around fakes
without root or real hardware, and ose_web.py is the one real wiring
point (mirrors ose.py's role for the CLI).

Route modules (added by later tasks) are thin wrappers reading their
dependencies off `request.app.state.*` by the names this module sets
here: settings, orchestrator, queue_runner, scanner, event_bus,
radio_lock, connection_factory, interface.
"""

import threading

from fastapi import FastAPI

import src.wps.connection as connection
from src.events import EventBus
from src.orchestrator import Orchestrator
from src.settings import Settings
from src.web import routes_events
from src.web import routes_queue
from src.web import routes_scan
from src.web.queue_runner import QueueRunner
from src.wifi.scanner import WiFiScanner


def create_app(
    interface: str,
    settings: Settings,
    orchestrator: Orchestrator,
    queue_runner: QueueRunner,
    scanner: WiFiScanner,
    event_bus: EventBus,
    radio_lock: threading.Lock,
    connection_factory=connection.Initialize,
) -> FastAPI:
    app = FastAPI()
    app.state.interface = interface
    app.state.settings = settings
    app.state.orchestrator = orchestrator
    app.state.queue_runner = queue_runner
    app.state.scanner = scanner
    app.state.event_bus = event_bus
    app.state.radio_lock = radio_lock
    app.state.connection_factory = connection_factory

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    app.include_router(routes_queue.router)
    app.include_router(routes_scan.router)
    app.include_router(routes_events.router)

    return app
