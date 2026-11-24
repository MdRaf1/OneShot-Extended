import threading
import time
from types import SimpleNamespace

from src.events import Event, EventBus
from src.web import routes_events


def _wait_until(predicate, timeout=2.0, interval=0.01):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def test_generate_events_yields_formatted_log_lines_and_unsubscribes_on_close():
    bus = EventBus()
    gen = routes_events._generate_events(bus)  # pylint: disable=protected-access

    def emit_once_subscribed():
        assert _wait_until(lambda: len(bus._subscribers) == 1)  # pylint: disable=protected-access
        bus.emit(Event(kind="info", level="info", message="hello"))

    threading.Thread(target=emit_once_subscribed, daemon=True).start()

    line = next(gen)
    assert line == "data: [INFO] hello\n\n"
    assert len(bus._subscribers) == 1  # pylint: disable=protected-access

    gen.close()
    assert bus._subscribers == []  # pylint: disable=protected-access


def test_get_events_route_wires_the_app_state_event_bus(monkeypatch):
    bus = EventBus()
    fake_request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(event_bus=bus)))

    seen_args = []
    original = routes_events._generate_events  # pylint: disable=protected-access

    def spy(event_bus):
        seen_args.append(event_bus)
        return original(event_bus)

    monkeypatch.setattr(routes_events, "_generate_events", spy)

    response = routes_events.get_events(fake_request)

    assert response.media_type == "text/event-stream"
    assert seen_args == [bus]
