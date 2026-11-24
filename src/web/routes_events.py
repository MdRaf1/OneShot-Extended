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

"""SSE events route: streams every engine Event to the browser as it's
emitted. No backlog/replay — a (re)connecting client only sees events
from the moment it connects (see the design doc's own Decisions); the
Queue/Scan screens re-fetch their current state instead of relying on
this stream to carry it.

_generate_events is a plain generator, extracted so it's testable via
the generator protocol directly (next()/close()) — this environment's
TestClient fully drains a StreamingResponse's body before its `stream()`
context manager returns, so a never-terminating generator can't be
exercised through an actual HTTP round-trip in tests (confirmed by
direct experiment, not assumed).
"""

import queue
from typing import Iterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from src import presenters
from src.events import EventBus

router = APIRouter()


def _generate_events(event_bus: EventBus) -> Iterator[str]:
    event_queue: "queue.Queue" = queue.Queue()
    unsubscribe = event_bus.subscribe(event_queue.put)
    try:
        while True:
            event = event_queue.get()
            yield f"data: {presenters.format_log_line(event)}\n\n"
    finally:
        unsubscribe()


@router.get("/api/events")
def get_events(request: Request) -> StreamingResponse:
    return StreamingResponse(_generate_events(request.app.state.event_bus), media_type="text/event-stream")
