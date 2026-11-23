import src.utils
from src.wifi.collector import WiFiCollector


def test_write_result_unaffected_by_write_pin_removal(tmp_path, monkeypatch):
    monkeypatch.setattr(src.utils, "REPORTS_DIR", str(tmp_path) + "/")
    WiFiCollector.writeResult("AA:BB:CC:DD:EE:FF", "home", "12345670", "secretpsk")
    assert (tmp_path / "stored.csv").exists()
    assert not hasattr(WiFiCollector, "writePin")
