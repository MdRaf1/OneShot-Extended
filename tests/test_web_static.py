import threading
from types import SimpleNamespace

from fastapi.testclient import TestClient

from src.web.app import create_app


def _make_app():
    return create_app(
        "wlan0", SimpleNamespace(), SimpleNamespace(), SimpleNamespace(),
        SimpleNamespace(), SimpleNamespace(), threading.Lock(),
    )


def test_index_page_serves_and_contains_expected_tabs():
    client = TestClient(_make_app())
    response = client.get("/")
    assert response.status_code == 200
    for expected in ("Scan", "Queue", "Log", "PBC"):
        assert expected in response.text


def test_api_routes_still_reachable_after_static_mount():
    client = TestClient(_make_app())
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
