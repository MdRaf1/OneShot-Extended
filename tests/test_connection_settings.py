import importlib
import sys
import time
from unittest.mock import MagicMock

import src.wps.connection
from src.settings import Settings
from src.wps.connection import Initialize


def test_importing_connection_does_not_parse_sys_argv(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["pytest"])
    importlib.reload(src.wps.connection)  # must not raise SystemExit


def _make_initialize_without_real_subprocess(monkeypatch, settings=None):
    monkeypatch.setattr(Initialize, "_initWpaSupplicant", lambda self: None)
    conn = Initialize("wlan0", settings=settings)
    conn.WPAS = MagicMock()
    return conn


def test_lock_retry_sleeps_for_settings_timeout(monkeypatch):
    settings = Settings(interface="wlan0", timeout=5)
    conn = _make_initialize_without_real_subprocess(monkeypatch, settings=settings)

    sleep_calls = []
    monkeypatch.setattr(time, "sleep", lambda s: sleep_calls.append(s))
    monkeypatch.setattr(conn, "_sendAndReceive", lambda cmd: "OK")
    monkeypatch.setattr(conn, "_sendOnly", lambda cmd: None)

    # First inner-loop iteration: pretend the interface stays up and the
    # handler reports a locked WSC_NACK (IS_LOCKED=True), ending that pass.
    def fake_handle_wpas(pbc_mode=False):
        conn.CONNECTION_STATUS.STATUS = 'WSC_NACK'
        conn.CONNECTION_STATUS.IS_LOCKED = True
        return False

    monkeypatch.setattr(conn, "_handleWpas", fake_handle_wpas)
    monkeypatch.setattr("src.utils.isInterfaceUp", lambda iface: True)

    # retry_on_lock=True would loop forever (by design) once locked, so
    # make the second pass's send fail to break out after one retry.
    call_count = {"n": 0}

    def send_and_receive(cmd):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return "OK"
        return "FAIL"  # second send: force a non-OK reply to exit the loop

    monkeypatch.setattr(conn, "_sendAndReceive", send_and_receive)

    conn._wpsConnection("AA:BB:CC:DD:EE:FF", "12345670", retry_on_lock=True)  # pylint: disable=protected-access

    assert 5 in sleep_calls
