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

_generate_events is an async generator, not a plain (sync) one. A sync
generator's next() runs in an anyio threadpool worker, and a real client
disconnect is only ever noticed there once next() returns on its own —
confirmed empirically (tests/test_web_routes_events_live.py) that a sync
version blocked in queue.Queue.get(), even with a get()-timeout/heartbeat
added, never saw the disconnect at all: Starlette only learns about it
via request.is_disconnected() polling the ASGI receive channel, which an
async route can await directly between heartbeats; a sync generator
running inside a worker thread never gets to call it. Without that check,
every leaked connection permanently holds one of anyio's (default 40)
threadpool tokens, and once they're all held, every further sync route —
including a plain health check — hangs forever.

event_bus.subscribe's callback runs on whatever thread calls
EventBus.emit() (the orchestrator's worker thread, logger calls from the
main thread, etc.), never on this coroutine's own event loop thread, so it
can't push into an asyncio.Queue directly — asyncio.Queue isn't
thread-safe. loop.call_soon_threadsafe is the standard bridge: it marshals
the delivery onto the loop that's running this generator.

This environment's TestClient fully drains a StreamingResponse's body
before its `stream()` context manager returns, so a never-terminating
generator can't be exercised through an actual HTTP round-trip in tests
(confirmed by direct experiment, not assumed) — _generate_events stays a
standalone function so tests can drive it directly via the async
generator protocol (anext()/aclose()), and tests/test_web_routes_events_live.py
proves the real-disconnect behavior against a live uvicorn server instead.
"""

import asyncio
from typing import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from src import presenters
from src.events import EventBus

router = APIRouter()

_HEARTBEAT_SECONDS = 15.0


async def _generate_events(event_bus: EventBus, request: Request) -> AsyncIterator[str]:
    loop = asyncio.get_running_loop()
    event_queue: "asyncio.Queue" = asyncio.Queue()
    unsubscribe = event_bus.subscribe(lambda event: loop.call_soon_threadsafe(event_queue.put_nowait, event))
    try:
        while True:
            if await request.is_disconnected():
                return
            try:
                event = await asyncio.wait_for(event_queue.get(), timeout=_HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            yield f"data: {presenters.format_log_line(event)}\n\n"
    finally:
        unsubscribe()


@router.get("/api/events")
async def get_events(request: Request) -> StreamingResponse:
    return StreamingResponse(_generate_events(request.app.state.event_bus, request), media_type="text/event-stream")
