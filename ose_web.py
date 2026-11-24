#!/usr/bin/env python3
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

"""Web GUI entrypoint for OneShot-Extended. See README.md for setup
(`pip install -r requirements-web.txt`) and run as root, same as ose.py:

    sudo python ose_web.py
"""

import sys
import threading

import uvicorn

from src import logger
from src import setup as ose_setup
from src.errors import FatalError
from src.events import EventBus
from src.orchestrator import Orchestrator
from src.settings import Settings
from src.web.app import create_app
from src.web.queue_runner import QueueRunner
from src.wifi.scanner import WiFiScanner

DEFAULT_INTERFACE = "wlan0"
HOST = "127.0.0.1"
PORT = 8000


def main() -> None:
    try:
        _run()
    except FatalError as e:
        sys.exit(f'[!] {e} \n')


def _run() -> None:
    ose_setup.checkRequirements()
    ose_setup.setupDirectories()

    settings = Settings(interface=DEFAULT_INTERFACE)

    event_bus = EventBus()
    logger.set_event_bus(event_bus)

    orchestrator = Orchestrator(DEFAULT_INTERFACE, settings, event_bus=event_bus)
    radio_lock = threading.Lock()
    queue_runner = QueueRunner(orchestrator, radio_lock)
    scanner = WiFiScanner(DEFAULT_INTERFACE, settings=settings)

    app = create_app(DEFAULT_INTERFACE, settings, orchestrator, queue_runner, scanner, event_bus, radio_lock)

    print(f"Open http://{HOST}:{PORT} in your browser")
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == '__main__':
    main()
