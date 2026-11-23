from unittest.mock import MagicMock

import time

import src.wps.connection
from src.session import SessionStore
from src.wps.bruteforce import Initialize
from src.wps.connection import Initialize as ConnectionInitialize


class ScriptedFakeConnection:
    """Fake standing in for bruteforce.Initialize.CONNECTION. Each call to
    singleConnection() consumes the next scripted result and updates a
    real ConnectionStatus object the same way the real connection would."""

    def __init__(self, interface, results):
        self.INTERFACE = interface
        self.results = list(results)
        self.CONNECTION_STATUS = src.wps.connection.ConnectionStatus()
        self.call_log = []

    def singleConnection(self, bssid, pin, **kwargs):  # pylint: disable=unused-argument
        self.call_log.append((bssid, pin))
        self.CONNECTION_STATUS.clear()

        result = self.results.pop(0)
        if result == "LOCKED":
            self.CONNECTION_STATUS.IS_LOCKED = True
        elif result == "WPS_FAIL":
            self.CONNECTION_STATUS.STATUS = 'WPS_FAIL'
        elif result == "VALID_FIRST_HALF":
            self.CONNECTION_STATUS.LAST_M_MESSAGE = 6  # isFirstHalfValid() => LAST_M_MESSAGE > 5
        elif result == "VALID_SECOND_HALF":
            self.CONNECTION_STATUS.LAST_M_MESSAGE = 7  # > 6, _secondHalfBruteforce's success check


def _make_bruteforce_initialize_with_fake_connection(monkeypatch, tmp_path, results):
    monkeypatch.setattr(ConnectionInitialize, "_initWpaSupplicant", lambda self: None)
    monkeypatch.setattr("src.utils.isInterfaceUp", lambda iface: True)
    session = SessionStore(tmp_path / "s.sqlite3")
    bf = Initialize("wlan0", session=session)
    bf.CONNECTION.WPAS = MagicMock()
    fake_conn = ScriptedFakeConnection("wlan0", results)
    bf.CONNECTION = fake_conn
    return bf, fake_conn


def test_first_half_bruteforce_call_sequence_unchanged(tmp_path, monkeypatch):
    bf, fake_conn = _make_bruteforce_initialize_with_fake_connection(
        monkeypatch, tmp_path, results=["LOCKED", "WPS_FAIL", "VALID_FIRST_HALF"]
    )
    monkeypatch.setattr(time, "sleep", lambda s: None)

    result = bf._firstHalfBruteforce("AA:BB:CC:DD:EE:FF", "0000")  # pylint: disable=protected-access

    # Captured by running this test against the pre-extraction
    # implementation (Step 2): since LOCKED and WPS_FAIL never advance
    # first_half (continue / recursive retry both reuse the same value),
    # all 3 scripted attempts are made with the identical PIN for
    # first_half="0000".
    checksum = bf.GENERATOR.checksum
    expected_pin = f'0000000{checksum(int("0000" + "000"))}'
    assert fake_conn.call_log == [
        ("AA:BB:CC:DD:EE:FF", expected_pin),
        ("AA:BB:CC:DD:EE:FF", expected_pin),
        ("AA:BB:CC:DD:EE:FF", expected_pin),
    ]
    assert result == "0000"


def test_second_half_bruteforce_call_sequence_unchanged(tmp_path, monkeypatch):
    bf, fake_conn = _make_bruteforce_initialize_with_fake_connection(
        monkeypatch, tmp_path, results=["LOCKED", "WPS_FAIL", "VALID_SECOND_HALF"]
    )
    monkeypatch.setattr(time, "sleep", lambda s: None)

    result = bf._secondHalfBruteforce("AA:BB:CC:DD:EE:FF", "0000", "001")  # pylint: disable=protected-access

    checksum = bf.GENERATOR.checksum
    expected_pin = f'0000001{checksum(int("0000" + "001"))}'
    assert fake_conn.call_log == [
        ("AA:BB:CC:DD:EE:FF", expected_pin),
        ("AA:BB:CC:DD:EE:FF", expected_pin),
        ("AA:BB:CC:DD:EE:FF", expected_pin),
    ]
    assert result == expected_pin


def test_first_half_bruteforce_advances_and_registers_attempts_on_plain_failure(tmp_path, monkeypatch):
    # A plain (non-locked, non-WPS_FAIL, non-valid) result must still
    # advance first_half and call registerAttempt, exactly as before.
    bf, fake_conn = _make_bruteforce_initialize_with_fake_connection(
        monkeypatch, tmp_path, results=["OTHER", "VALID_FIRST_HALF"]
    )
    monkeypatch.setattr(time, "sleep", lambda s: None)

    attempts = []
    monkeypatch.setattr(bf.BRUTEFORCE_STATUS, "registerAttempt", lambda mask: attempts.append(mask))

    result = bf._firstHalfBruteforce("AA:BB:CC:DD:EE:FF", "0000")  # pylint: disable=protected-access

    checksum = bf.GENERATOR.checksum
    pin0 = f'0000000{checksum(int("0000" + "000"))}'
    pin1 = f'0001000{checksum(int("0001" + "000"))}'
    assert fake_conn.call_log == [
        ("AA:BB:CC:DD:EE:FF", pin0),
        ("AA:BB:CC:DD:EE:FF", pin1),
    ]
    assert attempts == ["0001"]
    assert result == "0001"


def test_first_half_bruteforce_not_found_after_exhausting_range(tmp_path, monkeypatch):
    # Starting at "9999", a single non-matching attempt advances first_half
    # to "10000", which already fails the loop's `int(first_half) < 10000`
    # condition — exhausting the range in one attempt.
    bf, _fake_conn = _make_bruteforce_initialize_with_fake_connection(
        monkeypatch, tmp_path, results=["OTHER"]
    )
    monkeypatch.setattr(time, "sleep", lambda s: None)

    result = bf._firstHalfBruteforce("AA:BB:CC:DD:EE:FF", "9999")  # pylint: disable=protected-access

    assert result is False
