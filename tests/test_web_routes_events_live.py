"""Regression tests for the SSE route's real-disconnect behavior.

tests/test_web_routes_events.py proves _generate_events's generator
protocol (yields formatted lines, unsubscribes on .close()) but a real
client disconnect never reaches a generator suspended at its `yield` —
it abandons a generator blocked inside `event_queue.get()`, which never
raises GeneratorExit and never runs the `finally: unsubscribe()`. These
tests drive the route through a real uvicorn server and a real socket
disconnect to prove the actual failure mode and its fix.
"""

import socket
import threading
import time
from types import SimpleNamespace

import uvicorn

from src.events import EventBus
from src.web import routes_events
from src.web.app import create_app


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _LiveServer:
    def __init__(self, app, port):
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
        self.server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self):
        self._thread.start()
        deadline = time.monotonic() + 5.0
        while not self.server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert self.server.started, "uvicorn server did not start in time"

    def stop(self):
        self.server.should_exit = True
        self._thread.join(timeout=5.0)


def _make_live_app(event_bus):
    return create_app(
        "wlan0",
        SimpleNamespace(),  # fake_settings
        SimpleNamespace(),  # fake_orchestrator
        SimpleNamespace(),  # fake_queue_runner
        SimpleNamespace(),  # fake_scanner
        event_bus,
        threading.Lock(),
    )


def _open_and_abandon_sse_connection(port, event_bus, timeout=2.0):
    """Opens a real /api/events connection, waits for the subscription to
    register, then severs the connection without reading any response —
    the same shape as a browser tab being closed mid-stream."""

    sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    try:
        before = len(event_bus._subscribers)  # pylint: disable=protected-access
        sock.sendall(b"GET /api/events HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and len(event_bus._subscribers) <= before:  # pylint: disable=protected-access
            time.sleep(0.005)
        assert len(event_bus._subscribers) > before, "connection never subscribed"  # pylint: disable=protected-access
    finally:
        sock.close()


def test_sse_route_unsubscribes_after_real_client_disconnect(monkeypatch):
    monkeypatch.setattr(routes_events, "_HEARTBEAT_SECONDS", 0.05)
    bus = EventBus()
    server = _LiveServer(_make_live_app(bus), _free_port())
    server.start()
    try:
        port = server.server.config.port
        _open_and_abandon_sse_connection(port, bus)

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and bus._subscribers:  # pylint: disable=protected-access
            time.sleep(0.02)

        assert bus._subscribers == []  # pylint: disable=protected-access
    finally:
        server.stop()


def test_repeated_abandoned_sse_connections_dont_grow_the_subscriber_list(monkeypatch):
    """Review Focus #1, literally: reloading the events page repeatedly must
    not grow the EventBus's subscriber list unboundedly."""

    monkeypatch.setattr(routes_events, "_HEARTBEAT_SECONDS", 0.05)
    bus = EventBus()
    server = _LiveServer(_make_live_app(bus), _free_port())
    server.start()
    try:
        port = server.server.config.port
        for _ in range(45):
            sock = socket.create_connection(("127.0.0.1", port), timeout=2.0)
            try:
                sock.sendall(b"GET /api/events HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
            finally:
                sock.close()

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and bus._subscribers:  # pylint: disable=protected-access
            time.sleep(0.05)

        assert bus._subscribers == []  # pylint: disable=protected-access

        probe = socket.create_connection(("127.0.0.1", port), timeout=3.0)
        try:
            probe.sendall(b"GET /api/health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
            probe.settimeout(3.0)
            response = probe.recv(200)
        finally:
            probe.close()

        assert b"200" in response
    finally:
        server.stop()
