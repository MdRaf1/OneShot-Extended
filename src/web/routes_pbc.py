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

"""PBC (push-button) route: a manual, single-target action requiring a
human to physically press the router's WPS button — deliberately kept
separate from the Orchestrator's unattended queue (same rule the
now-deleted Termux:GUI PbcScreen followed).

Fixes a gap carried forward from Termux:GUI: the old pbc_screen.py never
caught FatalError around its connection_factory/singleConnection calls
at all, so a missing binary would vanish as an uncaught background
thread exception. run_pbc_once() now isolates FatalError exactly like
Orchestrator._run_bruteforce_for_target already does for the queue.
"""

import threading

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.errors import FatalError
from src.events import Event, EventBus
from src.settings import Settings

router = APIRouter()


class PbcRequest(BaseModel):
    bssid: str | None = None


def run_pbc_once(interface: str, settings: Settings, radio_lock: threading.Lock,
                  connection_factory, bssid: str | None, event_bus: EventBus) -> None:
    if not radio_lock.acquire(blocking=False):
        event_bus.emit(Event(kind='pbc_busy', level='warning', message='PBC: radio busy (queue is running)'))
        return

    try:
        connection_factory(interface, settings).singleConnection(bssid=bssid, pbc_mode=True)
    except FatalError as e:
        event_bus.emit(Event(kind='fatal_error', level='error', message=str(e)))
    finally:
        radio_lock.release()


@router.post("/api/pbc/start")
def post_pbc_start(body: PbcRequest, request: Request):
    radio_lock = request.app.state.radio_lock
    if radio_lock.locked():
        return JSONResponse(status_code=409, content={"detail": "radio busy (queue is running)"})

    thread = threading.Thread(
        target=run_pbc_once,
        args=(
            request.app.state.interface, request.app.state.settings, radio_lock,
            request.app.state.connection_factory, body.bssid, request.app.state.event_bus,
        ),
        daemon=True,
    )
    thread.start()

    return JSONResponse(status_code=202, content={"status": "started"})
