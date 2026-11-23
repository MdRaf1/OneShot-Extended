from src.events import Event, EventBus


def test_emit_calls_subscribers():
    bus = EventBus()
    seen = []
    bus.subscribe(lambda e: seen.append(e))
    bus.emit(Event(kind="x", level="info", message="hi"))
    assert seen[0].message == "hi"


def test_unsubscribe_stops_delivery():
    bus = EventBus()
    seen = []
    unsub = bus.subscribe(lambda e: seen.append(e))
    unsub()
    bus.emit(Event(kind="x", level="info", message="hi"))
    assert seen == []


def test_emit_survives_a_raising_subscriber():
    bus = EventBus()
    seen = []

    def raiser(_event):
        raise RuntimeError("bad")

    bus.subscribe(raiser)
    bus.subscribe(lambda e: seen.append(e))
    bus.emit(Event(kind="x", level="info", message="hi"))
    assert len(seen) == 1
