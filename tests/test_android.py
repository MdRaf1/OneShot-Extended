import subprocess
import time

import pytest

from src.wifi.android import AndroidNetwork


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    # disableWifi() has a real time.sleep(3); keep tests fast.
    monkeypatch.setattr(time, "sleep", lambda s: None)


def _raise_called_process_error(*args, **kwargs):  # pylint: disable=unused-argument
    raise subprocess.CalledProcessError(returncode=1, cmd=args[0] if args else [])


def _raise_file_not_found(*args, **kwargs):  # pylint: disable=unused-argument
    raise FileNotFoundError(2, "No such file or directory", "cmd")


def test_disable_wifi_logs_on_called_process_error(monkeypatch, caplog):
    monkeypatch.setattr(subprocess, "run", _raise_called_process_error)
    AndroidNetwork().disableWifi()  # must not raise
    assert "disable" in caplog.text.lower() or "wifi" in caplog.text.lower()


def test_disable_wifi_logs_on_missing_binary(monkeypatch, caplog):
    monkeypatch.setattr(subprocess, "run", _raise_file_not_found)
    AndroidNetwork().disableWifi()  # must not raise
    assert caplog.records  # something was logged, not silently swallowed


def test_enable_wifi_logs_on_called_process_error(monkeypatch, caplog):
    monkeypatch.setattr(subprocess, "run", _raise_called_process_error)
    AndroidNetwork().enableWifi()  # must not raise
    assert "enable" in caplog.text.lower() or "wifi" in caplog.text.lower()


def test_enable_wifi_logs_on_missing_binary(monkeypatch, caplog):
    monkeypatch.setattr(subprocess, "run", _raise_file_not_found)
    AndroidNetwork().enableWifi()  # must not raise
    assert caplog.records


def test_store_always_scan_state_still_logs_on_called_process_error(monkeypatch, caplog):
    # Regression: the one call site that already worked (check=True +
    # CalledProcessError handling) keeps working after this fix.
    monkeypatch.setattr(subprocess, "run", _raise_called_process_error)
    network = AndroidNetwork()
    network.storeAlwaysScanState()  # must not raise
    assert network.ENABLED_SCANNING == 1
    assert caplog.records


def test_store_always_scan_state_logs_on_missing_binary(monkeypatch, caplog):
    monkeypatch.setattr(subprocess, "run", _raise_file_not_found)
    network = AndroidNetwork()
    network.storeAlwaysScanState()  # must not raise
    assert caplog.records


def test_disable_wifi_still_disables_always_scanning_when_enabled(monkeypatch):
    # Regression: the "always scanning" sub-call still happens when
    # ENABLED_SCANNING == 1, and both calls go through check=True now.
    calls = []

    def fake_run(cmd, *args, **kwargs):  # pylint: disable=unused-argument
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    network = AndroidNetwork()
    network.ENABLED_SCANNING = 1
    network.disableWifi()
    assert ['cmd', 'wifi', 'set-wifi-enabled', 'disabled'] in calls
    assert ['cmd', '-w', 'wifi', 'set-scan-always-available', 'disabled'] in calls
