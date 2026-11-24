import threading
from types import SimpleNamespace

from fastapi.testclient import TestClient

from src.web.app import create_app


def _make_app():
    return create_app(
        "wlan0",
        SimpleNamespace(),  # fake_settings
        SimpleNamespace(),  # fake_orchestrator
        SimpleNamespace(),  # fake_queue_runner
        SimpleNamespace(),  # fake_scanner
        SimpleNamespace(),  # fake_event_bus
        threading.Lock(),
    )


def test_health_check_returns_ok():
    app = _make_app()
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_app_stores_every_dependency_on_app_state():
    app = _make_app()
    assert app.state.interface == "wlan0"
    for name in ("settings", "orchestrator", "queue_runner", "scanner", "event_bus", "radio_lock"):
        assert getattr(app.state, name) is not None
