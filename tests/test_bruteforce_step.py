import time
from unittest.mock import MagicMock

import pytest

import src.wps.connection
from src.session import SessionStore
from src.wps.bruteforce import Initialize
from src.wps.connection import Initialize as ConnectionInitialize


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    # _attemptPin's lock branch does time.sleep(self.settings.timeout)
    # (default 60s) on a "locked" result; keep these tests fast.
    monkeypatch.setattr(time, "sleep", lambda s: None)


class FakeConnection:
    """Fake standing in for bruteforce.Initialize.CONNECTION: one
    singleConnection() call, result controlled by `returns`."""

    def __init__(self, returns):
        self.INTERFACE = "wlan0"
        self.returns = returns
        self.CONNECTION_STATUS = src.wps.connection.ConnectionStatus()
        self.call_log = []

    def singleConnection(self, bssid, pin, **kwargs):  # pylint: disable=unused-argument
        self.call_log.append((bssid, pin))
        self.CONNECTION_STATUS.clear()

        if self.returns == "LOCKED":
            self.CONNECTION_STATUS.IS_LOCKED = True
        elif self.returns == "WPS_FAIL_OTHER":
            pass  # a generic non-matching failure: status stays '' (unset)
        elif self.returns == "WPS_FAIL":
            self.CONNECTION_STATUS.STATUS = 'WPS_FAIL'
        elif self.returns == "VALID_FIRST_HALF":
            self.CONNECTION_STATUS.LAST_M_MESSAGE = 6  # isFirstHalfValid() => LAST_M_MESSAGE > 5
        elif self.returns == "GOT_PSK":
            self.CONNECTION_STATUS.LAST_M_MESSAGE = 7  # > 6
            self.CONNECTION_STATUS.STATUS = 'GOT_PSK'


def _make_bruteforce_initialize_with_fakes(monkeypatch, tmp_path, connection):
    monkeypatch.setattr(ConnectionInitialize, "_initWpaSupplicant", lambda self: None)
    session = SessionStore(tmp_path / "s.sqlite3")
    bf = Initialize("wlan0", session=session)
    bf.CONNECTION.WPAS = MagicMock()
    bf.CONNECTION = connection
    return bf


def test_bruteforce_step_advances_on_plain_failure(tmp_path, monkeypatch):
    bf = _make_bruteforce_initialize_with_fakes(monkeypatch, tmp_path, FakeConnection(returns="WPS_FAIL_OTHER"))
    state, result = bf.bruteforceStep("AA:BB:CC:DD:EE:FF", "0000")
    assert state == "advanced" and result is None


def test_bruteforce_step_reports_locked(tmp_path, monkeypatch):
    bf = _make_bruteforce_initialize_with_fakes(monkeypatch, tmp_path, FakeConnection(returns="LOCKED"))
    state, result = bf.bruteforceStep("AA:BB:CC:DD:EE:FF", "0000")
    assert state == "locked"
    assert result is None


def test_bruteforce_step_reports_first_half_found(tmp_path, monkeypatch):
    bf = _make_bruteforce_initialize_with_fakes(monkeypatch, tmp_path, FakeConnection(returns="VALID_FIRST_HALF"))
    state, result = bf.bruteforceStep("AA:BB:CC:DD:EE:FF", "0000")
    assert state == "first_half_found"


def test_bruteforce_step_reports_cracked_with_full_pin(tmp_path, monkeypatch):
    bf = _make_bruteforce_initialize_with_fakes(monkeypatch, tmp_path, FakeConnection(returns="GOT_PSK"))
    state, result = bf.bruteforceStep("AA:BB:CC:DD:EE:FF", "0001234")
    assert state == "cracked" and result is not None and len(result) == 8


def test_bruteforce_step_exhausted_at_range_end_first_half(tmp_path, monkeypatch):
    bf = _make_bruteforce_initialize_with_fakes(monkeypatch, tmp_path, FakeConnection(returns="WPS_FAIL_OTHER"))
    state, result = bf.bruteforceStep("AA:BB:CC:DD:EE:FF", "9999")
    assert state == "exhausted"
    assert result is None


def test_bruteforce_step_exhausted_at_range_end_second_half(tmp_path, monkeypatch):
    bf = _make_bruteforce_initialize_with_fakes(monkeypatch, tmp_path, FakeConnection(returns="WPS_FAIL_OTHER"))
    state, result = bf.bruteforceStep("AA:BB:CC:DD:EE:FF", "0000999")
    assert state == "exhausted"
    assert result is None


def test_bruteforce_step_advances_on_plain_failure_second_half(tmp_path, monkeypatch):
    bf = _make_bruteforce_initialize_with_fakes(monkeypatch, tmp_path, FakeConnection(returns="WPS_FAIL_OTHER"))
    state, result = bf.bruteforceStep("AA:BB:CC:DD:EE:FF", "0000001")
    assert state == "advanced" and result is None


def test_bruteforce_step_requests_retry_on_real_wps_fail_first_half(tmp_path, monkeypatch):
    # A genuine WPS_FAIL (transaction glitch, not a wrong-pin signal) must
    # not advance past this mask value — unlike plain/other failures,
    # the CLI's own _firstHalfBruteforce retries the same pin on this
    # exact status (bruteforce.py's _attemptPin docstring), and the
    # orchestrator must get a distinct signal to do the same.
    bf = _make_bruteforce_initialize_with_fakes(monkeypatch, tmp_path, FakeConnection(returns="WPS_FAIL"))
    state, result = bf.bruteforceStep("AA:BB:CC:DD:EE:FF", "0000")
    assert state == "retry" and result is None


def test_bruteforce_step_requests_retry_on_real_wps_fail_second_half(tmp_path, monkeypatch):
    bf = _make_bruteforce_initialize_with_fakes(monkeypatch, tmp_path, FakeConnection(returns="WPS_FAIL"))
    state, result = bf.bruteforceStep("AA:BB:CC:DD:EE:FF", "0000001")
    assert state == "retry" and result is None


def test_bruteforce_step_does_not_sleep_or_loop(tmp_path, monkeypatch):
    # Regression: unlike _firstHalfBruteforce/_secondHalfBruteforce,
    # bruteforceStep must make exactly one singleConnection call per
    # invocation — no internal retry loop.
    fake_conn = FakeConnection(returns="LOCKED")
    bf = _make_bruteforce_initialize_with_fakes(monkeypatch, tmp_path, fake_conn)
    bf.bruteforceStep("AA:BB:CC:DD:EE:FF", "0000")
    assert len(fake_conn.call_log) == 1


def test_bruteforce_step_does_not_write_to_session(tmp_path, monkeypatch):
    # Regression: bruteforceStep owns one attempt's interpretation only;
    # the orchestrator (not this method) persists mask/state.
    bf = _make_bruteforce_initialize_with_fakes(monkeypatch, tmp_path, FakeConnection(returns="WPS_FAIL_OTHER"))
    bssid = "AA:BB:CC:DD:EE:FF"
    bf.bruteforceStep(bssid, "0000")
    assert bf.session.get_bruteforce_mask(bssid) is None
