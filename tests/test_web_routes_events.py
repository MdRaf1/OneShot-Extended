import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

from src.events import Event, EventBus
from src.web import routes_events


def _wait_until(predicate, timeout=2.0, interval=0.01):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class _FakeRequest:
    """Minimal stand-in for a Starlette Request: just the one awaitable
    method _generate_events actually calls."""

    def __init__(self, disconnected=False):
        self._disconnected = disconnected

    async def is_disconnected(self) -> bool:
        return self._disconnected


def test_generate_events_yields_formatted_log_lines():
    async def run():
        bus = EventBus()
        gen = routes_events._generate_events(bus, _FakeRequest())  # pylint: disable=protected-access

        def emit_once_subscribed():
            assert _wait_until(lambda: len(bus._subscribers) == 1)  # pylint: disable=protected-access
            bus.emit(Event(kind="info", level="info", message="hello"))

        threading.Thread(target=emit_once_subscribed, daemon=True).start()

        line = await gen.__anext__()
        assert line == "data: [INFO] hello\n\n"
        assert len(bus._subscribers) == 1  # pylint: disable=protected-access

        await gen.aclose()
        assert bus._subscribers == []  # pylint: disable=protected-access

    asyncio.run(run())


def test_generate_events_unsubscribes_and_stops_once_request_is_disconnected():
    async def run():
        bus = EventBus()
        gen = routes_events._generate_events(bus, _FakeRequest(disconnected=True))  # pylint: disable=protected-access

        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()

        assert bus._subscribers == []  # pylint: disable=protected-access

    asyncio.run(run())


def test_get_events_route_wires_the_app_state_event_bus():
    async def run():
        bus = EventBus()
        fake_request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(event_bus=bus)))

        seen_args = []
        original = routes_events._generate_events  # pylint: disable=protected-access

        def spy(event_bus, request):
            seen_args.append((event_bus, request))
            return original(event_bus, request)

        routes_events._generate_events = spy  # pylint: disable=protected-access
        try:
            response = await routes_events.get_events(fake_request)
        finally:
            routes_events._generate_events = original  # pylint: disable=protected-access

        assert response.media_type == "text/event-stream"
        assert seen_args == [(bus, fake_request)]

    asyncio.run(run())
