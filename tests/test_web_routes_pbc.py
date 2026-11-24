import threading
from types import SimpleNamespace

from fastapi.testclient import TestClient

from src.errors import FatalError
from src.events import EventBus
from src.web.app import create_app
from src.web.routes_pbc import run_pbc_once

FAKE_SETTINGS = SimpleNamespace()


class FakeConnection:
    def __init__(self):
        self.calls = []

    def singleConnection(self, bssid=None, pbc_mode=False):  # pylint: disable=invalid-name
        self.calls.append({"bssid": bssid, "pbc_mode": pbc_mode})


def test_run_pbc_once_emits_busy_event_when_lock_held():
    locked_lock = threading.Lock()
    locked_lock.acquire()  # pylint: disable=consider-using-with
    seen = []
    bus = EventBus()
    bus.subscribe(seen.append)

    run_pbc_once("wlan0", FAKE_SETTINGS, locked_lock, lambda i, s: FakeConnection(), None, bus)

    assert any(e.kind == "pbc_busy" for e in seen)


def test_run_pbc_once_calls_single_connection_with_bssid_and_pbc_mode():
    connection = FakeConnection()
    bus = EventBus()

    run_pbc_once("wlan0", FAKE_SETTINGS, threading.Lock(), lambda i, s: connection,
                 "AA:BB:CC:DD:EE:FF", bus)

    assert connection.calls == [{"bssid": "AA:BB:CC:DD:EE:FF", "pbc_mode": True}]


def test_run_pbc_once_releases_the_lock_after_running():
    lock = threading.Lock()
    bus = EventBus()

    run_pbc_once("wlan0", FAKE_SETTINGS, lock, lambda i, s: FakeConnection(), None, bus)

    assert lock.locked() is False


def test_run_pbc_once_emits_fatal_error_event_instead_of_raising():
    def raising_factory(interface, settings):  # pylint: disable=unused-argument
        raise FatalError("missing binary")

    seen = []
    bus = EventBus()
    bus.subscribe(seen.append)

    run_pbc_once("wlan0", FAKE_SETTINGS, threading.Lock(), raising_factory, None, bus)  # must not raise

    assert any(e.kind == "fatal_error" for e in seen)


def _make_app(radio_lock=None, connection_factory=None):
    return create_app(
        "wlan0", FAKE_SETTINGS, SimpleNamespace(), SimpleNamespace(),
        SimpleNamespace(), EventBus(), radio_lock or threading.Lock(),
        connection_factory=connection_factory or (lambda i, s: FakeConnection()),
    )


def test_post_pbc_start_returns_409_when_radio_locked():
    lock = threading.Lock()
    lock.acquire()  # pylint: disable=consider-using-with
    client = TestClient(_make_app(radio_lock=lock))

    response = client.post("/api/pbc/start", json={"bssid": None})

    assert response.status_code == 409
    assert response.json() == {"detail": "radio busy (queue is running)"}


def test_post_pbc_start_spawns_thread_when_lock_free():
    started = threading.Event()

    class SlowConnection(FakeConnection):
        def singleConnection(self, bssid=None, pbc_mode=False):  # pylint: disable=invalid-name
            super().singleConnection(bssid=bssid, pbc_mode=pbc_mode)
            started.set()

    client = TestClient(_make_app(connection_factory=lambda i, s: SlowConnection()))

    response = client.post("/api/pbc/start", json={"bssid": "AA:BB:CC:DD:EE:FF"})

    assert response.status_code == 202
    assert response.json() == {"status": "started"}
    assert started.wait(timeout=2)
