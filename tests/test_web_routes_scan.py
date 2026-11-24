import threading
from types import SimpleNamespace

from fastapi.testclient import TestClient

from src.web.app import create_app


class FakeScanner:
    def __init__(self, networks=None, stored=None, vuln_list=None):
        self._networks = networks
        self.STORED = stored or []
        self.VULN_LIST = vuln_list or []

    def _iwScanner(self):  # pylint: disable=invalid-name
        return self._networks


def _network(bssid="AA:BB:CC:DD:EE:FF", essid="home", wps_version="2.0",
             locked=False, model="RT-AC", model_number="68U", device_name="RT-AC68U"):
    return {
        "BSSID": bssid, "ESSID": essid, "Level": -45,
        "WPS version": wps_version, "WPS locked": locked,
        "Model": model, "Model number": model_number, "Device name": device_name,
    }


def _make_app(scanner):
    return create_app(
        "wlan0", SimpleNamespace(), SimpleNamespace(), SimpleNamespace(),
        scanner, SimpleNamespace(), threading.Lock(),
    )


def test_scan_returns_formatted_networks_with_bssid_and_essid():
    network = _network()
    scanner = FakeScanner(networks={0: network})
    client = TestClient(_make_app(scanner))

    response = client.get("/api/scan")

    assert response.status_code == 200
    assert response.json() == [{
        "bssid": "AA:BB:CC:DD:EE:FF",
        "essid": "home",
        "label": "home (AA:BB:CC:DD:EE:FF) -45dBm",
        "highlight": "none",
    }]


def test_scan_returns_empty_list_when_no_networks_found():
    scanner = FakeScanner(networks=False)
    client = TestClient(_make_app(scanner))

    response = client.get("/api/scan")

    assert response.status_code == 200
    assert response.json() == []


def test_scan_marks_stored_network():
    network = _network()
    scanner = FakeScanner(networks={0: network}, stored=[("AA:BB:CC:DD:EE:FF", "home")])
    client = TestClient(_make_app(scanner))

    response = client.get("/api/scan")

    assert response.json()[0]["highlight"] == "stored"


def test_scan_marks_vulnerable_model():
    network = _network(model="RT-AC", model_number="68U", device_name="RT-AC68U")
    scanner = FakeScanner(networks={0: network}, vuln_list=["RT-AC 68U"])
    client = TestClient(_make_app(scanner))

    response = client.get("/api/scan")

    assert response.json()[0]["highlight"] == "vulnerable_model"
